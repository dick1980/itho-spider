"""Small, dependency-free codec for the Itho Spider/evofw3 protocol.

Evidence: ramses_rf payload parsers and regression captures, issue 73, and
Onl1ne1373/home-assistant-blueprints spider.yaml v1.18. This is not a complete
Spider protocol implementation. In particular, the 01FF command template has
partly unknown fields. It must not be advertised as preserving every device
setting, nor used to implement HVAC mode, clock-program or preset changes.

Only incoming Spider packets update reported state. A transmitted packet/USB
echo is not an acknowledgement. This module performs no I/O or pairing.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, replace

NO_DEVICE = "--:------"
ALL_DEVICES = "63:262142"
SUPPORTED_CODES = frozenset({"01FF", "22C9", "30C9", "3110", "12C0", "1060"})
MIN_TEMPERATURE = 5.0
MAX_TEMPERATURE = 30.0
TEMPERATURE_STEP = 0.5
COMMAND_PROFILE = "spider-blueprint-v1.18-manual"

# The blueprint supplies both temperature fields and manual mode D0. We retain
# the observed second field instead of the blueprint's synthetic target + 1.
# Offsets 9/10 (14/3C) and 15/16 (B4/00) are NOT decoded device limits/modes.
# Copying corresponding status bytes into a command would be another unverified
# profile. Keep the published profile explicit, with its limitations documented.
_COMMAND_TEMPLATE = bytes.fromhex("008080282AD0000000143C80800000B40080800280FF80040000")
_DEVICE_ID_RE = re.compile(r"[0-9]{2}:[0-9]{6}\Z")
_HEX_RE = re.compile(r"[0-9A-Fa-f]+\Z")
_ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T\S+\Z")


class ProtocolError(ValueError):
    """A command cannot be constructed from the supplied information."""


@dataclass(frozen=True, slots=True)
class Packet:
    """An evofw3 receive line; src/dst/via retain the three wire addresses."""

    verb: str
    src: str
    dst: str
    via: str
    code: str
    payload: bytes
    rssi: int | None = None
    sequence: int | None = None
    raw: str = ""

    @property
    def payload_hex(self) -> str:
        return self.payload.hex().upper()

    def is_gateway_echo(self, gateway_id: str) -> bool:
        """The gateway's source ID identifies its echo, not an RSSI of zero."""
        return self.src == gateway_id


@dataclass(frozen=True, slots=True)
class SpiderState:
    """Reported values only; None means unknown, never a startup default.

    ``target_temperature`` and ``cooling_target`` are the two reported setpoint
    fields, not allowable minimum/maximum temperatures. They may be inverted
    (this device has reported 21/20). ``demand`` is a fraction from 0 to 1.
    Monotonic timestamps let the controller enforce freshness independently.
    """

    temperature: float | None = None
    display_temperature: float | None = None
    target_temperature: float | None = None
    cooling_target: float | None = None
    demand: float | None = None
    operating_mode: str | None = None
    battery_low: bool | None = None
    battery_percent: float | None = None
    time_planning: bool | None = None
    temp_adjusted: bool | None = None
    raw_01ff: bytes | None = None
    last_code: str | None = None
    last_seen: float | None = None
    last_setpoint_at: float | None = None
    last_01ff_at: float | None = None
    temperature_source: str | None = None
    temperature_at: float | None = None

    @property
    def heating_demand(self) -> float | None:
        return self.demand if self.operating_mode == "heat" else None


def validate_device_id(device_id: str, prefix: str | int | None = None) -> str:
    """Validate a RAMSES ID (6-bit type, 18-bit serial) without normalising it."""
    if not isinstance(device_id, str) or not _DEVICE_ID_RE.fullmatch(device_id):
        raise ProtocolError("Device ID must have the form 21:123456")
    device_type, serial_number = map(int, device_id.split(":"))
    if device_type > 63 or serial_number > 262143:
        raise ProtocolError("Device ID exceeds the RAMSES address range")
    if prefix is not None and device_type != int(prefix):
        raise ProtocolError(f"Device ID must start with {int(prefix):02d}:")
    return device_id


def parse_packet(line: str | bytes) -> Packet | None:
    """Parse a complete receive line, returning None for noise/invalid frames.

    Accepts the optional ISO timestamp used in saved logs. Rejects length
    mismatches, illegal addresses, error trailers and unsupported frame verbs.
    No outgoing, header-less command is accepted as a received packet.
    """
    if isinstance(line, bytes):
        try:
            line = line.decode("ascii")
        except UnicodeDecodeError:
            return None
    if not isinstance(line, str):
        return None
    raw = line.strip()
    if not raw or raw[0] in "#!@":
        return None
    # Comments in regression logs are evidence annotations, not serial data.
    fields = raw.split(" #", 1)[0].split()
    if fields and _ISO_DATE_RE.fullmatch(fields[0]):
        fields.pop(0)
    if len(fields) != 9:
        return None
    rssi, verb, sequence, src, dst, via, code, length, payload_hex = fields
    if verb not in {"I", "W", "RQ", "RP"}:
        return None
    if rssi not in {"---", "..."} and not re.fullmatch(r"[0-9]{3}", rssi):
        return None
    if sequence != "---" and not re.fullmatch(r"[0-9]{3}", sequence):
        return None
    if not re.fullmatch(r"[0-9A-Fa-f]{4}", code):
        return None
    if not re.fullmatch(r"[0-9]{3}", length):
        return None
    payload_length = int(length)
    if not 1 <= payload_length <= 48 or len(payload_hex) != payload_length * 2:
        return None
    if not _HEX_RE.fullmatch(payload_hex):
        return None
    try:
        for address in (src, dst, via):
            if address != NO_DEVICE:
                validate_device_id(address)
    except ProtocolError:
        return None
    return Packet(
        verb=verb,
        src=src,
        dst=dst,
        via=via,
        code=code.upper(),
        payload=bytes.fromhex(payload_hex),
        rssi=None if rssi in {"---", "..."} else int(rssi),
        sequence=None if sequence == "---" else int(sequence),
        raw=raw,
    )


def _setpoint(value: float | None) -> float | None:
    if value is None or not MIN_TEMPERATURE <= value <= MAX_TEMPERATURE:
        return None
    return value


def _half_temperature(raw: int) -> float | None:
    return None if raw in {0x7F, 0x80, 0xFF} else raw / 2.0


def _centi_temperature(raw: bytes) -> float | None:
    if raw in {b"\x7f\xff", b"\x31\xff", b"\x80\x00", b"\xff\xff"}:
        return None
    return int.from_bytes(raw, "big", signed=True) / 100.0


def _room_temperature(value: float | None) -> float | None:
    # Spider Base specifies a 0..40 C measuring range.
    return value if value is not None and 0 <= value <= 40 else None


def packet_is_from_spider(packet: Packet, spider_id: str, gateway_id: str) -> bool:
    """Match the configured source and this gateway/self/broadcast addressing.

    A direct report to a different gateway is not evidence of our association.
    This integration deliberately does not track other Autotemp relationships.
    """
    return packet.src == spider_id and packet.dst in {NO_DEVICE, spider_id, gateway_id, ALL_DEVICES}


def update_state(
    state: SpiderState,
    packet: Packet,
    spider_id: str,
    gateway_id: str,
    *,
    received_at: float | None = None,
) -> SpiderState:
    """Merge a supported report, ignoring other devices and gateway echoes.

    RQ/01FF carries real Spider status; ordinary RQs do not. W/22C9 is a local
    Spider setpoint report and is accepted. Controller commands from another
    source, including the configured gateway, cannot update this state.
    """
    if not packet_is_from_spider(packet, spider_id, gateway_id):
        return state
    if packet.code not in SUPPORTED_CODES:
        return state
    payload = packet.payload
    now = time.monotonic() if received_at is None else received_at
    changes: dict[str, object] = {}
    room_temp: float | None = None
    temperature_report = False

    if packet.code == "01FF":
        if packet.verb not in {"I", "RQ", "RP"} or len(payload) != 26:
            return state
        if payload[0] not in {0, 1} or payload[1] != 0x80:
            return state
        room_temp = _room_temperature(_half_temperature(payload[2]))
        temperature_report = True
        changes.update(
            display_temperature=room_temp,
            target_temperature=_setpoint(_half_temperature(payload[3])),
            cooling_target=(
                None if payload[11] == 0x80 else _setpoint(_half_temperature(payload[4]))
            ),
            time_planning=not bool(payload[5] & 0x40),
            temp_adjusted=bool(payload[5] & 0x20),
            raw_01ff=payload,
            last_setpoint_at=now,
            last_01ff_at=now,
        )
    elif packet.code == "22C9":
        if packet.verb not in {"I", "W", "RP"} or len(payload) != 6:
            return state
        if payload[0] != 0:
            return state
        changes.update(
            target_temperature=_setpoint(_centi_temperature(payload[1:3])),
            cooling_target=_setpoint(_centi_temperature(payload[3:5])),
            operating_mode={0: "off", 1: "heat", 2: "cool"}.get(payload[5]),
            last_setpoint_at=now,
        )
    elif packet.code == "30C9":
        if packet.verb not in {"I", "RP"} or len(payload) != 3:
            return state
        if payload[0] != 0:
            return state
        room_temp = _room_temperature(_centi_temperature(payload[1:3]))
        temperature_report = True
    elif packet.code == "3110":
        if packet.verb not in {"I", "RP"} or len(payload) != 4:
            return state
        if payload[0] != 0:
            return state
        mode = {0x00: "off", 0x10: "heat", 0x20: "cool"}.get(payload[3])
        if mode is None or payload[2] > 200:
            return state
        changes.update(
            operating_mode=mode,
            demand=None if mode == "off" else payload[2] / 200.0,
        )
    elif packet.code == "12C0":
        if packet.verb not in {"I", "RP"} or len(payload) not in {3, 4}:
            return state
        if payload[0] != 0 or payload[2] not in {0, 1, 2}:
            return state
        if payload[1] == 0x80:
            room_temp = None
        elif payload[2] == 1:
            room_temp = _room_temperature(payload[1] / 2.0)
        else:
            room_temp = _room_temperature(round((payload[1] - 32) * 5 / 9, 2))
        changes["display_temperature"] = room_temp
        temperature_report = True
    elif packet.code == "1060":
        if packet.verb not in {"I", "RP"} or len(payload) != 3:
            return state
        if payload[0] != 0:
            return state
        if payload[2] not in {0, 1} or (payload[1] > 200 and payload[1] != 0xFF):
            return state
        changes.update(
            battery_low=payload[2] == 0,
            battery_percent=None if payload[1] in {0, 0xFF} else payload[1] / 2.0,
        )

    if temperature_report:
        # Prefer a recent 0.01 C report to rounded display reports. After three
        # minutes without one, allow a fresh display report as the fallback.
        precise_is_recent = (
            state.temperature_source == "30C9"
            and state.temperature_at is not None
            and 0 <= now - state.temperature_at < 180
        )
        if packet.code == "30C9" or not precise_is_recent:
            changes.update(
                temperature=room_temp,
                temperature_source=packet.code,
                temperature_at=now,
            )
    changes.update(last_code=packet.code, last_seen=now)
    return replace(state, **changes)


def _require_half_step(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ProtocolError(f"{name} must be finite")
    if not math.isclose(value * 2, round(value * 2), abs_tol=1e-9):
        raise ProtocolError(f"{name} must be a multiple of 0.5 C")
    return float(value)


def build_setpoint_command(
    spider_id: str,
    gateway_id: str,
    temperature: float,
    state: SpiderState,
    *,
    verb: str = "W",
    min_temperature: float = MIN_TEMPERATURE,
    max_temperature: float = MAX_TEMPERATURE,
) -> str:
    """Build a CR-terminated manual heating command using the known profile.

    Requires observed manual 01FF state and both valid setpoint fields. This
    function does not update reported state. The caller MUST enforce freshness,
    verified gateway identity, request addressing (for RP), rate limits, and a
    bounded wait for a Spider report confirming the requested temperature.

    The second setpoint is retained, even if below the heating target. Hardware
    acceptance of every such combination is not established. Unknown template
    bytes follow the published blueprint; device-specific limits are not
    inferred from unknown status bytes. No clock/HVAC/preset write API exists.
    """
    validate_device_id(spider_id, 21)
    validate_device_id(gateway_id, 18)
    if verb not in {"W", "RP"}:
        raise ProtocolError("Only W and RP are supported for 01FF commands")
    temperature = _require_half_step(temperature, "Temperature")
    minimum = _require_half_step(min_temperature, "Minimum temperature")
    maximum = _require_half_step(max_temperature, "Maximum temperature")
    if not MIN_TEMPERATURE <= minimum <= maximum <= MAX_TEMPERATURE:
        raise ProtocolError("Configured temperature range must be within 5..30 C")
    if not minimum <= temperature <= maximum:
        raise ProtocolError("Temperature is outside the configured range")
    if state.raw_01ff is None or len(state.raw_01ff) != 26:
        raise ProtocolError("A current Spider 01FF report is required before writing")
    if state.raw_01ff[0] not in {0, 1} or state.raw_01ff[1] != 0x80:
        raise ProtocolError("The stored 01FF report has an unsupported format")
    if state.time_planning is not False:
        raise ProtocolError("Only an observed manual thermostat state is supported")
    if not state.raw_01ff[5] & 0x40:
        raise ProtocolError("The stored 01FF report does not indicate manual operation")
    if state.operating_mode in {"cool", "off"}:
        raise ProtocolError("Temperature writes are supported in heating operation only")
    if state.target_temperature is None or state.cooling_target is None:
        raise ProtocolError("Both current Spider setpoint fields must be known")
    current = _require_half_step(state.target_temperature, "Current target")
    cooling = _require_half_step(state.cooling_target, "Second setpoint")
    if _setpoint(current) is None or _setpoint(cooling) is None:
        raise ProtocolError("Reported setpoints must be within 5..30 C")
    payload = bytearray(_COMMAND_TEMPLATE)
    payload[3] = round(temperature * 2)
    payload[4] = round(cooling * 2)
    return (
        f"{verb} --- {gateway_id} {spider_id} {NO_DEVICE} 01FF "
        f"{len(payload):03d} {payload.hex().upper()}\r"
    )


def build_local_setpoint_ack(packet: Packet, spider_id: str, gateway_id: str) -> str:
    """Acknowledge this Spider's direct W/22C9 heating setpoint report.

    The published blueprint answers W/22C9 with I/22C9. Its hardcoded second
    temperature (20.5 C) is deliberately not used here: echo both reported
    fields. Live observations show W/22C9 after remote commands as well as
    physical changes; the verb alone does not identify a physical override.
    The caller uses the original report to confirm a matching pending target
    or to cancel a different one, never this acknowledgement's later USB echo.
    """
    validate_device_id(spider_id, 21)
    validate_device_id(gateway_id, 18)
    if (
        packet.src != spider_id
        or packet.dst != gateway_id
        or packet.via != NO_DEVICE
        or packet.verb != "W"
        or packet.code != "22C9"
        or len(packet.payload) != 6
        or packet.payload[0] != 0
        or packet.payload[5] != 1
    ):
        raise ProtocolError("Only a direct local W/22C9 heating request can be acknowledged")
    for raw in (packet.payload[1:3], packet.payload[3:5]):
        value = _setpoint(_centi_temperature(raw))
        if value is None:
            raise ProtocolError("Both local setpoint fields must be valid")
        _require_half_step(value, "Local setpoint")
    return f"I --- {gateway_id} {spider_id} {NO_DEVICE} 22C9 006 {packet.payload_hex}\r"
