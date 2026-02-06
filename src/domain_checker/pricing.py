from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import httpx

PORKBUN_URL = "https://api.porkbun.com/api/json/v3/pricing/get"
CLOUDFLARE_URL = "https://cfdomainpricing.com/prices.json"
CACHE_FILENAME = "pricing.json"
DEFAULT_MAX_AGE_HOURS = 24


async def fetch_pricing(
    cache_dir: Path,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, TLDPrice]:
    """Fetch and merge pricing from Porkbun and Cloudflare.

    Returns a dict mapping lowercase TLD to its best price info.
    """
    cache_path = cache_dir / CACHE_FILENAME
    cache_dir.mkdir(parents=True, exist_ok=True)

    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < max_age_hours:
            return _load_cache(cache_path)

    porkbun = await _fetch_porkbun()
    cloudflare = await _fetch_cloudflare()
    merged = _merge(porkbun, cloudflare)

    # Cache the merged result
    data = {tld: p.to_dict() for tld, p in merged.items()}
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return merged


async def _fetch_porkbun() -> dict[str, TLDPrice]:
    prices: dict[str, TLDPrice] = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(PORKBUN_URL, json={})
            resp.raise_for_status()
            data = resp.json()

        for tld, info in data.get("pricing", {}).items():
            tld_lower = tld.lower()
            try:
                reg = float(info["registration"])
                renew = float(info["renewal"])
                prices[tld_lower] = TLDPrice(
                    registration=reg,
                    renewal=renew,
                    source="porkbun",
                )
            except (KeyError, ValueError, TypeError):
                continue
    except (httpx.HTTPError, OSError):
        pass
    return prices


async def _fetch_cloudflare() -> dict[str, TLDPrice]:
    prices: dict[str, TLDPrice] = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(CLOUDFLARE_URL)
            resp.raise_for_status()
            data = resp.json()

        for tld, info in data.items():
            tld_lower = tld.lower()
            try:
                reg = float(info["registration"])
                renew = float(info["renewal"])
                prices[tld_lower] = TLDPrice(
                    registration=reg,
                    renewal=renew,
                    source="cloudflare",
                )
            except (KeyError, ValueError, TypeError):
                continue
    except (httpx.HTTPError, OSError):
        pass
    return prices


def _merge(
    porkbun: dict[str, TLDPrice],
    cloudflare: dict[str, TLDPrice],
) -> dict[str, TLDPrice]:
    """Merge pricing, keeping the cheaper registration price when both exist."""
    merged: dict[str, TLDPrice] = {}

    all_tlds = set(porkbun) | set(cloudflare)
    for tld in all_tlds:
        pb = porkbun.get(tld)
        cf = cloudflare.get(tld)

        if pb and cf:
            merged[tld] = pb if pb.registration <= cf.registration else cf
        elif pb:
            merged[tld] = pb
        elif cf:
            merged[tld] = cf

    return merged


def _load_cache(path: Path) -> dict[str, TLDPrice]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {tld: TLDPrice.from_dict(d) for tld, d in data.items()}


def get_price(pricing: dict[str, TLDPrice], tld: str) -> Optional[TLDPrice]:
    return pricing.get(tld.lower())


class TLDPrice:
    __slots__ = ("registration", "renewal", "source")

    def __init__(self, registration: float, renewal: float, source: str):
        self.registration = registration
        self.renewal = renewal
        self.source = source

    def to_dict(self) -> dict:
        return {
            "registration": self.registration,
            "renewal": self.renewal,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TLDPrice:
        return cls(
            registration=d["registration"],
            renewal=d["renewal"],
            source=d["source"],
        )
