from __future__ import annotations

import json
from pathlib import Path

from despairplay.engine.fixes import (
    FIX_ENABLE_RAOP_DISCOVER,
    apply_enable_raop_discover,
    apply_user_fix,
    plan_user_fix,
)
from despairplay.engine.host import PIPEWIRE_USER_UNITS
from despairplay.engine.pipewire import (
    check_raop_autostart,
    check_raop_discover_loaded,
    check_raop_sinks,
    default_audio_sink_name,
    local_sinks,
    raop_discover_is_loaded,
    raop_sink_labels,
)
from despairplay.engine.result import Status
from despairplay.engine.suite import run_checks, run_scan
from fakes import FakeHost

FIXTURES = Path(__file__).parent / "fixtures"


def _load_dump(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _all_units_up() -> dict[str, bool]:
    return dict.fromkeys(PIPEWIRE_USER_UNITS, True)


def test_parse_loaded_dump() -> None:
    dump = _load_dump("pw-dump-raop-loaded.json")
    assert raop_discover_is_loaded(dump) is True
    assert raop_sink_labels(dump) == ("Living Room",)


def test_parse_no_raop_dump() -> None:
    dump = _load_dump("pw-dump-no-raop.json")
    assert raop_discover_is_loaded(dump) is False
    assert raop_sink_labels(dump) == ()
    sinks = local_sinks(dump)
    assert len(sinks) == 1
    assert sinks[0].node_name == "alsa_output.pci-0000_00_1f.3.analog-stereo"


def test_local_sinks_skip_raop_and_mark_default() -> None:
    dump = _load_dump("pw-dump-local-sinks.json")
    assert raop_sink_labels(dump) == ("MagniFi Mini AX-4652",)
    sinks = local_sinks(dump)
    assert [item.node_name for item in sinks] == [
        "alsa_output.pci-0000_0d_00.4.analog-stereo",
        "alsa_output.pci-0000_0b_00.1.hdmi-stereo",
        "alsa_output.pci-0000_0d_00.4.iec958-stereo",
    ]
    analog, hdmi, spdif = sinks
    assert analog.is_default is True
    assert analog.is_loaded is True
    assert analog.active_port == "Line Out"
    assert analog.ports == ("Line Out",)
    assert analog.icon_name == "audio-card-symbolic"
    assert hdmi.is_default is False
    assert hdmi.active_port == "HDMI / DisplayPort"
    assert hdmi.ports == ("HDMI / DisplayPort",)
    assert hdmi.icon_name == "audio-card-symbolic"
    assert spdif.name == "Digital Output (S/PDIF)"
    assert spdif.is_loaded is False
    assert spdif.is_default is False
    assert spdif.profile == "Digital Stereo (IEC958) Output"
    assert spdif.icon_name == "audio-card-symbolic"
    assert default_audio_sink_name(dump) == (
        "alsa_output.pci-0000_0d_00.4.analog-stereo"
    )


def test_local_sinks_use_playback_channels_and_json_default() -> None:
    dump = _load_dump("pw-dump-channels-only.json")
    sinks = local_sinks(dump)
    assert len(sinks) == 1
    headset = sinks[0]
    assert headset.is_default is True
    assert headset.ports == ("FL", "FR")
    assert headset.icon_name == "audio-headphones-symbolic"
    assert "monitor" not in " ".join(headset.ports).lower()


def test_local_sinks_empty_when_only_raop() -> None:
    dump = _load_dump("pw-dump-raop-loaded.json")
    assert local_sinks(dump) == ()


def test_run_scan_includes_local_sinks() -> None:
    result = run_scan(
        FakeHost(
            units=_all_units_up(),
            dump=_load_dump("pw-dump-local-sinks.json"),
        )
    )
    assert len(result.sinks) == 3
    assert result.sinks[0].is_default is True


def test_parse_sinks_only_dump() -> None:
    dump = _load_dump("pw-dump-raop-sinks-only.json")
    assert raop_discover_is_loaded(dump) is False
    assert raop_sink_labels(dump) == ("MagniFi Mini AX-4652",)


def test_autostart_ok_with_gnome_toggle() -> None:
    result = check_raop_autostart(
        FakeHost(
            units=_all_units_up(),
            toggle_path=Path(
                "/home/nick/.local/share/gnome-shell/extensions/"
                "pipewire-airplay-toggle@craw0967.github.com"
            ),
        )
    )
    assert result.status is Status.OK
    assert result.fix_id is None
    assert "toggle" in result.reason.lower()


def test_discover_ok_via_pactl() -> None:
    result = check_raop_discover_loaded(
        FakeHost(
            units=_all_units_up(),
            dump=_load_dump("pw-dump-no-raop.json"),
            pactl_raop=True,
        )
    )
    assert result.status is Status.OK
    assert "pactl" in result.reason


def test_autostart_fail_offers_fix() -> None:
    result = check_raop_autostart(FakeHost(units=_all_units_up()))
    assert result.status is Status.FAIL
    assert result.fix_id == FIX_ENABLE_RAOP_DISCOVER


def test_autostart_warn_when_only_template(tmp_path: Path) -> None:
    template = tmp_path / "50-raop.conf"
    template.write_text(
        "{ name = libpipewire-module-raop-discover }\n",
        encoding="utf-8",
    )
    result = check_raop_autostart(FakeHost(units=_all_units_up(), avail=template))
    assert result.status is Status.WARN
    assert result.fix_id == FIX_ENABLE_RAOP_DISCOVER


def test_autostart_ok_with_user_dropin(tmp_path: Path) -> None:
    dropin = tmp_path / "raop-discover.conf"
    dropin.write_text("x", encoding="utf-8")
    result = check_raop_autostart(
        FakeHost(units=_all_units_up(), user_dropins=(dropin,))
    )
    assert result.status is Status.OK
    assert result.fix_id is None


def test_autostart_warn_when_sinks_live_without_dropin() -> None:
    result = check_raop_autostart(
        FakeHost(
            units=_all_units_up(),
            dump=_load_dump("pw-dump-raop-sinks-only.json"),
        )
    )
    assert result.status is Status.WARN
    assert result.fix_id == FIX_ENABLE_RAOP_DISCOVER


def test_discover_ok_when_sinks_without_module() -> None:
    result = check_raop_discover_loaded(
        FakeHost(
            units=_all_units_up(),
            dump=_load_dump("pw-dump-raop-sinks-only.json"),
        )
    )
    assert result.status is Status.OK
    assert result.fix_id is None


def test_discover_loaded_fail_offers_fix() -> None:
    result = check_raop_discover_loaded(
        FakeHost(
            units=_all_units_up(),
            discover=Path("/usr/lib/x/libpipewire-module-raop-discover.so"),
            dump=_load_dump("pw-dump-no-raop.json"),
        )
    )
    assert result.status is Status.FAIL
    assert result.fix_id == FIX_ENABLE_RAOP_DISCOVER


def test_discover_fail_with_toggle_does_not_offer_dropin() -> None:
    result = check_raop_discover_loaded(
        FakeHost(
            units=_all_units_up(),
            discover=Path("/usr/lib/x/libpipewire-module-raop-discover.so"),
            dump=_load_dump("pw-dump-no-raop.json"),
            toggle_path=Path("/tmp/pipewire-airplay-toggle@craw0967.github.com"),
        )
    )
    assert result.status is Status.FAIL
    assert result.fix_id is None
    assert "toggle" in result.reason.lower()


def test_sinks_warn_when_none() -> None:
    result = check_raop_sinks(
        FakeHost(units=_all_units_up(), dump=_load_dump("pw-dump-no-raop.json"))
    )
    assert result.status is Status.WARN


def test_sinks_ok_when_present() -> None:
    result = check_raop_sinks(
        FakeHost(units=_all_units_up(), dump=_load_dump("pw-dump-raop-loaded.json"))
    )
    assert result.status is Status.OK
    assert "Living Room" in result.reason


def test_apply_writes_dropin(tmp_path: Path) -> None:
    dest = apply_enable_raop_discover(
        user_conf_d=tmp_path / "pipewire.conf.d",
        avail=None,
        restart=lambda: None,
    )
    assert dest.name == "raop-discover.conf"
    assert "libpipewire-module-raop-discover" in dest.read_text(encoding="utf-8")


def test_apply_copies_avail_template(tmp_path: Path) -> None:
    avail = tmp_path / "50-raop.conf"
    avail.write_text("# distro template\n", encoding="utf-8")
    dest = apply_enable_raop_discover(
        user_conf_d=tmp_path / "d",
        avail=avail,
        restart=lambda: None,
    )
    assert dest.name == "50-raop.conf"
    assert dest.read_text(encoding="utf-8") == "# distro template\n"


def test_apply_user_fix_restarts(tmp_path: Path) -> None:
    host = FakeHost(units=_all_units_up(), conf_d=tmp_path / "pipewire.conf.d")
    dest = apply_user_fix(FIX_ENABLE_RAOP_DISCOVER, host)
    assert dest.is_file()
    assert host.restarted


def test_plan_mentions_restart() -> None:
    lines = plan_user_fix(FIX_ENABLE_RAOP_DISCOVER, FakeHost(units=_all_units_up()))
    assert lines is not None
    assert any("systemctl --user restart" in line for line in lines)


def test_run_checks_order() -> None:
    results = run_checks(
        FakeHost(
            units=_all_units_up(),
            discover=Path("/tmp/libpipewire-module-raop-discover.so"),
            sink=Path("/tmp/libpipewire-module-raop-sink.so"),
            dump=_load_dump("pw-dump-no-raop.json"),
        )
    )
    assert [item.check_id for item in results] == [
        "pipewire-user-units",
        "raop-modules",
        "raop-autostart",
        "raop-discover-loaded",
        "raop-sinks",
        "avahi-packages",
        "avahi-daemon",
        "nsswitch-mdns",
        "mdns-udp-5353",
        "firewall",
        "vpn-interfaces",
        "mdns-speakers",
    ]
