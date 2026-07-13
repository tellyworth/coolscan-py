#!/usr/bin/env python3
"""Analyze USB capture files for Nikon Coolscan protocol.

Parses text-format or pcapng capture files, decodes each USB transfer into
named commands with parameters, groups events into protocol phases, detects
errors and issues, and outputs a human-readable summary or JSON.

Supports diffing two captures and annotating commands against protocol.py.
"""

import argparse
import json
import sys
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ensure repo root is importable so we can use sibling packages
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from coolscan.usb_replay import _decode_payload_field, BULK_OUT_EP, BULK_IN_EP

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class SenseKey:
    """SCSI sense key names."""
    GOOD = "GOOD"
    RECOVERED_ERR = "RECOVERED_ERR"
    NOT_READY = "NOT_READY"
    MEDIA_ERR = "MEDIA_ERR"
    HARDWARE_ERR = "HARDWARE_ERR"
    ILLEGAL_REQ = "ILLEGAL_REQ"
    UNIT_ATTENTION = "UNIT_ATTENTION"
    DATA_PROTECT = "DATA_PROTECT"
    VENDOR_SPECIFIC = "VENDOR_SPECIFIC"
    ABORTED = "ABORTED"


class Phase(Enum):
    INIT = "init"
    READY_WAIT = "ready_wait"
    CONFIG = "config"
    PRESCAN = "prescan"
    SCAN = "scan"
    EJECT = "eject"
    UNKNOWN = "unknown"


# Lookup tables

CMD_NAMES: Dict[int, str] = {
    0x00: "TEST_UNIT_READY",
    0x12: "INQUIRY",
    0x15: "MODE_SELECT",
    0x16: "RESERVE_UNIT",
    0x17: "RELEASE_UNIT",
    0x1a: "MODE_SENSE",
    0x1b: "START_STOP_UNIT",
    0x24: "SCAN",
    0x25: "READ_CAPACITY",
    0x28: "READ",
    0x2a: "WRITE",
    0xc1: "EXECUTE",
    0xd0: "PHASE_CHECK",
    0xe0: "VENDOR_E0",
    0xe1: "VENDOR_E1",
}

SENSE_KEY_NAMES: Dict[int, str] = {
    0x00: SenseKey.GOOD,
    0x01: SenseKey.RECOVERED_ERR,
    0x02: SenseKey.NOT_READY,
    0x03: SenseKey.MEDIA_ERR,
    0x04: SenseKey.HARDWARE_ERR,
    0x05: SenseKey.ILLEGAL_REQ,
    0x06: SenseKey.UNIT_ATTENTION,
    0x07: SenseKey.DATA_PROTECT,
    0x09: SenseKey.VENDOR_SPECIFIC,
    0x0B: SenseKey.ABORTED,
}

PHASE_TYPE_NAMES: Dict[int, str] = {
    0x00: "NONE",
    0x01: "STATUS",
    0x02: "OUT",
    0x03: "IN",
    0x04: "BUSY",
}

DATA_TYPE_NAMES: Dict[int, str] = {
    0x00: "IMAGE_DATA",
    0x01: "LUT",
    0x87: "STATUS_PROGRESS",
    0x8F: "CONTROL_FRAME",
    0x92: "BORDER_POSITION",
    0x8C: "CHANNEL_STATE",
    0xA0: "SHADING_DATA",
    0x8E: "EXPOSURE_CALIBRATION",
    0x88: "IMAGE_POSITIONS",
    0xC0: "USER_REG_GAMMA",
    0xE0: "DEVICE_INTERNAL_INFO",
}

E0_SUBCODE_NAMES: Dict[int, str] = {
    0x80: "reset",
    0xa0: "autofocus",
    0xb0: "calibrate",
    0xb4: "ice_setup",
    0xc1: "frame_select",
    0xd0: "eject",
    0xd1: "load",
}

E1_SUBCODE_NAMES: Dict[int, str] = {
    0x91: "densitometry",
    0xc1: "get_focus",
}

# Channel name lookup
CHANNEL_NAMES: Dict[int, str] = {
    0: "default",
    1: "R",
    2: "G",
    3: "B",
    4: "reserved",
    9: "IR",
}

# WDB mode names (58-byte capture format, bytes 32-33)
_WDB_MODE_NAMES: Dict[int, str] = {
    0x0002: "prescan",
    0x0005: "preview/main",
}

# WDB transfer byte names (58-byte capture format, byte 34)
_WDB_TRANSFER_NAMES: Dict[int, str] = {
    0x08: "prescan/main",
    0x0C: "low-res preview",
}

# WDB film/preview flag names (58-byte capture format, byte 49)
_WDB_FILM_NAMES: Dict[int, str] = {
    0x00: "main",
    0x80: "IR preview",
    0x81: "prescan/low-res",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DecodedInfo:
    cmd_name: str
    cmd_hex: str
    params: Dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    error_detail: str = ""


@dataclass
class Event:
    index: int
    timestamp: float
    direction: str  # "out" or "in"
    endpoint: int
    raw: bytes
    decoded: Optional[DecodedInfo] = None
    phase: str = ""


@dataclass
class Issue:
    event_index: int
    severity: str  # "error", "warning", "info"
    message: str


@dataclass
class PhaseGroup:
    name: str
    start_index: int
    end_index: int
    start_time: float
    end_time: float
    event_count: int
    out_count: int
    in_count: int
    issues: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_text_capture(path: str) -> List[Event]:
    """Parse a text capture file into events.

    Format: tab-separated columns -- timestamp, endpoint (hex), length, payload.
    Payload is hex or @relative/path for binary file reference.
    """
    file_path = Path(path).resolve()
    base_dir = file_path.parent
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    events: List[Event] = []
    idx = 0
    for lineno, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            timestamp = float(parts[0])
        except ValueError:
            timestamp = 0.0
        try:
            endpoint = int(parts[1], 0)
        except ValueError:
            continue
        try:
            declared = int(parts[2])
        except ValueError:
            continue
        try:
            payload = _decode_payload_field(lineno, parts[3], declared, base_dir)
        except ValueError:
            continue
        direction = "out" if endpoint == BULK_OUT_EP else "in"
        events.append(Event(
            index=idx,
            timestamp=timestamp,
            direction=direction,
            endpoint=endpoint,
            raw=payload,
        ))
        idx += 1

    return events


def parse_pcapng(path: str) -> List[Event]:
    """Parse a pcapng file using tshark (via generate_fixture_from_pcapng)."""
    file_path = Path(path).resolve()
    try:
        from scripts.generate_fixture_from_pcapng import _extract_packets, _has_tshark
        if not _has_tshark():
            print("Error: tshark not found on PATH. Install wireshark/tshark first.",
                  file=sys.stderr)
            return []
        packets = _extract_packets(file_path)
        if not packets:
            return []
        # packets: (frame_num, direction, endpoint, data, timestamp)
        events: List[Event] = []
        for idx, (frame_num, direction, endpoint, data, ts) in enumerate(packets):
            events.append(Event(
                index=idx,
                timestamp=ts,
                direction=direction.lower(),
                endpoint=endpoint,
                raw=data,
            ))
        return events
    except ImportError:
        # Fallback: try parse_pcapng.extract_usb_traffic (no timestamps)
        try:
            from parse_pcapng import extract_usb_traffic
            packets = extract_usb_traffic(str(file_path))
            events: List[Event] = []
            for idx, (frame_num, direction, endpoint, data) in enumerate(packets):
                events.append(Event(
                    index=idx,
                    timestamp=0.0,
                    direction=direction.lower(),
                    endpoint=endpoint,
                    raw=data,
                ))
            return events
        except ImportError as exc:
            print(f"Error: cannot import pcapng parser: {exc}", file=sys.stderr)
            return []


def load_capture(path: str) -> List[Event]:
    """Load events from either text or pcapng file."""
    p = Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return []
    if p.suffix == ".pcapng":
        return parse_pcapng(str(p))
    else:
        return parse_text_capture(str(p))


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------


def _decode_wdb_58(data: bytes) -> Dict[str, Any]:
    """Decode a 58-byte capture WDB payload."""
    if len(data) < 58:
        return {}
    import struct as _struct

    channel = data[8]
    ch_name = CHANNEL_NAMES.get(channel, f"ch{channel}")

    x_res = _struct.unpack(">H", data[10:12])[0]
    y_res = _struct.unpack(">H", data[12:14])[0]

    frame_offset = _struct.unpack(">I", data[18:22])[0]
    width = _struct.unpack(">I", data[22:26])[0]
    line_count = _struct.unpack(">H", data[30:32])[0]

    mode = _struct.unpack(">H", data[32:34])[0]
    mode_name = _WDB_MODE_NAMES.get(mode, f"0x{mode:04x}")

    transfer_byte = data[34]
    transfer_name = _WDB_TRANSFER_NAMES.get(transfer_byte, f"0x{transfer_byte:02x}")

    film_flag = data[49]
    film_name = _WDB_FILM_NAMES.get(film_flag, f"0x{film_flag:02x}")

    sub_mode = data[50]
    exposure = _struct.unpack(">I", data[54:58])[0]

    return {
        "channel": f"{ch_name}({channel})",
        "resolution": f"{x_res}x{y_res}",
        "frame_offset": f"0x{frame_offset:08x}",
        "width": width,
        "lines": line_count,
        "mode": mode_name,
        "transfer": transfer_name,
        "film": film_name,
        "sub_mode": sub_mode,
        "exposure": f"0x{exposure:08x}",
    }


def _decode_frame_table(data: bytes) -> Dict[str, Any]:
    """Decode a 52-byte frame-position table (WRITE 0x8f payload)."""
    if len(data) < 52:
        return {}
    import struct as _struct

    entries = []
    for i in range(3):
        base = 4 + i * 16
        y_start = _struct.unpack(">I", data[base:base + 4])[0]
        x1 = _struct.unpack(">I", data[base + 4:base + 8])[0]
        y_end = _struct.unpack(">I", data[base + 8:base + 12])[0]
        x2 = _struct.unpack(">I", data[base + 12:base + 16])[0]
        entries.append(
            f"e{i}:y={y_start}/x1=0x{x1:08x}/ye={y_end}"
        )

    return {"entries": entries}


def _decode_channel_list(raw: bytes) -> DecodedInfo:
    """Decode SHORT_OUT channel list payloads."""
    channel_names = []
    for b in raw:
        name = CHANNEL_NAMES.get(b, str(b))
        if b == 9:
            name += "(IR)"
        channel_names.append(name)
    return DecodedInfo(
        cmd_name="SHORT_OUT",
        cmd_hex=raw.hex(),
        params={"channels": raw.hex(), "names": channel_names},
    )


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def decode_out_command(raw: bytes) -> DecodedInfo:
    """Decode an OUT (host->device) message."""
    if not raw:
        return DecodedInfo(cmd_name="EMPTY", cmd_hex="")

    # 1-byte phase check
    if len(raw) == 1 and raw[0] == 0xd0:
        return DecodedInfo(cmd_name="PHASE_CHECK", cmd_hex="d0")

    # Large payloads (>10 bytes) are data transfers (LUT, scan params, etc.),
    # not commands. The actual command was sent earlier.
    if len(raw) > 10:
        params: Dict[str, Any] = {"size": len(raw)}

        # Detect 58-byte WDB payloads (from SCAN commands)
        if len(raw) == 58:
            wdb_info = _decode_wdb_58(raw)
            if wdb_info:
                params.update(wdb_info)
                return DecodedInfo(
                    cmd_name="DATA_OUT(WDB58)",
                    cmd_hex=f"{len(raw)}B",
                    params=params,
                )

        # Detect 52-byte frame table (WRITE 0x8f payload)
        if len(raw) == 52:
            ft_info = _decode_frame_table(raw)
            if ft_info:
                params.update(ft_info)
                return DecodedInfo(
                    cmd_name="DATA_OUT(frame_table)",
                    cmd_hex=f"{len(raw)}B",
                    params=params,
                )

        # Detect 8192-byte LUT payloads
        if len(raw) == 8192:
            params["type"] = "LUT"

        return DecodedInfo(
            cmd_name="DATA_OUT",
            cmd_hex=f"{len(raw)}B",
            params=params,
        )

    if len(raw) >= 6:
        cmd = raw[0]
        name = CMD_NAMES.get(cmd, f"UNKNOWN_0x{cmd:02x}")
        params: Dict[str, Any] = {}

        if cmd in (0x00, 0x16, 0x17, 0xc1):
            # Simple 6-byte commands, no interesting params
            pass
        elif cmd == 0x12:
            # INQUIRY: 12 00/01 page alloc control
            params["page"] = f"0x{raw[1]:02x}"
            params["param2"] = f"0x{raw[2]:02x}"
            params["alloc_len"] = raw[4]
            params["control"] = f"0x{raw[5]:02x}"
        elif cmd == 0x15:
            # MODE_SELECT
            params["page"] = f"0x{raw[1]:02x}"
            params["alloc_len"] = raw[4]
        elif cmd == 0x1a:
            # MODE_SENSE
            params["page"] = f"0x{raw[2]:02x}"
            params["alloc_len"] = raw[4]
        elif cmd == 0x1b:
            # START_STOP (also used for color sequence)
            params["num_colors"] = raw[4]
        elif cmd == 0x24:
            # SCAN (10 bytes): 24 00 00 00 00 00 00 00 3a XX
            if len(raw) >= 10:
                params["data_len"] = raw[8]
                params["scan_type"] = f"0x{raw[9]:02x}"
        elif cmd == 0x28:
            # READ(10): 28 00 XX 00 ... len ...
            params["datatype"] = f"0x{raw[2]:02x}"
            if len(raw) >= 10:
                params["length"] = (raw[7] << 16) | (raw[8] << 8) | raw[9]
        elif cmd == 0x2a:
            # WRITE(10): 2a 00 XX 00 ...
            params["datatype"] = f"0x{raw[2]:02x}"
            if len(raw) >= 10:
                params["length"] = (raw[7] << 16) | (raw[8] << 8) | raw[9]
                # Flag WRITE 0x8f as frame table
                if raw[2] == 0x8f:
                    params["purpose"] = "frame_table"
        elif cmd == 0xe0:
            # VENDOR: subcode in byte 2
            if len(raw) >= 10:
                subcode = raw[2]
                sub_name = E0_SUBCODE_NAMES.get(subcode, "unknown")
                params["subcode"] = f"0x{subcode:02x} ({sub_name})"
        elif cmd == 0xe1:
            if len(raw) >= 10:
                subcode = raw[2]
                sub_name = E1_SUBCODE_NAMES.get(subcode, "unknown")
                params["subcode"] = f"0x{subcode:02x} ({sub_name})"
        elif cmd == 0x25:
            # READ_CAPACITY: channel in byte 1 and byte 5
            ch = raw[1] if len(raw) > 1 else 0
            ch_name = CHANNEL_NAMES.get(ch, f"ch{ch}")
            params["channel"] = f"{ch_name}({ch})"
            if ch == 9:
                params["channel"] += " [IR]"

        return DecodedInfo(
            cmd_name=name,
            cmd_hex=raw[:min(6, len(raw))].hex(),
            params=params,
        )

    # Short payloads (2-10 bytes) — could be SHORT_OUT channel lists
    if len(raw) >= 2:
        ch_names = [CHANNEL_NAMES.get(b, str(b)) for b in raw]
        if any(b == 9 for b in raw):
            return DecodedInfo(
                cmd_name="SHORT_OUT",
                cmd_hex=raw.hex(),
                params={"channels": raw.hex(), "names": ch_names, "has_ir": True},
            )
        return DecodedInfo(
            cmd_name="SHORT_OUT",
            cmd_hex=raw.hex(),
            params={"channels": raw.hex(), "names": ch_names},
        )

    return DecodedInfo(
        cmd_name=f"SHORT_OUT ({len(raw)}B)",
        cmd_hex=raw.hex(),
    )


def decode_in_response(raw: bytes) -> DecodedInfo:
    """Decode an IN (device->host) message."""
    if not raw:
        return DecodedInfo(cmd_name="EMPTY", cmd_hex="")

    # 1 byte: phase check response
    if len(raw) == 1:
        phase_name = PHASE_TYPE_NAMES.get(
            raw[0], f"unknown_0x{raw[0]:02x}"
        )
        return DecodedInfo(
            cmd_name="PHASE_RESP",
            cmd_hex=f"{raw[0]:02x}",
            params={"phase": phase_name},
        )

    # 8 bytes: status response
    if len(raw) == 8:
        sense_key = raw[1] & 0x0F
        sense_name = SENSE_KEY_NAMES.get(
            sense_key, f"UNKNOWN_0x{sense_key:02x}"
        )
        is_error = sense_key not in (0x00, 0x01, 0x09)

        # Special: vendor REISSUE
        if sense_key == 0x09 and raw[2] == 0x80 and raw[3] == 0x06:
            aux = raw[4] if len(raw) > 4 else 0
            if aux in (0x00, 0x01):
                sense_name = "REISSUE"
                is_error = False

        params: Dict[str, Any] = {
            "sense": sense_name,
            "asc": f"0x{raw[2]:02x}",
            "ascq": f"0x{raw[3]:02x}",
        }
        error_detail = ""
        if is_error:
            error_detail = (
                f"Error: {sense_name} (ASC={params['asc']}, ASCQ={params['ascq']})"
            )

        return DecodedInfo(
            cmd_name="STATUS",
            cmd_hex=raw.hex(),
            params=params,
            is_error=is_error,
            error_detail=error_detail,
        )

    # >= 4 bytes starting with 0x06: data response (inquiry page, LUT header, etc.)
    if len(raw) >= 4 and raw[0] == 0x06:
        params: Dict[str, Any] = {
            "page": f"0x{raw[1]:02x}",
            "length": (raw[2] << 8) | raw[3],
        }
        if len(raw) > 4:
            data_part = raw[4:]
            try:
                text = data_part.decode("ascii").strip("\x00")
                if text and all(32 <= ord(c) < 127 for c in text):
                    params["text"] = text
            except (UnicodeDecodeError, ValueError):
                pass
        return DecodedInfo(
            cmd_name="DATA_RESP",
            cmd_hex=raw[:4].hex(),
            params=params,
        )

    # Large data block (image data, LUT data, etc.)
    return DecodedInfo(
        cmd_name="DATA_BLOCK",
        cmd_hex=f"{len(raw)}B",
        params={"size": len(raw)},
    )


# ---------------------------------------------------------------------------
# Phase detection
# ---------------------------------------------------------------------------


def detect_phases(events: List[Event]) -> List[Event]:
    """Walk through events and assign phase labels.

    Phase transitions:
    - INIT → READY_WAIT: 3+ consecutive TUR commands
    - INIT/READY_WAIT → CONFIG: MODE_SELECT, WRITE, or START_STOP
    - CONFIG/READY_WAIT → PRESCAN: first SCAN command
    - PRESCAN → SCAN: second SCAN command (after prescan data reads)
    - SCAN/CONFIG → EJECT: VENDOR e0/d0 eject subcode
    - EJECT → INIT: VENDOR e0/80 reset subcode
    """
    current_phase = Phase.INIT
    tur_count = 0
    seen_scan = False
    scan_data_read = False

    for ev in events:
        if ev.direction != "out":
            ev.phase = current_phase.value
            continue

        if not ev.raw:
            ev.phase = current_phase.value
            continue

        first_byte = ev.raw[0]

        # Track TUR sequences
        if first_byte == 0x00:
            tur_count += 1
            if tur_count >= 3 and current_phase == Phase.INIT:
                current_phase = Phase.READY_WAIT
        elif first_byte == 0x12:
            # INQUIRY is part of init, don't transition
            tur_count = 0
        elif first_byte == 0x24:
            # SCAN command
            tur_count = 0
            if not seen_scan:
                current_phase = Phase.PRESCAN
                seen_scan = True
            else:
                current_phase = Phase.SCAN
            scan_data_read = False
        elif first_byte == 0x28 and current_phase in (Phase.PRESCAN, Phase.SCAN):
            scan_data_read = True
        elif first_byte in (0x2a, 0x15, 0x1b):
            # MODE_SELECT, WRITE, START_STOP → CONFIG
            if current_phase in (Phase.INIT, Phase.READY_WAIT):
                current_phase = Phase.CONFIG
            tur_count = 0
        elif first_byte == 0xe0:
            subcode = ev.raw[2] if len(ev.raw) > 2 else 0
            if subcode == 0x80:
                current_phase = Phase.INIT
                tur_count = 0
                seen_scan = False
            elif subcode == 0xd0:
                current_phase = Phase.EJECT
                tur_count = 0
        elif first_byte in (0x16, 0x17, 0x1a):
            # RESERVE, RELEASE, MODE_SENSE stay in INIT or transition READY_WAIT→CONFIG
            if current_phase == Phase.INIT:
                tur_count = 0
            elif current_phase == Phase.READY_WAIT:
                current_phase = Phase.CONFIG
                tur_count = 0
        else:
            tur_count = 0

        ev.phase = current_phase.value

    return events


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------


def detect_issues(events: List[Event]) -> List[Issue]:
    """Detect protocol errors and anomalies.

    Context-aware: NOT_READY after TUR is expected (scanner becoming ready).
    UNIT_ATTENTION after reset/inquiry is normal. Short data payloads after
    READ commands are legitimate protocol behavior.
    """
    issues: List[Issue] = []

    # Build a lookup: for each IN event, find the preceding OUT command
    last_out_cmd = None  # first byte of last OUT command (6+ byte cmds only)

    for ev in events:
        if not ev.decoded:
            continue

        if ev.direction == "out":
            # Track the last significant OUT command (skip phase checks and
            # short data payloads which are arguments to preceding commands)
            if ev.raw and ev.raw[0] != 0xd0 and len(ev.raw) >= 6:
                last_out_cmd = ev.raw[0]

            # Unknown command codes (only for actual commands, not data payloads)
            if "UNKNOWN" in ev.decoded.cmd_name and ev.decoded.cmd_name != "DATA_OUT":
                issues.append(Issue(
                    event_index=ev.index,
                    severity="warning",
                    message=f"Unknown command 0x{ev.raw[0]:02x} at event {ev.index}",
                ))
        else:
            # IN response - context-aware error detection
            if ev.decoded.is_error and ev.decoded.params:
                sense = ev.decoded.params.get("sense", "")
                asc = ev.decoded.params.get("asc", "")
                ascq = ev.decoded.params.get("ascq", "")
                # NOT_READY (becoming ready, ASC=04/ASCQ=01) after TUR is expected
                if (sense == SenseKey.NOT_READY
                        and last_out_cmd == 0x00
                        and asc == "0x04" and ascq == "0x01"):
                    continue
                # UNIT_ATTENTION after reset/inquiry/TUR is normal
                if sense == SenseKey.UNIT_ATTENTION:
                    if last_out_cmd in (0xe0, 0x12, 0x00, None):
                        continue

                issues.append(Issue(
                    event_index=ev.index,
                    severity="error",
                    message=ev.decoded.error_detail
                    or f"Error status at event {ev.index}",
                ))

    return issues


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------


def build_command_signature(ev: Event) -> Optional[str]:
    """Build a comparable signature for alignment."""
    if ev.direction != "out" or not ev.raw:
        return None
    if ev.raw[0] == 0x00:
        return "TUR"  # Normalize TUR for diff
    return ev.raw[:min(10, len(ev.raw))].hex()


def diff_events(events_a: List[Event], events_b: List[Event]) -> List[Dict[str, Any]]:
    """Diff two event sequences by aligning on command signatures."""
    sigs_a = [(ev, build_command_signature(ev)) for ev in events_a]
    sigs_b = [(ev, build_command_signature(ev)) for ev in events_b]

    # Filter to OUT commands with signatures
    cmds_a = [(ev, sig) for ev, sig in sigs_a if sig and sig != "TUR"]
    cmds_b = [(ev, sig) for ev, sig in sigs_b if sig and sig != "TUR"]

    diffs: List[Dict[str, Any]] = []
    i, j = 0, 0
    while i < len(cmds_a) and j < len(cmds_b):
        ev_a, sig_a = cmds_a[i]
        ev_b, sig_b = cmds_b[j]

        if sig_a == sig_b:
            # Check for parameter differences
            if ev_a.raw != ev_b.raw:
                diffs.append({
                    "type": "changed",
                    "event_a": ev_a.index,
                    "event_b": ev_b.index,
                    "sig": sig_a,
                    "raw_a": ev_a.raw.hex(),
                    "raw_b": ev_b.raw.hex(),
                    "time_delta": round(ev_b.timestamp - ev_a.timestamp, 3),
                })
            i += 1
            j += 1
        else:
            # Try to find match ahead in B
            found_b: Optional[int] = None
            for k in range(j, min(j + 20, len(cmds_b))):
                if cmds_b[k][1] == sig_a:
                    found_b = k
                    break

            if found_b is not None:
                # Events extra in B
                for m in range(j, found_b):
                    ev_m, sig_m = cmds_b[m]
                    diffs.append({
                        "type": "extra_in_b",
                        "event": ev_m.index,
                        "sig": sig_m,
                    })
                j = found_b + 1
                i += 1
            else:
                # Try to find match ahead in A
                found_a: Optional[int] = None
                for k in range(i, min(i + 20, len(cmds_a))):
                    if cmds_a[k][1] == sig_b:
                        found_a = k
                        break

                if found_a is not None:
                    for m in range(i, found_a):
                        ev_m, sig_m = cmds_a[m]
                        diffs.append({
                            "type": "missing_in_b",
                            "event": ev_m.index,
                            "sig": sig_m,
                        })
                    i = found_a + 1
                    j += 1
                else:
                    diffs.append({
                        "type": "mismatch",
                        "event_a": ev_a.index,
                        "event_b": ev_b.index,
                        "sig_a": sig_a,
                        "sig_b": sig_b,
                    })
                    i += 1
                    j += 1

    # Remaining events
    while i < len(cmds_a):
        ev, sig = cmds_a[i]
        diffs.append({"type": "missing_in_b", "event": ev.index, "sig": sig})
        i += 1
    while j < len(cmds_b):
        ev, sig = cmds_b[j]
        diffs.append({"type": "extra_in_b", "event": ev.index, "sig": sig})
        j += 1

    return diffs


# ---------------------------------------------------------------------------
# Protocol annotation
# ---------------------------------------------------------------------------


def annotate_protocol(events: List[Event]) -> List[Issue]:
    """Cross-reference commands against protocol.py implementation."""
    implemented: Dict[str, List[int]] = {
        "test_unit_ready": [0x00],
        "inquiry": [0x12],
        "reserve_unit": [0x16],
        "release_unit": [0x17],
        "mode_sense": [0x1a],
        "mode_select": [0x15],
        "send_lut": [0x2a],
        "read_scan_data": [0x28],
        "read_prescan_image_data": [0x28],
        "read_control_frame": [0x28],
        "read_channel_state": [0x28],
        "read_focus": [0xe1],
        "eject_medium": [0xe0],
        "load_medium": [0xe0],
        "execute_cmd": [0xc1],
        "reset_scanner": [0xe0],
        "start_stop_unit": [0x1b],
        "read_capacity": [0x25],
        "scan_setup": [0x24],
    }

    implemented_codes: set = set()
    for codes in implemented.values():
        implemented_codes.update(codes)

    issues: List[Issue] = []
    seen_codes: set = set()
    for ev in events:
        if ev.direction != "out" or not ev.raw or len(ev.raw) < 6:
            continue  # Skip data payloads, only check actual commands
        # Skip DATA_OUT and SHORT_OUT (data transfers, not commands)
        if ev.decoded and ev.decoded.cmd_name in ("DATA_OUT", "EMPTY"):
            continue
        if ev.raw[0] == 0xd0:
            continue  # Phase check is handled inline
        code = ev.raw[0]
        if code in seen_codes:
            continue
        seen_codes.add(code)

        if code not in implemented_codes:
            name = CMD_NAMES.get(code, f"0x{code:02x}")
            issues.append(Issue(
                event_index=ev.index,
                severity="info",
                message=(
                    f"Command {name} (0x{code:02x}) at event {ev.index} "
                    f"has no obvious protocol.py handler"
                ),
            ))

    return issues


# ---------------------------------------------------------------------------
# Phase grouping
# ---------------------------------------------------------------------------


def group_phases(events: List[Event]) -> List[PhaseGroup]:
    """Group consecutive events with the same phase into PhaseGroup objects."""
    if not events:
        return []

    groups: List[PhaseGroup] = []
    current_name = events[0].phase
    current_start = events[0].index
    current_start_time = events[0].timestamp
    current_out = 0
    current_in = 0

    for ev in events:
        if ev.phase != current_name:
            groups.append(PhaseGroup(
                name=current_name,
                start_index=current_start,
                end_index=ev.index - 1,
                start_time=current_start_time,
                end_time=events[ev.index - 1].timestamp if ev.index > 0 else current_start_time,
                event_count=ev.index - current_start,
                out_count=current_out,
                in_count=current_in,
            ))
            current_name = ev.phase
            current_start = ev.index
            current_start_time = ev.timestamp
            current_out = 0
            current_in = 0

        if ev.direction == "out":
            current_out += 1
        else:
            current_in += 1

    # Final group
    groups.append(PhaseGroup(
        name=current_name,
        start_index=current_start,
        end_index=len(events) - 1,
        start_time=current_start_time,
        end_time=events[-1].timestamp,
        event_count=len(events) - current_start,
        out_count=current_out,
        in_count=current_in,
    ))

    return groups


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def print_summary(
    events: List[Event],
    phases: List[PhaseGroup],
    issues: List[Issue],
    verbose: bool = False,
) -> None:
    """Print human-readable summary."""
    out_count = sum(1 for e in events if e.direction == "out")
    in_count = sum(1 for e in events if e.direction == "in")
    total_time = events[-1].timestamp if events else 0

    print()
    print("=" * 70)
    print("CAPTURE ANALYSIS SUMMARY")
    print("=" * 70)
    print(f"Total events: {len(events)} ({out_count} OUT, {in_count} IN)")
    print(f"Duration: {total_time:.2f}s")
    print()

    # Phase breakdown
    print(
        f"{'Phase':<15} {'Events':>6} {'OUT':>5} {'IN':>5} "
        f"{'Start':>8} {'End':>8} {'Duration':>8}"
    )
    print("-" * 70)
    for ph in phases:
        dur = ph.end_time - ph.start_time
        print(
            f"{ph.name:<15} {ph.event_count:6d} {ph.out_count:5d} "
            f"{ph.in_count:5d} {ph.start_time:8.3f} {ph.end_time:8.3f} "
            f"{dur:8.3f}"
        )
    print()

    # Command frequency
    cmd_counter: Counter = Counter()
    for ev in events:
        if ev.direction == "out" and ev.decoded:
            cmd_counter[ev.decoded.cmd_name] += 1

    print("Command frequency:")
    for name, count in cmd_counter.most_common():
        print(f"  {name:<25} {count:4d}")
    print()

    # Issues
    if issues:
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        infos = [i for i in issues if i.severity == "info"]

        print(
            f"Issues: {len(errors)} errors, "
            f"{len(warnings)} warnings, {len(infos)} info"
        )
        print()

        for issue in issues:
            marker = {"error": "!!", "warning": "~>", "info": "  "}[issue.severity]
            print(f"  {marker} Event {issue.event_index}: {issue.message}")
        print()

    # Per-event detail
    max_events = len(events) if verbose else 200
    print(
        f"{'Event':>5} {'Time':>8} {'Dir':>3} {'Size':>4} "
        f"{'Phase':<12} Description"
    )
    print("-" * 90)
    for ev in events[:max_events]:
        dec = ev.decoded
        desc = ""
        if dec:
            params_str = " ".join(f"{k}={v}" for k, v in dec.params.items())
            desc = dec.cmd_name
            if params_str:
                desc += f" ({params_str})"
            if dec.is_error:
                desc += f" *** {dec.error_detail}"
        else:
            desc = f"raw {len(ev.raw)}B"

        print(
            f"{ev.index:5d} {ev.timestamp:8.3f} {ev.direction:>3} "
            f"{len(ev.raw):4d} {ev.phase:<12} {desc}"
        )

    if len(events) > max_events:
        print(f"\n... ({len(events) - max_events} more events, use --verbose for all)")


def json_output(
    events: List[Event],
    phases: List[PhaseGroup],
    issues: List[Issue],
    verbose: bool = False,
) -> Dict[str, Any]:
    """Build JSON-serializable output."""
    max_events = len(events) if verbose else 200
    return {
        "summary": {
            "total_events": len(events),
            "out_count": sum(1 for e in events if e.direction == "out"),
            "in_count": sum(1 for e in events if e.direction == "in"),
            "duration": events[-1].timestamp if events else 0,
        },
        "phases": [asdict(p) for p in phases],
        "issues": [asdict(i) for i in issues],
        "command_frequency": dict(Counter(
            e.decoded.cmd_name
            for e in events
            if e.direction == "out" and e.decoded
        )),
        "events": [
            {
                "index": e.index,
                "timestamp": e.timestamp,
                "direction": e.direction,
                "endpoint": f"0x{e.endpoint:02x}",
                "size": len(e.raw),
                "phase": e.phase,
                "decoded": asdict(e.decoded) if e.decoded else None,
            }
            for e in events[:max_events]
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _decode_all(events: List[Event]) -> None:
    """Decode all events in-place."""
    for ev in events:
        if ev.direction == "out":
            ev.decoded = decode_out_command(ev.raw)
        else:
            ev.decoded = decode_in_response(ev.raw)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze USB capture files for Nikon Coolscan protocol"
    )
    parser.add_argument(
        "file", nargs="?", help="Capture file (.txt or .pcapng)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    parser.add_argument(
        "--diff-a", help="First file for diff comparison",
    )
    parser.add_argument(
        "--diff-b", help="Second file for diff comparison",
    )
    parser.add_argument(
        "--annotate", action="store_true",
        help="Annotate commands against protocol.py implementation",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show all events (not just first 200)",
    )

    args = parser.parse_args()

    if args.diff_a and args.diff_b:
        # Diff mode
        events_a = load_capture(args.diff_a)
        events_b = load_capture(args.diff_b)
        _decode_all(events_a)
        _decode_all(events_b)
        events_a = detect_phases(events_a)
        events_b = detect_phases(events_b)
        diffs = diff_events(events_a, events_b)

        if args.json:
            print(json.dumps({"differences": diffs, "count": len(diffs)}, indent=2))
        else:
            print(f"Differences: {len(diffs)}")
            for d in diffs:
                if d["type"] == "changed":
                    print(
                        f"  Changed at A:{d['event_a']}/B:{d['event_b']}: "
                        f"{d['sig']} (delta {d['time_delta']}s)"
                    )
                elif d["type"] == "missing_in_b":
                    print(f"  Missing in B at {d['event']}: {d['sig']}")
                elif d["type"] == "extra_in_b":
                    print(f"  Extra in B at {d['event']}: {d['sig']}")
                elif d["type"] == "mismatch":
                    print(
                        f"  Mismatch at A:{d['event_a']}/{d['event_b']}: "
                        f"{d['sig_a']} vs {d['sig_b']}"
                    )
        return 0 if not diffs else 1

    if not args.file:
        parser.print_help()
        return 1

    events = load_capture(args.file)
    if not events:
        print(f"No events found in {args.file}", file=sys.stderr)
        return 1

    # Decode
    _decode_all(events)

    # Detect phases
    events = detect_phases(events)

    # Group phases
    phases = group_phases(events)

    # Detect issues
    issues = detect_issues(events)

    if args.annotate:
        annotation_issues = annotate_protocol(events)
        issues.extend(annotation_issues)

    # Output
    if args.json:
        output = json_output(events, phases, issues, verbose=args.verbose)
        print(json.dumps(output, indent=2, default=str))
    else:
        print_summary(events, phases, issues, verbose=args.verbose)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
