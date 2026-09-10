"""Run the Overview check suite and collect AirPlay devices."""

from __future__ import annotations

from dataclasses import dataclass

from despairplay.engine.host import Host, LiveHost
from despairplay.engine.mdns import (
    AirPlayDevice,
    check_mdns_speakers,
    group_devices,
)
from despairplay.engine.network import (
    check_avahi_daemon,
    check_avahi_packages,
    check_firewall,
    check_mdns_udp,
    check_nsswitch_mdns,
    check_vpn_interfaces,
)
from despairplay.engine.pipewire import (
    check_pipewire_user_units,
    check_raop_autostart,
    check_raop_discover_loaded,
    check_raop_modules,
    check_raop_sinks,
    raop_sink_labels,
)
from despairplay.engine.result import CheckResult


@dataclass(frozen=True)
class ScanResult:
    checks: tuple[CheckResult, ...]
    devices: tuple[AirPlayDevice, ...]


def run_scan(host: Host | None = None) -> ScanResult:
    probe = host if host is not None else LiveHost()
    checks = (
        check_pipewire_user_units(probe),
        check_raop_modules(probe),
        check_raop_autostart(probe),
        check_raop_discover_loaded(probe),
        check_raop_sinks(probe),
        check_avahi_packages(probe),
        check_avahi_daemon(probe),
        check_nsswitch_mdns(probe),
        check_mdns_udp(probe),
        check_firewall(probe),
        check_vpn_interfaces(probe),
        check_mdns_speakers(probe),
    )
    records = probe.avahi_records()
    labels = raop_sink_labels(probe.pw_dump_json())
    devices = group_devices(records or (), labels) if records is not None else ()
    return ScanResult(checks=checks, devices=devices)


def run_checks(host: Host | None = None) -> tuple[CheckResult, ...]:
    return run_scan(host).checks
