from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import httpx

RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
CACHE_FILENAME = "rdap_bootstrap.json"
DEFAULT_MAX_AGE_HOURS = 24


async def load_rdap_bootstrap(
    cache_dir: Path,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, str]:
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
                resp = await client.get(RDAP_BOOTSTRAP_URL)
                resp.raise_for_status()
                cache_path.write_text(resp.text, encoding="utf-8")
        except (httpx.HTTPError, OSError):
            if not cache_path.exists():
                raise RuntimeError(
                    f"Failed to download RDAP bootstrap and no cache at {cache_path}"
                )

    return _parse_bootstrap(cache_path)


def _parse_bootstrap(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}

    for service in data.get("services", []):
        if len(service) < 2:
            continue
        tld_list = service[0]
        url_list = service[1]
        if not url_list:
            continue
        base_url = url_list[0].rstrip("/")
        for tld in tld_list:
            mapping[tld.lower()] = base_url

    return mapping


def get_rdap_url(bootstrap: dict[str, str], tld: str) -> Optional[str]:
    return bootstrap.get(tld.lower())
