"""Avahi listener cache and D-Bus object lifetime. No system bus."""

from __future__ import annotations

import threading
import time
from typing import Any

from despairplay.engine.avahi_browse import (
    _BROWSER_IFACE,
    _RESOLVER_IFACE,
    AvahiListener,
    AvahiSignal,
)
from despairplay.engine.mdns import SERVICE_AIRPLAY, SERVICE_RAOP, group_devices

_RAOP_NAME = "AABBCCDDEEFF@Lounge"
_V6 = (2, 1)
_V4 = (2, 0)


class FakeBus:
    def __init__(self, *, fail_browser_at: int | None = None) -> None:
        self.fail_browser_at = fail_browser_at
        self.calls: list[tuple[Any, ...]] = []
        self.closed = False
        self._browsers = 0
        self._resolvers = 0
        self._signals: list[AvahiSignal] = []
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)

    def add_match(self, interface: str) -> None:
        with self._lock:
            self.calls.append(("add_match", interface))

    def remove_match(self, interface: str) -> None:
        with self._lock:
            self.calls.append(("remove_match", interface))

    def call(
        self,
        path: str,
        interface: str,
        method: str,
        signature: str | None,
        body: tuple[object, ...],
        timeout: float,
    ) -> tuple[Any, ...]:
        del timeout
        with self._lock:
            self.calls.append(("call", method, path, interface, signature, body))
            if method == "ServiceBrowserNew":
                self._browsers += 1
                if self.fail_browser_at == self._browsers:
                    raise RuntimeError("ServiceBrowserNew failed")
                return (f"/browsers/{self._browsers}",)
            if method == "ServiceResolverNew":
                self._resolvers += 1
                return (f"/resolvers/{self._resolvers}",)
            if method == "Free":
                return ()
            raise AssertionError(method)

    def recv(self, timeout: float) -> AvahiSignal | None:
        deadline = time.monotonic() + timeout
        with self._wake:
            while not self._signals:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._wake.wait(timeout=remaining)
            return self._signals.pop(0)

    def push(self, signal: AvahiSignal) -> None:
        with self._wake:
            self._signals.append(signal)
            self._wake.notify()

    def close(self) -> None:
        with self._lock:
            self.closed = True

    def count(self, method: str) -> int:
        with self._lock:
            return sum(
                1 for item in self.calls if item[0] == "call" and item[1] == method
            )

    def call_bodies(self, method: str) -> list[tuple[object, ...]]:
        with self._lock:
            return [
                item[5]
                for item in self.calls
                if item[0] == "call" and item[1] == method
            ]

    def free_targets(self) -> list[tuple[str, str]]:
        with self._lock:
            return [
                (str(item[2]), str(item[3]))
                for item in self.calls
                if item[0] == "call" and item[1] == "Free"
            ]

    def removed(self) -> list[str]:
        with self._lock:
            return [str(item[1]) for item in self.calls if item[0] == "remove_match"]


def _wait(predicate: Any, detail: Any) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(detail())


def _listener(bus: FakeBus, **kwargs: Any) -> AvahiListener:
    options: dict[str, Any] = {
        "connect": lambda: bus,
        "fallback": lambda: None,
        "recv_timeout": 0.05,
        "resolve_timeout": 0.15,
    }
    options.update(kwargs)
    return AvahiListener(**options)


def _item(
    member: str,
    *,
    interface: int,
    protocol: int,
    name: str,
    service: str,
) -> AvahiSignal:
    return AvahiSignal(
        path="/browsers/1",
        interface=_BROWSER_IFACE,
        member=member,
        body=(interface, protocol, name, service, "local", 0),
    )


def _found(
    path: str,
    *,
    name: str,
    service: str,
    address: str,
    protocol: int,
    interface: int = 2,
) -> AvahiSignal:
    return AvahiSignal(
        path=path,
        interface=_RESOLVER_IFACE,
        member="Found",
        body=(
            interface,
            protocol,
            name,
            service,
            "local",
            "lounge.local",
            protocol,
            address,
            7000,
            [b"am=Test"],
            0,
        ),
    )


def test_start_is_idempotent_and_stop_frees_browsers() -> None:
    bus = FakeBus()
    listener = _listener(bus)
    assert listener.records() is None
    assert bus.count("ServiceBrowserNew") == 0
    try:
        listener.start()
        _wait(lambda: listener.records() == (), lambda: listener.records())
        listener.start()
        for _ in range(5):
            assert listener.records() == ()
        assert bus.count("ServiceBrowserNew") == 2
        assert bus.call_bodies("ServiceBrowserNew") == [
            (-1, -1, SERVICE_RAOP, "local", 0),
            (-1, -1, SERVICE_AIRPLAY, "local", 0),
        ]
    finally:
        listener.stop()
    frees = bus.free_targets()
    assert ("/browsers/1", _BROWSER_IFACE) in frees
    assert ("/browsers/2", _BROWSER_IFACE) in frees
    assert bus.removed() == [_BROWSER_IFACE, _RESOLVER_IFACE]
    assert bus.closed
    assert listener.records() is None


def test_stop_frees_browser_when_second_service_browser_new_fails() -> None:
    bus = FakeBus(fail_browser_at=2)
    listener = _listener(bus)
    try:
        listener.start()
        _wait(
            lambda: listener.failed() and bus.closed,
            lambda: (listener.failed(), bus.closed, bus.calls),
        )
        assert bus.count("ServiceBrowserNew") == 2
        frees = bus.free_targets()
        assert ("/browsers/1", _BROWSER_IFACE) in frees
        assert not any(path == "/browsers/2" for path, _iface in frees)
        assert bus.removed() == [_BROWSER_IFACE, _RESOLVER_IFACE]
        assert listener.records() is None
        assert listener.failed()
    finally:
        listener.stop()


def test_item_new_found_and_remove_update_cache() -> None:
    bus = FakeBus()
    listener = _listener(bus, resolve_timeout=1.0)
    try:
        listener.start()
        _wait(lambda: listener.records() == (), lambda: listener.records())
        bus.push(
            _item(
                "ItemNew",
                interface=_V6[0],
                protocol=_V6[1],
                name=_RAOP_NAME,
                service=SERVICE_RAOP,
            )
        )
        _wait(lambda: bus.count("ServiceResolverNew") == 1, lambda: bus.calls)
        bus.push(
            _found(
                "/resolvers/1",
                name=_RAOP_NAME,
                service=SERVICE_RAOP,
                address="fe80::1",
                protocol=_V6[1],
            )
        )
        _wait(
            lambda: _addresses(listener, SERVICE_RAOP) == ["fe80::1"],
            lambda: listener.records(),
        )
        bus.push(
            _item(
                "ItemNew",
                interface=_V4[0],
                protocol=_V4[1],
                name=_RAOP_NAME,
                service=SERVICE_RAOP,
            )
        )
        _wait(lambda: bus.count("ServiceResolverNew") == 2, lambda: bus.calls)
        bus.push(
            _found(
                "/resolvers/2",
                name=_RAOP_NAME,
                service=SERVICE_RAOP,
                address="192.168.1.20",
                protocol=_V4[1],
            )
        )
        _wait(
            lambda: _addresses(listener, SERVICE_RAOP) == ["192.168.1.20"],
            lambda: listener.records(),
        )
        before = bus.count("ServiceResolverNew")
        bus.push(
            _item(
                "ItemNew",
                interface=3,
                protocol=_V6[1],
                name=_RAOP_NAME,
                service=SERVICE_RAOP,
            )
        )
        bus.push(
            _item(
                "ItemNew",
                interface=_V4[0],
                protocol=_V4[1],
                name="Lounge",
                service=SERVICE_AIRPLAY,
            )
        )
        _wait(
            lambda: bus.count("ServiceResolverNew") == before + 1,
            lambda: bus.calls,
        )
        assert bus.call_bodies("ServiceResolverNew")[-1][2] == "Lounge"
        time.sleep(0.15)
        assert bus.count("ServiceResolverNew") == before + 1
        bus.push(
            _found(
                "/resolvers/3",
                name="Lounge",
                service=SERVICE_AIRPLAY,
                address="192.168.1.20",
                protocol=_V4[1],
            )
        )
        _wait(
            lambda: len(listener.records() or ()) == 2,
            lambda: listener.records(),
        )
        devices = group_devices(listener.records() or ())
        assert len(devices) == 1
        assert devices[0].has_raop is True
        assert devices[0].has_airplay is True
        assert ("/resolvers/1", _RESOLVER_IFACE) in bus.free_targets()
        assert ("/resolvers/2", _RESOLVER_IFACE) in bus.free_targets()
        bus.push(
            _item(
                "ItemRemove",
                interface=_V4[0],
                protocol=_V4[1],
                name=_RAOP_NAME,
                service=SERVICE_RAOP,
            )
        )
        _wait(
            lambda: _addresses(listener, SERVICE_RAOP) == ["fe80::1"],
            lambda: listener.records(),
        )
        bus.push(
            _item(
                "ItemRemove",
                interface=_V6[0],
                protocol=_V6[1],
                name=_RAOP_NAME,
                service=SERVICE_RAOP,
            )
        )
        _wait(
            lambda: _addresses(listener, SERVICE_RAOP) == [],
            lambda: listener.records(),
        )
        assert _addresses(listener, SERVICE_AIRPLAY) == ["192.168.1.20"]
    finally:
        listener.stop()
    assert ("/resolvers/3", _RESOLVER_IFACE) in bus.free_targets()


def test_resolver_is_freed_when_resolve_times_out() -> None:
    bus = FakeBus()
    listener = _listener(bus)
    try:
        listener.start()
        _wait(lambda: listener.records() == (), lambda: listener.records())
        bus.push(
            _item(
                "ItemNew",
                interface=_V4[0],
                protocol=_V4[1],
                name=_RAOP_NAME,
                service=SERVICE_RAOP,
            )
        )
        _wait(
            lambda: ("/resolvers/1", _RESOLVER_IFACE) in bus.free_targets(),
            lambda: bus.free_targets(),
        )
        assert bus.count("ServiceResolverNew") == 1
        assert listener.records() == ()
    finally:
        listener.stop()
    resolver_frees = [
        path
        for path, interface in bus.free_targets()
        if path == "/resolvers/1" and interface == _RESOLVER_IFACE
    ]
    assert resolver_frees == ["/resolvers/1"]


def _addresses(listener: AvahiListener, service: str) -> list[str]:
    records = listener.records() or ()
    return [item.address for item in records if item.service_type == service]
