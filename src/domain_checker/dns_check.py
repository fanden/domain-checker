from __future__ import annotations

from typing import Optional

import dns.asyncresolver
import dns.exception
import dns.name
import dns.rdatatype
import dns.resolver


async def check_dns(
    domain: str,
    resolver: dns.asyncresolver.Resolver,
    timeout: float = 5.0,
) -> tuple[Optional[bool], Optional[bool]]:
    """Check DNS for NS records.

    Returns (has_ns, has_soa) where None means the check failed.
    has_ns=False from NXDOMAIN strongly suggests the domain is available.
    """
    has_ns: Optional[bool] = None
    has_soa: Optional[bool] = None

    try:
        answer = await resolver.resolve(domain, "NS", lifetime=timeout)
        has_ns = len(answer) > 0
    except dns.resolver.NXDOMAIN:
        has_ns = False
        has_soa = False
        return has_ns, has_soa
    except dns.resolver.NoAnswer:
        has_ns = False
    except (dns.exception.DNSException, OSError):
        has_ns = None

    if has_ns is False:
        try:
            answer = await resolver.resolve(domain, "SOA", lifetime=timeout)
            has_soa = len(answer) > 0
        except dns.resolver.NXDOMAIN:
            has_soa = False
        except dns.resolver.NoAnswer:
            has_soa = False
        except (dns.exception.DNSException, OSError):
            has_soa = None

    return has_ns, has_soa


def make_resolver(
    nameservers: Optional[list[str]] = None,
) -> dns.asyncresolver.Resolver:
    resolver = dns.asyncresolver.Resolver()
    if nameservers:
        resolver.nameservers = nameservers
    return resolver
