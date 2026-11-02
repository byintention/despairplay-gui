"""Persistent Avahi browse: one ServiceBrowser pair, CLI fallback once."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from despairplay.engine.mdns import (
    SERVICE_AIRPLAY,
    SERVICE_RAOP,
    MdnsRecord,
    parse_avahi_browse_p,
    parse_txt_pairs,
)

log = logging.getLogger(__name__)

_AVAHI = "org.freedesktop.Avahi"
_SERVER_IFACE = f"{_AVAHI}.Server"
_BROWSER_IFACE = f"{_AVAHI}.ServiceBrowser"
_RESOLVER_IFACE = f"{_AVAHI}.ServiceResolver"
_MATCH_INTERFACES = (_BROWSER_IFACE, _RESOLVER_IFACE)
_IF_UNSPEC = -1
_PROTO_UNSPEC = -1
_PROTO_INET = 0
_BROWSE_TYPES = (SERVICE_RAOP, SERVICE_AIRPLAY)
_MAX_RECORDS = 64
# interface, protocol, type, domain, flags
_SERVICE_BROWSER_NEW_SIG = "iissu"
# interface, protocol, name, type, domain, aprotocol, flags
_SERVICE_RESOLVER_NEW_SIG = "iisssiu"

ServiceKey = tuple[int, int, str, str, str]


@dataclass(frozen=True)
class AvahiSignal:
    path: str
    interface: str
    member: str
    body: tuple[Any, ...]


class AvahiConnection(Protocol):
    def add_match(self, interface: str) -> None: ...

    def remove_match(self, interface: str) -> None: ...

    def call(
        self,
        path: str,
        interface: str,
        method: str,
        signature: str | None,
        body: tuple[object, ...],
        timeout: float,
    ) -> tuple[Any, ...]: ...

    def recv(self, timeout: float) -> AvahiSignal | None: ...

    def close(self) -> None: ...


class AvahiListener:
    """One system-bus client and two service browsers for the app lifetime."""

    def __init__(
        self,
        *,
        connect: Callable[[], AvahiConnection] | None = None,
        fallback: Callable[[], tuple[MdnsRecord, ...] | None] | None = None,
        on_change: Callable[[], None] | None = None,
        resolve_timeout: float = 1.5,
        recv_timeout: float = 0.5,
    ) -> None:
        self._connect = connect if connect is not None else _connect_system
        self._fallback = fallback if fallback is not None else _browse_fallback
        self._on_change = on_change
        self._resolve_timeout = resolve_timeout
        self._recv_timeout = recv_timeout
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False
        self._failed = False
        self._records: dict[ServiceKey, MdnsRecord] = {}
        self._fallback_records: tuple[MdnsRecord, ...] | None = None
        self._queue: deque[ServiceKey] = deque()
        self._queued: set[ServiceKey] = set()
        self._inflight: ServiceKey | None = None
        self._resolver_path: str | None = None
        self._resolve_deadline = 0.0

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        with self._lock:
            self._on_change = callback

    def start(self) -> None:
        """Open the browser pair. A second call while running does nothing."""
        with self._lock:
            if self._running:
                return
            self._stop.clear()
            self._failed = False
            self._connected = False
            self._records.clear()
            self._fallback_records = None
            self._queue.clear()
            self._queued.clear()
            self._inflight = None
            self._resolver_path = None
            self._running = True
            self._thread = threading.Thread(
                target=self._run,
                name="avahi-mdns",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Free browsers, drop match rules, and close the bus connection."""
        with self._lock:
            thread = self._thread
            self._stop.set()
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.is_alive()
        ):
            thread.join(timeout=12)
            if thread.is_alive():
                log.warning("Avahi listener did not stop within 12s")
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None
                self._running = False

    def restart(self) -> None:
        """Free the current pair, then open one new pair."""
        self.stop()
        self.start()

    def records(self) -> tuple[MdnsRecord, ...] | None:
        """Snapshot of resolved services. None until connected, or after failure."""
        with self._lock:
            if self._failed or not self._connected:
                return None
            if self._fallback_records is not None:
                return self._fallback_records
            return _prefer_ipv4(self._records)

    def failed(self) -> bool:
        with self._lock:
            return self._failed

    def _run(self) -> None:
        conn: AvahiConnection | None = None
        browser_paths: list[str] = []
        added: list[str] = []
        connected_before = False
        try:
            conn = self._connect()
            for interface in _MATCH_INTERFACES:
                conn.add_match(interface)
                added.append(interface)
            for service in _BROWSE_TYPES:
                if self._stop.is_set():
                    break
                reply = conn.call(
                    "/",
                    _SERVER_IFACE,
                    "ServiceBrowserNew",
                    _SERVICE_BROWSER_NEW_SIG,
                    (_IF_UNSPEC, _PROTO_UNSPEC, service, "local", 0),
                    2.0,
                )
                browser_paths.append(str(reply[0]))
            if len(browser_paths) == len(_BROWSE_TYPES) and not self._stop.is_set():
                connected_before = True
                with self._lock:
                    self._connected = True
                    self._failed = False
                    self._fallback_records = None
                self._emit()
                while not self._stop.is_set():
                    self._expire_resolver(conn)
                    self._pump_resolver(conn)
                    signal = conn.recv(self._recv_timeout)
                    if signal is not None:
                        self._handle(conn, signal)
        except Exception as exc:
            log.warning("Avahi listener failed: %s", exc)
            if not connected_before and not self._stop.is_set():
                self._apply_fallback()
        finally:
            self._teardown(conn, browser_paths, added)
            with self._lock:
                self._running = False
                self._inflight = None
                self._resolver_path = None
                self._queue.clear()
                self._queued.clear()
                keep_fallback = (
                    self._fallback_records is not None and not self._stop.is_set()
                )
                if self._stop.is_set():
                    self._connected = False
                    self._failed = False
                    self._records.clear()
                    self._fallback_records = None
                elif keep_fallback:
                    self._connected = True
                    self._failed = False
                elif not connected_before:
                    self._connected = False
                    self._failed = True
                    self._records.clear()
                else:
                    self._connected = False
                    self._failed = True
                    self._records.clear()
                    self._fallback_records = None
            self._emit()

    def _teardown(
        self,
        conn: AvahiConnection | None,
        browser_paths: list[str],
        added: list[str],
    ) -> None:
        if conn is None:
            return
        self._free_resolver(conn)
        for path in browser_paths:
            _free(conn, path, _BROWSER_IFACE)
        for interface in added:
            try:
                conn.remove_match(interface)
            except Exception as exc:
                log.debug("Avahi RemoveMatch %s failed: %s", interface, exc)
        try:
            conn.close()
        except Exception as exc:
            log.debug("Avahi connection close failed: %s", exc)

    def _apply_fallback(self) -> None:
        try:
            found = self._fallback()
        except Exception as exc:
            log.warning("avahi-browse fallback failed: %s", exc)
            found = None
        with self._lock:
            if found is not None:
                self._fallback_records = tuple(found)
                self._connected = True
                self._failed = False
                return
            self._fallback_records = None
            self._connected = False
            self._failed = True

    def _handle(self, conn: AvahiConnection, signal: AvahiSignal) -> None:
        if signal.member == "ItemNew":
            key = _key_from_body(signal.body)
            if key is not None:
                self._enqueue(key)
            return
        if signal.member == "ItemRemove":
            key = _key_from_body(signal.body)
            if key is not None:
                self._drop(conn, key)
            return
        path = self._resolver_path_now()
        if path is None or signal.path != path:
            return
        if signal.member == "Failure":
            self._free_resolver(conn)
            return
        if signal.member != "Found":
            return
        try:
            record = _record_from_found(signal.body)
        except (IndexError, TypeError, ValueError) as exc:
            log.warning("Avahi Found signal was not a record: %s", exc)
            record = None
        self._commit(record)
        self._free_resolver(conn)
        self._emit()

    def _enqueue(self, key: ServiceKey) -> None:
        with self._lock:
            if key in self._records or key in self._queued or key == self._inflight:
                return
            name_type = (key[2], key[3])
            if key[1] != _PROTO_INET and self._has_inet_locked(name_type):
                return
            pending = len(self._records) + len(self._queue)
            if self._inflight is not None:
                pending += 1
            if pending >= _MAX_RECORDS:
                return
            self._queue.append(key)
            self._queued.add(key)

    def _drop(self, conn: AvahiConnection, key: ServiceKey) -> None:
        changed = False
        free_current = False
        with self._lock:
            if self._records.pop(key, None) is not None:
                changed = True
            if key in self._queued:
                self._queued.discard(key)
                self._queue = deque(item for item in self._queue if item != key)
            if self._inflight == key:
                self._inflight = None
                free_current = self._resolver_path is not None
                changed = True
        if free_current:
            self._free_resolver(conn)
        if changed:
            self._emit()

    def _commit(self, record: MdnsRecord | None) -> None:
        if record is None:
            return
        with self._lock:
            key = self._inflight
            if key is None:
                return
            if key not in self._records and len(self._records) >= _MAX_RECORDS:
                return
            self._records[key] = record

    def _pump_resolver(self, conn: AvahiConnection) -> None:
        with self._lock:
            if self._resolver_path is not None or not self._queue:
                return
            key = self._queue.popleft()
            self._queued.discard(key)
            self._inflight = key
        interface, protocol, name, stype, domain = key
        try:
            reply = conn.call(
                "/",
                _SERVER_IFACE,
                "ServiceResolverNew",
                _SERVICE_RESOLVER_NEW_SIG,
                (interface, protocol, name, stype, domain, protocol, 0),
                2.0,
            )
            path = str(reply[0])
        except Exception as exc:
            log.warning("ServiceResolverNew %s failed: %s", name, exc)
            with self._lock:
                if self._inflight == key:
                    self._inflight = None
            return
        stale = False
        with self._lock:
            if self._inflight != key:
                stale = True
            else:
                self._resolver_path = path
                self._resolve_deadline = time.monotonic() + self._resolve_timeout
        if stale:
            _free(conn, path, _RESOLVER_IFACE)

    def _expire_resolver(self, conn: AvahiConnection) -> None:
        with self._lock:
            path = self._resolver_path
            expired = path is not None and time.monotonic() >= self._resolve_deadline
            name = self._inflight[2] if self._inflight is not None else path
        if not expired:
            return
        log.warning("Avahi resolve timed out for %s", name)
        self._free_resolver(conn)

    def _free_resolver(self, conn: AvahiConnection) -> None:
        with self._lock:
            path = self._resolver_path
            self._resolver_path = None
            self._inflight = None
        if path:
            _free(conn, path, _RESOLVER_IFACE)

    def _resolver_path_now(self) -> str | None:
        with self._lock:
            return self._resolver_path

    def _has_inet_locked(self, name_type: tuple[str, str]) -> bool:
        if any(
            (key[2], key[3]) == name_type and key[1] == _PROTO_INET
            for key in self._records
        ):
            return True
        if any(
            (key[2], key[3]) == name_type and key[1] == _PROTO_INET
            for key in self._queue
        ):
            return True
        inflight = self._inflight
        return (
            inflight is not None
            and (inflight[2], inflight[3]) == name_type
            and inflight[1] == _PROTO_INET
        )

    def _emit(self) -> None:
        with self._lock:
            callback = self._on_change
        if callback is None:
            return
        try:
            callback()
        except Exception:
            log.exception("Avahi listener callback failed")


_shared_lock = threading.Lock()
_shared: AvahiListener | None = None


def shared_listener() -> AvahiListener:
    """Process-wide listener. The UI starts and stops it."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = AvahiListener()
        return _shared


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


def _browse_fallback() -> tuple[MdnsRecord, ...] | None:
    return browse_via_avahi_browse()


def _connect_system() -> AvahiConnection:
    return _JeepneyConnection()


def _prefer_ipv4(records: dict[ServiceKey, MdnsRecord]) -> tuple[MdnsRecord, ...]:
    best: dict[tuple[str, str], tuple[int, MdnsRecord]] = {}
    for key, record in records.items():
        name_type = (key[2], key[3])
        proto = key[1]
        previous = best.get(name_type)
        if previous is None or proto == _PROTO_INET:
            best[name_type] = (proto, record)
    return tuple(item for _proto, item in best.values())


def _key_from_body(body: tuple[Any, ...]) -> ServiceKey | None:
    if len(body) < 5:
        return None
    try:
        return (int(body[0]), int(body[1]), str(body[2]), str(body[3]), str(body[4]))
    except (TypeError, ValueError):
        return None


def _record_from_found(body: tuple[Any, ...]) -> MdnsRecord:
    # iissssisqaayu: iface proto name type domain host aproto addr port txt flags
    return MdnsRecord(
        name=str(body[2]),
        service_type=str(body[3]),
        host=str(body[5]),
        address=str(body[7]),
        port=int(body[8]),
        txt=_txt_from_dbus(body[9]),
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


def _free(conn: AvahiConnection, path: str, interface: str) -> None:
    try:
        conn.call(path, interface, "Free", None, (), 1.0)
    except Exception as exc:
        log.debug("Avahi Free %s failed: %s", path, exc)


class _JeepneyConnection:
    """System bus wrapper. Imported only when the real listener connects."""

    def __init__(self) -> None:
        from jeepney.io.blocking import open_dbus_connection

        self._conn = open_dbus_connection(bus="SYSTEM")
        self._handles: list[Any] = []
        self._queues: list[Any] = []

    def add_match(self, interface: str) -> None:
        from jeepney.bus_messages import MatchRule, message_bus
        from jeepney.io.blocking import Proxy

        # Bus matches the well-known name. The local filter sees the unique
        # sender on each signal, so it matches the interface only.
        bus_rule = MatchRule(type="signal", sender=_AVAHI, interface=interface)
        local_rule = MatchRule(type="signal", interface=interface)
        handle = self._conn.filter(local_rule, bufsize=256)
        self._handles.append(handle)
        self._queues.append(handle.queue)
        Proxy(message_bus, self._conn, timeout=2.0).AddMatch(bus_rule)

    def remove_match(self, interface: str) -> None:
        from jeepney.bus_messages import MatchRule, message_bus
        from jeepney.io.blocking import Proxy

        rule = MatchRule(type="signal", sender=_AVAHI, interface=interface)
        Proxy(message_bus, self._conn, timeout=2.0).RemoveMatch(rule)

    def call(
        self,
        path: str,
        interface: str,
        method: str,
        signature: str | None,
        body: tuple[object, ...],
        timeout: float,
    ) -> tuple[Any, ...]:
        from jeepney import DBusAddress, new_method_call
        from jeepney.wrappers import unwrap_msg

        address = DBusAddress(path, bus_name=_AVAHI, interface=interface)
        message = new_method_call(address, method, signature, body)
        reply = unwrap_msg(self._conn.send_and_get_reply(message, timeout=timeout))
        if not isinstance(reply, tuple):
            return (reply,)
        return reply

    def recv(self, timeout: float) -> AvahiSignal | None:
        deadline = time.monotonic() + timeout
        while True:
            queued = self._pop_queued()
            if queued is not None:
                return queued
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                self._conn.recv_messages(timeout=remaining)
            except TimeoutError:
                return None

    def close(self) -> None:
        for handle in self._handles:
            handle.close()
        self._handles.clear()
        self._queues.clear()
        self._conn.close()

    def _pop_queued(self) -> AvahiSignal | None:
        from jeepney import HeaderFields, MessageType

        for queue in self._queues:
            if not queue:
                continue
            msg = queue.popleft()
            header = msg.header
            if header.message_type is not MessageType.signal:
                continue
            fields = header.fields
            return AvahiSignal(
                path=str(fields.get(HeaderFields.path, "")),
                interface=str(fields.get(HeaderFields.interface, "")),
                member=str(fields.get(HeaderFields.member, "")),
                body=tuple(msg.body),
            )
        return None
