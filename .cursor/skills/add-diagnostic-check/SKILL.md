---
name: add-diagnostic-check
description: >-
  Add or change a DespairPlay diagnostic check or one-click fix (Avahi,
  PipeWire RAOP, firewall, mDNS, speakers). Use when implementing engine
  checks, parsers, fixtures, Fix actions, or pkexec helper allow-list entries.
---

# Add a diagnostic check

Follow [docs/DESIGN.md](../../../docs/DESIGN.md) and [CONTRIBUTING.md](../../../CONTRIBUTING.md).

## Steps

1. **One engine module** under `src/despairplay/engine/`. No `gi`, no GTK. Return `ok | warn | fail`, short reason, evidence (command or path), optional fix id.
2. **Parse structured data**: Avahi D-Bus (`org.freedesktop.Avahi`), `pw-dump` JSON, `dpkg-query`, file existence. Do not scrape `avahi-browse` as the primary path.
3. **Fixture + unit test** in `tests/fixtures/` + `tests/`. Default pytest is offline. Live network tests: `@pytest.mark.integration` and never run in CI.
4. **Ubuntu names**: `libpipewire-0.3-modules`, `avahi-daemon`, `libnss-mdns`. Detect RAOP by `.so` under `/usr/lib/*/pipewire-0.3/`, not Arch `pipewire-zeroconf`.
5. **UI row** in Issues (and the matching System/Network/Speakers section). **Fix** only if the action is allow-listed and you show the exact commands first.
6. **Changelog**: user-visible check or fix → bullet under `## [Unreleased]` in `CHANGELOG.md`.

## Fixes

| Level | Examples |
| --- | --- |
| User | Copy `pipewire.conf.avail` RAOP template or write `~/.config/pipewire/pipewire.conf.d/raop-discover.conf`; `systemctl --user restart pipewire pipewire-pulse wireplumber`; `pw-cli load-module …` |
| `pkexec` helper | `apt-get install` allow-listed packages; `systemctl enable --now avahi-daemon`; UFW `5353/udp` (optional `6001:6002/udp`) |

Do **not**: edit `/etc/nsswitch.conf` or `systemd-resolved` in v1; set default sink; “fix” VLAN/AP isolation; use `shell=True`; silently rewrite unrelated config.

## AirPlay 2

If a device has `_airplay._tcp` and no `_raop._tcp`, the result is a first-class **AirPlay 2-only** warning, not fail/install-more-packages.
