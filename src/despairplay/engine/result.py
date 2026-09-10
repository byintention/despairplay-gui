"""Check outcome types. No GTK."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


class Group(str, Enum):
    SYSTEM = "system"
    NETWORK = "network"
    SPEAKERS = "speakers"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    title: str
    status: Status
    reason: str
    evidence: str
    group: Group
    fix_id: str | None = None
