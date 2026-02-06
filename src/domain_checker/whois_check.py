from __future__ import annotations

import asyncio
from typing import Optional

from .models import Availability

IANA_WHOIS = "whois.iana.org"

# Patterns indicating a domain is available
AVAILABLE_PATTERNS = [
    "no match",
    "not found",
    "no data found",
    "domain not found",
    "no entries found",
    "status: free",
    "status: available",
    "is available for registration",
    "no object found",
    "object does not exist",
    "nothing found",
]

# Patterns indicating a domain is registered
REGISTERED_PATTERNS = [
    "domain name:",
    "registrar:",
    "creation date:",
    "registered on:",
    "nserver:",
    "name server:",
    "status: active",
    "registry domain id:",
    "updated date:",
    "registrant:",
]

# Cache of TLD -> WHOIS server hostname
_whois_server_cache: dict[str, Optional[str]] = {}


async def _raw_whois_query(
    query: str, server: str, port: int = 43, timeout: float = 10.0
) -> str:
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(server, port), timeout=timeout
    )
    try:
        writer.write(f"{query}\r\n".encode("utf-8"))
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
        return data.decode("utf-8", errors="replace")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def discover_whois_server(tld: str, timeout: float = 10.0) -> Optional[str]:
    """Query whois.iana.org for the WHOIS server of a TLD."""
    if tld in _whois_server_cache:
        return _whois_server_cache[tld]

    try:
        response = await _raw_whois_query(tld, IANA_WHOIS, timeout=timeout)
        for line in response.splitlines():
            line = line.strip()
            if line.lower().startswith("whois:"):
                server = line.split(":", 1)[1].strip()
                if server:
                    _whois_server_cache[tld] = server
                    return server
        _whois_server_cache[tld] = None
        return None
    except (OSError, asyncio.TimeoutError):
        _whois_server_cache[tld] = None
        return None


async def check_whois(
    domain: str,
    whois_server: str,
    timeout: float = 10.0,
) -> Optional[Availability]:
    """Query WHOIS server for domain availability.

    Returns AVAILABLE, REGISTERED, or None if inconclusive.
    """
    try:
        response = await _raw_whois_query(domain, whois_server, timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return None

    lower = response.lower()

    for pattern in AVAILABLE_PATTERNS:
        if pattern in lower:
            return Availability.AVAILABLE

    for pattern in REGISTERED_PATTERNS:
        if pattern in lower:
            return Availability.REGISTERED

    # Response exists but couldn't determine — inconclusive
    if len(response.strip()) > 0:
        return None
    return None
