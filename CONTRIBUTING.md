# Contributing

## Environment

1. If GI/GTK packages are missing, **list** the apt packages (see README) and let Nick install them. Agents must not run `sudo apt` (or any system-wide installer) without explaining first, and only as a last resort.
2. GTK/libadwaita **must** come from distro GI packages, not pip. Python tools go in `.venv` via `make install-dev` (`--system-site-packages` so `import gi` works).
3. `make check` must pass before you stop. Missing system libraries are not a reason to install them unattended.

The folder name `Airplay GUI` has a space. Quote the path in shells. The Python package is `despairplay`; the console script is `despairplay`.

This repository is **byintention** (`origin` uses `github-intention`). Commits must not use ThePracticeNick or `nick@the-practice.co.uk`.

## Layout

| Path | Role |
| --- | --- |
| `src/despairplay/engine/` | Checks and fixes. **No GTK.** Unit-tested from fixtures. |
| `src/despairplay/ui/` | GTK4 / libadwaita only. Import GI via `ui/gi_imports.py`. |
| `tests/fixtures/` | Sample `pw-dump` JSON, Avahi TXT, UFW status. |
| `data/` | Desktop file, later pkexec policy/helper. |
| `docs/DESIGN.md` | Architecture source of truth (AirPlay 1 vs 2, check list). |

## Adding a check

1. One module under `engine/` that returns `ok | warn | fail`, a short reason, evidence (command/path), and an optional fix id.
2. One fixture in `tests/fixtures/` and a parser unit test. Do not import GTK in tests.
3. Wire it into Audio system or Network in the UI with a **Fix** action only when the fix is allow-listed and safe.
4. Add a bullet under `## [Unreleased]` in `CHANGELOG.md` if the check is user-visible.
5. Ubuntu package names (`libpipewire-0.3-modules`, `avahi-daemon`), never Arch’s `pipewire-zeroconf`.

Privileged fixes go through the pkexec helper’s argv allow-list. No `shell=True`. Do not auto-edit `/etc/nsswitch.conf` or `systemd-resolved` in v1. Do not set the default PipeWire sink automatically.

## Types and GI

mypy runs `--strict` on `src/despairplay`. `gi` / `gi.repository.*` are `ignore_missing_imports`. Do not fight PyGObject stubs; isolate GTK in `ui/`.

## Releases

1. Move `## [Unreleased]` notes to `## [x.y.z] - YYYY-MM-DD` in `CHANGELOG.md`.
2. Set `__version__` in `src/despairplay/__init__.py` (single version source).
3. Tag the release.

Keep a Changelog + SemVer. Every user-visible check or fix lands under Unreleased until then.
