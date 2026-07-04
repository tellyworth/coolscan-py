#!/usr/bin/env python3
"""
Generate a golden fixture from ``ls40-single-bw.pcapng``.

Extracts all OUT/IN bulk transfer events using tshark, normalizes known
non-determinism (TUR retry collapse, timestamp offsets), and writes a
text fixture in the same tab-separated format as ``test_basic_scan_capture.txt``.

Embeds the pcapng SHA-256 checksum in the fixture header for traceability.

Requires: ``tshark`` on PATH, ``ls40-single-bw.pcapng`` at repo root.

Example::

    python3 scripts/generate_fixture_from_pcapng.py
"""

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

BULK_OUT_EP = 0x01
BULK_IN_EP = 0x82



def _pcapng_sha256(path: Path) -> str:
    """Compute SHA-256 of the pcapng file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _has_tshark() -> bool:
    try:
        subprocess.run(["tshark", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _extract_packets(pcap_path: Path) -> list[tuple[int, str, int, bytes, float]]:
    """Extract USB bulk packets from pcapng using tshark.

    Returns list of (frame_num, direction, endpoint, data, relative_timestamp).
    Direction is "OUT" (host->device, ep 0x01) or "IN" (device->host, ep 0x82).
    """
    cmd = [
        "tshark",
        "-r", str(pcap_path),
        "-Y", "usb",
        "-T", "fields",
        "-e", "frame.number",
        "-e", "usb.endpoint_address",
        "-e", "usb.dst",
        "-e", "usb.capdata",
        "-e", "frame.time_relative",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"tshark failed: {result.stderr}", file=sys.stderr)
        return []

    packets: list[tuple[int, str, int, bytes, float]] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue

        parts = line.split("\t")
        if len(parts) < 5:
            continue

        frame_num = int(parts[0])
        endpoint_str = parts[1]
        dst = parts[2]
        capdata = parts[3].strip()
        ts_str = parts[4]

        # Parse endpoint
        try:
            if endpoint_str.startswith("0x"):
                endpoint = int(endpoint_str, 16)
            else:
                endpoint = 0
        except (ValueError, AttributeError):
            continue

        # Determine direction from endpoint (0x01 = OUT, 0x82 = IN)
        if endpoint == BULK_OUT_EP:
            direction = "OUT"
        elif endpoint == BULK_IN_EP:
            direction = "IN"
        else:
            continue

        # Parse timestamp
        try:
            ts = float(ts_str)
        except (ValueError, IndexError):
            ts = 0.0

        # Parse hex data
        if capdata:
            hex_str = re.sub(r"[: ]", "", capdata)
            try:
                data = bytes.fromhex(hex_str)
                if len(data) > 0:
                    packets.append((frame_num, direction, endpoint, data, ts))
            except ValueError:
                continue

    return packets


def _collapse_tur_retries(
    packets: list[tuple[int, str, int, bytes, float]],
    max_tur_cycles: int = 3,
) -> list[tuple[int, str, int, bytes, float]]:
    """Collapse repeated TUR+PHASE_CHECK polling cycles.

    The capture has 200+ TUR cycles; we keep only ``max_tur_cycles`` per
    polling phase to make the fixture manageable while still exercising
    retry logic.

    A TUR cycle is: OUT(0x00...) -> OUT(0xd0) -> IN(phase) -> IN(status).
    We identify consecutive runs of such cycles and collapse them.
    """
    result: list[tuple[int, str, int, bytes, float]] = []
    i = 0
    n = len(packets)

    while i < n:
        fn, direction, ep, data, ts = packets[i]

        # Check if this starts a TUR cycle: OUT TUR command (0x00)
        if (
            direction == "OUT"
            and len(data) >= 6
            and data[0] == 0x00
        ):
            # Look ahead to see if this is a TUR+PHASE_CHECK cycle
            cycle_events = _extract_tur_cycle(packets, i)
            if cycle_events:
                # Count how many consecutive TUR cycles
                cycle_count = 1
                j = i + len(cycle_events)
                while j < n:
                    next_cycle = _extract_tur_cycle(packets, j)
                    if next_cycle:
                        cycle_count += 1
                        j += len(next_cycle)
                    else:
                        break

                # Keep first cycle + up to (max_tur_cycles - 1) more
                keep_cycles = min(cycle_count, max_tur_cycles)
                for c in range(keep_cycles):
                    if c == 0:
                        result.extend(cycle_events)
                    else:
                        # Re-fetch cycle c
                        ci = i + c * len(cycle_events)
                        if ci < n:
                            sub = _extract_tur_cycle(packets, ci)
                            if sub:
                                result.extend(sub)

                # Make last kept cycle return READY if there were more cycles
                # (simulating that repeated polling eventually succeeds)
                if cycle_count > max_tur_cycles and result:
                    result = _force_ready_on_last_tur(result)

                i = j
                continue

        result.append(packets[i])
        i += 1

    return result


def _extract_tur_cycle(
    packets: list[tuple[int, str, int, bytes, float]],
    start: int,
) -> list[tuple[int, str, int, bytes, float]] | None:
    """Extract a single TUR+PHASE_CHECK cycle starting at index ``start``.

    Pattern: OUT(TUR) -> OUT(d0) -> IN(phase_byte) -> IN(8-byte status)
    """
    if start + 3 >= len(packets):
        return None

    p0, p1, p2, p3 = packets[start], packets[start + 1], packets[start + 2], packets[start + 3]

    if not (
        p0[1] == "OUT" and len(p0[3]) >= 6 and p0[3][0] == 0x00  # TUR
        and p1[1] == "OUT" and p1[3] == b"\xd0"  # PHASE_CHECK
        and p2[1] == "IN" and len(p2[3]) == 1  # phase byte
        and p3[1] == "IN" and len(p3[3]) == 8  # status
    ):
        return None

    return [p0, p1, p2, p3]


def _force_ready_on_last_tur(
    packets: list[tuple[int, str, int, bytes, float]],
) -> list[tuple[int, str, int, bytes, float]]:
    """Force the last TUR cycle in the list to return READY status."""
    result = list(packets)
    # Find the last 8-byte status IN
    for i in range(len(result) - 1, -1, -1):
        if result[i][1] == "IN" and len(result[i][3]) == 8:
            fn, direction, ep, data, ts = result[i]
            result[i] = (fn, direction, ep, b"\x00" * 8, ts)
            break
    return result


def _normalize_timestamps(
    packets: list[tuple[int, str, int, bytes, float]],
) -> list[tuple[int, str, int, bytes, float]]:
    """Shift all timestamps so the first event starts at 0.000."""
    if not packets:
        return packets

    base_ts = packets[0][4]
    return [(fn, d, ep, data, ts - base_ts) for fn, d, ep, data, ts in packets]


def _write_fixture(
    packets: list[tuple[int, str, int, bytes, float]],
    output_path: Path,
    pcap_path: Path,
    pcap_sha: str,
) -> None:
    """Write packets to a fixture file in the standard tab-separated format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append(f"# Golden fixture generated from {pcap_path.name}")
    lines.append(f"# pcapng SHA-256: {pcap_sha}")
    lines.append(f"# Total events: {len(packets)}")
    out_count = sum(1 for _, d, _, _, _ in packets if d == "OUT")
    in_count = sum(1 for _, d, _, _, _ in packets if d == "IN")
    lines.append(f"# OUT commands: {out_count}")
    lines.append(f"# IN responses: {in_count}")
    lines.append("")

    for fn, direction, ep, data, ts in packets:
        ep_hex = f"0x{ep:02x}"
        length = len(data)

        # For large payloads (>4096 bytes), use @path reference
        if length > 4096:
            bin_name = f"golden_data_{fn:04d}.bin"
            bin_path = output_path.parent / bin_name
            bin_path.write_bytes(data)
            lines.append(f"{ts:.9f}\t{ep_hex}\t{length}\t@{bin_name}")
        else:
            hex_data = data.hex()
            lines.append(f"{ts:.9f}\t{ep_hex}\t{length}\t{hex_data}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a golden fixture from a pcapng file.")
    parser.add_argument(
        "--pcap", 
        type=Path, 
        default=_REPO / "ls40-single-bw.pcapng", 
        help="Path to the pcapng capture file"
    )
    parser.add_argument(
        "--output", 
        type=Path, 
        default=_REPO / "reference" / "golden_single_bw.txt", 
        help="Path to the output fixture file"
    )
    args = parser.parse_args()

    pcap_path = args.pcap
    output_path = args.output

    if not _has_tshark():
        print("Error: tshark not found on PATH. Install wireshark/tshark first.", file=sys.stderr)
        return 1

    if not pcap_path.is_file():
        print(f"Error: pcapng file not found: {pcap_path}", file=sys.stderr)
        return 1

    print(f"Reading pcapng: {pcap_path}")
    pcap_sha = _pcapng_sha256(pcap_path)
    print(f"SHA-256: {pcap_sha}")

    packets = _extract_packets(pcap_path)
    if not packets:
        print("Error: no USB bulk packets extracted", file=sys.stderr)
        return 1

    print(f"Extracted {len(packets)} packets")

    # Normalize timestamps
    packets = _normalize_timestamps(packets)

    # Collapse TUR retries (keep 3 per phase)
    out_before = len(packets)
    packets = _collapse_tur_retries(packets, max_tur_cycles=3)
    print(f"Collapsed TUR cycles: {out_before} -> {len(packets)} events")

    # Write fixture
    _write_fixture(packets, output_path, pcap_path, pcap_sha)
    print(f"Wrote golden fixture: {output_path}")
    print(f"  OUT events: {sum(1 for _, d, _, _, _ in packets if d == 'OUT')}")
    print(f"  IN events: {sum(1 for _, d, _, _, _ in packets if d == 'IN')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
