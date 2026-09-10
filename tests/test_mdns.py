"""mDNS grouping, Avahi parsable output, and AirPlay 2-only checks."""

from __future__ import annotations

import json
from pathlib import Path

from despairplay.engine.host import PIPEWIRE_USER_UNITS
from despairplay.engine.mdns import (
    check_mdns_speakers,
    friendly_name,
    group_devices,
    parse_avahi_browse_p,
    records_from_dicts,
)
from despairplay.engine.pipewire import raop_sink_labels
from despairplay.engine.result import Status
from fakes import FakeHost

FIXTURES = Path(__file__).parent / "fixtures"


def _all_units_up() -> dict[str, bool]:
    return dict.fromkeys(PIPEWIRE_USER_UNITS, True)


def _records() -> tuple:
    data = json.loads((FIXTURES / "avahi-records.json").read_text(encoding="utf-8"))
    return records_from_dicts(data)


def test_avahi_browser_new_signature_matches_args() -> None:
    from despairplay.engine.avahi_browse import _SERVICE_BROWSER_NEW_SIG

    body = (-1, -1, "_raop._tcp", "local", 0)
    assert len(_SERVICE_BROWSER_NEW_SIG) == len(body)


def test_friendly_name_strips_mac_prefix() -> None:
    assert friendly_name("AABBCCDDEEFF@MagniFi Mini AX-4652") == "MagniFi Mini AX-4652"
    assert friendly_name("Lounge+") == "Lounge+"


def test_parse_avahi_browse_p() -> None:
    text = (FIXTURES / "avahi-browse-p.txt").read_text(encoding="utf-8")
    records = parse_avahi_browse_p(text)
    assert len(records) == 2
    raop = next(item for item in records if item.service_type == "_raop._tcp")
    assert raop.port == 7000
    assert raop.txt["am"] == "K54AP"
    assert raop.address == "192.168.1.102"


def test_group_raop_and_airplay_same_ip() -> None:
    devices = group_devices(_records())
    by_name = {item.name: item for item in devices}
    magnifi = by_name["MagniFi Mini AX-4652"]
    assert magnifi.has_raop is True
    assert magnifi.has_airplay is True
    assert magnifi.airplay2_only is False
    assert magnifi.txt["am"] == "K54AP"
    lounge = by_name["Lounge+"]
    assert lounge.airplay2_only is True
    assert lounge.has_raop is False


def test_group_matches_pipewire_sink() -> None:
    dump = json.loads(
        (FIXTURES / "pw-dump-raop-sinks-only.json").read_text(encoding="utf-8")
    )
    devices = group_devices(_records(), raop_sink_labels(dump))
    magnifi = next(item for item in devices if item.has_raop)
    assert magnifi.sink_label == "MagniFi Mini AX-4652"


def test_speakers_warn_mixed() -> None:
    result = check_mdns_speakers(FakeHost(units=_all_units_up(), avahi=_records()))
    assert result.status is Status.WARN
    assert "MagniFi Mini" in result.reason
    assert "Lounge+" in result.reason
    records = tuple(item for item in _records() if item.service_type == "_raop._tcp")
    result = check_mdns_speakers(FakeHost(units=_all_units_up(), avahi=records))
    assert result.status is Status.OK
    assert "MagniFi Mini" in result.reason


def test_speakers_warn_airplay2_only() -> None:
    records = tuple(item for item in _records() if item.name == "Lounge+")
    result = check_mdns_speakers(FakeHost(units=_all_units_up(), avahi=records))
    assert result.status is Status.WARN
    assert "AirPlay 2 only" in result.reason
    assert result.fix_id is None


def test_speakers_warn_when_browse_fails() -> None:
    result = check_mdns_speakers(FakeHost(units=_all_units_up(), avahi=None))
    assert result.status is Status.WARN
    assert "Could not browse" in result.reason


def test_speakers_warn_when_empty() -> None:
    result = check_mdns_speakers(FakeHost(units=_all_units_up(), avahi=()))
    assert result.status is Status.WARN
    assert "No AirPlay speakers" in result.reason
