"""PipeWire session, RAOP modules, drop-in, graph, and local sinks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from despairplay.engine.fixes import FIX_ENABLE_RAOP_DISCOVER
from despairplay.engine.host import PIPEWIRE_USER_UNITS, Host
from despairplay.engine.result import CheckResult, Group, Status

_UNITS_EVIDENCE = "systemctl --user is-active " + " ".join(PIPEWIRE_USER_UNITS)
_MODULE_EVIDENCE = "/usr/lib/*/pipewire-0.3/libpipewire-module-raop-*.so"
_DUMP_EVIDENCE = "pw-dump"
_RAOP_DISCOVER_NAME = "libpipewire-module-raop-discover"
_DEFAULT_SINK_KEY = "default.audio.sink"
_ICON_PREFIXES = (
    ("audio-headset", "audio-headset-symbolic"),
    ("audio-headphones", "audio-headphones-symbolic"),
    ("audio-speakers", "audio-speakers-symbolic"),
    ("audio-card", "audio-card-symbolic"),
)


@dataclass(frozen=True)
class LocalSink:
    key: str
    name: str
    node_name: str
    description: str
    nick: str
    profile: str
    icon_name: str
    is_default: bool
    ports: tuple[str, ...]
    active_port: str | None
    is_loaded: bool = True


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


def _object_id(item: Mapping[str, Any]) -> int | None:
    return _as_int(item.get("id"))


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _info(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(item.get("info"))


def _props(item: Mapping[str, Any]) -> Mapping[str, Any]:
    info = _info(item)
    props = _as_mapping(info.get("props"))
    if props:
        return props
    return _as_mapping(item.get("props"))


def _params(item: Mapping[str, Any]) -> Mapping[str, Any]:
    info = _info(item)
    params = info.get("params")
    if params is None:
        params = item.get("params")
    return _as_mapping(params)


def _metadata_entries(item: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = item.get("metadata")
    if raw is None:
        raw = _info(item).get("metadata")
    if not isinstance(raw, list):
        return ()
    return tuple(_as_mapping(entry) for entry in raw)


def _sink_name_from_meta_value(value: object) -> str | None:
    if isinstance(value, Mapping):
        name = value.get("name")
        return str(name) if name else None
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return text or None
            if isinstance(parsed, Mapping):
                name = parsed.get("name")
                return str(name) if name else None
        return text or None
    return None


def default_audio_sink_name(dump: object) -> str | None:
    if not isinstance(dump, list):
        return None
    found: str | None = None
    for obj in dump:
        item = _as_mapping(obj)
        if item.get("type") != "PipeWire:Interface:Metadata":
            continue
        for entry in _metadata_entries(item):
            if entry.get("key") != _DEFAULT_SINK_KEY:
                continue
            name = _sink_name_from_meta_value(entry.get("value"))
            if name:
                found = name
    return found


def _route_maps(params: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    raw = params.get(key)
    if not isinstance(raw, list):
        return ()
    return tuple(_as_mapping(item) for item in raw)


def _is_output_route(route: Mapping[str, Any]) -> bool:
    direction = str(route.get("direction") or "").lower()
    if direction == "output":
        return True
    name = str(route.get("name") or "").lower()
    return "output" in name and "input" not in name


def _route_label(route: Mapping[str, Any]) -> str:
    return str(route.get("description") or route.get("name") or "Port")


def _spa_info_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, list) or len(raw) < 3:
        return {}
    items = raw[1:]
    parsed: dict[str, str] = {}
    for index in range(0, len(items) - 1, 2):
        parsed[str(items[index])] = str(items[index + 1])
    return parsed


def _profile_indexes(route: Mapping[str, Any]) -> tuple[int, ...]:
    raw = route.get("profiles")
    if not isinstance(raw, list):
        return ()
    indexes: list[int] = []
    for item in raw:
        value = _as_int(item)
        if value is not None:
            indexes.append(value)
    return tuple(indexes)


def _route_available(route: Mapping[str, Any]) -> str:
    return str(route.get("available") or "").lower()


@dataclass(frozen=True)
class _CardProfile:
    index: int
    name: str
    description: str


@dataclass(frozen=True)
class _CardRoute:
    name: str
    label: str
    available: str
    profile_indexes: tuple[int, ...]
    port_type: str
    icon_hint: str


@dataclass(frozen=True)
class _Card:
    device_id: int
    device_name: str
    device_label: str
    icon_name: str
    active_profile_index: int | None
    active_route_name: str | None
    active_route_label: str | None
    profiles: tuple[_CardProfile, ...]
    routes: tuple[_CardRoute, ...]


def _parse_card_route(route: Mapping[str, Any]) -> _CardRoute:
    info = _spa_info_map(route.get("info"))
    return _CardRoute(
        name=str(route.get("name") or ""),
        label=_route_label(route),
        available=_route_available(route),
        profile_indexes=_profile_indexes(route),
        port_type=str(info.get("port.type") or ""),
        icon_hint=str(info.get("device.icon_name") or ""),
    )


def _parse_cards(dump: list[object]) -> dict[int, _Card]:
    cards: dict[int, _Card] = {}
    for obj in dump:
        item = _as_mapping(obj)
        if item.get("type") != "PipeWire:Interface:Device":
            continue
        device_id = _object_id(item)
        if device_id is None:
            continue
        props = _props(item)
        params = _params(item)
        profiles: list[_CardProfile] = []
        for raw in _route_maps(params, "EnumProfile"):
            index = _as_int(raw.get("index"))
            name = str(raw.get("name") or "")
            if index is None or not name:
                continue
            profiles.append(
                _CardProfile(
                    index=index,
                    name=name,
                    description=str(raw.get("description") or ""),
                )
            )
        active_rows = _route_maps(params, "Profile")
        active_index = _as_int(active_rows[0].get("index")) if active_rows else None
        enum_routes = tuple(
            _parse_card_route(route)
            for route in _route_maps(params, "EnumRoute")
            if _is_output_route(route)
        )
        active_routes = tuple(
            _parse_card_route(route)
            for route in _route_maps(params, "Route")
            if _is_output_route(route)
        )
        active = active_routes[0] if active_routes else None
        cards[device_id] = _Card(
            device_id=device_id,
            device_name=str(props.get("device.name") or ""),
            device_label=str(
                props.get("device.description") or props.get("device.nick") or ""
            ),
            icon_name=str(props.get("device.icon-name") or ""),
            active_profile_index=active_index,
            active_route_name=active.name if active is not None else None,
            active_route_label=active.label if active is not None else None,
            profiles=tuple(profiles),
            routes=enum_routes,
        )
    return cards


def _profile_output_suffix(profile_name: str) -> str | None:
    if not profile_name.startswith("output:"):
        return None
    output_part = profile_name.removeprefix("output:").split("+", 1)[0]
    if not output_part or output_part == "off" or output_part.startswith("pro"):
        return None
    return output_part


def _predicted_sink_name(device_name: str, profile_name: str) -> str:
    suffix = _profile_output_suffix(profile_name)
    if not suffix or not device_name.startswith("alsa_card."):
        return ""
    card = device_name.removeprefix("alsa_card.")
    return f"alsa_output.{card}.{suffix}"


def _best_output_profile(route: _CardRoute, card: _Card) -> _CardProfile | None:
    by_index = {item.index: item for item in card.profiles}
    ranked: list[tuple[tuple[int, int], _CardProfile]] = []
    for index in route.profile_indexes:
        profile = by_index.get(index)
        if profile is None:
            continue
        if _profile_output_suffix(profile.name) is None:
            continue
        score = (0 if "+" in profile.name else 1, 1 if "stereo" in profile.name else 0)
        ranked.append((score, profile))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _ports_for_live_sink(card: _Card) -> tuple[tuple[str, ...], str | None]:
    active_label = card.active_route_label
    if card.active_profile_index is None or not any(
        route.profile_indexes for route in card.routes
    ):
        ports = tuple(route.label for route in card.routes if route.available != "no")
        if not ports and active_label:
            ports = (active_label,)
        return ports, active_label
    ports = tuple(
        route.label
        for route in card.routes
        if card.active_profile_index in route.profile_indexes
        and (route.available != "no" or route.name == card.active_route_name)
    )
    if not ports and active_label:
        ports = (active_label,)
    return ports, active_label


def _playback_channels(dump: list[object], node_id: int) -> tuple[str, ...]:
    channels: list[tuple[int, str]] = []
    for obj in dump:
        item = _as_mapping(obj)
        if item.get("type") != "PipeWire:Interface:Port":
            continue
        info = _info(item)
        props = _props(item)
        port_node = _as_int(props.get("node.id"))
        if port_node != node_id:
            continue
        direction = str(info.get("direction") or props.get("port.direction") or "")
        name = str(props.get("port.name") or "")
        if direction.lower() in {"output", "out"} or name.startswith("monitor"):
            continue
        label = str(props.get("audio.channel") or name)
        if not label or label.upper() == "UNK":
            continue
        index = _as_int(props.get("port.id")) or 0
        channels.append((index, label))
    channels.sort()
    return tuple(label for _index, label in channels)


def _symbolic_icon(props: Mapping[str, Any], *, active_port: str | None) -> str:
    for key in ("device.icon-name", "media.icon-name"):
        raw = str(props.get(key) or "")
        if raw.endswith("-symbolic"):
            return raw
        for prefix, icon in _ICON_PREFIXES:
            if raw == prefix or raw.startswith(f"{prefix}-"):
                return icon
    blob = " ".join(
        [
            str(props.get("device.profile.name") or ""),
            str(props.get("device.profile.description") or ""),
            str(props.get("node.name") or ""),
            str(active_port or ""),
        ]
    ).lower()
    if "headset" in blob:
        return "audio-headset-symbolic"
    if "headphone" in blob:
        return "audio-headphones-symbolic"
    if "hdmi" in blob or "displayport" in blob or "spdif" in blob or "iec958" in blob:
        return "audio-card-symbolic"
    if "usb" in blob:
        return "audio-card-symbolic"
    return "audio-speakers-symbolic"


def _icon_for_route(route: _CardRoute, props: Mapping[str, Any]) -> str:
    hint = route.icon_hint
    if hint.endswith("-symbolic"):
        return hint
    for prefix, icon in _ICON_PREFIXES:
        if hint == prefix or hint.startswith(f"{prefix}-"):
            return icon
    port = route.port_type.lower()
    if port in {"headphones"}:
        return "audio-headphones-symbolic"
    if port in {"headset"}:
        return "audio-headset-symbolic"
    if port in {"hdmi", "spdif", "iec958"}:
        return "audio-card-symbolic"
    return _symbolic_icon(props, active_port=route.label)


def local_sinks(dump: object) -> tuple[LocalSink, ...]:
    if not isinstance(dump, list):
        return ()
    default_name = default_audio_sink_name(dump)
    cards = _parse_cards(dump)
    sinks: list[LocalSink] = []
    loaded_keys: set[str] = set()
    for obj in dump:
        item = _as_mapping(obj)
        if item.get("type") != "PipeWire:Interface:Node":
            continue
        props = _props(item)
        if props.get("media.class") != "Audio/Sink":
            continue
        if _is_raop_sink(props):
            continue
        node_name = str(props.get("node.name") or "")
        if not node_name or node_name == "auto_null":
            continue
        description = str(props.get("node.description") or "")
        nick = str(props.get("node.nick") or "")
        profile_label = str(
            props.get("device.profile.description")
            or props.get("device.profile.name")
            or ""
        )
        device_id = _as_int(props.get("device.id"))
        node_id = _object_id(item)
        card = cards.get(device_id) if device_id is not None else None
        if card is not None:
            ports, active_port = _ports_for_live_sink(card)
        else:
            ports = _playback_channels(dump, node_id) if node_id is not None else ()
            active_port = None
        if active_port is None and len(ports) == 1:
            active_port = ports[0]
        name = description or nick or node_name
        loaded_keys.add(node_name)
        sinks.append(
            LocalSink(
                key=f"pc:{node_name}",
                name=name,
                node_name=node_name,
                description=description,
                nick=nick,
                profile=profile_label,
                icon_name=_symbolic_icon(props, active_port=active_port),
                is_default=bool(default_name) and node_name == default_name,
                ports=ports,
                active_port=active_port,
                is_loaded=True,
            )
        )
    for card in cards.values():
        for route in card.routes:
            if route.available == "no":
                continue
            if not route.name or route.name == card.active_route_name:
                continue
            if not route.profile_indexes:
                continue
            card_profile = _best_output_profile(route, card)
            if card_profile is None:
                continue
            node_name = _predicted_sink_name(card.device_name, card_profile.name)
            if node_name and node_name in loaded_keys:
                continue
            key = f"pc:{card.device_id}:{route.name}"
            sinks.append(
                LocalSink(
                    key=key,
                    name=route.label,
                    node_name=node_name,
                    description=card.device_label,
                    nick=route.label,
                    profile=card_profile.description or card_profile.name,
                    icon_name=_icon_for_route(
                        route, {"device.icon-name": card.icon_name}
                    ),
                    is_default=False,
                    ports=(route.label,),
                    active_port=None,
                    is_loaded=False,
                )
            )
    sinks.sort(
        key=lambda item: (not item.is_default, not item.is_loaded, item.name.casefold())
    )
    return tuple(sinks)


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
