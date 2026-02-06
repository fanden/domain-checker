from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class RateLimiter:
    def __init__(
        self,
        global_limit: int = 100,
        per_host_limit: int = 10,
        whois_per_host_limit: int = 3,
    ):
        self._global_sem = asyncio.Semaphore(global_limit)
        self._host_sems: dict[str, asyncio.Semaphore] = {}
        self._per_host_limit = per_host_limit
        self._whois_per_host_limit = whois_per_host_limit

    def _get_host_sem(self, host: str, is_whois: bool = False) -> asyncio.Semaphore:
        key = f"{'whois:' if is_whois else ''}{host}"
        if key not in self._host_sems:
            limit = self._whois_per_host_limit if is_whois else self._per_host_limit
            self._host_sems[key] = asyncio.Semaphore(limit)
        return self._host_sems[key]

    @asynccontextmanager
    async def acquire(
        self, host: str, is_whois: bool = False
    ) -> AsyncIterator[None]:
        host_sem = self._get_host_sem(host, is_whois)
        async with self._global_sem:
            async with host_sem:
                yield
