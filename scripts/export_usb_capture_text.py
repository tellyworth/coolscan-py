#!/usr/bin/env python3
"""
Export USB bulk transfers from a .pcapng into ``test_basic_scan_capture.txt`` column format.

Requires ``tshark`` on PATH. Uses :func:`parse_pcapng.extract_usb_traffic`.

Example::

    ./scripts/export_usb_capture_text.py ls40-single-bw.pcapng -o new_capture.txt
    ./scripts/export_usb_capture_text.py ls40-single-bw.pcapng --frame-min 500 --frame-max 2000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from parse_pcapng import extract_usb_traffic  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pcapng", type=Path, help="Input .pcapng path")
    ap.add_argument("-o", "--output", type=Path, help="Output text path (default: stdout)")
    ap.add_argument("--frame-min", type=int, default=None)
    ap.add_argument("--frame-max", type=int, default=None)
    args = ap.parse_args()

    packets = extract_usb_traffic(str(args.pcapng))
    if not packets:
        print("No packets extracted (missing tshark or empty filter).", file=sys.stderr)
        return 1

    lines_out: list[str] = []
    t = 0.0
    for frame_num, direction, endpoint, data in packets:
        if args.frame_min is not None and frame_num < args.frame_min:
            continue
        if args.frame_max is not None and frame_num > args.frame_max:
            continue
        if not data:
            continue
        t += 0.0001
        ep_hex = f"0x{endpoint & 0xFF:02x}"
        hx = data.hex()
        lines_out.append(f"{t:.9f}\t{ep_hex}\t{len(data)}\t{hx}")

    text = "\n".join(lines_out) + ("\n" if lines_out else "")
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
