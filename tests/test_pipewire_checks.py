from __future__ import annotations

from pathlib import Path

from despairplay.engine.host import PIPEWIRE_USER_UNITS
from despairplay.engine.pipewire import check_pipewire_user_units, check_raop_modules
from despairplay.engine.result import Status
from fakes import FakeHost


def _all_units_up() -> dict[str, bool]:
    return dict.fromkeys(PIPEWIRE_USER_UNITS, True)


def test_pipewire_units_ok() -> None:
    result = check_pipewire_user_units(FakeHost(units=_all_units_up()))
    assert result.status is Status.OK
    assert result.fix_id is None


def test_pipewire_units_fail_lists_inactive() -> None:
    units = _all_units_up()
    units["wireplumber.service"] = False
    result = check_pipewire_user_units(FakeHost(units=units))
    assert result.status is Status.FAIL
    assert "wireplumber.service" in result.reason
    assert "pipewire.service" not in result.reason


def test_raop_modules_ok() -> None:
    result = check_raop_modules(
        FakeHost(
            units=_all_units_up(),
            discover=Path(
                "/usr/lib/x86_64-linux-gnu/pipewire-0.3/libpipewire-module-raop-discover.so"
            ),
            sink=Path(
                "/usr/lib/x86_64-linux-gnu/pipewire-0.3/libpipewire-module-raop-sink.so"
            ),
        )
    )
    assert result.status is Status.OK
    assert "discover.so" in result.evidence


def test_raop_modules_fail_when_missing() -> None:
    result = check_raop_modules(FakeHost(units=_all_units_up()))
    assert result.status is Status.FAIL
    assert "libpipewire-0.3-modules" in result.reason
    assert "raop-discover" in result.reason
    assert "raop-sink" in result.reason
