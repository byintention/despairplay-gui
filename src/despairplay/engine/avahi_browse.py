"""Live Avahi browse: D-Bus primary, avahi-browse parsable fallback."""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Any

from despairplay.engine.mdns import (
    SERVICE_AIRPLAY,
    SERVICE_RAOP,
    MdnsRecord,
    parse_avahi_browse_p,
    parse_txt_pairs,
)

log = logging.getLogger(__name__)

_AVAHI = "org.freedesktop.Avahi"
_IF_UNSPEC = -1
_PROTO_UNSPEC = -1
_PROTO_INET = 0
_BROWSE_TYPES = (SERVICE_RAOP, SERVICE_AIRPLAY)
_MAX_SERVICES = 32
# interface, protocol, type, domain, flags
_SERVICE_BROWSER_NEW_SIG = "iissu"


def browse_avahi(*, timeout: float = 3.0) -> tuple[MdnsRecord, ...] | None:
    try:
        records = browse_via_dbus(timeout=timeout)
    except Exception as exc:
        log.warning("Avahi D-Bus browse failed: %s", exc)
        records = None
    if records is not None:
        return records
    return browse_via_avahi_browse(timeout=timeout)


def browse_via_avahi_browse(*, timeout: float = 8.0) -> tuple[MdnsRecord, ...] | None:
    chunks: list[str] = []
    per = max(timeout / len(_BROWSE_TYPES), 1.0)
    for service in _BROWSE_TYPES:
        try:
            completed = subprocess.run(
                ["avahi-browse", "-t", "-r", "-p", service],
                check=False,
                capture_output=True,
                text=True,
                timeout=per,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("avahi-browse %s failed: %s", service, exc)
            continue
        if completed.returncode != 0:
            continue
        chunks.append(completed.stdout)
    if not chunks:
        return None
    return parse_avahi_browse_p("\n".join(chunks))


def browse_via_dbus(*, timeout: float = 3.0) -> tuple[MdnsRecord, ...]:
    from jeepney import DBusAddress, HeaderFields, MessageType
    from jeepney.bus_messages import MatchRule, message_bus
    from jeepney.io.blocking import Proxy, open_dbus_connection
    from jeepney.wrappers import DBusErrorResponse

    server = DBusAddress("/", bus_name=_AVAHI, interface=f"{_AVAHI}.Server")
    browser_rule = MatchRule(
        type="signal",
        interface=f"{_AVAHI}.ServiceBrowser",
    )
    resolver_rule = MatchRule(
        type="signal",
        interface=f"{_AVAHI}.ServiceResolver",
    )
    items: dict[tuple[str, str], tuple[int, int, str, str, str]] = {}
    with open_dbus_connection(bus="SYSTEM") as conn:
        bus = Proxy(message_bus, conn, timeout=2.0)
        bus.AddMatch(browser_rule)
        bus.AddMatch(resolver_rule)
        with conn.filter(browser_rule, bufsize=256) as browser_q:
            paths: list[str] = []
            pending: set[str] = set()
            try:
                for service in _BROWSE_TYPES:
                    path = _call(
                        conn,
                        server,
                        "ServiceBrowserNew",
                        _SERVICE_BROWSER_NEW_SIG,
                        (_IF_UNSPEC, _PROTO_UNSPEC, service, "local", 0),
                        2.0,
                    )[0]
                    paths.append(str(path))
                    pending.add(str(path))
            except DBusErrorResponse as exc:
                log.warning("ServiceBrowserNew failed: %s", exc)
                raise
            deadline = time.monotonic() + timeout
            while pending and time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    signal = conn.recv_until_filtered(
                        browser_q, timeout=max(remaining, 0.05)
                    )
                except TimeoutError:
                    break
                if signal.header.message_type is not MessageType.signal:
                    continue
                member = str(signal.header.fields[HeaderFields.member])
                path = str(signal.header.fields[HeaderFields.path])
                if member == "ItemNew":
                    interface, protocol, name, stype, domain, _flags = signal.body
                    key = (str(name), str(stype))
                    previous = items.get(key)
                    if previous is None or int(protocol) == _PROTO_INET:
                        items[key] = (
                            int(interface),
                            int(protocol),
                            str(name),
                            str(stype),
                            str(domain),
                        )
                elif member in {"AllForNow", "Failure"}:
                    pending.discard(path)
            records = _resolve_items(
                conn, server, resolver_rule, tuple(items.values())[:_MAX_SERVICES]
            )
            for path in paths:
                _free_path(conn, path, f"{_AVAHI}.ServiceBrowser")
    return records


def _call(
    conn: Any,
    address: Any,
    method: str,
    signature: str | None,
    body: tuple[object, ...],
    timeout: float,
) -> tuple[Any, ...]:
    from jeepney import new_method_call
    from jeepney.wrappers import unwrap_msg

    message = new_method_call(address, method, signature, body)
    reply = unwrap_msg(conn.send_and_get_reply(message, timeout=timeout))
    if not isinstance(reply, tuple):
        return (reply,)
    return reply


def _free_path(conn: Any, path: str, interface: str) -> None:
    from jeepney import DBusAddress
    from jeepney.wrappers import DBusErrorResponse

    obj = DBusAddress(path, bus_name=_AVAHI, interface=interface)
    try:
        _call(conn, obj, "Free", None, (), 1.0)
    except (DBusErrorResponse, TimeoutError, OSError) as exc:
        log.debug("Avahi Free %s failed: %s", path, exc)


def _resolve_items(
    conn: Any,
    server: Any,
    resolver_rule: Any,
    items: tuple[tuple[int, int, str, str, str], ...],
) -> tuple[MdnsRecord, ...]:
    from jeepney import HeaderFields, MessageType

    records: list[MdnsRecord] = []
    with conn.filter(resolver_rule, bufsize=64) as found_q:
        for interface, protocol, name, stype, domain in items:
            try:
                path = _call(
                    conn,
                    server,
                    "ServiceResolverNew",
                    "iisssiu",
                    (interface, protocol, name, stype, domain, protocol, 0),
                    2.0,
                )[0]
            except Exception as exc:
                log.warning("ServiceResolverNew %s failed: %s", name, exc)
                continue
            path_s = str(path)
            try:
                record = _wait_found(conn, found_q, path_s, HeaderFields, MessageType)
            except TimeoutError:
                log.warning("Avahi resolve timed out for %s", name)
                record = None
            _free_path(conn, path_s, f"{_AVAHI}.ServiceResolver")
            if record is not None:
                records.append(record)
    return tuple(records)


def _wait_found(
    conn: Any,
    queue: Any,
    path: str,
    header_fields: Any,
    message_type: Any,
) -> MdnsRecord | None:
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        signal = conn.recv_until_filtered(queue, timeout=max(remaining, 0.05))
        if signal.header.message_type is not message_type.signal:
            continue
        if str(signal.header.fields[header_fields.path]) != path:
            continue
        member = str(signal.header.fields[header_fields.member])
        if member == "Failure":
            return None
        if member != "Found":
            continue
        return _record_from_found(signal.body)
    raise TimeoutError


def _record_from_found(body: tuple[Any, ...]) -> MdnsRecord:
    # iissssisqaayu: iface proto name type domain host aproto addr port txt flags
    name = str(body[2])
    stype = str(body[3])
    host = str(body[5])
    address = str(body[7])
    port = int(body[8])
    txt = _txt_from_dbus(body[9])
    return MdnsRecord(
        name=name,
        service_type=stype,
        host=host,
        address=address,
        port=port,
        txt=txt,
    )


def _txt_from_dbus(raw: object) -> dict[str, str]:
    items: list[bytes] = []
    if not isinstance(raw, (list, tuple)):
        return {}
    for item in raw:
        if isinstance(item, bytes):
            items.append(item)
        elif isinstance(item, str):
            items.append(item.encode("utf-8"))
        elif isinstance(item, (list, tuple)):
            items.append(bytes(item))
    return parse_txt_pairs(tuple(items))
