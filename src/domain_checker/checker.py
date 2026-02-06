from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

import httpx

from .dns_check import check_dns, make_resolver
from .models import (
    Availability,
    CheckerConfig,
    CheckMethod,
    CheckResult,
    TaskState,
)
from .rate_limiter import RateLimiter
from .rdap_bootstrap import get_rdap_url
from .rdap_check import check_rdap
from .state import StateManager
from .whois_check import check_whois, discover_whois_server


async def check_single_domain(
    word: str,
    tld: str,
    resolver,
    rdap_bootstrap: dict[str, str],
    http_client: httpx.AsyncClient,
    rate_limiter: RateLimiter,
    config: CheckerConfig,
) -> CheckResult:
    domain = f"{word}.{tld}"
    result = CheckResult(domain=domain, word=word, tld=tld)

    # Phase 1: DNS
    try:
        has_ns, has_soa = await check_dns(
            domain, resolver, timeout=min(config.timeout, 5.0)
        )
        result.dns_has_ns = has_ns

        if has_ns:
            result.availability = Availability.REGISTERED
            result.method = CheckMethod.DNS
            return result
    except Exception as e:
        result.error_message = f"DNS: {e}"

    if config.dns_only:
        if result.dns_has_ns is False:
            result.availability = Availability.AVAILABLE
            result.method = CheckMethod.DNS
        else:
            result.availability = Availability.UNKNOWN
            result.method = CheckMethod.DNS
        return result

    # Phase 2: RDAP
    rdap_url = get_rdap_url(rdap_bootstrap, tld)
    if rdap_url:
        try:
            rdap_result = await check_rdap(
                domain, tld, rdap_bootstrap, http_client,
                rate_limiter, timeout=config.timeout,
            )
            if rdap_result is not None:
                result.availability = rdap_result
                result.method = CheckMethod.RDAP
                return result
        except Exception as e:
            result.error_message = f"RDAP: {e}"

    # Phase 3: WHOIS (if enabled)
    if config.use_whois:
        whois_server = await discover_whois_server(tld, timeout=config.timeout)
        if whois_server:
            try:
                async with rate_limiter.acquire(whois_server, is_whois=True):
                    whois_result = await check_whois(
                        domain, whois_server, timeout=config.timeout
                    )
                if whois_result is not None:
                    result.availability = whois_result
                    result.method = CheckMethod.WHOIS
                    return result
            except Exception as e:
                result.error_message = f"WHOIS: {e}"

    # No definitive answer
    if result.dns_has_ns is False:
        result.availability = Availability.AVAILABLE
        result.method = CheckMethod.DNS
    else:
        result.availability = Availability.UNKNOWN

    return result


async def check_all_domains(
    words: list[str],
    tld_list: list[str],
    state: TaskState,
    state_manager: StateManager,
    rdap_bootstrap: dict[str, str],
    config: CheckerConfig,
    progress_callback: Optional[Callable[[CheckResult, int, int], None]] = None,
) -> TaskState:
    """Check all word+TLD combinations, saving checkpoints along the way."""

    all_combos = [(w, t) for w in words for t in tld_list]
    already_checked = set(state.results.keys())
    remaining = [(w, t) for w, t in all_combos if f"{w}.{t}" not in already_checked]

    state.total_combinations = len(all_combos)
    state.checked_count = len(already_checked)

    resolver = make_resolver(config.nameservers)
    rate_limiter = RateLimiter(
        global_limit=config.concurrency,
        per_host_limit=config.rdap_per_host,
        whois_per_host_limit=config.whois_per_host,
    )

    dns_semaphore = asyncio.Semaphore(config.dns_concurrency)
    checks_since_save = 0

    async with httpx.AsyncClient(
        follow_redirects=True,
        limits=httpx.Limits(
            max_connections=config.concurrency,
            max_keepalive_connections=50,
        ),
    ) as http_client:

        async def _check_one(word: str, tld: str) -> CheckResult:
            nonlocal checks_since_save
            async with dns_semaphore:
                result = await check_single_domain(
                    word, tld, resolver, rdap_bootstrap,
                    http_client, rate_limiter, config,
                )

            state.results[result.domain] = result
            state.checked_count += 1

            checks_since_save += 1
            if checks_since_save >= config.checkpoint_every:
                checks_since_save = 0
                state_manager.save(state)

            if progress_callback:
                progress_callback(result, state.checked_count, state.total_combinations)

            return result

        # Run all remaining checks with concurrency control
        tasks = [_check_one(w, t) for w, t in remaining]

        # Process in batches to avoid creating too many tasks at once
        batch_size = config.concurrency * 2
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i : i + batch_size]
            await asyncio.gather(*batch, return_exceptions=True)

    state.completed = True
    state.updated_at = time.time()
    state_manager.save(state)
    return state
