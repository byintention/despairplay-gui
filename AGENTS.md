# Agent map

Python GTK4 diagnostic app. Read [docs/DESIGN.md](docs/DESIGN.md) before adding checks or UI.

## Layout

- Package: `src/despairplay/` (import `despairplay`, script `despairplay`).
- Engine (no GTK): `src/despairplay/engine/`
- UI only: `src/despairplay/ui/` — GI imports via `ui/gi_imports.py`
- Tests: `tests/` + `tests/fixtures/`. No live speakers in default pytest.
- Durable design: `docs/DESIGN.md`. User-visible changes: `CHANGELOG.md` Unreleased.

## Commands

`make check` (lint, mypy, pytest). `make run` launches the GUI. Venv **must** be `python3 -m venv --system-site-packages` so distro `gi` is visible.

Do **not** `apt`/install system-wide packages on this machine without explaining them first, and only as a last resort. See `.cursor/rules/no-system-packages.mdc`. List the command and wait.

## Skills and rules

- Always-on: `.cursor/rules/python-gtk.mdc`, `.cursor/rules/no-system-packages.mdc`
- UI files: `.cursor/rules/gtk-ui.mdc`
- Skills: `.cursor/skills/gtk4-libadwaita/`, `.cursor/skills/add-diagnostic-check/`

Ubuntu/Zorin package names. RAOP/AirPlay 1 sender only. No AirPlay receiver or AirPlay 2 implementation.
