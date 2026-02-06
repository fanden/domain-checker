from __future__ import annotations

import time
from pathlib import Path

import httpx

IANA_TLD_URL = "https://data.iana.org/TLD/tlds-alpha-by-domain.txt"
CACHE_FILENAME = "tlds.txt"
DEFAULT_MAX_AGE_HOURS = 24


async def fetch_tld_list(
    cache_dir: Path,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    include_idn: bool = False,
) -> list[str]:
    cache_path = cache_dir / CACHE_FILENAME
    cache_dir.mkdir(parents=True, exist_ok=True)

    need_download = True
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < max_age_hours:
            need_download = False

    if need_download:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(IANA_TLD_URL)
                resp.raise_for_status()
                cache_path.write_text(resp.text, encoding="utf-8")
        except (httpx.HTTPError, OSError):
            if not cache_path.exists():
                raise RuntimeError(
                    f"Failed to download TLD list and no cache exists at {cache_path}"
                )

    return _parse_tld_file(cache_path, include_idn)


def _parse_tld_file(path: Path, include_idn: bool) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tlds = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tld = line.lower()
        if not include_idn and tld.startswith("xn--"):
            continue
        tlds.append(tld)
    tlds.sort()
    return tlds
