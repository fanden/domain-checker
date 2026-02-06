from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urlparse

import httpx

from .models import Availability
from .rate_limiter import RateLimiter
from .rdap_bootstrap import get_rdap_url

MAX_RETRIES = 3
BACKOFF_BASE = 2.0


async def check_rdap(
    domain: str,
    tld: str,
    rdap_bootstrap: dict[str, str],
    client: httpx.AsyncClient,
    rate_limiter: RateLimiter,
    timeout: float = 10.0,
) -> Optional[Availability]:
    """Query the RDAP server for domain availability.

    Returns AVAILABLE, REGISTERED, or None if inconclusive.
    """
    base_url = get_rdap_url(rdap_bootstrap, tld)
    if not base_url:
        return None

    url = f"{base_url}/domain/{domain}"
    host = urlparse(base_url).hostname or base_url

    for attempt in range(MAX_RETRIES):
        try:
            async with rate_limiter.acquire(host):
                resp = await client.get(url, timeout=timeout, follow_redirects=True)

            if resp.status_code == 200:
                return Availability.REGISTERED
            if resp.status_code == 404:
                return Availability.AVAILABLE
            if resp.status_code == 429:
                wait = BACKOFF_BASE ** (attempt + 1)
                await asyncio.sleep(wait)
                continue
            # Other status codes — inconclusive
            return None
        except (httpx.HTTPError, OSError, asyncio.TimeoutError):
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_BASE ** attempt)
                continue
            return None

    return None
