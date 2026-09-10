# DespairPlay Project Overview

## What this project is

`Airplay GUI` is a **Python GTK4/libadwaita desktop app** called **DespairPlay**.

Its purpose is to **diagnose the Linux AirPlay sender stack** — specifically the path for sending audio to AirPlay speakers via **RAOP / AirPlay 1**.

It is **not**:
- an AirPlay receiver
- a screen mirroring app
- an AirPlay 2 sender

That limitation is intentional and central to the app’s design: if a speaker is **AirPlay 2-only**, the app is supposed to explain that clearly instead of pretending the problem is just “missing packages”.

## Core architecture

The project is split cleanly into two parts:

- `src/despairplay/engine/`  
  Pure Python diagnostic engine. No GTK imports. This contains:
  - system/network checks
  - mDNS / Avahi discovery logic
  - PipeWire / RAOP detection
  - safe user-level fixes

- `src/despairplay/ui/`  
  GTK4/libadwaita frontend only. GI imports are centralized in:
  - `src/despairplay/ui/gi_imports.py`

That separation is reinforced in docs and tests.

## Package / entry points

From `pyproject.toml` and `__main__.py`:

- Python package: `despairplay`
- Console script: `despairplay`
- App entry: `despairplay.__main__:main`
- GUI startup flows through:
  - `src/despairplay/ui/app.py`
  - `src/despairplay/ui/window.py`

The current version is:
- `0.1.0`

## Developer setup

### Requirements
This project expects **Linux**, specifically **Ubuntu / Zorin** conventions.

Important setup rule:
- GTK bindings come from **system GI packages**, **not pip**

The README says the user must install GTK-related system packages manually if missing, such as:
- `python3-gi`
- `gir1.2-gtk-4.0`
- `gir1.2-adw-1`
- `pipewire-bin`
- `avahi-utils`

Also, PipeWire RAOP modules are expected from:
- `libpipewire-0.3-modules`

### Virtual environment
The venv must be created with:

```bash
python3 -m venv --system-site-packages
```

That matters because `gi` must remain visible from distro packages.

### Standard workflow
The intended source workflow is:

```bash
make install-dev
make run
```

### Make targets
`Makefile` defines:

- `make install-dev` — create `.venv` and install editable package with dev extras
- `make lint` — Ruff check + format check
- `make format` — Ruff autofix + formatting
- `make typecheck` — mypy strict
- `make test` — pytest
- `make check` — lint + typecheck + test
- `make run` — run GUI

## Dependencies / tooling

Python packaging is intentionally light:

- Build backend: `hatchling`
- Runtime Python deps: effectively none in `pip`
- Dev deps:
  - `ruff`
  - `mypy`
  - `pytest`
  - `pytest-cov`
  - `pre-commit`

So the app relies heavily on:
- distro-provided GTK / libadwaita GI bindings
- system tools like `pw-dump`, `systemctl`, `dpkg-query`, `ufw`

## What the app does

### High-level purpose
It inspects whether Linux is correctly set up to send audio to AirPlay speakers through:

- **PipeWire**
- **RAOP discovery/sink modules**
- **Avahi / mDNS**
- **firewall rules**
- **network conditions like VPNs**

### The scan flow
The main scan entry is:

- `src/despairplay/engine/suite.py`

`run_scan()` collects:
1. a list of diagnostic checks
2. discovered AirPlay devices

The checks currently run in this order:

1. PipeWire user units
2. RAOP modules present
3. RAOP autostart configured
4. RAOP discover module loaded
5. RAOP sinks present
6. Avahi packages installed
7. Avahi daemon active
8. `nsswitch.conf` has mDNS support
9. UDP 5353 listening
10. firewall status
11. VPN interface warning
12. discovered AirPlay speakers

## Checks currently implemented

### PipeWire / RAOP checks
In `src/despairplay/engine/pipewire.py`:

- whether these user services are active:
  - `pipewire.service`
  - `pipewire-pulse.service`
  - `wireplumber.service`

- whether these shared objects exist:
  - `libpipewire-module-raop-discover.so`
  - `libpipewire-module-raop-sink.so`

- whether RAOP autostart is configured via:
  - PipeWire user/system drop-ins, or
  - GNOME extension `pipewire-airplay-toggle`

- whether RAOP discovery is currently loaded, detected via:
  - `pw-dump`, or
  - `pactl list short modules`

- whether live RAOP sinks exist in the PipeWire graph

### Avahi / network checks
In `src/despairplay/engine/network.py`:

- required Avahi packages installed:
  - `avahi-daemon`
  - `avahi-utils`
  - `libnss-mdns`

- `avahi-daemon` running

- `hosts:` line in `/etc/nsswitch.conf` includes an mDNS resolver

- whether anything is listening on UDP port `5353`

- firewall status:
  - UFW support
  - firewalld support
  - fail if mDNS is blocked
  - warn if RAOP UDP `6001-6002` may be blocked

- VPN interface detection
  - warns when interfaces like `tun`, `wg`, `tailscale`, etc. are present

### AirPlay / mDNS speaker checks
In `src/despairplay/engine/mdns.py`:

- discovers `_raop._tcp` and `_airplay._tcp`
- groups records into friendly “devices”
- distinguishes:
  - devices that support RAOP
  - devices that are **AirPlay 2-only**

This is one of the key product ideas:
- if a device advertises only `_airplay._tcp` and not `_raop._tcp`, the app marks it as **AirPlay 2-only** and warns that Linux cannot send to it.

## Discovery implementation

The design prefers **Avahi D-Bus** as the primary discovery path.

The changelog indicates the app currently uses:
- **Avahi D-Bus**, with
- `avahi-browse -p` fallback

The engine also parses:
- Avahi TXT records
- `pw-dump` JSON
- UFW status text
- `/proc/net/udp`

So the app is built around structured or semi-structured system inspection, not just generic shell scraping everywhere.

## Fix functionality

There is currently **one implemented fix**, in:

- `src/despairplay/engine/fixes.py`

### Implemented safe user-level fix
`enable-raop-discover`

What it does:
- creates `~/.config/pipewire/pipewire.conf.d/`
- either:
  - copies an existing distro RAOP template like `50-raop.conf`, or
  - writes a minimal `raop-discover.conf`
- restarts:
  - `pipewire`
  - `pipewire-pulse`
  - `wireplumber`

The app can also **plan** the fix first and show what it will do before applying it.

### What is not implemented yet
The design mentions privileged fixes via `pkexec`, like:
- installing missing packages
- enabling Avahi
- opening firewall ports

But those do **not** appear to be implemented yet in the current codebase.

## Current UI behavior

The UI in `src/despairplay/ui/window.py` is already more than a stub.

### Layout
It follows a **GNOME Settings-style split view** using libadwaita:
- left sidebar
- main content pane

### Sidebar sections
The design and changelog indicate three sections:

- **Overview**
- **AirPlay**
- **This PC**

Current state:
- Overview is functional
- AirPlay device listing is functional
- “This PC” exists conceptually, but changelog says it is still **placeholder**

### UI characteristics
Implemented UI details include:
- refresh button
- status icons for `ok / warn / fail`
- “Ready” bar
- static check cards
- first-load skeleton placeholders
- periodic refresh timer (`~3s`) for device appearance

Important UX rule:
- selecting a device is **inspect only**
- the app does **not** auto-change the default output sink

## Testing state

Tests are reasonably solid for the engine side.

### Test coverage focus
The tests cover:
- parser behavior
- check logic
- fake host scenarios
- fix behavior

Relevant files:
- `tests/test_mdns.py`
- `tests/test_network.py`
- `tests/test_pipewire_checks.py`
- `tests/test_pipewire_dump.py`
- `tests/test_package.py`
- `tests/fakes.py`

### Test philosophy
- default pytest is **offline**
- no real speakers required
- fixture-driven
- integration tests are intended to be opt-in

That matches the design goals.

## Current maturity / status

This project is in an **alpha / early implementation stage**.

Evidence:
- classifier says `Development Status :: 3 - Alpha`
- changelog shows many pieces as newly added
- some planned v1 features are present only in design, not fully implemented

### Implemented now
- packaging/tooling scaffold
- engine architecture
- core PipeWire checks
- core Avahi/network checks
- AirPlay vs AirPlay 2-only diagnosis
- one user-level fix
- GTK split-view UI bound to checks

### Still incomplete / future-looking
- full “This PC” sink inspection
- privileged fixes via `pkexec`
- more complete system repair flows
- likely broader UI polish and richer device detail panes

## Practical mental model

The project is essentially:

> A Linux desktop troubleshooting app for “Why can’t my PC see or use this AirPlay speaker?”

It answers questions like:
- Is PipeWire running?
- Are the RAOP modules installed?
- Is RAOP discovery enabled?
- Is Avahi working?
- Is mDNS blocked?
- Is a firewall interfering?
- Is a VPN breaking multicast?
- Is this speaker actually RAOP-capable, or is it AirPlay 2-only?

## Key files to know

If you want the fastest orientation:

- `Airplay GUI/README.md` — setup and purpose
- `Airplay GUI/docs/DESIGN.md` — architecture and product rules
- `Airplay GUI/src/despairplay/engine/suite.py` — overall scan orchestration
- `Airplay GUI/src/despairplay/engine/pipewire.py` — PipeWire/RAOP checks
- `Airplay GUI/src/despairplay/engine/network.py` — Avahi/firewall/VPN checks
- `Airplay GUI/src/despairplay/engine/mdns.py` — device discovery and AirPlay 2-only logic
- `Airplay GUI/src/despairplay/engine/fixes.py` — implemented fix
- `Airplay GUI/src/despairplay/ui/window.py` — main UI
- `Airplay GUI/tests/` — fixture-driven engine tests
