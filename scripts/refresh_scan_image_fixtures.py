#!/usr/bin/env python3
"""
Rebuild ``tests/fixtures/scan_image_block{1,2,3,4}.bin`` from ``ls40-single-bw.pcapng``.

The full-scan image READs start at frame ~2399.  Each logical READ(10) CDB issue
returns a single **65508**-byte bulk IN URB (the scanner's max packet size).
The CDB allocation length (258048, 223488, etc.) is the *requested* size, but
the scanner streams data in 65508-byte chunks, with the host re-issuing the
same CDB for each chunk.

This script extracts the first 4 image IN transfers from the first stripe
(frames 2399-2438), producing one ``.bin`` file per 65508-byte IN.

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
BULK_OUT = 0x01


def _is_image_read_cdb(data: bytes) -> bool:
    """Check if data is a 10-byte image READ(10) CDB (datatype 0x00)."""
    return (
        len(data) == 10
        and data[0] == 0x28
        and data[1] == 0x00
        and data[2] == 0x00
    )


def extract_first_stripe_ins(packets: list) -> list[bytes]:
    """Extract the first 4 image IN transfers from the full-scan first stripe.

    The first stripe (frames 2399-2438) has 4 READ CDBs, each producing one
    65508-byte IN transfer.  We collect those 4 INs and return them as a list.
    """
    # Find the first full-scan image READ CDB
    start = None
    for i, (_fn, d, ep, data) in enumerate(packets):
        if d == "OUT" and (ep & 0xFF) == BULK_OUT and _is_image_read_cdb(data):
            # Full-scan reads have large allocation lengths (>200KB)
            alloc = int.from_bytes(data[6:9], "big")
            if alloc >= 200_000:
                start = i
                break

    if start is None:
        raise ValueError("No full-scan image READ(10) found in capture.")

    ins: list[bytes] = []
    idx = start + 1

    while idx < len(packets) and len(ins) < 4:
        _fn, d, ep, data = packets[idx]

        if d == "IN" and (ep & 0xFF) == BULK_IN and len(data) > 8:
            # Large IN transfer — this is image data
            ins.append(bytes(data))
        elif d == "OUT" and (ep & 0xFF) == BULK_OUT:
            # Non-phase OUT after we've seen some INs — might be end of stripe
            if len(data) != 1 or data != b"\xd0":
                if _is_image_read_cdb(data):
                    # Different CDB (e.g., 223488-alloc tail read) — still collect
                    pass
                else:
                    # Non-image command (TUR, SET_WINDOW, etc.) — end of stripe
                    break

        idx += 1

    if len(ins) < 4:
        raise ValueError(f"Expected 4 IN transfers, got {len(ins)}.")

    return ins


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

    ins = extract_first_stripe_ins(packets)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for i, chunk in enumerate(ins, start=1):
        path = args.out_dir / f"scan_image_block{i}.bin"
        path.write_bytes(chunk)
        total += len(chunk)
        print(f"  block{i}: {len(chunk)} bytes -> {path.name}")

    print(f"Wrote {len(ins)} blocks, {total} total bytes under {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
