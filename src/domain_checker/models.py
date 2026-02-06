from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Availability(Enum):
    AVAILABLE = "available"
    REGISTERED = "registered"
    UNKNOWN = "unknown"
    ERROR = "error"
    NO_SERVER = "no_server"  # TLD has no WHOIS/RDAP server


class CheckMethod(Enum):
    DNS = "dns"
    RDAP = "rdap"
    WHOIS = "whois"
    NONE = "none"


@dataclass
class CheckResult:
    domain: str
    word: str
    tld: str
    availability: Availability = Availability.UNKNOWN
    method: CheckMethod = CheckMethod.NONE
    dns_has_ns: Optional[bool] = None
    rdap_status: Optional[int] = None
    error_message: Optional[str] = None
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "word": self.word,
            "tld": self.tld,
            "availability": self.availability.value,
            "method": self.method.value,
            "dns_has_ns": self.dns_has_ns,
            "rdap_status": self.rdap_status,
            "error_message": self.error_message,
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CheckResult:
        return cls(
            domain=d["domain"],
            word=d["word"],
            tld=d["tld"],
            availability=Availability(d["availability"]),
            method=CheckMethod(d["method"]),
            dns_has_ns=d.get("dns_has_ns"),
            rdap_status=d.get("rdap_status"),
            error_message=d.get("error_message"),
            checked_at=d.get("checked_at", 0),
        )


@dataclass
class TaskState:
    words: list[str]
    tld_list: list[str]
    results: dict[str, CheckResult] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed: bool = False
    total_combinations: int = 0
    checked_count: int = 0

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "words": self.words,
            "tld_list": self.tld_list,
            "total_combinations": self.total_combinations,
            "checked_count": self.checked_count,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed": self.completed,
            "results": {k: v.to_dict() for k, v in self.results.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> TaskState:
        state = cls(
            words=d["words"],
            tld_list=d["tld_list"],
            started_at=d.get("started_at", 0),
            updated_at=d.get("updated_at", 0),
            completed=d.get("completed", False),
            total_combinations=d.get("total_combinations", 0),
            checked_count=d.get("checked_count", 0),
        )
        state.results = {
            k: CheckResult.from_dict(v) for k, v in d.get("results", {}).items()
        }
        return state


@dataclass
class CheckerConfig:
    use_whois: bool = True
    dns_only: bool = False
    concurrency: int = 100
    dns_concurrency: int = 50
    rdap_per_host: int = 10
    whois_per_host: int = 3
    timeout: float = 10.0
    checkpoint_every: int = 50
    nameservers: Optional[list[str]] = None
    verbose: bool = False
    quiet: bool = False
