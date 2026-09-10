# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project harness: packaging (`despairplay` 0.1.0), Ruff, mypy, pytest, Makefile, pre-commit, and CI.
- Placeholder GTK4/libadwaita window so `make run` can verify system GI packages.
- Design note, contributing guide, and Cursor rules/skills for Linux GTK development.
- Workstation rule: no system-wide package installs without a prior explanation; last resort only.
- Overview checks: PipeWire user units, RAOP `.so` files, autostart drop-in, discover module loaded (`pw-dump`), and RAOP sinks.
- User-level **Fix** to enable RAOP discover (write/copy drop-in, restart PipeWire session) after showing the commands.
- Split-view window (Overview / AirPlay / This PC) bound to those checks.
- This PC sidebar lists local PipeWire output sinks (HDMI, built-in, USB) and other available card outputs such as S/PDIF even when that profile is not loaded. Selecting a row inspects name, ports, and the current default; it does not change the default sink.
- Overview **Network** checks: Avahi packages and daemon, nsswitch mDNS, UDP 5353, UFW/firewalld (no pkexec Fix yet), and a VPN-interface warning.
- AirPlay sidebar lists `_raop._tcp` / `_airplay._tcp` devices from Avahi (D-Bus, with `avahi-browse -p` fallback). AirPlay 2-only speakers are a warning, not “install more packages”.
- First-load skeleton uses the real status bar widgets (same height as Ready / Warnings). Overview checks, AirPlay, and This PC still skeleton until the first scan; later refreshes keep the last results.

### Changed

- Renamed the app from AirPlay Doctor to **DespairPlay** (package and console script `despairplay`, app id `uk.intention.DespairPlay`).
- UI direction: GNOME Settings-style sidebar (Overview, AirPlay devices, This PC outputs).
- Check rows: not clickable (no hover highlight or tooltip). OK status is a 28px filled circle with a tick (`emblem-default-symbolic`) plus Adwaita success colour.
- Ready state is a light grey bar with a green circle-tick before the word “Ready”, not the accent `Adw.Banner`.
- Checks use static cards instead of libadwaita boxed-list rows, which always show a hover.
- RAOP is treated as working when `raop_sink.*` / `sess.media=raop` nodes exist, even if `libpipewire-module-raop-discover` is not listed. Missing drop-in is a warning if speakers are already visible.
- Overview **Audio system** heading (was System). Fail/warn stay on Audio system and Network rows; there is no separate Issues list.

### Fixed

- Avahi D-Bus browse used the wrong `ServiceBrowserNew` signature, so discovery failed on every refresh. Missing `firewall-cmd` is ignored on Ubuntu instead of logging a warning.
- This PC lists S/PDIF (and similar card outputs) when the jack exists but PipeWire has another profile loaded.
