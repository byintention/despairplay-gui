"""Avahi, mDNS, firewall, and VPN checks. No GTK."""

from __future__ import annotations

import re

from despairplay.engine.host import Host
from despairplay.engine.result import CheckResult, Group, Status

AVAHI_PACKAGES = ("avahi-daemon", "avahi-utils", "libnss-mdns")
AVAHI_UNIT = "avahi-daemon.service"
MDNS_PORT = 5353
RAOP_UDP_PORTS = (6001, 6002)
VPN_PREFIXES = ("tun", "tap", "wg", "tailscale", "nordlynx", "proton", "zt")

_PACKAGES_EVIDENCE = "dpkg-query -W " + " ".join(AVAHI_PACKAGES)
_DAEMON_EVIDENCE = "systemctl is-active avahi-daemon"
_NSSWITCH_EVIDENCE = "/etc/nsswitch.conf"
_UDP_EVIDENCE = "/proc/net/udp"
_UFW_EVIDENCE = "ufw status"
_FIREWALLD_EVIDENCE = "firewall-cmd --query-port"
_IFACE_EVIDENCE = "/sys/class/net"
_MDNS_NSS = frozenset(
    {"mdns4_minimal", "mdns_minimal", "mdns6_minimal", "mdns4", "mdns"}
)
_UFW_UDP_PORT = re.compile(r"(\d+)(?::(\d+))?/udp")


def parse_proc_net_udp(text: str) -> frozenset[int]:
    """Local ports from a `/proc/net/udp` or `/proc/net/udp6` table."""
    ports: set[int] = set()
    for raw in text.splitlines()[1:]:
        parts = raw.split()
        if len(parts) < 2:
            continue
        local = parts[1]
        if ":" not in local:
            continue
        port_hex = local.rsplit(":", 1)[-1]
        try:
            ports.add(int(port_hex, 16))
        except ValueError:
            continue
    return frozenset(ports)


def nsswitch_hosts_has_mdns(line: str | None) -> bool:
    if line is None:
        return False
    stripped = line.split("#", 1)[0].strip()
    if not stripped.lower().startswith("hosts"):
        return False
    rest = stripped.split(":", 1)[-1]
    tokens = rest.replace("[", " ").replace("]", " ").split()
    return any(token in _MDNS_NSS for token in tokens)


def parse_ufw_active(text: str) -> bool | None:
    for raw in text.splitlines():
        stripped = raw.strip().lower()
        if stripped == "status: active":
            return True
        if stripped == "status: inactive":
            return False
    return None


def ufw_allows_udp_port(text: str, port: int) -> bool:
    for raw in text.splitlines():
        lower = raw.lower()
        if "allow" not in lower:
            continue
        for match in _UFW_UDP_PORT.finditer(lower):
            start = int(match.group(1))
            end = int(match.group(2) or match.group(1))
            if start <= port <= end:
                return True
    return False


def vpn_interface_names(interfaces: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    skip = {"lo", "docker0"}
    for name in interfaces:
        if name in skip:
            continue
        lower = name.lower()
        if any(lower == prefix or lower.startswith(prefix) for prefix in VPN_PREFIXES):
            found.append(name)
    return tuple(found)


def check_avahi_packages(host: Host) -> CheckResult:
    missing = [pkg for pkg in AVAHI_PACKAGES if not host.dpkg_is_installed(pkg)]
    if not missing:
        return CheckResult(
            check_id="avahi-packages",
            title="Avahi packages",
            status=Status.OK,
            reason="avahi-daemon, avahi-utils, and libnss-mdns are installed",
            evidence=_PACKAGES_EVIDENCE,
            group=Group.NETWORK,
        )
    required_missing = "avahi-daemon" in missing
    listed = ", ".join(missing)
    return CheckResult(
        check_id="avahi-packages",
        title="Avahi packages",
        status=Status.FAIL if required_missing else Status.WARN,
        reason=f"Missing: {listed}",
        evidence=_PACKAGES_EVIDENCE,
        group=Group.NETWORK,
    )


def check_avahi_daemon(host: Host) -> CheckResult:
    if host.system_unit_is_active(AVAHI_UNIT):
        return CheckResult(
            check_id="avahi-daemon",
            title="Avahi daemon",
            status=Status.OK,
            reason="avahi-daemon is running",
            evidence=_DAEMON_EVIDENCE,
            group=Group.NETWORK,
        )
    return CheckResult(
        check_id="avahi-daemon",
        title="Avahi daemon",
        status=Status.FAIL,
        reason="avahi-daemon is not running",
        evidence=_DAEMON_EVIDENCE,
        group=Group.NETWORK,
    )


def check_nsswitch_mdns(host: Host) -> CheckResult:
    line = host.nsswitch_hosts_line()
    if nsswitch_hosts_has_mdns(line):
        return CheckResult(
            check_id="nsswitch-mdns",
            title="mDNS name lookup",
            status=Status.OK,
            reason="nsswitch hosts line includes an mDNS plugin",
            evidence=_NSSWITCH_EVIDENCE,
            group=Group.NETWORK,
        )
    return CheckResult(
        check_id="nsswitch-mdns",
        title="mDNS name lookup",
        status=Status.WARN,
        reason=("hosts: has no mdns4_minimal / mdns_minimal; .local names may fail"),
        evidence=_NSSWITCH_EVIDENCE,
        group=Group.NETWORK,
    )


def check_mdns_udp(host: Host) -> CheckResult:
    if MDNS_PORT in host.udp_listen_ports():
        return CheckResult(
            check_id="mdns-udp-5353",
            title="mDNS port 5353",
            status=Status.OK,
            reason="UDP 5353 is listening",
            evidence=_UDP_EVIDENCE,
            group=Group.NETWORK,
        )
    return CheckResult(
        check_id="mdns-udp-5353",
        title="mDNS port 5353",
        status=Status.FAIL,
        reason="Nothing is listening on UDP 5353 (Avahi mDNS)",
        evidence=_UDP_EVIDENCE,
        group=Group.NETWORK,
    )


def check_firewall(host: Host) -> CheckResult:
    ufw_text = host.ufw_status_text()
    ufw_state = parse_ufw_active(ufw_text) if ufw_text is not None else False
    fw_running = host.firewalld_is_running()
    if ufw_text is not None and ufw_state is None:
        return CheckResult(
            check_id="firewall",
            title="Firewall",
            status=Status.WARN,
            reason="Could not read UFW status",
            evidence=_UFW_EVIDENCE,
            group=Group.NETWORK,
        )
    if not ufw_state and not fw_running:
        return CheckResult(
            check_id="firewall",
            title="Firewall",
            status=Status.OK,
            reason="No host firewall is active",
            evidence=_UFW_EVIDENCE,
            group=Group.NETWORK,
        )
    issues: list[str] = []
    status = Status.OK
    evidence = _UFW_EVIDENCE
    if ufw_state and ufw_text is not None:
        if not ufw_allows_udp_port(ufw_text, MDNS_PORT):
            issues.append("UFW does not allow UDP 5353")
            status = Status.FAIL
        elif not all(ufw_allows_udp_port(ufw_text, port) for port in RAOP_UDP_PORTS):
            issues.append("UFW allows mDNS but not RAOP UDP 6001-6002")
            status = Status.WARN
    if fw_running:
        evidence = _FIREWALLD_EVIDENCE
        mdns_ok = host.firewalld_udp_port_allowed(MDNS_PORT)
        if mdns_ok is False:
            issues.append("firewalld does not allow UDP 5353")
            status = Status.FAIL
        elif mdns_ok is True and not all(
            host.firewalld_udp_port_allowed(port) for port in RAOP_UDP_PORTS
        ):
            issues.append("firewalld may block RAOP UDP 6001-6002")
            if status is Status.OK:
                status = Status.WARN
    if not issues:
        return CheckResult(
            check_id="firewall",
            title="Firewall",
            status=Status.OK,
            reason="Firewall allows mDNS",
            evidence=evidence,
            group=Group.NETWORK,
        )
    return CheckResult(
        check_id="firewall",
        title="Firewall",
        status=status,
        reason="; ".join(issues),
        evidence=evidence,
        group=Group.NETWORK,
    )


def check_vpn_interfaces(host: Host) -> CheckResult:
    names = vpn_interface_names(host.network_interfaces())
    if not names:
        return CheckResult(
            check_id="vpn-interfaces",
            title="VPN",
            status=Status.OK,
            reason="No VPN interfaces detected",
            evidence=_IFACE_EVIDENCE,
            group=Group.NETWORK,
        )
    listed = ", ".join(names)
    noun = "interface" if len(names) == 1 else "interfaces"
    return CheckResult(
        check_id="vpn-interfaces",
        title="VPN",
        status=Status.WARN,
        reason=f"VPN {noun} {listed}; multicast/mDNS often fails on VPNs",
        evidence=_IFACE_EVIDENCE,
        group=Group.NETWORK,
    )
