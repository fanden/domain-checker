from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
)

from .checker import check_all_domains
from .models import Availability, CheckerConfig, CheckResult, TaskState
from .output import format_duration, print_results
from .pricing import fetch_pricing
from .rdap_bootstrap import load_rdap_bootstrap
from .state import StateManager
from .tld_list import fetch_tld_list


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="domain-checker",
        description="Check domain availability across all TLDs.",
    )
    p.add_argument(
        "words", nargs="+", metavar="WORD",
        help='Words to check (e.g. "milk" "cookies")',
    )
    p.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output file path",
    )
    p.add_argument(
        "-f", "--format", dest="fmt", default="table",
        choices=["table", "csv", "json"],
        help="Output format (default: table)",
    )
    p.add_argument(
        "--filter", dest="filter_status", default="all",
        choices=["all", "available", "registered"],
        help="Filter results (default: all)",
    )
    p.add_argument(
        "--resume", action="store_true", default=False,
        help="Resume a previously started check",
    )
    p.add_argument(
        "--no-resume", action="store_true", default=False,
        help="Start fresh even if a state file exists",
    )
    p.add_argument(
        "--tlds", nargs="+", default=None,
        help="Check only specific TLDs",
    )
    p.add_argument(
        "--exclude-tlds", nargs="+", default=None,
        help="Exclude specific TLDs",
    )
    p.add_argument(
        "--include-idn", action="store_true", default=False,
        help="Include internationalized (xn--) TLDs",
    )
    p.add_argument(
        "--dns-only", action="store_true", default=False,
        help="Only use DNS checking (fastest, less accurate)",
    )
    p.add_argument(
        "--no-whois", action="store_true", default=False,
        help="Skip WHOIS fallback (use DNS + RDAP only)",
    )
    p.add_argument(
        "--nameservers", nargs="+", default=None,
        help="Custom DNS nameservers (e.g. 8.8.8.8 1.1.1.1)",
    )
    p.add_argument(
        "--concurrency", type=int, default=100,
        help="Max concurrent checks (default: 100)",
    )
    p.add_argument(
        "--checkpoint-every", type=int, default=50,
        help="Save state every N checks (default: 50)",
    )
    p.add_argument(
        "--data-dir", type=Path, default=Path("data"),
        help="Directory for cache and state files (default: ./data)",
    )
    p.add_argument(
        "--timeout", type=float, default=10.0,
        help="Per-check timeout in seconds (default: 10)",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", default=False,
        help="Verbose output",
    )
    p.add_argument(
        "-q", "--quiet", action="store_true", default=False,
        help="Suppress progress output",
    )
    p.add_argument(
        "--no-prices", action="store_true", default=False,
        help="Skip fetching TLD pricing data",
    )
    return p


async def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    # Use safe_box to avoid encoding issues on Windows legacy consoles
    console = Console(safe_box=True, highlight=False)
    words = [w.lower().strip() for w in args.words]
    data_dir: Path = args.data_dir.resolve()

    # Load TLD list
    console.print("[dim]Fetching TLD list...[/dim]")
    if args.tlds:
        tld_list = sorted(t.lower() for t in args.tlds)
    else:
        tld_list = await fetch_tld_list(
            data_dir, include_idn=args.include_idn
        )
        if args.exclude_tlds:
            exclude = {t.lower() for t in args.exclude_tlds}
            tld_list = [t for t in tld_list if t not in exclude]

    console.print(f"[dim]Loaded {len(tld_list)} TLDs[/dim]")

    # Load RDAP bootstrap
    rdap_bootstrap: dict[str, str] = {}
    if not args.dns_only:
        console.print("[dim]Fetching RDAP bootstrap data...[/dim]")
        rdap_bootstrap = await load_rdap_bootstrap(data_dir)
        console.print(f"[dim]RDAP covers {len(rdap_bootstrap)} TLDs[/dim]")

    # Load pricing data
    pricing = {}
    if not args.no_prices:
        console.print("[dim]Fetching TLD pricing data...[/dim]")
        pricing = await fetch_pricing(data_dir)
        console.print(f"[dim]Pricing available for {len(pricing)} TLDs[/dim]")

    # State management
    state_mgr = StateManager(data_dir, words)

    if state_mgr.exists() and not args.no_resume:
        if args.resume:
            do_resume = True
        else:
            existing = state_mgr.load()
            console.print(
                f"\n[yellow]Found existing state: "
                f"{existing.checked_count}/{existing.total_combinations} checked "
                f"({format_duration(existing.updated_at - existing.started_at)} elapsed)[/yellow]"
            )
            try:
                answer = console.input("[yellow]Resume? [Y/n]: [/yellow]").strip().lower()
                do_resume = answer in ("", "y", "yes")
            except (EOFError, KeyboardInterrupt):
                return 130

        if do_resume:
            state = state_mgr.load()
            console.print(
                f"[green]Resuming: {state.checked_count}/{state.total_combinations} already done[/green]"
            )
        else:
            state_mgr.delete()
            state = TaskState(words=words, tld_list=tld_list)
    else:
        state = TaskState(words=words, tld_list=tld_list)

    state.tld_list = tld_list
    state.words = words
    total = len(words) * len(tld_list)
    state.total_combinations = total

    config = CheckerConfig(
        use_whois=not args.no_whois,
        dns_only=args.dns_only,
        concurrency=args.concurrency,
        checkpoint_every=args.checkpoint_every,
        timeout=args.timeout,
        nameservers=args.nameservers,
        verbose=args.verbose,
        quiet=args.quiet,
    )

    # Set up Ctrl+C handler
    def _sigint_handler(sig, frame):
        console.print("\n[yellow]Interrupted! Saving state...[/yellow]")
        state_mgr.save(state)
        console.print(
            f"[yellow]State saved: {state.checked_count}/{state.total_combinations} checked[/yellow]"
        )
        console.print(f"[yellow]Resume with: domain-checker {' '.join(words)} --resume[/yellow]")
        sys.exit(130)

    signal.signal(signal.SIGINT, _sigint_handler)

    # Progress tracking
    available_count = sum(
        1 for r in state.results.values()
        if r.availability == Availability.AVAILABLE
    )

    remaining = total - state.checked_count
    console.print(
        f"\n[bold]Checking {total:,} domain combinations "
        f"({len(words)} words x {len(tld_list)} TLDs)[/bold]"
    )
    if state.checked_count > 0:
        console.print(f"[dim]Skipping {state.checked_count:,} already checked[/dim]")
    console.print()

    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(complete_style="green", finished_style="green"),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        TextColumn("[green]{task.fields[available]}[/green] available"),
        console=console,
        disable=args.quiet,
    )

    with progress:
        task_id = progress.add_task(
            "Checking domains",
            total=total,
            completed=state.checked_count,
            available=available_count,
        )

        def on_progress(result: CheckResult, done: int, total_n: int):
            nonlocal available_count
            if result.availability == Availability.AVAILABLE:
                available_count += 1
            progress.update(task_id, completed=done, available=available_count)
            if args.verbose and not args.quiet:
                if result.availability == Availability.AVAILABLE:
                    price_info = ""
                    p = pricing.get(result.tld)
                    if p:
                        price_info = f" ~${p.registration:.2f}"
                    progress.console.print(
                        f"  [green]AVAIL[/green] {result.domain}{price_info} ({result.method.value})"
                    )

        await check_all_domains(
            words=words,
            tld_list=tld_list,
            state=state,
            state_manager=state_mgr,
            rdap_bootstrap=rdap_bootstrap,
            config=config,
            progress_callback=on_progress,
        )

    # Output results
    console.print()
    print_results(
        state,
        fmt=args.fmt,
        filter_status=args.filter_status,
        output_file=args.output,
        pricing=pricing,
    )

    if args.output:
        console.print(f"Results written to: [cyan]{args.output}[/cyan]")

    console.print(f"State saved to: [dim]{state_mgr.filepath}[/dim]")
    return 0


def main_sync() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
