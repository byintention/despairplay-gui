"""User-level PipeWire RAOP enable (no root)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from despairplay.engine.host import Host

FIX_ENABLE_RAOP_DISCOVER = "enable-raop-discover"

_DROPIN_BODY = """context.modules = [
  { name = libpipewire-module-raop-discover }
]
"""

_USER_CONF_D = Path.home() / ".config" / "pipewire" / "pipewire.conf.d"


def plan_user_fix(fix_id: str, host: Host) -> tuple[str, ...] | None:
    if fix_id != FIX_ENABLE_RAOP_DISCOVER:
        return None
    lines = [f"mkdir -p {_USER_CONF_D}"]
    avail = host.raop_avail_template()
    if avail is not None:
        lines.append(f"cp {avail} {_USER_CONF_D / avail.name}")
    else:
        dest = _USER_CONF_D / "raop-discover.conf"
        lines.append(f"write {dest}")
        lines.append(
            "  context.modules = [{ name = libpipewire-module-raop-discover }]"
        )
    lines.append("systemctl --user restart pipewire pipewire-pulse wireplumber")
    return tuple(lines)


def apply_enable_raop_discover(
    *,
    user_conf_d: Path,
    avail: Path | None,
    restart: Callable[[], None],
) -> Path:
    """Write or copy the RAOP drop-in, then restart the user session."""
    user_conf_d.mkdir(parents=True, exist_ok=True)
    if avail is not None and avail.is_file():
        dest = user_conf_d / avail.name
        dest.write_text(avail.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        dest = user_conf_d / "raop-discover.conf"
        dest.write_text(_DROPIN_BODY, encoding="utf-8")
    restart()
    return dest


def apply_user_fix(fix_id: str, host: Host) -> Path:
    if fix_id != FIX_ENABLE_RAOP_DISCOVER:
        msg = f"Unknown or non-user fix: {fix_id}"
        raise ValueError(msg)
    return apply_enable_raop_discover(
        user_conf_d=host.pipewire_user_conf_d(),
        avail=host.raop_avail_template(),
        restart=host.restart_pipewire_user_session,
    )
