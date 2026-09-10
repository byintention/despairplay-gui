"""Check and fix engine. Pure Python — do not import GTK here."""

from __future__ import annotations

from despairplay.engine.fixes import apply_user_fix, plan_user_fix
from despairplay.engine.mdns import AirPlayDevice
from despairplay.engine.pipewire import LocalSink
from despairplay.engine.result import CheckResult, Group, Status
from despairplay.engine.suite import ScanResult, run_checks, run_scan

__all__ = [
    "AirPlayDevice",
    "CheckResult",
    "Group",
    "LocalSink",
    "ScanResult",
    "Status",
    "apply_user_fix",
    "plan_user_fix",
    "run_checks",
    "run_scan",
]
