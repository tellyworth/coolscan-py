#!/usr/bin/env python3
"""
Rebuild ``tests/fixtures/scan_image_block*.bin`` from ``ls40-single-bw.pcapng``.

Full-scan image READ(10) commands use 258048, 223488, 259200, or 103680 byte
allocations.  Each logical READ is split across multiple 65508-byte IN URBs
on the wire.  This script concatenates the wire-order IN payloads per
logical READ, then writes one binary blob per unique allocation size so
the replay fixture can reference a representative block.

Requires: ``ls40-single-bw.pcapng`` at the repo root, ``tshark`` on PATH.

Example::

    ./scripts/refresh_scan_image_fixtures.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from parse_pcapng import extract_usb_traffic  # noqa: E402

BULK_IN = 0x82
READ_258048 = bytes.fromhex("28000000000003f00080")
READ_223488 = bytes.fromhex("28000000000003690080")
READ_259200 = bytes.fromhex("28000000000003f48080")
READ_103680 = bytes.fromhex("28000000000001950080")

# Allocation sizes in order of appearance in capture
FULL_SCAN_ALLOCS = [258048, 223488, 259200, 103680]
FULL_SCAN_CDBS = [READ_258048, READ_223488, READ_259200, READ_103680]


def find_full_scan_read_range(packets: list) -> tuple:
    """Find the packet indices bounding the full-scan image data section."""
    full_scan_cdb_set = set(FULL_SCAN_CDBS)

    start_idx = None
    for idx, (_fn, d, ep, data) in enumerate(packets):
        if d == "OUT" and (ep & 0xFF) == 0x01 and data in full_scan_cdb_set:
            start_idx = idx
            break

    if start_idx is None:
        return None, None

    last_read_idx = start_idx
    for idx, (_fn, d, ep, data) in enumerate(packets):
        if d == "OUT" and (ep & 0xFF) == 0x01 and data in full_scan_cdb_set:
            last_read_idx = idx

    end_idx = last_read_idx + 1
    large_in_count = 0
    while end_idx < len(packets):
        _fn, d, ep, payload = packets[end_idx]
        if d == "IN" and (ep & 0xFF) == BULK_IN and len(payload) > 8:
            large_in_count += 1
        end_idx += 1
        if large_in_count >= 2:
            break

    return start_idx, end_idx


def extract_full_scan_image_blocks(packets: list) -> dict:
    """Extract one representative image block per unique allocation size.

    Collects all bulk IN payloads between the first and last full-scan READ,
    then slices into blocks matching each allocation size.
    """
    start_idx, end_idx = find_full_scan_read_range(packets)
    if start_idx is None:
        return {}

    stream = bytearray()
    for pkt in packets[start_idx:end_idx]:
        _fn, d, ep, payload = pkt
        if d != "IN" or (ep & 0xFF) != BULK_IN:
            continue
        if len(payload) in (1, 8):
            continue
        stream.extend(payload)

    blocks: dict[int, bytes] = {}
    offset = 0
    for alloc in FULL_SCAN_ALLOCS:
        if offset + alloc <= len(stream):
            blocks[alloc] = bytes(stream[offset:offset + alloc])
            print(f"  Extracted {alloc} bytes from stream offset {offset}")
            offset += alloc
        else:
            print(f"  Warning: stream too short for {alloc}-byte block")

    return blocks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--pcap",
        type=Path,
        default=_REPO / "ls40-single-bw.pcapng",
        help="Input pcapng",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO / "tests" / "fixtures",
        help="Output directory",
    )
    args = ap.parse_args()

    if not args.pcap.is_file():
        print(f"Missing pcap: {args.pcap}", file=sys.stderr)
        return 1

    packets = extract_usb_traffic(str(args.pcap))
    if not packets:
        print("No USB bulk rows (tshark missing or empty).", file=sys.stderr)
        return 1

    blocks = extract_full_scan_image_blocks(packets)
    if not blocks:
        print("No full-scan image blocks found.", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for idx, alloc in enumerate(FULL_SCAN_ALLOCS, start=1):
        if alloc in blocks:
            fname = f"scan_image_block{idx}.bin"
            path = args.out_dir / fname
            path.write_bytes(blocks[alloc])
            total += len(blocks[alloc])
            print(f"Wrote {path.name}: {len(blocks[alloc])} bytes")

    print(f"Total: {total} bytes under {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
