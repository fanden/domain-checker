from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from .models import Availability, CheckResult, TaskState
from .pricing import TLDPrice


def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def print_results(
    state: TaskState,
    fmt: str = "table",
    filter_status: str = "all",
    output_file: Optional[Path] = None,
    pricing: Optional[dict[str, TLDPrice]] = None,
) -> None:
    results = list(state.results.values())

    if filter_status == "available":
        results = [r for r in results if r.availability == Availability.AVAILABLE]
    elif filter_status == "registered":
        results = [r for r in results if r.availability == Availability.REGISTERED]

    results.sort(key=lambda r: (r.word, r.tld))
    pricing = pricing or {}

    if fmt == "json":
        _output_json(results, output_file, pricing)
    elif fmt == "csv":
        _output_csv(results, output_file, pricing)
    else:
        _output_table(state, results, filter_status, output_file, pricing)


def _format_price(pricing: dict[str, TLDPrice], tld: str) -> str:
    p = pricing.get(tld)
    if p:
        return f"${p.registration:.2f}"
    return "-"


def _format_renewal(pricing: dict[str, TLDPrice], tld: str) -> str:
    p = pricing.get(tld)
    if p:
        return f"${p.renewal:.2f}"
    return "-"


def _output_table(
    state: TaskState,
    results: list[CheckResult],
    filter_status: str,
    output_file: Optional[Path],
    pricing: dict[str, TLDPrice],
) -> None:
    console = Console(
        file=open(output_file, "w") if output_file else None,
        safe_box=True,
        highlight=False,
    )
    duration = state.updated_at - state.started_at

    console.print()
    console.print(
        f"[bold]Domain Availability Report[/bold]",
    )
    console.print(f"Words: [cyan]{', '.join(state.words)}[/cyan]")
    console.print(f"TLDs checked: [cyan]{len(state.tld_list):,}[/cyan]")
    console.print(f"Duration: [cyan]{format_duration(duration)}[/cyan]")
    console.print()

    # Summary counts from full results (not filtered)
    all_results = list(state.results.values())
    available = [r for r in all_results if r.availability == Availability.AVAILABLE]
    registered = [r for r in all_results if r.availability == Availability.REGISTERED]
    unknown = [
        r for r in all_results
        if r.availability in (Availability.UNKNOWN, Availability.ERROR, Availability.NO_SERVER)
    ]

    if available:
        console.print(
            f"[bold green]Available Domains ({len(available)} found):[/bold green]"
        )
        avail_sorted = sorted(available, key=lambda x: (x.word, x.tld))
        for r in avail_sorted:
            price_str = _format_price(pricing, r.tld)
            renewal_str = _format_renewal(pricing, r.tld)
            if price_str != "-":
                console.print(
                    f"  [green]{r.domain:<30}[/green]  "
                    f"reg: [cyan]{price_str:>8}[/cyan]  "
                    f"renew: [cyan]{renewal_str:>8}[/cyan]  "
                    f"({r.method.value})"
                )
            else:
                console.print(
                    f"  [green]{r.domain:<30}[/green]  "
                    f"({r.method.value})"
                )
        console.print()

    if filter_status == "all" and len(results) > len(available):
        table = Table(title="All Results", show_lines=False)
        table.add_column("Domain", style="white")
        table.add_column("Status", style="white")
        table.add_column("Reg. Price", justify="right")
        table.add_column("Renewal", justify="right")
        table.add_column("Method", style="dim")

        for r in results:
            if r.availability == Availability.AVAILABLE:
                status = "[green]AVAILABLE[/green]"
            elif r.availability == Availability.REGISTERED:
                status = "[red]REGISTERED[/red]"
            else:
                status = f"[yellow]{r.availability.value.upper()}[/yellow]"

            price_str = _format_price(pricing, r.tld)
            renewal_str = _format_renewal(pricing, r.tld)
            table.add_row(r.domain, status, price_str, renewal_str, r.method.value)

        console.print(table)
        console.print()

    console.print("[bold]Summary:[/bold]")
    total = len(all_results)
    if total:
        console.print(
            f"  [green]Available:  {len(available):>6}[/green]"
            f"  ({len(available) / total * 100:.1f}%)"
        )
        console.print(
            f"  [red]Registered: {len(registered):>6}[/red]"
            f"  ({len(registered) / total * 100:.1f}%)"
        )
        console.print(
            f"  [yellow]Unknown:    {len(unknown):>6}[/yellow]"
            f"  ({len(unknown) / total * 100:.1f}%)"
        )
    console.print()

    if output_file:
        console.file.close()


def _output_json(
    results: list[CheckResult],
    output_file: Optional[Path],
    pricing: dict[str, TLDPrice],
) -> None:
    data = []
    for r in results:
        d = r.to_dict()
        p = pricing.get(r.tld)
        d["reg_price"] = p.registration if p else None
        d["renewal_price"] = p.renewal if p else None
        d["price_source"] = p.source if p else None
        data.append(d)
    text = json.dumps(data, indent=2)
    if output_file:
        output_file.write_text(text, encoding="utf-8")
    else:
        print(text)


def _output_csv(
    results: list[CheckResult],
    output_file: Optional[Path],
    pricing: dict[str, TLDPrice],
) -> None:
    buf = io.StringIO() if not output_file else open(output_file, "w", newline="", encoding="utf-8")
    writer = csv.writer(buf)
    writer.writerow([
        "domain", "word", "tld", "availability", "method",
        "dns_has_ns", "rdap_status", "reg_price", "renewal_price",
        "price_source", "checked_at",
    ])
    for r in results:
        p = pricing.get(r.tld)
        writer.writerow([
            r.domain, r.word, r.tld,
            r.availability.value, r.method.value,
            r.dns_has_ns, r.rdap_status,
            f"{p.registration:.2f}" if p else "",
            f"{p.renewal:.2f}" if p else "",
            p.source if p else "",
            r.checked_at,
        ])
    if output_file:
        buf.close()
    else:
        print(buf.getvalue())
