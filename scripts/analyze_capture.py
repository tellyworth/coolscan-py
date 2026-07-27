#!/usr/bin/env python3
"""Analyze USB capture files for Nikon Coolscan protocol.

Parses text-format or pcapng capture files, decodes each USB transfer into
named commands with parameters, groups events into protocol phases, detects
errors and issues, and outputs a human-readable summary or JSON.

Supports diffing two captures, structural extraction of WDBs and control
frames, generic event filtering, and protocol annotation.
"""

import argparse
import json
import os
import sys
import struct
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
from coolscan.protocol import (
    DataType,
    PhaseType,
    StatusType,
    WindowDescriptorBlock,
    CHANNEL_RED,
    CHANNEL_GREEN,
    CHANNEL_BLUE,
    CHANNEL_IR,
    WDB_MODE_PRESCAN,
    WDB_MODE_PREVIEW_MAIN,
    WDB_TRANSFER_PRESCAN_MAIN,
    WDB_TRANSFER_LOW_RES_PREVIEW,
    WDB_FILM_PRESCAN,
    WDB_FILM_IR_PREVIEW,
    WDB_FILM_MAIN_SCAN,
    WDB_SUBMODE_PRESCAN_MAIN,
    WDB_SUBMODE_LOW_RES_96DPI,
    parse_status_response,
)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


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

# Derived from shared enums/constants
DATA_TYPE_NAMES: Dict[int, str] = {dt.value: dt.name for dt in DataType}
PHASE_TYPE_NAMES: Dict[int, str] = {pt.value: pt.name for pt in PhaseType}

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

# Channel name lookup (derived from shared constants)
CHANNEL_NAMES: Dict[int, str] = {
    0: "default",
    CHANNEL_RED: "R",
    CHANNEL_GREEN: "G",
    CHANNEL_BLUE: "B",
    4: "reserved",
    CHANNEL_IR: "IR",
}

# WDB mode names (derived from shared constants)
_WDB_MODE_NAMES: Dict[int, str] = {
    WDB_MODE_PRESCAN: "prescan",
    WDB_MODE_PREVIEW_MAIN: "preview/main",
}

# WDB transfer byte names (derived from shared constants)
_WDB_TRANSFER_NAMES: Dict[int, str] = {
    WDB_TRANSFER_PRESCAN_MAIN: "prescan/main",
    WDB_TRANSFER_LOW_RES_PREVIEW: "low-res preview",
}

# WDB film/preview flag names (derived from shared constants)
_WDB_FILM_NAMES: Dict[int, str] = {
    WDB_FILM_MAIN_SCAN: "main",
    WDB_FILM_IR_PREVIEW: "IR preview",
    WDB_FILM_PRESCAN: "prescan/low-res",
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


@dataclass
class WdbRow:
    """Decoded Window Descriptor Block row."""
    line_num: int
    timestamp: float
    window_id: int
    x_res: int
    y_res: int
    offset_x: int
    offset_y: int
    size_x: int
    size_y: int
    scan_kind: str
    exposure: int
    raw_hex: str


@dataclass
class CtrlFrameEntry:
    """Single frame position entry within a CONTROL_FRAME payload."""
    entry_index: int
    y_start: int
    y_end: int
    height: int


@dataclass
class CtrlFrameRow:
    """Decoded CONTROL_FRAME row."""
    line_num: int
    timestamp: float
    entry_index: int
    frame_index: int
    y_start: int
    y_end: int
    height: int
    raw_hex: str = ""


@dataclass
class ReadCapRow:
    """Decoded READ_CAPACITY response row."""
    line_num: int
    timestamp: float
    window_id: int
    x_res: int
    y_res: int
    offset_x: int
    offset_y: int
    size_x: int
    size_y: int
    exposure: int = 0
    raw_hex: str = ""


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
    """Load events from either text or pcapng file.

    Returns raw events without decoding.  Call ``_decode_all()`` before
    using extraction functions (``extract_wdbs``, ``extract_control_frames``,
    etc.) or any function that inspects ``ev.decoded``.
    """
    p = Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return []
    if p.suffix == ".pcapng":
        return parse_pcapng(str(p))
    else:
        return parse_text_capture(str(p))


def load_capture_decoded(path: str) -> List[Event]:
    """Load and decode events from a capture file.

    Convenience wrapper around ``load_capture()`` + ``_decode_all()``.
    Returns events ready for extraction, filtering, and analysis.
    """
    events = load_capture(path)
    _decode_all(events)
    return events


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------


def _decode_wdb_58(data: bytes) -> Dict[str, Any]:
    """Decode a 58-byte capture WDB payload using shared protocol parsing."""
    if len(data) < 58:
        return {}

    wdb = WindowDescriptorBlock.from_bytes_58(data)
    ch_name = CHANNEL_NAMES.get(wdb.channel, f"ch{wdb.channel}")
    mode_name = _WDB_MODE_NAMES.get(wdb.wdb_mode, f"0x{wdb.wdb_mode:04x}")
    transfer_name = _WDB_TRANSFER_NAMES.get(
        wdb.transfer_byte, f"0x{wdb.transfer_byte:02x}"
    )
    film_name = _WDB_FILM_NAMES.get(wdb.film_flag, f"0x{wdb.film_flag:02x}")

    return {
        "channel": f"{ch_name}({wdb.channel})",
        "resolution": f"{wdb.x_resolution}x{wdb.y_resolution}",
        "frame_offset": f"0x{wdb.frame_offset:08x}",
        "width": wdb.width,
        "lines": wdb.length,
        "mode": mode_name,
        "transfer": transfer_name,
        "film": film_name,
        "sub_mode": wdb.sub_mode,
        "exposure": f"0x{wdb.exposure:08x}",
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

    if len(raw) == 1 and raw[0] == 0xd0:
        return DecodedInfo(cmd_name="PHASE_CHECK", cmd_hex="d0")

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
            pass
        elif cmd == 0x12:
            params["page"] = f"0x{raw[1]:02x}"
            params["param2"] = f"0x{raw[2]:02x}"
            params["alloc_len"] = raw[4]
            params["control"] = f"0x{raw[5]:02x}"
            if len(raw) >= 10:
                params["cdb_hex"] = raw[:10].hex()
        elif cmd == 0x15:
            params["page"] = f"0x{raw[1]:02x}"
            params["alloc_len"] = raw[4]
            if len(raw) >= 10:
                params["cdb_hex"] = raw[:10].hex()
        elif cmd == 0x1a:
            params["page"] = f"0x{raw[2]:02x}"
            params["alloc_len"] = raw[4]
            if len(raw) >= 10:
                params["cdb_hex"] = raw[:10].hex()
        elif cmd == 0x1b:
            params["num_colors"] = raw[4]
            if len(raw) >= 10:
                params["cdb_hex"] = raw[:10].hex()
        elif cmd == 0x24:
            if len(raw) >= 10:
                params["data_len"] = raw[8]
                params["scan_type"] = f"0x{raw[9]:02x}"
                params["cdb_hex"] = raw[:10].hex()
        elif cmd == 0x28:
            params["datatype"] = f"0x{raw[2]:02x}"
            if len(raw) >= 10:
                params["length"] = (raw[6] << 16) | (raw[7] << 8) | raw[8]
                params["cdb_hex"] = raw[:10].hex()
        elif cmd == 0x2a:
            params["datatype"] = f"0x{raw[2]:02x}"
            if len(raw) >= 10:
                params["length"] = (raw[6] << 16) | (raw[7] << 8) | raw[8]
                params["cdb_hex"] = raw[:10].hex()
                # Flag WRITE 0x8f as frame table
                if raw[2] == 0x8f:
                    params["purpose"] = "frame_table"
        elif cmd == 0xe0:
            if len(raw) >= 10:
                subcode = raw[2]
                sub_name = E0_SUBCODE_NAMES.get(subcode, "unknown")
                params["subcode"] = f"0x{subcode:02x} ({sub_name})"
                params["cdb_hex"] = raw[:10].hex()
        elif cmd == 0xe1:
            if len(raw) >= 10:
                subcode = raw[2]
                sub_name = E1_SUBCODE_NAMES.get(subcode, "unknown")
                params["subcode"] = f"0x{subcode:02x} ({sub_name})"
                params["cdb_hex"] = raw[:10].hex()
        elif cmd == 0x25:
            # READ_CAPACITY: channel in byte 1 and byte 5
            ch = raw[1] if len(raw) > 1 else 0
            ch_name = CHANNEL_NAMES.get(ch, f"ch{ch}")
            params["channel"] = f"{ch_name}({ch})"
            if ch == 9:
                params["channel"] += " [IR]"
            if len(raw) >= 10:
                params["cdb_hex"] = raw[:10].hex()

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

    if len(raw) == 1:
        phase_name = PHASE_TYPE_NAMES.get(
            raw[0], f"unknown_0x{raw[0]:02x}"
        )
        return DecodedInfo(
            cmd_name="PHASE_RESP",
            cmd_hex=f"{raw[0]:02x}",
            params={"phase": phase_name},
        )

    if len(raw) == 8:
        status, info = parse_status_response(raw)
        sense_key = info["sense_key"]
        sense_asc = info["sense_asc"]
        sense_ascq = info["sense_ascq"]

        # Map StatusType to human-readable sense names
        SENSE_KEY_NAMES = {
            0x00: "GOOD", 0x01: "RECOVERED_ERR", 0x02: "NOT_READY",
            0x03: "MEDIA_ERR", 0x04: "HARDWARE_ERR", 0x05: "ILLEGAL_REQ",
            0x06: "UNIT_ATTENTION", 0x07: "DATA_PROTECT",
            0x09: "VENDOR_SPECIFIC", 0x0B: "ABORTED",
        }
        sense_name = SENSE_KEY_NAMES.get(sense_key, f"UNKNOWN_0x{sense_key:02x}")
        if status == StatusType.REISSUE:
            sense_name = "REISSUE"

        is_error = status not in (StatusType.READY, StatusType.REISSUE)

        params: Dict[str, Any] = {
            "sense": sense_name,
            "asc": f"0x{sense_asc:02x}",
            "ascq": f"0x{sense_ascq:02x}",
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

    return DecodedInfo(
        cmd_name="DATA_BLOCK",
        cmd_hex=f"{len(raw)}B",
        params={"size": len(raw)},
    )


# ---------------------------------------------------------------------------
# Phase detection
# ---------------------------------------------------------------------------


def detect_phases(events: List[Event]) -> List[Event]:
    """Walk through events and assign phase labels."""
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

        if first_byte == 0x00:
            tur_count += 1
            if tur_count >= 3 and current_phase == Phase.INIT:
                current_phase = Phase.READY_WAIT
        elif first_byte == 0x12:
            tur_count = 0
        elif first_byte == 0x24:
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
    """Detect protocol errors and anomalies."""
    issues: List[Issue] = []
    last_out_cmd = None

    for ev in events:
        if not ev.decoded:
            continue

        if ev.direction == "out":
            if ev.raw and ev.raw[0] != 0xd0 and len(ev.raw) >= 6:
                last_out_cmd = ev.raw[0]

            if "UNKNOWN" in ev.decoded.cmd_name and ev.decoded.cmd_name != "DATA_OUT":
                issues.append(Issue(
                    event_index=ev.index,
                    severity="warning",
                    message=f"Unknown command 0x{ev.raw[0]:02x} at event {ev.index}",
                ))
        else:
            if ev.decoded.is_error and ev.decoded.params:
                sense = ev.decoded.params.get("sense", "")

                if sense == "NOT_READY":
                    if last_out_cmd == 0x00:
                        continue

                if sense == "UNIT_ATTENTION":
                    if last_out_cmd in (0x12, 0x00, 0xe0):
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
        return "TUR"
    return ev.raw[:min(10, len(ev.raw))].hex()


def diff_events(events_a: List[Event], events_b: List[Event]) -> List[Dict[str, Any]]:
    """Diff two event sequences by aligning on command signatures."""
    sigs_a = [(ev, build_command_signature(ev)) for ev in events_a]
    sigs_b = [(ev, build_command_signature(ev)) for ev in events_b]

    cmds_a = [(ev, sig) for ev, sig in sigs_a if sig and sig != "TUR"]
    cmds_b = [(ev, sig) for ev, sig in sigs_b if sig and sig != "TUR"]

    diffs: List[Dict[str, Any]] = []
    i, j = 0, 0
    while i < len(cmds_a) and j < len(cmds_b):
        ev_a, sig_a = cmds_a[i]
        ev_b, sig_b = cmds_b[j]

        if sig_a == sig_b:
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
            found_b: Optional[int] = None
            for k in range(j, min(j + 20, len(cmds_b))):
                if cmds_b[k][1] == sig_a:
                    found_b = k
                    break

            if found_b is not None:
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
            continue
        if ev.decoded and ev.decoded.cmd_name in ("DATA_OUT", "EMPTY"):
            continue
        if ev.raw[0] == 0xd0:
            continue
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
# WDB / CONTROL_FRAME / READ_CAPACITY extraction
# ---------------------------------------------------------------------------


def _find_data_transfer_after_cmd(
    events: List[Event],
    cmd_index: int,
    direction: str,
) -> Optional[Event]:
    """Given a command event index, find the data transfer event that follows.

    After an OUT command, the typical sequence is:
      OUT cmd -> PHASE_CHECK(d0) OUT -> PHASE_RESP(02) IN -> DATA_OUT OUT -> STATUS IN
    After an IN-read command:
      OUT cmd -> PHASE_CHECK(d0) OUT -> PHASE_RESP(03) IN -> DATA_BLOCK IN -> STATUS IN

    This skips the phase handshake and status, returning the data event.
    """
    n = len(events)
    idx = cmd_index + 1

    while idx < n:
        ev = events[idx]
        decoded = ev.decoded

        # Phasthr
        if decoded and decoded.cmd_name in ("PHASE_CHECK", "PHASE_RESP"):
            idx += 1
            continue

        # STATUS (8 bytes) -- stop if we hit a non-data status
        if decoded and decoded.cmd_name == "STATUS":
            return None

        # DATA_OUT on OUT direction, or DATA_BLOCK/DATA_RESP on IN direction
        if direction == "out" and decoded and decoded.cmd_name.startswith("DATA_OUT"):
            return ev
        if direction == "in" and decoded and decoded.cmd_name in ("DATA_BLOCK", "DATA_RESP"):
            return ev

        # For READ commands, also accept large IN payloads that are DATA_BLOCK
        if direction == "in" and ev.direction == "in" and len(ev.raw) > 16:
            return ev

        idx += 1

    return None


def _parse_wdb_from_bytes(data: bytes) -> Optional[WdbRow]:
    """Parse a 58-byte WDB payload into structured fields.

    Delegates to WindowDescriptorBlock.from_bytes_58() for consistent parsing.
    """
    if len(data) < 58:
        return None

    wdb = WindowDescriptorBlock.from_bytes_58(data)

    # Map WDB sub-mode byte to scan_kind names
    scan_kind_map = {
        WDB_SUBMODE_PRESCAN_MAIN: "normal",
        WDB_SUBMODE_LOW_RES_96DPI: "prescan",
    }
    scan_kind = scan_kind_map.get(wdb.sub_mode, f"0x{wdb.sub_mode:02x}")

    return WdbRow(
        line_num=0,
        timestamp=0.0,
        window_id=wdb.channel,
        x_res=wdb.x_resolution,
        y_res=wdb.y_resolution,
        offset_x=wdb.frame_offset,
        offset_y=0,  # Not available in 58-byte format
        size_x=wdb.width,
        size_y=wdb.length,
        scan_kind=scan_kind,
        exposure=wdb.exposure,
        raw_hex=data.hex(),
    )


def _looks_like_wdb(data: bytes) -> bool:
    """Heuristic: does this payload look like a WDB?"""
    if len(data) != 58:
        return False
    # WDB has recognizable field at byte 7 (length=0x32=50), and resolution
    # at bytes 10-13
    if data[0x07] != 0x32:
        return False
    x_res = struct.unpack(">H", data[0x0A:0x0C])[0]
    y_res = struct.unpack(">H", data[0x0C:0x0E])[0]
    # Valid resolutions: 96-4800 DPI range (plausible values)
    if x_res < 96 or x_res > 4800:
        return False
    return True


def _looks_like_control_frame(data: bytes) -> bool:
    """Heuristic: does this payload look like a CONTROL_FRAME?"""
    if len(data) != 52:
        return False
    if data[0:2] != b'\x00\x32':
        return False
    return True


def extract_wdbs(events: List[Event]) -> List[WdbRow]:
    """Extract all WINDOW Descriptor Blocks from SET_WINDOW (0x24) commands."""
    rows: List[WdbRow] = []

    for ev in events:
        if ev.direction != "out" or not ev.raw:
            continue
        if len(ev.raw) < 10 or ev.raw[0] != 0x24:
            continue

        data_ev = _find_data_transfer_after_cmd(events, ev.index, "out")
        if not data_ev:
            continue

        wdb = _parse_wdb_from_bytes(data_ev.raw)
        if wdb:
            wdb.line_num = data_ev.index
            wdb.timestamp = data_ev.timestamp
            rows.append(wdb)

    return rows


def extract_control_frames(events: List[Event]) -> List[CtrlFrameRow]:
    """Extract CONTROL_FRAME entries from WRITE(0x8F) commands."""
    rows: List[CtrlFrameRow] = []

    for ev in events:
        if ev.direction != "out" or not ev.raw:
            continue
        if len(ev.raw) < 10 or ev.raw[0] != 0x2a or ev.raw[2] != 0x8F:
            continue

        data_ev = _find_data_transfer_after_cmd(events, ev.index, "out")
        if not data_ev:
            continue

        payload = data_ev.raw
        if _looks_like_control_frame(payload):
            # Header: 4 bytes, then 16-byte entries
            num_entries = payload[2] if len(payload) > 2 else 3
            entry_count = (len(payload) - 4) // 16
            for ei in range(entry_count):
                base = 4 + ei * 16
                if base + 16 > len(payload):
                    break
                y_start = struct.unpack(">L", payload[base:base + 4])[0]
                y_end = struct.unpack(">L", payload[base + 8:base + 12])[0]
                height = y_end - y_start

                rows.append(CtrlFrameRow(
                    line_num=data_ev.index,
                    timestamp=data_ev.timestamp,
                    entry_index=ei,
                    frame_index=ei,
                    y_start=y_start,
                    y_end=y_end,
                    height=height,
                    raw_hex=payload.hex(),
                ))
        else:
            # Still emit a row for non-standard payloads
            rows.append(CtrlFrameRow(
                line_num=data_ev.index,
                timestamp=data_ev.timestamp,
                entry_index=0,
                frame_index=0,
                y_start=0,
                y_end=0,
                height=len(payload),
                raw_hex=payload.hex(),
            ))

    return rows


def extract_read_capacity(events: List[Event]) -> List[ReadCapRow]:
    """Extract READ_CAPACITY (0x25) responses."""
    rows: List[ReadCapRow] = []

    for ev in events:
        if ev.direction != "out" or not ev.raw:
            continue
        if len(ev.raw) < 10 or ev.raw[0] != 0x25:
            continue

        data_ev = _find_data_transfer_after_cmd(events, ev.index, "in")
        if not data_ev:
            continue

        payload = data_ev.raw
        if len(payload) < 34:
            continue

        window_id = payload[0x08] if len(payload) > 0x08 else 0
        x_res = struct.unpack(">H", payload[0x0A:0x0C])[0] if len(payload) > 0x0B else 0
        y_res = struct.unpack(">H", payload[0x0C:0x0E])[0] if len(payload) > 0x0D else 0
        offset_x = struct.unpack(">I", payload[0x0E:0x12])[0] if len(payload) > 0x11 else 0
        offset_y = struct.unpack(">I", payload[0x12:0x16])[0] if len(payload) > 0x15 else 0
        size_x = struct.unpack(">I", payload[0x16:0x1A])[0] if len(payload) > 0x19 else 0
        size_y = struct.unpack(">I", payload[0x1A:0x1E])[0] if len(payload) > 0x1D else 0
        exposure = struct.unpack(">I", payload[0x36:0x3A])[0] if len(payload) >= 0x3A else 0

        rows.append(ReadCapRow(
            line_num=data_ev.index,
            timestamp=data_ev.timestamp,
            window_id=window_id,
            x_res=x_res,
            y_res=y_res,
            offset_x=offset_x,
            offset_y=offset_y,
            size_x=size_x,
            size_y=size_y,
            exposure=exposure,
            raw_hex=payload.hex(),
        ))

    return rows


# ---------------------------------------------------------------------------
# Structural diff helpers
# ---------------------------------------------------------------------------


def diff_wdbs(rows_a: List[WdbRow], rows_b: List[WdbRow]) -> List[Dict[str, Any]]:
    """Diff two WDB row lists by sequence position. Returns per-field changes."""
    diffs: List[Dict[str, Any]] = []
    fields = [
        "window_id", "x_res", "y_res", "offset_x", "offset_y",
        "size_x", "size_y", "scan_kind", "exposure",
    ]

    max_len = max(len(rows_a), len(rows_b))
    for i in range(max_len):
        wa = rows_a[i] if i < len(rows_a) else None
        wb = rows_b[i] if i < len(rows_b) else None

        if wa is None:
            diffs.append({"seq": i, "type": "extra_in_b", "row": asdict(wb)})
            continue
        if wb is None:
            diffs.append({"seq": i, "type": "missing_in_b", "row": asdict(wa)})
            continue

        changed: Dict[str, str] = {}
        for f in fields:
            va = getattr(wa, f)
            vb = getattr(wb, f)
            if va != vb:
                if isinstance(va, int) and isinstance(vb, int):
                    changed[f] = f"{va} != {vb}"
                else:
                    changed[f] = f"{va} != {vb}"

        if changed:
            diffs.append({
                "seq": i,
                "type": "changed",
                "window_a": wa.window_id,
                "window_b": wb.window_id,
                "changes": changed,
            })

    return diffs


def diff_control_frames(
    rows_a: List[CtrlFrameRow],
    rows_b: List[CtrlFrameRow],
) -> List[Dict[str, Any]]:
    """Diff two control-frame row lists by sequence position."""
    diffs: List[Dict[str, Any]] = []
    fields = ["entry_index", "y_start", "y_end", "height"]

    max_len = max(len(rows_a), len(rows_b))
    for i in range(max_len):
        ra = rows_a[i] if i < len(rows_a) else None
        rb = rows_b[i] if i < len(rows_b) else None

        if ra is None:
            diffs.append({"seq": i, "type": "extra_in_b", "entry": asdict(rb)})
            continue
        if rb is None:
            diffs.append({"seq": i, "type": "missing_in_b", "entry": asdict(ra)})
            continue

        changed: Dict[str, str] = {}
        for f in fields:
            va = getattr(ra, f)
            vb = getattr(rb, f)
            if va != vb:
                changed[f] = f"{va} != {vb}"

        if changed:
            diffs.append({
                "seq": i,
                "type": "changed",
                "entry_a": asdict(ra),
                "entry_b": asdict(rb),
                "changes": changed,
            })

    return diffs


# ---------------------------------------------------------------------------
# Generic filter engine
# ---------------------------------------------------------------------------


class _FilterAST:
    """Minimal AST for filter expressions."""
    pass


class _FilterField(_FilterAST):
    name: str
    op: str
    value: Any  # str, int, float


class _FilterAnd(_FilterAST):
    left: _FilterAST
    right: _FilterAST


class _FilterOr(_FilterAST):
    left: _FilterAST
    right: _FilterAST


def _resolve_event_field(event: Event, name: str) -> Optional[Any]:
    """Resolve a filter field name to an event attribute/value."""
    dec = event.decoded
    if name == "cmd":
        return dec.cmd_name if dec else None
    if name == "cmd_hex":
        return dec.cmd_hex if dec else None
    if name == "data_type":
        if dec and "datatype" in dec.params:
            raw = dec.params["datatype"]
            if isinstance(raw, str) and raw.startswith("0x"):
                return int(raw, 16)
        return None
    if name == "endpoint":
        raw_ep = event.endpoint
        return raw_ep
    if name == "length":
        # For READ/WRITE commands, return the CDB-declared transfer length
        if dec and "length" in dec.params:
            return dec.params["length"]
        return len(event.raw)
    if name == "phase":
        return event.phase
    if name == "direction":
        return event.direction
    if name == "size":
        return len(event.raw)
    if name == "index":
        return event.index
    # Check decoded params as fallback
    if dec and name in dec.params:
        return dec.params[name]
    return None


def _parse_value(tok: str) -> Any:
    """Parse a filter value token."""
    tok = tok.strip()
    if tok.startswith('"') and tok.endswith('"'):
        return tok[1:-1]
    if tok.startswith("'") and tok.endswith("'"):
        return tok[1:-1]
    if tok.startswith("0x") or tok.startswith("0X"):
        return int(tok, 16)
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    return tok


def _tokenize_expr(expr: str) -> List[str]:
    """Tokenize a filter expression into words and operators."""
    tokens: List[str] = []
    i = 0
    while i < len(expr):
        if expr[i].isspace():
            i += 1
            continue
        # Quoted string
        if expr[i] in ('"', "'"):
            q = expr[i]
            j = expr.index(q, i + 1)
            tokens.append(expr[i:j + 1])
            i = j + 1
            continue
        # Two-char operators
        if expr[i:i + 2] in ("!=", ">=", "<="):
            tokens.append(expr[i:i + 2])
            i += 2
            continue
        # Single-char operator
        if expr[i] in ("=", ">", "<"):
            tokens.append(expr[i])
            i += 1
            continue
        # Word
        j = i
        while j < len(expr) and not expr[j].isspace() and expr[j] not in ('=', '!', '>', '<', '"', "'"):
            j += 1
        tokens.append(expr[i:j])
        i = j
    return tokens


def _parse_or(tokens: List[str], pos: int) -> Tuple[_FilterAST, int]:
    left, pos = _parse_and(tokens, pos)
    while pos < len(tokens) and tokens[pos] == "or":
        right, pos = _parse_and(tokens, pos + 1)
        node = _FilterOr()
        node.left = left
        node.right = right
        left = node
    return left, pos


def _parse_and(tokens: List[str], pos: int) -> Tuple[_FilterAST, int]:
    left, pos = _parse_field(tokens, pos)
    while pos < len(tokens) and tokens[pos] == "and":
        right, pos = _parse_field(tokens, pos + 1)
        node = _FilterAnd()
        node.left = left
        node.right = right
        left = node
    return left, pos


def _parse_field(tokens: List[str], pos: int) -> Tuple[_FilterAST, int]:
    if pos >= len(tokens):
        raise ValueError(f"Unexpected end of expression at token {pos}")
    name = tokens[pos]
    pos += 1

    if pos < len(tokens) and tokens[pos] in ("=", "!=", ">", "<", ">=", "<="):
        op = tokens[pos]
        pos += 1
        if pos >= len(tokens):
            raise ValueError(f"Expected value after '{op}'")
        value = _parse_value(tokens[pos])
        pos += 1
        node = _FilterField()
        node.name = name
        node.op = "==" if op == "=" else op
        node.value = value
        return node, pos
    else:
        # Bare field name like "out" means truthiness check
        node = _FilterField()
        node.name = name
        node.op = "=="
        node.value = True
        return node, pos


def parse_filter_expr(expr: str) -> _FilterAST:
    """Parse a filter expression string into an AST."""
    tokens = _tokenize_expr(expr)
    if not tokens:
        raise ValueError("Empty filter expression")
    ast, pos = _parse_or(tokens, 0)
    return ast


def _compare(val: Any, op: str, target: Any) -> bool:
    """Compare two values with an operator."""
    # Try numeric comparison
    try:
        a = float(val) if not isinstance(val, (int, float)) else val
        b = float(target) if not isinstance(target, (int, float)) else target
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if op == ">":
            return a > b
        if op == "<":
            return a < b
        if op == ">=":
            return a >= b
        if op == "<=":
            return a <= b
    except (TypeError, ValueError):
        pass

    # String comparison
    sa = str(val)
    sb = str(target)
    if op == "==":
        return sa == sb
    if op == "!=":
        return sa != sb
    if op == ">" or op == ">=":
        return sa > sb if op == ">" else sa >= sb
    if op == "<" or op == "<=":
        return sa < sb if op == "<" else sa <= sb
    return False


def event_matches(event: Event, ast: _FilterAST) -> bool:
    """Evaluate whether an event matches a filter AST."""
    if isinstance(ast, _FilterField):
        val = _resolve_event_field(event, ast.name)
        if val is None:
            return False
        return _compare(val, ast.op, ast.value)
    if isinstance(ast, _FilterAnd):
        return event_matches(event, ast.left) and event_matches(event, ast.right)
    if isinstance(ast, _FilterOr):
        return event_matches(event, ast.left) or event_matches(event, ast.right)
    return False


def filter_events(events: List[Event], ast: _FilterAST) -> List[Event]:
    """Return events that match the filter AST, re-indexed sequentially."""
    result = [ev for ev in events if event_matches(ev, ast)]
    for i, ev in enumerate(result):
        ev.index = i
    return result


# ---------------------------------------------------------------------------
# Payload inline detection (for event listing)
# ---------------------------------------------------------------------------


def _decode_inline_payload(ev: Event) -> Optional[str]:
    """Try to decode a DATA_OUT / DATA_BLOCK payload into inline description."""
    raw = ev.raw
    if ev.decoded and ev.decoded.cmd_name == "DATA_OUT" and _looks_like_wdb(raw):
        w = _parse_wdb_from_bytes(raw)
        if w:
            return (
                f"WDB win={w.window_id} "
                f"res={w.x_res}x{w.y_res} "
                f"off=({w.offset_x},{w.offset_y}) "
                f"size=({w.size_x}x{w.size_y}) "
                f"kind={w.scan_kind} "
                f"exposure=0x{w.exposure:08x}"
            )
    if ev.decoded and ev.decoded.cmd_name == "DATA_OUT" and _looks_like_control_frame(raw):
        num_entries = raw[2] if len(raw) > 2 else 3
        entry_count = (len(raw) - 4) // 16
        entries = []
        for ei in range(entry_count):
            base = 4 + ei * 16
            if base + 16 > len(raw):
                break
            ys = struct.unpack(">L", raw[base:base + 4])[0]
            ye = struct.unpack(">L", raw[base + 8:base + 12])[0]
            entries.append(f"[{ys}-{ye}]")
        return f"CONTROL_FRAME entries={entry_count}: {' '.join(entries)}"
    return None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _print_tsv_wdbs(rows: List[WdbRow], label: str = ""):
    """Print WDB rows as TSV."""
    prefix = f"[{label}] " if label else ""
    print(f"\n{prefix}WDB extraction ({len(rows)} entries):")
    cols = [
        "line_num", "timestamp", "window_id", "x_res", "y_res",
        "offset_x", "offset_y", "size_x", "size_y",
        "scan_kind", "exposure", "raw_hex",
    ]
    print("\t".join(cols))
    for r in rows:
        vals = [
            str(r.line_num),
            f"{r.timestamp:.6f}",
            str(r.window_id),
            str(r.x_res),
            str(r.y_res),
            str(r.offset_x),
            str(r.offset_y),
            str(r.size_x),
            str(r.size_y),
            r.scan_kind,
            f"0x{r.exposure:08x}",
            r.raw_hex,
        ]
        print("\t".join(vals))


def wdb_rows_to_json(rows: List[WdbRow]) -> List[Dict[str, Any]]:
    """Serialize WDB extraction rows as JSON-serializable dicts."""
    return [asdict(r) for r in rows]


def _print_tsv_control_frames(rows: List[CtrlFrameRow], label: str = ""):
    """Print CONTROL_FRAME rows as TSV."""
    prefix = f"[{label}] " if label else ""
    print(f"\n{prefix}CONTROL_FRAME extraction ({len(rows)} entries):")
    cols = ["line_num", "timestamp", "entry_index", "frame_index", "y_start", "y_end", "height"]
    print("\t".join(cols))
    for r in rows:
        print("\t".join([
            str(r.line_num),
            f"{r.timestamp:.6f}",
            str(r.entry_index),
            str(r.frame_index),
            str(r.y_start),
            str(r.y_end),
            str(r.height),
        ]))


def cf_rows_to_json(rows: List[CtrlFrameRow]) -> List[Dict[str, Any]]:
    """Serialize CONTROL_FRAME extraction rows as JSON-serializable dicts."""
    return [asdict(r) for r in rows]


def _print_tsv_read_cap(rows: List[ReadCapRow], label: str = ""):
    """Print READ_CAPACITY rows as TSV."""
    prefix = f"[{label}] " if label else ""
    print(f"\n{prefix}READ_CAPACITY extraction ({len(rows)} entries):")
    cols = [
        "line_num", "timestamp", "window_id", "x_res", "y_res",
        "offset_x", "offset_y", "size_x", "size_y", "exposure", "raw_hex",
    ]
    print("\t".join(cols))
    for r in rows:
        print("\t".join([
            str(r.line_num),
            f"{r.timestamp:.6f}",
            str(r.window_id),
            str(r.x_res),
            str(r.y_res),
            str(r.offset_x),
            str(r.offset_y),
            str(r.size_x),
            str(r.size_y),
            f"0x{r.exposure:08x}",
            r.raw_hex,
        ]))


def readcap_rows_to_json(rows: List[ReadCapRow]) -> List[Dict[str, Any]]:
    """Serialize READ_CAPACITY extraction rows as JSON-serializable dicts."""
    return [asdict(r) for r in rows]


def json_structured_output(
    events: List[Event],
    phases: List[PhaseGroup],
    issues: List[Issue],
    wdbs: Optional[List[WdbRow]] = None,
    control_frames: Optional[List[CtrlFrameRow]] = None,
    read_capacity: Optional[List[ReadCapRow]] = None,
    verbose: bool = False,
    max_events: int = 10000,
) -> Dict[str, Any]:
    """Build a JSON-serializable dict with event data and all structural extractions.

    This is the recommended API for programmatic consumers (tests, scripts).
    Returns a dict suitable for ``json.dumps()`` that includes event summary,
    phases, issues, command frequency, and optionally WDB/CF/ReadCap extraction
    results.
    """
    base = json_output(events, phases, issues, verbose=verbose, max_events=max_events)
    if wdbs:
        base["wdbs"] = wdb_rows_to_json(wdbs)
    if control_frames:
        base["control_frames"] = cf_rows_to_json(control_frames)
    if read_capacity:
        base["read_capacity"] = readcap_rows_to_json(read_capacity)
    return base


def _print_wdb_diff(diffs: List[Dict[str, Any]], label_a: str = "A", label_b: str = "B"):
    """Print WDB structural diff."""
    if not diffs:
        print("\nWDB diff: no differences")
        return
    print(f"\nWDB diff ({len(diffs)} differences):")
    for d in diffs:
        if d["type"] == "changed":
            changes = ", ".join(f"{k}: {v}" for k, v in d["changes"].items())
            print(f"  seq={d['seq']} win_a={d['window_a']} win_b={d['window_b']}: {changes}")
        elif d["type"] == "missing_in_b":
            r = d["row"]
            print(f"  seq={d['seq']} missing_in_b: win={r['window_id']} res={r['x_res']}x{r['y_res']}")
        elif d["type"] == "extra_in_b":
            r = d["row"]
            print(f"  seq={d['seq']} extra_in_b: win={r['window_id']} res={r['x_res']}x{r['y_res']}")


def _print_cf_diff(diffs: List[Dict[str, Any]], label_a: str = "A", label_b: str = "B"):
    """Print CONTROL_FRAME structural diff."""
    if not diffs:
        print("\nCONTROL_FRAME diff: no differences")
        return
    print(f"\nCONTROL_FRAME diff ({len(diffs)} differences):")
    for d in diffs:
        if d["type"] == "changed":
            changes = ", ".join(f"{k}: {v}" for k, v in d["changes"].items())
            print(f"  seq={d['seq']}: {changes}")
        elif d["type"] == "missing_in_b":
            e = d["entry"]
            print(f"  seq={d['seq']} missing_in_b: entry={e['entry_index']} y={e['y_start']}-{e['y_end']}")
        elif d["type"] == "extra_in_b":
            e = d["entry"]
            print(f"  seq={d['seq']} extra_in_b: entry={e['entry_index']} y={e['y_start']}-{e['y_end']}")


def print_summary(
    events: List[Event],
    phases: List[PhaseGroup],
    issues: List[Issue],
    verbose: bool = False,
    max_events: int = 10000,
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
    display_count = max_events if not verbose else len(events)
    if verbose:
        print(
            f"{'Event':>5} {'Time':>8} {'Dir':>3} {'Size':>4} "
            f"{'Phase':<12} {'RawHex':<22} Description"
        )
        print("-" * 112)
        for ev in events[:display_count]:
            dec = ev.decoded
            desc = ""
            raw_hex = ""
            if dec:
                inline = False
                if dec.cmd_name in ("DATA_OUT", "DATA_BLOCK"):
                    decoded_payload = _decode_inline_payload(ev)
                    if decoded_payload:
                        desc = f"{dec.cmd_name} {decoded_payload}"
                        inline = True
                if not inline:
                    params_str = " ".join(f"{k}={v}" for k, v in dec.params.items())
                    desc = dec.cmd_name
                    if params_str:
                        desc += f" ({params_str})"
                if dec.is_error:
                    desc += f" *** {dec.error_detail}"
                if ev.direction == "out" and len(ev.raw) >= 6:
                    raw_hex = ev.raw[:min(10, len(ev.raw))].hex()
                elif ev.direction == "in" and len(ev.raw) <= 16:
                    raw_hex = ev.raw.hex()
            else:
                desc = f"raw {len(ev.raw)}B"
                raw_hex = ev.raw[:min(16, len(ev.raw))].hex()

            print(
                f"{ev.index:5d} {ev.timestamp:8.3f} {ev.direction:>3} "
                f"{len(ev.raw):4d} {ev.phase:<12} {raw_hex:<22} {desc}"
            )
    else:
        print(
            f"{'Event':>5} {'Time':>8} {'Dir':>3} {'Size':>4} "
            f"{'Phase':<12} Description"
        )
        print("-" * 90)
        for ev in events[:display_count]:
            dec = ev.decoded
            desc = ""
            if dec:
                inline = False
                if dec.cmd_name in ("DATA_OUT", "DATA_BLOCK"):
                    decoded_payload = _decode_inline_payload(ev)
                    if decoded_payload:
                        desc = f"{dec.cmd_name} {decoded_payload}"
                        inline = True

                if not inline:
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

    if len(events) > display_count:
        print(f"\n... ({len(events) - display_count} more events, use --verbose for all)")


def print_grouped_by_phase(
    events: List[Event],
    phases: List[PhaseGroup],
    issues: List[Issue],
    max_events: int = 10000,
    verbose: bool = False,
) -> None:
    """Print events grouped by phase with per-phase summary."""
    display_count = max_events
    out_count = sum(1 for e in events if e.direction == "out")
    in_count = sum(1 for e in events if e.direction == "in")
    total_time = events[-1].timestamp if events else 0

    print()
    print("=" * 70)
    print("CAPTURE ANALYSIS (GROUPED BY PHASE)")
    print("=" * 70)
    print(f"Total events: {len(events)} ({out_count} OUT, {in_count} IN)")
    print(f"Duration: {total_time:.2f}s")
    print(f"Phases: {len(phases)}")
    print()

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

    # Collect issues per phase
    phase_issues: Dict[str, List[Issue]] = defaultdict(list)
    for iss in issues:
        ev = events[iss.event_index] if iss.event_index < len(events) else None
        if ev:
            phase_issues[ev.phase].append(iss)

    for ph in phases:
        print(f"\n{'=' * 70}")
        print(f"Phase: {ph.name}")
        print(f"  Events: {ph.event_count} ({ph.out_count} OUT, {ph.in_count} IN)")
        dur = ph.end_time - ph.start_time
        print(f"  Time: {ph.start_time:.3f} - {ph.end_time:.3f} ({dur:.3f}s)")

        phase_issue_list = phase_issues.get(ph.name, [])
        if phase_issue_list:
            print(f"  Issues: {len(phase_issue_list)}")
            for iss in phase_issue_list:
                marker = {"error": "!!", "warning": "~>", "info": "  "}[iss.severity]
                print(f"  {marker} Event {iss.event_index}: {iss.message}")

        # Command frequency for this phase
        phase_cmds: Counter = Counter()
        for ev in events:
            if ev.phase == ph.name and ev.direction == "out" and ev.decoded:
                phase_cmds[ev.decoded.cmd_name] += 1

        if phase_cmds:
            print("  Commands:")
            for name, count in phase_cmds.most_common():
                print(f"    {name:<25} {count:4d}")

        # Events (truncated)
        phase_events = [
            ev for ev in events
            if ph.start_index <= ev.index <= ph.end_index
            and ev.index < display_count
        ]
        if phase_events:
            if verbose:
                print(
                    f"  {'Event':>5} {'Time':>8} {'Dir':>3} {'Size':>4} "
                    f"{'RawHex':<22} Description"
                )
            else:
                print(
                    f"  {'Event':>5} {'Time':>8} {'Dir':>3} {'Size':>4} Description"
                )
            for ev in phase_events[:display_count]:
                dec = ev.decoded
                desc = ""
                raw_hex = ""
                if dec:
                    inline = False
                    if dec.cmd_name in ("DATA_OUT", "DATA_BLOCK"):
                        decoded_payload = _decode_inline_payload(ev)
                        if decoded_payload:
                            desc = f"{dec.cmd_name} {decoded_payload}"
                            inline = True
                    if not inline:
                        params_str = " ".join(
                            f"{k}={v}" for k, v in dec.params.items()
                        )
                        desc = dec.cmd_name
                        if params_str:
                            desc += f" ({params_str})"
                    if dec.is_error:
                        desc += f" *** {dec.error_detail}"
                    if verbose:
                        if ev.direction == "out" and len(ev.raw) >= 6:
                            raw_hex = ev.raw[:min(10, len(ev.raw))].hex()
                        elif ev.direction == "in" and len(ev.raw) <= 16:
                            raw_hex = ev.raw.hex()
                else:
                    desc = f"raw {len(ev.raw)}B"
                    if verbose:
                        raw_hex = ev.raw[:min(16, len(ev.raw))].hex()

                if verbose:
                    print(
                        f"  {ev.index:5d} {ev.timestamp:8.3f} {ev.direction:>3} "
                        f"{len(ev.raw):4d} {raw_hex:<22} {desc}"
                    )
                else:
                    print(
                        f"  {ev.index:5d} {ev.timestamp:8.3f} {ev.direction:>3} "
                        f"{len(ev.raw):4d} {desc}"
                    )


def print_data_samples(events: List[Event], n_bytes: int) -> None:
    """Print first N bytes of each IN transfer payload."""
    in_events = [ev for ev in events if ev.direction == "in"]
    print(f"\nData samples (first {n_bytes} bytes of each IN transfer, {len(in_events)} total):")
    print(f"{'Event':>5} {'Time':>8} {'Size':>6} {'SampleHex'}")
    print("-" * 80)
    for ev in in_events:
        sample = ev.raw[:n_bytes].hex()
        print(
            f"{ev.index:5d} {ev.timestamp:8.3f} {len(ev.raw):6d} {sample}"
        )


def print_timeline(events: List[Event]) -> None:
    """Print OUT->IN command-response pairs with timing deltas."""
    print("\nCommand-response timeline:")
    print(f"{'OUT#':>5} {'OUT Time':>8} {'OUT Cmd':<20} {'IN#':>5} "
          f"{'IN Time':>8} {'IN Size':>6} {'Delta(s)':>8}")
    print("-" * 80)

    i = 0
    n = len(events)
    while i < n:
        ev_out = events[i]
        if ev_out.direction != "out":
            i += 1
            continue

        # Find the next IN response
        j = i + 1
        ev_in = None
        while j < n:
            if events[j].direction == "in":
                ev_in = events[j]
                break
            j += 1

        if ev_in is None:
            break

        out_dec = ev_out.decoded
        in_dec = ev_in.decoded
        out_name = out_dec.cmd_name if out_dec else f"raw({len(ev_out.raw)}B)"
        delta = ev_in.timestamp - ev_out.timestamp

        print(
            f"{ev_out.index:5d} {ev_out.timestamp:8.3f} {out_name:<20} "
            f"{ev_in.index:5d} {ev_in.timestamp:8.3f} {len(ev_in.raw):6d} "
            f"{delta:8.3f}"
        )

        # Skip past the response sequence (phase handshake + data + status)
        i = j + 1
        # Skip subsequent IN events that are part of the same response
        while i < n and events[i].direction == "in":
            i += 1


def compute_datatype_summary(events: List[Event]) -> Dict[str, Dict[str, Any]]:
    """Compute per-datatype transfer totals from READ/WRITE commands and IN data.

    Returns dict keyed by datatype hex (e.g. '0x00'), each with:
    - name: human-readable name
    - commands: number of READ/WRITE commands
    - declared_bytes: sum of CDB-declared transfer lengths
    - actual_bytes: sum of IN data block sizes for that datatype
    """
    summary: Dict[str, Dict[str, Any]] = {}
    current_datatype: Optional[str] = None

    for ev in events:
        dec = ev.decoded
        if not dec:
            continue

        # Track READ/WRITE datatype from OUT commands
        if ev.direction == "out" and "datatype" in dec.params:
            dt = dec.params["datatype"]  # e.g. "0x00"
            current_datatype = dt
            entry = summary.setdefault(dt, {
                "name": DATA_TYPE_NAMES.get(int(dt, 16), "unknown"),
                "commands": 0,
                "declared_bytes": 0,
                "actual_bytes": 0,
            })
            entry["commands"] += 1
            if "length" in dec.params:
                entry["declared_bytes"] += dec.params["length"]
            continue

        # Phase checks, status, etc. don't change datatype context
        if ev.direction == "out":
            # Non-datatype OUT commands (TUR, phase check, etc.) don't change context
            continue

        # IN events: accumulate actual data bytes under current datatype
        if current_datatype and dec.cmd_name in ("DATA_BLOCK", "DATA_RESP"):
            entry = summary.get(current_datatype)
            if entry:
                entry["actual_bytes"] += len(ev.raw)

    return summary


def print_datatype_summary(events: List[Event]) -> None:
    """Print per-datatype transfer summary."""
    summary = compute_datatype_summary(events)
    if not summary:
        return

    print("\nData transfer by datatype:")
    print(f"  {'Datatype':<12} {'Name':<22} {'Cmds':>5} "
          f"{'Declared':>12} {'Actual':>12}")
    print("  " + "-" * 65)
    for dt in sorted(summary.keys()):
        s = summary[dt]
        print(
            f"  {dt:<12} {s['name']:<22} {s['commands']:>5} "
            f"{s['declared_bytes']:>12,} {s['actual_bytes']:>12,}"
        )


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def json_output(
    events: List[Event],
    phases: List[PhaseGroup],
    issues: List[Issue],
    verbose: bool = False,
    max_events: int = 10000,
) -> Dict[str, Any]:
    """Build JSON-serializable output."""
    display_count = len(events) if verbose else max_events
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
                "raw_hex": e.raw[:min(10, len(e.raw))].hex()
                if e.direction == "out" and len(e.raw) <= 16
                else e.raw.hex() if len(e.raw) <= 16 else e.raw[:16].hex() + "...",
                "phase": e.phase,
                "decoded": asdict(e.decoded) if e.decoded else None,
                **({"declared_length": e.decoded.params["length"]}
                   if e.decoded and "length" in e.decoded.params else {}),
            }
            for e in events[:display_count]
        ],
    }




# ---------------------------------------------------------------------------
# Frame detection from WDBs
# ---------------------------------------------------------------------------


def _classify_scan_type(x_res: int, channel: int) -> str:
    """Classify a scan frame by resolution and channel."""
    if x_res <= 120:
        return "prescan"
    if x_res >= 1000:
        return "full_res_ir" if channel == 9 else "full_res"
    return "preview_ir" if channel == 9 else "preview"


def _build_frame_info(events: List[Event]) -> List[Dict[str, Any]]:
    """Walk events and build frame info dicts from WDBs and DATA_BLOCKs.

    Returns a list of dicts, one per detected image frame.
    """
    # Active WDB state — updated when we see a SCAN command
    active_wdb: Optional[Dict[str, Any]] = None

    # Current frame being accumulated
    current_data = bytearray()
    current_wdb: Optional[Dict[str, Any]] = None
    in_read = False

    frames: List[Dict[str, Any]] = []

    def _finalize_frame() -> None:
        nonlocal current_data, current_wdb, in_read
        if not current_wdb or not current_data:
            return
        w = current_wdb
        width = w["width"]
        h_declared = w["height"]
        channel = w["channel"]
        num_channels = 1 if channel == 9 else 3
        x_res = w["x_res"]
        y_res = w["y_res"]
        transfer_byte = w["transfer_byte"]

        # Determine depth
        if x_res >= 1000 and channel != 9 and transfer_byte == 0x0C:
            depth = 12
        else:
            depth = 8

        bytes_per_channel = 2 if depth > 8 else 1
        h_actual = len(current_data) // (width * num_channels * bytes_per_channel)
        if h_actual == 0:
            return

        scan_type = _classify_scan_type(x_res, channel)
        has_ir = channel == 9

        frames.append({
            "scan_type": scan_type,
            "resolution_str": f"{x_res}x{y_res} DPI",
            "x_res": x_res,
            "width": width,
            "h_declared": h_declared,
            "h_actual": h_actual,
            "has_ir": has_ir,
            "bytes": len(current_data),
            "offset": w["offset"],
            "data": bytes(current_data),
            "depth": depth,
            "num_channels": num_channels,
        })

    for ev in events:
        if not ev.raw:
            continue

        if ev.direction == "out":
            # SCAN (0x24) — look for WDB in next few events
            if ev.raw[0] == 0x24:
                # Finalize any previous frame first
                _finalize_frame()
                current_data = bytearray()
                current_wdb = None
                in_read = False

                # Look ahead up to 10 events for WDB DATA_OUT
                n = len(events)
                ev_idx = ev.index
                for k in range(ev_idx + 1, min(ev_idx + 11, n)):
                    candidate = events[k]
                    if candidate.direction == "out" and len(candidate.raw) == 58:
                        if candidate.decoded and candidate.decoded.cmd_name.startswith("DATA_OUT"):
                            wdb = WindowDescriptorBlock.from_bytes_58(candidate.raw)
                            active_wdb = {
                                "x_res": wdb.x_resolution,
                                "y_res": wdb.y_resolution,
                                "width": wdb.width,
                                "height": wdb.length,
                                "offset": wdb.frame_offset,
                                "channel": wdb.channel,
                                "transfer_byte": wdb.transfer_byte,
                            }
                            break
                continue

            # READ(10) with datatype=0x00 — subsequent chunks accumulate
            if (ev.raw[0] == 0x28 and len(ev.raw) >= 10 and ev.raw[2] == 0x00):
                in_read = True
                current_wdb = active_wdb
                continue

            # Any other OUT command (not 0x00 TUR, not 0xd0 PHASE_CHECK)
            # ends the current data collection
            if ev.raw[0] not in (0x00, 0xd0):
                if in_read and current_data:
                    _finalize_frame()
                in_read = False
                current_data = bytearray()
                current_wdb = None
                continue

        elif ev.direction == "in":
            if in_read and ev.decoded and ev.decoded.cmd_name == "DATA_BLOCK":
                current_data.extend(ev.raw)

    # Finalize last frame
    _finalize_frame()

    return frames


def _print_frame_list(frames_info: List[Dict[str, Any]]) -> None:
    """Print frame metadata as a TSV table to stdout."""
    headers = [
        "idx", "scan_type", "resolution", "width",
        "h_declared", "h_actual", "has_ir", "bytes", "offset",
    ]
    print("\t".join(headers))
    for i, fi in enumerate(frames_info):
        row = [
            str(i),
            fi["scan_type"],
            fi["resolution_str"],
            str(fi["width"]),
            str(fi["h_declared"]),
            str(fi["h_actual"]),
            "yes" if fi["has_ir"] else "no",
            str(fi["bytes"]),
            str(fi["offset"]),
        ]
        print("\t".join(row))


# ---------------------------------------------------------------------------
# Image extraction from captures
# ---------------------------------------------------------------------------


def _parse_frame_ids(spec: str) -> Optional[List[int]]:
    """Parse a frame selector string like '0,2-4,6' into a list of indices.

    Returns None for 'all' (meaning all frames), or a sorted list of indices.
    """
    if spec == "all":
        return None
    indices: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            indices.extend(range(int(lo), int(hi) + 1))
        else:
            indices.append(int(part))
    return sorted(set(indices))


def extract_image_frames(
    events: List[Event],
    output_dir: str,
    frame_ids: Optional[List[int]] = None,
    fmt: str = "jpeg",
) -> List[Dict[str, Any]]:
    """Extract image frames from capture events and save as TIFF/JPEG.

    Parameters are auto-detected from WDB payloads within the capture.

    Args:
        events: Decoded events (call ``_decode_all()`` first).
        output_dir: Directory to write output files.
        frame_ids: Frame indices to extract. None means all frames.
            Empty list means all full-res frames only (default).
        fmt: Output format: "tiff", "jpeg", or "both".

    Returns:
        List of dicts with keys: frame_index, bytes_count, tiff_path, jpeg_path.
    """
    import numpy as np
    from PIL import Image

    from coolscan.scanner import LS40_CHANNEL_OFFSETS, _parse_scan_data
    from coolscan.cli import (
        _apply_auto_adjust,
        _save_jpeg,
        _save_tiff_dual_ifd,
    )

    os.makedirs(output_dir, exist_ok=True)
    out_path = Path(output_dir).resolve()

    # Build frame info from events
    frames_info = _build_frame_info(events)

    if not frames_info:
        print("No image frames found in capture.", file=sys.stderr)
        return []

    # Determine basename from output directory
    basename = out_path.stem or "scan"

    # Filter frames by frame_ids
    if frame_ids is None:
        # "all" — extract every frame
        selected = list(enumerate(frames_info))
    elif frame_ids:
        # Specific frame indices
        selected = [(i, fi) for i, fi in enumerate(frames_info) if i in frame_ids]
    else:
        # Empty list: default — all full-res frames (skip prescan/preview)
        selected = [
            (i, fi) for i, fi in enumerate(frames_info)
            if fi["scan_type"] in ("full_res", "full_res_ir")
        ]

    if not selected:
        print("No matching frames found.", file=sys.stderr)
        return []

    results: List[Dict[str, Any]] = []
    total_bytes = 0

    for frame_idx, fi in selected:
        scan_data = fi["data"]
        width = fi["width"]
        h_actual = fi["h_actual"]
        num_channels = fi["num_channels"]
        depth = fi["depth"]
        has_ir = fi["has_ir"]
        scan_type = fi["scan_type"]
        resolution_str = fi["resolution_str"]
        h_declared = fi["h_declared"]

        print(f"  Frame {frame_idx} ({scan_type}): {len(scan_data)} bytes")
        total_bytes += len(scan_data)

        # Warn on truncated data
        bytes_per_channel = 2 if depth > 8 else 1
        declared_bytes = width * h_declared * num_channels * bytes_per_channel
        if len(scan_data) < 0.5 * declared_bytes:
            print(
                f"    Warning: capture truncated — got {len(scan_data)} bytes, "
                f"expected {declared_bytes} from WDB",
                file=sys.stderr,
            )

        # Parse raw scan data
        # LS40_CHANNEL_OFFSETS are calibrated for 2900 DPI full-res only;
        # prescan/preview at lower DPI already compensates the CCD offset
        if has_ir:
            channel_offsets = (0,)
        elif fi.get("x_res", 2900) >= 1000:
            channel_offsets = LS40_CHANNEL_OFFSETS
        else:
            channel_offsets = (0, 0, 0)

        img_arr, trailing = _parse_scan_data(
            bytearray(scan_data),
            width=width,
            height=h_actual,
            num_channels=num_channels,
            depth=depth,
            format="plane",
            channel_offsets=channel_offsets,
        )

        # Build frame name
        res_short = resolution_str.split("x")[0]  # e.g. "2900"
        frame_name = f"{basename}_frame_{frame_idx:03d}_{scan_type}_{res_short}dpi"

        # TIFF output
        tiff_path = None
        if fmt in ("tiff", "both"):
            tiff_p = out_path / f"{frame_name}.tiff"
            if has_ir:
                # Single-channel IR: write as grayscale TIFF
                if depth > 8:
                    ir_data = img_arr[:, :, 0].astype(np.uint16)
                    ir_data = (ir_data.astype(np.uint32) * 65535 // 4095).astype(np.uint16)
                    pil_img = Image.fromarray(ir_data, mode="I;16")
                else:
                    ir_data = img_arr[:, :, 0].astype(np.uint8)
                    pil_img = Image.fromarray(ir_data, mode="L")
                pil_img.save(str(tiff_p))
            else:
                rgb_arr = np.ascontiguousarray(img_arr[:, :, 0:3])
                if depth > 8 and rgb_arr.dtype == np.uint16:
                    tiff_rgb = (rgb_arr.astype(np.uint32) * 65535 // 4095).astype(np.uint16)
                else:
                    tiff_rgb = rgb_arr
                _save_tiff_dual_ifd(tiff_rgb, None, tiff_p, exif_data=None)
            tiff_path = str(tiff_p)
            print(f"    Saved TIFF: {tiff_p}")

        # JPEG output
        jpeg_path = None
        if fmt in ("jpeg", "both"):
            jpeg_p = out_path / f"{frame_name}.jpg"
            if has_ir:
                # Single-channel IR: convert to 8-bit grayscale JPEG
                if depth > 8:
                    ir_8bit = (img_arr[:, :, 0].astype(np.uint32) >> 4).astype(np.uint8)
                else:
                    ir_8bit = img_arr[:, :, 0].astype(np.uint8)
                pil_img = Image.fromarray(ir_8bit, mode="L")
                pil_img.save(str(jpeg_p), "JPEG")
            else:
                rgb_arr = np.ascontiguousarray(img_arr[:, :, 0:3])
                if rgb_arr.dtype == np.uint16:
                    jpeg_input = (rgb_arr >> 4).astype(np.uint8)
                else:
                    jpeg_input = rgb_arr
                jpeg_arr = np.ascontiguousarray(jpeg_input)
                jpeg_arr = _apply_auto_adjust(jpeg_arr)
                jpeg_arr = np.ascontiguousarray(jpeg_arr)
                _save_jpeg(jpeg_arr, jpeg_p, exif_data=None)
            jpeg_path = str(jpeg_p)
            print(f"    Saved JPEG: {jpeg_p}")

        results.append({
            "frame_index": frame_idx,
            "bytes_count": len(scan_data),
            "tiff_path": tiff_path,
            "jpeg_path": jpeg_path,
        })

    # Print summary
    print(f"\nImage extraction complete: {len(results)} frames, {total_bytes} total bytes")
    print(f"Output directory: {out_path}")
    return results


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
        help="Show all events (not just first N)",
    )
    parser.add_argument(
        "--max-events", type=int, default=10000,
        help="Max events in output (default 10000, 0=unlimited)",
    )
    parser.add_argument(
        "--extract-wdbs", action="store_true",
        help="Extract and tabulate SET_WINDOW (0x24) WDB payloads",
    )
    parser.add_argument(
        "--extract-control-frames", action="store_true",
        help="Extract and tabulate CONTROL_FRAME (0x8F) payloads",
    )
    parser.add_argument(
        "--extract-read-capacity", action="store_true",
        help="Extract and tabulate READ_CAPACITY (0x25) responses",
    )
    parser.add_argument(
        "--filter", metavar="EXPR",
        help="Filter events: e.g. --filter 'cmd=SCAN' or --filter 'data_type=0x8f and length>50'",
    )
    parser.add_argument(
        "--diff-wdbs", action="store_true",
        help="Structural diff of WDBs between two captures (with --diff-a/--diff-b)",
    )
    parser.add_argument(
        "--diff-control-frames", action="store_true",
        help="Structural diff of CONTROL_FRAMES (with --diff-a/--diff-b)",
    )
    parser.add_argument(
        "--group-by-phase", action="store_true",
        help="Output events grouped by phase with per-phase stats",
    )
    parser.add_argument(
        "--extract-data-samples", type=int, default=0, metavar="N",
        help="Show first N bytes of each IN transfer payload as hex",
    )
    parser.add_argument(
        "--timeline", action="store_true",
        help="Show OUT->IN command-response pairs with timing deltas",
    )
    parser.add_argument(
        "--datatype-summary", action="store_true",
        help="Show per-datatype transfer totals (declared vs actual bytes)",
    )
    parser.add_argument(
        "--extract-images", metavar="FRAMES",
        help="Extract image frames (e.g. '0,2-4,6' or 'all')",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Output directory for extracted images (default: current directory)",
    )
    parser.add_argument(
        "--extract-format", choices=["tiff", "jpeg", "both"], default="jpeg",
        help="Output format for extraction (default: jpeg)",
    )
    parser.add_argument(
        "--list-frames", action="store_true",
        help="List detected image frames as a TSV table",
    )

    args = parser.parse_args()

    max_events = args.max_events if args.max_events > 0 else 1000000

    # -----------------------------------------------------------------------
    # Filter AST
    # -----------------------------------------------------------------------
    filter_ast: Optional[_FilterAST] = None
    if args.filter:
        try:
            filter_ast = parse_filter_expr(args.filter)
        except ValueError as e:
            print(f"Filter error: {e}", file=sys.stderr)
            return 1

    # -----------------------------------------------------------------------
    # Diff mode
    # -----------------------------------------------------------------------
    if args.diff_a and args.diff_b:
        events_a = load_capture(args.diff_a)
        events_b = load_capture(args.diff_b)
        _decode_all(events_a)
        _decode_all(events_b)
        events_a = detect_phases(events_a)
        events_b = detect_phases(events_b)

        if filter_ast:
            events_a = filter_events(events_a, filter_ast)
            events_b = filter_events(events_b, filter_ast)

        if not args.json:
            if args.extract_wdbs:
                _print_tsv_wdbs(extract_wdbs(events_a), args.diff_a)
                _print_tsv_wdbs(extract_wdbs(events_b), args.diff_b)

            if args.extract_control_frames:
                _print_tsv_control_frames(extract_control_frames(events_a), args.diff_a)
                _print_tsv_control_frames(extract_control_frames(events_b), args.diff_b)

            if args.extract_read_capacity:
                _print_tsv_read_cap(extract_read_capacity(events_a), args.diff_a)
                _print_tsv_read_cap(extract_read_capacity(events_b), args.diff_b)

        if args.diff_wdbs:
            _print_wdb_diff(
                diff_wdbs(extract_wdbs(events_a), extract_wdbs(events_b)),
                args.diff_a, args.diff_b,
            )

        if args.diff_control_frames:
            _print_cf_diff(
                diff_control_frames(
                    extract_control_frames(events_a),
                    extract_control_frames(events_b),
                ),
                args.diff_a, args.diff_b,
            )

        # Standard diff
        diffs = diff_events(events_a, events_b)

        if args.json:
            output: Dict[str, Any] = {"differences": diffs, "count": len(diffs)}
            if args.extract_wdbs:
                output["wdbs_a"] = wdb_rows_to_json(extract_wdbs(events_a))
                output["wdbs_b"] = wdb_rows_to_json(extract_wdbs(events_b))
            if args.extract_control_frames:
                output["control_frames_a"] = cf_rows_to_json(extract_control_frames(events_a))
                output["control_frames_b"] = cf_rows_to_json(extract_control_frames(events_b))
            if args.extract_read_capacity:
                output["read_capacity_a"] = readcap_rows_to_json(extract_read_capacity(events_a))
                output["read_capacity_b"] = readcap_rows_to_json(extract_read_capacity(events_b))
            print(json.dumps(output, indent=2))
        elif not (args.extract_wdbs or args.extract_control_frames or
                  args.diff_wdbs or args.diff_control_frames):
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

    # -----------------------------------------------------------------------
    # Single-file mode
    # -----------------------------------------------------------------------
    if not args.file:
        parser.print_help()
        return 1

    events = load_capture(args.file)
    if not events:
        print(f"No events found in {args.file}", file=sys.stderr)
        return 1

    _decode_all(events)
    events = detect_phases(events)

    if filter_ast:
        events = filter_events(events, filter_ast)

    phases = group_phases(events)
    issues = detect_issues(events)

    if args.annotate:
        annotation_issues = annotate_protocol(events)
        issues.extend(annotation_issues)

    # --list-frames: print frame table and exit
    if args.list_frames:
        frames_info = _build_frame_info(events)
        _print_frame_list(frames_info)
        return 0

    # Extraction outputs (TSV to stdout, unless --json)
    if not args.json:
        if args.extract_wdbs:
            _print_tsv_wdbs(extract_wdbs(events))

        if args.extract_control_frames:
            _print_tsv_control_frames(extract_control_frames(events))

        if args.extract_read_capacity:
            _print_tsv_read_cap(extract_read_capacity(events))

        if args.extract_data_samples > 0:
            print_data_samples(events, args.extract_data_samples)

        if args.timeline:
            print_timeline(events)

        if args.datatype_summary:
            print_datatype_summary(events)

        if args.extract_images:
            frame_ids = _parse_frame_ids(args.extract_images)
            extract_image_frames(
                events,
                output_dir=args.output_dir,
                frame_ids=frame_ids,
                fmt=args.extract_format,
            )

    # Output
    if args.json:
        if args.extract_wdbs or args.extract_control_frames or args.extract_read_capacity:
            output = json_structured_output(
                events, phases, issues,
                wdbs=extract_wdbs(events) if args.extract_wdbs else None,
                control_frames=extract_control_frames(events) if args.extract_control_frames else None,
                read_capacity=extract_read_capacity(events) if args.extract_read_capacity else None,
                verbose=args.verbose, max_events=max_events,
            )
        else:
            output = json_output(events, phases, issues, verbose=args.verbose, max_events=max_events)
        if args.datatype_summary:
            output["datatype_summary"] = compute_datatype_summary(events)
        print(json.dumps(output, indent=2, default=str))
    elif args.group_by_phase:
        print_grouped_by_phase(events, phases, issues, max_events=max_events, verbose=args.verbose)
    elif args.timeline:
        print_timeline(events)
    else:
        print_summary(events, phases, issues, verbose=args.verbose, max_events=max_events)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
