"""mDNS AirPlay/RAOP records, grouping, and speaker check. No GTK."""

from __future__ import annotations

from dataclasses import dataclass

from despairplay.engine.host import Host
from despairplay.engine.pipewire import raop_sink_labels
from despairplay.engine.result import CheckResult, Group, Status

SERVICE_RAOP = "_raop._tcp"
SERVICE_AIRPLAY = "_airplay._tcp"
_EVIDENCE = "org.freedesktop.Avahi ServiceBrowser"


@dataclass(frozen=True)
class MdnsRecord:
    name: str
    service_type: str
    host: str
    address: str
    port: int
    txt: dict[str, str]


@dataclass(frozen=True)
class AirPlayDevice:
    key: str
    name: str
    address: str
    port: int
    host: str
    has_raop: bool
    has_airplay: bool
    airplay2_only: bool
    txt: dict[str, str]
    sink_label: str | None


def friendly_name(mdns_name: str) -> str:
    if "@" in mdns_name:
        suffix = mdns_name.split("@", 1)[1].strip()
        if suffix:
            return suffix
    return mdns_name


def parse_txt_pairs(items: list[bytes] | tuple[bytes, ...]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        text = item.decode("utf-8", errors="replace")
        if "=" in text:
            key, value = text.split("=", 1)
            parsed[key] = value
        elif text:
            parsed[text] = ""
    return parsed


def parse_avahi_quoted_txt(raw: str) -> dict[str, str]:
    quoted = [match[1:-1] for match in _quoted_chunks(raw)]
    if quoted:
        return parse_txt_pairs(tuple(chunk.encode("utf-8") for chunk in quoted))
    parts = [part.strip() for part in raw.split() if part.strip()]
    return parse_txt_pairs(tuple(part.encode("utf-8") for part in parts))


def _quoted_chunks(raw: str) -> list[str]:
    chunks: list[str] = []
    start: int | None = None
    for index, char in enumerate(raw):
        if char == '"' and start is None:
            start = index
        elif char == '"' and start is not None:
            chunks.append(raw[start : index + 1])
            start = None
    return chunks


def parse_avahi_browse_p(text: str) -> tuple[MdnsRecord, ...]:
    records: list[MdnsRecord] = []
    for raw in text.splitlines():
        if not raw.startswith("="):
            continue
        parts = raw.split(";")
        if len(parts) < 9:
            continue
        service_type = parts[4]
        if service_type not in {SERVICE_RAOP, SERVICE_AIRPLAY}:
            continue
        try:
            port = int(parts[8])
        except ValueError:
            continue
        txt_raw = ";".join(parts[9:]) if len(parts) > 9 else ""
        records.append(
            MdnsRecord(
                name=parts[3],
                service_type=service_type,
                host=parts[6],
                address=parts[7],
                port=port,
                txt=parse_avahi_quoted_txt(txt_raw),
            )
        )
    return tuple(records)


def records_from_dicts(rows: object) -> tuple[MdnsRecord, ...]:
    if not isinstance(rows, list):
        return ()
    records: list[MdnsRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        txt_raw = row.get("txt")
        txt = (
            {str(key): str(value) for key, value in txt_raw.items()}
            if isinstance(txt_raw, dict)
            else {}
        )
        try:
            port = int(row.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        records.append(
            MdnsRecord(
                name=str(row.get("name") or ""),
                service_type=str(row.get("service_type") or ""),
                host=str(row.get("host") or ""),
                address=str(row.get("address") or ""),
                port=port,
                txt=txt,
            )
        )
    return tuple(records)


def _bucket(record: MdnsRecord) -> str:
    address = record.address
    if address and ":" not in address:
        return f"ip:{address}"
    return f"name:{friendly_name(record.name).casefold()}"


def _match_sink(name: str, labels: tuple[str, ...]) -> str | None:
    folded = name.casefold()
    for label in labels:
        other = label.casefold()
        if folded == other or folded in other or other in folded:
            return label
    return None


def group_devices(
    records: tuple[MdnsRecord, ...],
    sink_labels: tuple[str, ...] = (),
) -> tuple[AirPlayDevice, ...]:
    buckets: dict[str, list[MdnsRecord]] = {}
    for record in records:
        buckets.setdefault(_bucket(record), []).append(record)
    devices: list[AirPlayDevice] = []
    for key, group in buckets.items():
        has_raop = any(item.service_type == SERVICE_RAOP for item in group)
        has_airplay = any(item.service_type == SERVICE_AIRPLAY for item in group)
        raop = next((item for item in group if item.service_type == SERVICE_RAOP), None)
        airplay = next(
            (item for item in group if item.service_type == SERVICE_AIRPLAY), None
        )
        primary = raop or airplay or group[0]
        name = friendly_name(primary.name)
        txt: dict[str, str] = {}
        if airplay is not None:
            txt.update(airplay.txt)
        if raop is not None:
            txt.update(raop.txt)
        devices.append(
            AirPlayDevice(
                key=key,
                name=name,
                address=primary.address,
                port=primary.port,
                host=primary.host,
                has_raop=has_raop,
                has_airplay=has_airplay,
                airplay2_only=has_airplay and not has_raop,
                txt=txt,
                sink_label=_match_sink(name, sink_labels),
            )
        )
    devices.sort(key=lambda item: item.name.casefold())
    return tuple(devices)


def check_mdns_speakers(host: Host) -> CheckResult:
    records = host.avahi_records()
    if records is None:
        return CheckResult(
            check_id="mdns-speakers",
            title="AirPlay speakers on the network",
            status=Status.WARN,
            reason="Could not browse mDNS (Avahi D-Bus)",
            evidence=_EVIDENCE,
            group=Group.SPEAKERS,
        )
    labels = raop_sink_labels(host.pw_dump_json())
    devices = group_devices(records, labels)
    raop = tuple(item.name for item in devices if item.has_raop)
    ap2 = tuple(item.name for item in devices if item.airplay2_only)
    if not devices:
        return CheckResult(
            check_id="mdns-speakers",
            title="AirPlay speakers on the network",
            status=Status.WARN,
            reason="No AirPlay speakers advertised on the network",
            evidence=_EVIDENCE,
            group=Group.SPEAKERS,
        )
    if raop and not ap2:
        return CheckResult(
            check_id="mdns-speakers",
            title="AirPlay speakers on the network",
            status=Status.OK,
            reason=", ".join(raop),
            evidence=_EVIDENCE,
            group=Group.SPEAKERS,
        )
    if raop and ap2:
        return CheckResult(
            check_id="mdns-speakers",
            title="AirPlay speakers on the network",
            status=Status.WARN,
            reason=(
                f"RAOP: {', '.join(raop)}. AirPlay 2 only (Linux cannot send): "
                f"{', '.join(ap2)}"
            ),
            evidence=_EVIDENCE,
            group=Group.SPEAKERS,
        )
    return CheckResult(
        check_id="mdns-speakers",
        title="AirPlay speakers on the network",
        status=Status.WARN,
        reason=("AirPlay 2 only (Linux cannot send): " + ", ".join(ap2)),
        evidence=_EVIDENCE,
        group=Group.SPEAKERS,
    )
