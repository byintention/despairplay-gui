"""Shared Host fake for engine tests. No GTK."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from despairplay.engine.mdns import MdnsRecord
from despairplay.engine.network import AVAHI_PACKAGES, AVAHI_UNIT, MDNS_PORT


@dataclass
class FakeHost:
    units: dict[str, bool]
    discover: Path | None = None
    sink: Path | None = None
    dump: object | None = None
    user_dropins: tuple[Path, ...] = ()
    system_dropins: tuple[Path, ...] = ()
    avail: Path | None = None
    conf_d: Path = field(default_factory=lambda: Path("/tmp/despairplay-conf.d"))
    restarted: bool = False
    toggle_path: Path | None = None
    pactl_raop: bool = False
    packages: frozenset[str] = field(default_factory=lambda: frozenset(AVAHI_PACKAGES))
    system_units: dict[str, bool] = field(default_factory=lambda: {AVAHI_UNIT: True})
    nsswitch_hosts: str | None = "hosts: files mdns4_minimal [NOTFOUND=return] dns"
    udp_ports: frozenset[int] = field(default_factory=lambda: frozenset({MDNS_PORT}))
    ufw_status: str | None = None
    firewalld_running: bool = False
    firewalld_udp: frozenset[int] = field(default_factory=frozenset)
    interfaces: tuple[str, ...] = ("lo", "wlan0")
    avahi: tuple[MdnsRecord, ...] | None = ()

    def user_unit_is_active(self, unit: str) -> bool:
        return self.units.get(unit, False)

    def raop_discover_path(self) -> Path | None:
        return self.discover

    def raop_sink_path(self) -> Path | None:
        return self.sink

    def pw_dump_json(self) -> object | None:
        return self.dump

    def raop_user_dropins(self) -> tuple[Path, ...]:
        return self.user_dropins

    def raop_system_dropins(self) -> tuple[Path, ...]:
        return self.system_dropins

    def raop_avail_template(self) -> Path | None:
        return self.avail

    def pipewire_user_conf_d(self) -> Path:
        return self.conf_d

    def restart_pipewire_user_session(self) -> None:
        self.restarted = True

    def gnome_airplay_toggle_path(self) -> Path | None:
        return self.toggle_path

    def pactl_raop_discover_loaded(self) -> bool:
        return self.pactl_raop

    def dpkg_is_installed(self, package: str) -> bool:
        return package in self.packages

    def system_unit_is_active(self, unit: str) -> bool:
        if unit in self.system_units:
            return self.system_units[unit]
        if not unit.endswith(".service"):
            return self.system_units.get(f"{unit}.service", False)
        return False

    def nsswitch_hosts_line(self) -> str | None:
        return self.nsswitch_hosts

    def udp_listen_ports(self) -> frozenset[int]:
        return self.udp_ports

    def ufw_status_text(self) -> str | None:
        return self.ufw_status

    def firewalld_is_running(self) -> bool:
        return self.firewalld_running

    def firewalld_udp_port_allowed(self, port: int) -> bool | None:
        if not self.firewalld_running:
            return None
        return port in self.firewalld_udp

    def network_interfaces(self) -> tuple[str, ...]:
        return self.interfaces

    def avahi_records(self) -> tuple[MdnsRecord, ...] | None:
        return self.avahi
