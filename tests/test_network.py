"""Parser and check tests for Avahi / mDNS / firewall / VPN."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from despairplay.engine.host import PIPEWIRE_USER_UNITS
from despairplay.engine.network import (
    check_avahi_daemon,
    check_avahi_packages,
    check_firewall,
    check_mdns_udp,
    check_nsswitch_mdns,
    check_vpn_interfaces,
    nsswitch_hosts_has_mdns,
    parse_proc_net_udp,
    parse_ufw_active,
    ufw_allows_udp_port,
    vpn_interface_names,
)
from despairplay.engine.result import Group, Status
from fakes import FakeHost

FIXTURES = Path(__file__).parent / "fixtures"


def _all_units_up() -> dict[str, bool]:
    return dict.fromkeys(PIPEWIRE_USER_UNITS, True)


def _host(**kwargs: Any) -> FakeHost:
    return FakeHost(units=_all_units_up(), **kwargs)


def test_parse_proc_net_udp_mdns() -> None:
    text = (FIXTURES / "proc-net-udp-mdns.txt").read_text(encoding="utf-8")
    assert 5353 in parse_proc_net_udp(text)


def test_parse_proc_net_udp_empty() -> None:
    text = (FIXTURES / "proc-net-udp-empty.txt").read_text(encoding="utf-8")
    assert parse_proc_net_udp(text) == frozenset()


def test_nsswitch_detects_mdns() -> None:
    mdns = (FIXTURES / "nsswitch-mdns.conf").read_text(encoding="utf-8")
    line = next(
        raw.strip() for raw in mdns.splitlines() if raw.strip().startswith("hosts:")
    )
    assert nsswitch_hosts_has_mdns(line) is True
    none = (FIXTURES / "nsswitch-no-mdns.conf").read_text(encoding="utf-8")
    line = next(
        raw.strip() for raw in none.splitlines() if raw.strip().startswith("hosts:")
    )
    assert nsswitch_hosts_has_mdns(line) is False


def test_ufw_active_allows_mdns() -> None:
    text = (FIXTURES / "ufw-active-mdns.txt").read_text(encoding="utf-8")
    assert parse_ufw_active(text) is True
    assert ufw_allows_udp_port(text, 5353) is True
    assert ufw_allows_udp_port(text, 6001) is True


def test_ufw_active_blocks_mdns() -> None:
    text = (FIXTURES / "ufw-active-no-mdns.txt").read_text(encoding="utf-8")
    assert parse_ufw_active(text) is True
    assert ufw_allows_udp_port(text, 5353) is False


def test_ufw_inactive() -> None:
    text = (FIXTURES / "ufw-inactive.txt").read_text(encoding="utf-8")
    assert parse_ufw_active(text) is False


def test_vpn_prefixes() -> None:
    assert vpn_interface_names(("lo", "wlan0", "tun0", "wg0")) == ("tun0", "wg0")
    assert vpn_interface_names(("lo", "docker0", "enp0s3")) == ()


def test_avahi_packages_ok() -> None:
    result = check_avahi_packages(_host())
    assert result.status is Status.OK
    assert result.group is Group.NETWORK


def test_avahi_packages_fail_without_daemon() -> None:
    result = check_avahi_packages(_host(packages=frozenset({"avahi-utils"})))
    assert result.status is Status.FAIL
    assert "avahi-daemon" in result.reason


def test_avahi_packages_warn_without_utils() -> None:
    result = check_avahi_packages(
        _host(packages=frozenset({"avahi-daemon", "libnss-mdns"}))
    )
    assert result.status is Status.WARN
    assert "avahi-utils" in result.reason


def test_avahi_daemon_fail() -> None:
    result = check_avahi_daemon(_host(system_units={"avahi-daemon.service": False}))
    assert result.status is Status.FAIL


def test_nsswitch_warn_without_mdns() -> None:
    result = check_nsswitch_mdns(_host(nsswitch_hosts="hosts: files dns"))
    assert result.status is Status.WARN
    assert result.fix_id is None


def test_mdns_udp_fail() -> None:
    result = check_mdns_udp(_host(udp_ports=frozenset()))
    assert result.status is Status.FAIL


def test_firewall_ok_when_inactive() -> None:
    result = check_firewall(_host(ufw_status="Status: inactive\n"))
    assert result.status is Status.OK


def test_firewall_fail_when_ufw_blocks_mdns() -> None:
    text = (FIXTURES / "ufw-active-no-mdns.txt").read_text(encoding="utf-8")
    result = check_firewall(_host(ufw_status=text))
    assert result.status is Status.FAIL
    assert "5353" in result.reason


def test_firewall_warn_when_ufw_missing_raop_ports() -> None:
    text = (FIXTURES / "ufw-active-mdns-no-raop.txt").read_text(encoding="utf-8")
    result = check_firewall(_host(ufw_status=text))
    assert result.status is Status.WARN
    assert "6001" in result.reason


def test_firewall_ok_when_ufw_allows_mdns() -> None:
    text = (FIXTURES / "ufw-active-mdns.txt").read_text(encoding="utf-8")
    result = check_firewall(_host(ufw_status=text))
    assert result.status is Status.OK


def test_firewall_fail_when_firewalld_blocks_mdns() -> None:
    result = check_firewall(_host(firewalld_running=True, firewalld_udp=frozenset()))
    assert result.status is Status.FAIL


def test_vpn_warns() -> None:
    result = check_vpn_interfaces(_host(interfaces=("lo", "wlan0", "tailscale0")))
    assert result.status is Status.WARN
    assert "tailscale0" in result.reason
