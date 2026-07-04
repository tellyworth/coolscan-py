#!/usr/bin/env python3
"""
Rebuild ``reference/prescan_image_block{1,2,3}.bin`` from ``ls40-single-bw.pcapng``.

``parse_pcapng.extract_usb_traffic`` / ``tshark`` record prescan image bytes as several
large IN URBs (typically **65508** bytes) plus a final **11520**-byte IN, with 1-byte
phase and 8-byte status rows between host phases. ``CoolscanProtocol.read_prescan_image_data``
still performs three logical reads (**130752 + 130752 + 11520**). This script concatenates
every bulk IN payload (excluding 1- and 8-byte rows) from the first prescan image
``READ(10)`` OUT through the **11520**-byte IN, then slices that byte string in order.

Requires: ``ls40-single-bw.pcapng`` at the repo root (gitignored but present locally),
``tshark`` on PATH.

Example::

    ./scripts/refresh_prescan_image_fixtures.py
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
READ_130752 = bytes.fromhex("28000000000001fec080")


def image_bulk_stream_after_first_read(packets: list) -> bytes:
    start = None
    for i, (_fn, d, ep, data) in enumerate(packets):
        if d == "OUT" and (ep & 0xFF) == 0x01 and data == READ_130752:
            start = i
            break
    if start is None:
        raise ValueError("No OUT matching 28000000000001fec080 (first prescan image READ).")

    buf = bytearray()
    for _fn, d, ep, data in packets[start + 1 :]:
        if d != "IN" or (ep & 0xFF) != BULK_IN:
            continue
        if len(data) in (1, 8):
            continue
        buf.extend(data)
        if len(data) == 11520:
            break
    return bytes(buf)


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

    blob = image_bulk_stream_after_first_read(packets)
    need = 130_752 + 130_752 + 11_520
    if len(blob) < need:
        print(
            f"Expected at least {need} concatenated image bytes, got {len(blob)}.",
            file=sys.stderr,
        )
        return 1

    b1, b2, b3 = blob[:130_752], blob[130_752 : 261_504], blob[261_504 : need]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "prescan_image_block1.bin").write_bytes(b1)
    (args.out_dir / "prescan_image_block2.bin").write_bytes(b2)
    (args.out_dir / "prescan_image_block3.bin").write_bytes(b3)
    total = len(b1) + len(b2) + len(b3)
    print(f"Wrote {len(b1)} + {len(b2)} + {len(b3)} = {total} bytes under {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
