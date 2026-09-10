# Security Audit — 2026-08-27

## Scope

Reviewed the current codebase for security-relevant issues in:

- process execution
- privilege boundaries
- handling of untrusted network input
- file writes and configuration changes
- dangerous dynamic execution patterns

Primary files reviewed:

- `src/despairplay/engine/host.py`
- `src/despairplay/engine/avahi_browse.py`
- `src/despairplay/engine/fixes.py`
- `src/despairplay/engine/mdns.py`
- `src/despairplay/engine/network.py`
- `src/despairplay/engine/pipewire.py`
- `src/despairplay/engine/suite.py`
- `src/despairplay/ui/window.py`
- `docs/DESIGN.md`
- `pyproject.toml`
- `README.md`

## Overall assessment

The project currently has a **fairly small attack surface** and I did **not** find any obvious critical vulnerabilities such as remote code execution, shell injection, unsafe deserialization, or arbitrary privileged command execution.

The most important current concerns are local trust-boundary issues rather than remotely exploitable bugs.

## Findings

### 1. External commands are resolved via inherited `PATH`

**Severity:** Medium

The app invokes external tools by name rather than by absolute path, including:

- `systemctl`
- `pw-dump`
- `pactl`
- `dpkg-query`
- `ufw`
- `firewall-cmd`
- `avahi-browse`

Relevant code:

- `src/despairplay/engine/host.py`
- `src/despairplay/engine/avahi_browse.py`

This is **not** shell injection, because the code uses `subprocess.run([...])` argument vectors rather than `shell=True`, which is good. However, command resolution still depends on the process environment `PATH`.

### Risk

If the app is launched from a compromised or unusual environment, a malicious binary earlier in `PATH` could be executed instead of the intended system utility.

### Recommendation

- Resolve binaries once with `shutil.which()` and validate expected locations.
- Prefer absolute paths where practical.
- Fail safely if a required binary resolves to an unexpected location.

---

### 2. Unverified template copy into user PipeWire config

**Severity:** Medium

The user fix path copies a discovered PipeWire config template directly into the user config directory when available.

Relevant code:

- `src/despairplay/engine/fixes.py`
- `src/despairplay/engine/host.py`

Current behavior copies the entire template contents if `host.raop_avail_template()` returns a file.

### Risk

The source is expected to be a trusted system template under `/usr/share/pipewire/pipewire.conf.avail`, but the code does not currently verify:

- that the filename is one of a small expected allow-list
- that the resolved path remains under the expected directory
- that the content actually matches the intended RAOP-discover use case

This is not a likely remote exploit, but it is a trust-boundary weakness that could propagate unexpected config into the user profile on a compromised or misconfigured system.

### Recommendation

- Allow only expected filenames such as `50-raop.conf`, `raop.conf`, or `50-raop-discover.conf`.
- Verify the resolved template path is under the expected system template directory.
- Optionally validate that the template content contains the expected RAOP module stanza.
- Otherwise fall back to the built-in minimal config body.

---

### 3. Untrusted mDNS strings are displayed directly in the UI

**Severity:** Low

The app reads device names, addresses, hostnames, and TXT metadata from mDNS/Avahi and displays them in the UI.

Relevant code:

- `src/despairplay/engine/mdns.py`
- `src/despairplay/ui/window.py`

### Risk

This data comes from the local network and should be treated as untrusted input. In the current GTK UI this does **not** appear to create code-execution risk, but it can still create:

- misleading or spoofed device presentation
- long or malformed strings
- control-character or Unicode display edge cases
- noisy debug/support output

### Recommendation

- Normalize or strip control characters.
- Cap visible string lengths for names and TXT fields.
- Normalize whitespace before display.
- Keep raw TXT rendering bounded.

---

### 4. Future privileged-fix implementation is a major security hotspot

**Severity:** Design risk / future concern

The design document correctly states that privileged fixes should use:

> `pkexec` (fixed argv allow-list, not a free-form shell)

Relevant design note:

- `docs/DESIGN.md`

This is the right direction, but it will require careful implementation when added.

### Risk

If future root-level fixes are implemented with a generic shell wrapper or user-controlled command construction, that could introduce a high-severity privilege escalation or command injection vulnerability.

### Recommendation

When privileged fixes are implemented:

- use a very small dedicated helper
- use a strict allow-list of actions
- validate every argument against exact known values or enums
- do not pass free-form shell commands
- keep polkit permissions as narrow as possible
- log requested actions clearly

## Positive observations

### Safe subprocess style

I did not find `shell=True` usage. Process invocation is done with argv arrays, which materially reduces injection risk.

### No dangerous dynamic execution found

I did not find use of:

- `eval`
- `exec`
- `pickle`
- unsafe YAML deserialization

### Bounded subprocess calls

Most external command calls use explicit timeouts, which helps reduce hang and denial-of-service style issues from misbehaving tools or environments.

### Limited write surface

Current write behavior is narrow and mostly limited to the user PipeWire config path in `src/despairplay/engine/fixes.py`.

## Issues not observed

I did not find evidence of:

- shell injection from mDNS device names or TXT fields
- arbitrary file write based on network input
- embedded secrets or API keys
- inbound network service exposure
- unsafe download/update logic

## Recommended next hardening steps

1. Centralize and harden binary resolution in `src/despairplay/engine/host.py`.
2. Constrain and validate template copying in `src/despairplay/engine/fixes.py`.
3. Sanitize and bound mDNS-derived display strings before rendering in `src/despairplay/engine/mdns.py` / `src/despairplay/ui/window.py`.
4. Add a brief implementation security note for future privileged fixes in `docs/DESIGN.md` or `CONTRIBUTING.md`.

## Validation

No code changes were made as part of this audit note. I did run project diagnostics to check for editor-reported issues, but I did not run the full test suite as part of the security review.