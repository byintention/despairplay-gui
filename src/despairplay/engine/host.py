"""Machine probes used by checks. Live host vs fakes in tests."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from despairplay.engine.mdns import MdnsRecord

log = logging.getLogger(__name__)

PIPEWIRE_USER_UNITS = (
    "pipewire.service",
    "pipewire-pulse.service",
    "wireplumber.service",
)

_RAOP_DISCOVER = "libpipewire-module-raop-discover.so"
_RAOP_SINK = "libpipewire-module-raop-sink.so"
_USR_LIB = Path("/usr/lib")
_ETC_CONF_D = Path("/etc/pipewire/pipewire.conf.d")
_AVAIL_DIR = Path("/usr/share/pipewire/pipewire.conf.avail")
_USER_CONF_D = Path.home() / ".config" / "pipewire" / "pipewire.conf.d"
_TOGGLE_UUID = "pipewire-airplay-toggle@craw0967.github.com"
_PACTL_RAOP = "module-raop-discover"


class Host(Protocol):
    def user_unit_is_active(self, unit: str) -> bool: ...

    def raop_discover_path(self) -> Path | None: ...

    def raop_sink_path(self) -> Path | None: ...

    def pw_dump_json(self) -> object | None: ...

    def raop_user_dropins(self) -> tuple[Path, ...]: ...

    def raop_system_dropins(self) -> tuple[Path, ...]: ...

    def raop_avail_template(self) -> Path | None: ...

    def pipewire_user_conf_d(self) -> Path: ...

    def restart_pipewire_user_session(self) -> None: ...

    def gnome_airplay_toggle_path(self) -> Path | None: ...

    def pactl_raop_discover_loaded(self) -> bool: ...

    def dpkg_is_installed(self, package: str) -> bool: ...

    def system_unit_is_active(self, unit: str) -> bool: ...

    def nsswitch_hosts_line(self) -> str | None: ...

    def udp_listen_ports(self) -> frozenset[int]: ...

    def ufw_status_text(self) -> str | None: ...

    def firewalld_is_running(self) -> bool: ...

    def firewalld_udp_port_allowed(self, port: int) -> bool | None: ...

    def network_interfaces(self) -> tuple[str, ...]: ...

    def avahi_records(self) -> tuple[MdnsRecord, ...] | None: ...


def find_gnome_airplay_toggle() -> Path | None:
    candidates = (
        Path.home() / ".local/share/gnome-shell/extensions" / _TOGGLE_UUID,
        Path("/usr/share/gnome-shell/extensions") / _TOGGLE_UUID,
    )
    for path in candidates:
        if path.is_dir():
            return path
    return None


def find_raop_module(filename: str) -> Path | None:
    """Ubuntu multiarch first, then /usr/lib/pipewire-0.3/."""
    direct = _USR_LIB / "pipewire-0.3" / filename
    if direct.is_file():
        return direct
    matches = sorted(
        path for path in _USR_LIB.glob(f"*/pipewire-0.3/{filename}") if path.is_file()
    )
    return matches[0] if matches else None


def raop_named_files(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and "raop" in path.name.lower()
        )
    )


def find_raop_avail_template() -> Path | None:
    for name in ("50-raop.conf", "raop.conf", "50-raop-discover.conf"):
        candidate = _AVAIL_DIR / name
        if candidate.is_file():
            return candidate
    matches = raop_named_files(_AVAIL_DIR)
    return matches[0] if matches else None


class LiveHost:
    """Talk to this machine. Not used by default pytest."""

    def __init__(self) -> None:
        self._avahi_fetched = False
        self._avahi_records: tuple[MdnsRecord, ...] | None = None

    def user_unit_is_active(self, unit: str) -> bool:
        try:
            completed = subprocess.run(
                ["systemctl", "--user", "is-active", "--quiet", unit],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("systemctl --user is-active %s failed: %s", unit, exc)
            return False
        return completed.returncode == 0

    def raop_discover_path(self) -> Path | None:
        return find_raop_module(_RAOP_DISCOVER)

    def raop_sink_path(self) -> Path | None:
        return find_raop_module(_RAOP_SINK)

    def pw_dump_json(self) -> object | None:
        try:
            completed = subprocess.run(
                ["pw-dump"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("pw-dump failed: %s", exc)
            return None
        if completed.returncode != 0:
            log.warning("pw-dump exited %s", completed.returncode)
            return None
        try:
            parsed: object = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            log.warning("pw-dump was not JSON: %s", exc)
            return None
        return parsed

    def raop_user_dropins(self) -> tuple[Path, ...]:
        return raop_named_files(_USER_CONF_D)

    def raop_system_dropins(self) -> tuple[Path, ...]:
        return raop_named_files(_ETC_CONF_D)

    def raop_avail_template(self) -> Path | None:
        return find_raop_avail_template()

    def pipewire_user_conf_d(self) -> Path:
        return _USER_CONF_D

    def restart_pipewire_user_session(self) -> None:
        try:
            completed = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "restart",
                    "pipewire",
                    "pipewire-pulse",
                    "wireplumber",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise OSError(f"Could not restart PipeWire: {exc}") from exc
        if completed.returncode != 0:
            detail = (
                completed.stderr or completed.stdout or "systemctl failed"
            ).strip()
            raise OSError(detail)

    def gnome_airplay_toggle_path(self) -> Path | None:
        return find_gnome_airplay_toggle()

    def pactl_raop_discover_loaded(self) -> bool:
        try:
            completed = subprocess.run(
                ["pactl", "list", "short", "modules"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("pactl list modules failed: %s", exc)
            return False
        if completed.returncode != 0:
            return False
        for line in completed.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == _PACTL_RAOP:
                return True
        return False

    def dpkg_is_installed(self, package: str) -> bool:
        try:
            completed = subprocess.run(
                ["dpkg-query", "-W", "-f", "${Status}", package],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("dpkg-query %s failed: %s", package, exc)
            return False
        if completed.returncode != 0:
            return False
        return completed.stdout.strip() == "install ok installed"

    def system_unit_is_active(self, unit: str) -> bool:
        try:
            completed = subprocess.run(
                ["systemctl", "is-active", "--quiet", unit],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("systemctl is-active %s failed: %s", unit, exc)
            return False
        return completed.returncode == 0

    def nsswitch_hosts_line(self) -> str | None:
        path = Path("/etc/nsswitch.conf")
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("could not read nsswitch.conf: %s", exc)
            return None
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("hosts:") or stripped.lower().startswith(
                "hosts "
            ):
                return stripped
        return None

    def udp_listen_ports(self) -> frozenset[int]:
        from despairplay.engine.network import parse_proc_net_udp

        ports: set[int] = set()
        for name in ("udp", "udp6"):
            path = Path("/proc/net") / name
            if not path.is_file():
                continue
            try:
                ports |= set(parse_proc_net_udp(path.read_text(encoding="utf-8")))
            except OSError as exc:
                log.warning("could not read %s: %s", path, exc)
        return frozenset(ports)

    def ufw_status_text(self) -> str | None:
        if shutil.which("ufw") is None:
            return None
        try:
            completed = subprocess.run(
                ["ufw", "status"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("ufw status failed: %s", exc)
            return None
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "ufw failed").strip()
            return f"Status: unknown\n{detail}"
        return completed.stdout

    def firewalld_is_running(self) -> bool:
        if shutil.which("firewall-cmd") is None:
            return False
        try:
            completed = subprocess.run(
                ["firewall-cmd", "--state"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("firewall-cmd --state failed: %s", exc)
            return False
        return completed.returncode == 0 and completed.stdout.strip() == "running"

    def firewalld_udp_port_allowed(self, port: int) -> bool | None:
        if not self.firewalld_is_running():
            return None
        try:
            completed = subprocess.run(
                ["firewall-cmd", f"--query-port={port}/udp"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("firewall-cmd --query-port %s failed: %s", port, exc)
            return None
        return completed.returncode == 0

    def network_interfaces(self) -> tuple[str, ...]:
        path = Path("/sys/class/net")
        if not path.is_dir():
            return ()
        try:
            return tuple(sorted(entry.name for entry in path.iterdir()))
        except OSError as exc:
            log.warning("could not list %s: %s", path, exc)
            return ()

    def avahi_records(self) -> tuple[MdnsRecord, ...] | None:
        if not self._avahi_fetched:
            from despairplay.engine.avahi_browse import browse_avahi

            self._avahi_records = browse_avahi()
            self._avahi_fetched = True
        return self._avahi_records
