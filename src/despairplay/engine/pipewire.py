"""PipeWire session, RAOP modules, drop-in, and graph checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from despairplay.engine.fixes import FIX_ENABLE_RAOP_DISCOVER
from despairplay.engine.host import PIPEWIRE_USER_UNITS, Host
from despairplay.engine.result import CheckResult, Group, Status

_UNITS_EVIDENCE = "systemctl --user is-active " + " ".join(PIPEWIRE_USER_UNITS)
_MODULE_EVIDENCE = "/usr/lib/*/pipewire-0.3/libpipewire-module-raop-*.so"
_DUMP_EVIDENCE = "pw-dump"
_RAOP_DISCOVER_NAME = "libpipewire-module-raop-discover"


def _as_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def raop_discover_is_loaded(dump: object) -> bool:
    if not isinstance(dump, list):
        return False
    for obj in dump:
        item = _as_mapping(obj)
        if item.get("type") != "PipeWire:Interface:Module":
            continue
        info = _as_mapping(item.get("info"))
        props = _as_mapping(info.get("props"))
        names = {info.get("name"), props.get("module.name")}
        if _RAOP_DISCOVER_NAME in names:
            return True
    return False


def raop_sink_labels(dump: object) -> tuple[str, ...]:
    if not isinstance(dump, list):
        return ()
    labels: list[str] = []
    for obj in dump:
        item = _as_mapping(obj)
        if item.get("type") != "PipeWire:Interface:Node":
            continue
        info = _as_mapping(item.get("info"))
        props = _as_mapping(info.get("props"))
        if props.get("media.class") != "Audio/Sink":
            continue
        if not _is_raop_sink(props):
            continue
        label = str(
            props.get("node.description") or props.get("node.name") or "RAOP sink"
        )
        labels.append(label)
    return tuple(labels)


def _is_raop_sink(props: Mapping[str, Any]) -> bool:
    factory = str(props.get("factory.name") or "").lower()
    name = str(props.get("node.name") or "").lower()
    media_name = str(props.get("media.name") or "").lower()
    sess = str(props.get("sess.media") or "").lower()
    if sess == "raop" or media_name.startswith("raop"):
        return True
    if "raop" in factory or name.startswith("raop"):
        return True
    return any(str(key).lower().startswith("raop.") for key in props)


def check_pipewire_user_units(host: Host) -> CheckResult:
    inactive = [
        unit for unit in PIPEWIRE_USER_UNITS if not host.user_unit_is_active(unit)
    ]
    if not inactive:
        return CheckResult(
            check_id="pipewire-user-units",
            title="PipeWire user session",
            status=Status.OK,
            reason="pipewire, pipewire-pulse, and wireplumber are running",
            evidence=_UNITS_EVIDENCE,
            group=Group.SYSTEM,
        )
    names = ", ".join(inactive)
    return CheckResult(
        check_id="pipewire-user-units",
        title="PipeWire user session",
        status=Status.FAIL,
        reason=f"Not running: {names}",
        evidence=_UNITS_EVIDENCE,
        group=Group.SYSTEM,
    )


def check_raop_modules(host: Host) -> CheckResult:
    discover = host.raop_discover_path()
    sink = host.raop_sink_path()
    missing: list[str] = []
    if discover is None:
        missing.append("raop-discover")
    if sink is None:
        missing.append("raop-sink")
    if discover is not None and sink is not None:
        return CheckResult(
            check_id="raop-modules",
            title="AirPlay (RAOP) modules",
            status=Status.OK,
            reason="discover and sink modules are installed",
            evidence=f"{discover}; {sink}",
            group=Group.SYSTEM,
        )
    return CheckResult(
        check_id="raop-modules",
        title="AirPlay (RAOP) modules",
        status=Status.FAIL,
        reason=f"Missing: {', '.join(missing)} (package libpipewire-0.3-modules)",
        evidence=_MODULE_EVIDENCE,
        group=Group.SYSTEM,
    )


def check_raop_autostart(host: Host) -> CheckResult:
    user = host.raop_user_dropins()
    system = host.raop_system_dropins()
    enabled = user + system
    if enabled:
        paths = "; ".join(str(path) for path in enabled)
        return CheckResult(
            check_id="raop-autostart",
            title="AirPlay autostart drop-in",
            status=Status.OK,
            reason="RAOP discover is set to load on login",
            evidence=paths,
            group=Group.SYSTEM,
        )
    toggle = host.gnome_airplay_toggle_path()
    if toggle is not None:
        return CheckResult(
            check_id="raop-autostart",
            title="AirPlay autostart drop-in",
            status=Status.OK,
            reason=(
                "GNOME AirPlay toggle is installed; speakers appear when you turn it on"
            ),
            evidence=str(toggle),
            group=Group.SYSTEM,
        )
    avail = host.raop_avail_template()
    dump = host.pw_dump_json()
    sinks_live = bool(dump is not None and raop_sink_labels(dump))
    if avail is not None:
        status = Status.WARN
        reason = f"Template exists but is not enabled: {avail.name}"
        evidence = str(avail)
    elif sinks_live:
        status = Status.WARN
        reason = (
            "Speakers are visible now, but there is no drop-in so this may not "
            "survive logout"
        )
        evidence = "~/.config/pipewire/pipewire.conf.d/*raop*"
    else:
        status = Status.FAIL
        reason = "No PipeWire RAOP drop-in in user or system config"
        evidence = "~/.config/pipewire/pipewire.conf.d/*raop*"
    return CheckResult(
        check_id="raop-autostart",
        title="AirPlay autostart drop-in",
        status=status,
        reason=reason,
        evidence=evidence,
        group=Group.SYSTEM,
        fix_id=FIX_ENABLE_RAOP_DISCOVER,
    )


def check_raop_discover_loaded(host: Host) -> CheckResult:
    dump = host.pw_dump_json()
    if dump is not None and raop_discover_is_loaded(dump):
        return CheckResult(
            check_id="raop-discover-loaded",
            title="AirPlay discover module loaded",
            status=Status.OK,
            reason="libpipewire-module-raop-discover is in the graph",
            evidence=_DUMP_EVIDENCE,
            group=Group.SYSTEM,
        )
    if host.pactl_raop_discover_loaded():
        return CheckResult(
            check_id="raop-discover-loaded",
            title="AirPlay discover module loaded",
            status=Status.OK,
            reason="pactl module-raop-discover is loaded (GNOME toggle)",
            evidence="pactl list short modules",
            group=Group.SYSTEM,
        )
    if dump is None:
        return CheckResult(
            check_id="raop-discover-loaded",
            title="AirPlay discover module loaded",
            status=Status.WARN,
            reason="Could not read the PipeWire graph (pw-dump)",
            evidence=_DUMP_EVIDENCE,
            group=Group.SYSTEM,
        )
    labels = raop_sink_labels(dump)
    if labels:
        return CheckResult(
            check_id="raop-discover-loaded",
            title="AirPlay discover module loaded",
            status=Status.OK,
            reason="RAOP sinks are active (discover may be via pipewire-pulse)",
            evidence=_DUMP_EVIDENCE,
            group=Group.SYSTEM,
        )
    can_fix = (
        host.raop_discover_path() is not None
        and host.gnome_airplay_toggle_path() is None
    )
    if can_fix:
        reason = "RAOP discover is installed but not loaded"
        fix_id = FIX_ENABLE_RAOP_DISCOVER
    elif host.gnome_airplay_toggle_path() is not None:
        reason = "GNOME AirPlay toggle is off; turn it on to discover speakers"
        fix_id = None
    else:
        reason = "RAOP discover module is not loaded"
        fix_id = None
    return CheckResult(
        check_id="raop-discover-loaded",
        title="AirPlay discover module loaded",
        status=Status.FAIL,
        reason=reason,
        evidence=_DUMP_EVIDENCE,
        group=Group.SYSTEM,
        fix_id=fix_id,
    )


def check_raop_sinks(host: Host) -> CheckResult:
    dump = host.pw_dump_json()
    if dump is None:
        return CheckResult(
            check_id="raop-sinks",
            title="AirPlay sinks",
            status=Status.WARN,
            reason="Could not read the PipeWire graph (pw-dump)",
            evidence=_DUMP_EVIDENCE,
            group=Group.SYSTEM,
        )
    labels = raop_sink_labels(dump)
    if labels:
        return CheckResult(
            check_id="raop-sinks",
            title="AirPlay sinks",
            status=Status.OK,
            reason=", ".join(labels),
            evidence=_DUMP_EVIDENCE,
            group=Group.SYSTEM,
        )
    return CheckResult(
        check_id="raop-sinks",
        title="AirPlay sinks",
        status=Status.WARN,
        reason="No AirPlay sinks in the graph yet",
        evidence=_DUMP_EVIDENCE,
        group=Group.SYSTEM,
    )
