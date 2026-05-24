#!/usr/bin/env python3
"""
Audit READ(10) image transfers (datatype 0x00) in ``ls40-single-bw.pcapng``.

``extract_usb_traffic`` yields one row per captured bulk URB. The Nikon host
often reissues the **same** 10-byte READ(10) CDB several times while data
arrives as multiple large IN transfers. This script collapses consecutive
identical image READ commands and sums the intervening bulk IN payloads that
are not 1-byte phase or 8-byte status rows, then compares the sum to the CDB
allocation length (bytes 6–8, big-endian).

Run before extending full-scan replay fixtures. Mismatches mean the capture does
not match a single ``read_scan_data(length)`` read, or merging rules need work.

Example::

    ./scripts/audit_capture_read_batches.py
    ./scripts/audit_capture_read_batches.py --min-alloc 200000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterator, List, Tuple

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from parse_pcapng import extract_usb_traffic  # noqa: E402

BULK_IN = 0x82


def iter_image_read_batches(
    pkts: list,
) -> Iterator[Tuple[int, bytes, int, List[int]]]:
    """Yield (first_frame_num, cdb10, allocation, list of bulk IN lengths).

    A **batch** starts at each OUT with a 10-byte image READ(10). It ends when the
    capture shows an OUT that is neither the phase ping ``d0`` nor a repeat of
    that same 10-byte READ. That approximates one host ``read(length)`` attempt
    spanning only the URBs framed by that SCSI command issue.
    """
    i = 0
    n = len(pkts)
    while i < n:
        fn, d, ep, data = pkts[i]
        if not (
            d == "OUT"
            and (ep & 0xFF) == 0x01
            and len(data) == 10
            and data[0] == 0x28
            and data[2] == 0x00
        ):
            i += 1
            continue

        start_fn = fn
        cmd = data
        alloc = int.from_bytes(cmd[6:9], "big")
        lengths: List[int] = []
        i += 1
        while i < n:
            d2, ep2, data2 = pkts[i][1], pkts[i][2], pkts[i][3]
            if d2 == "OUT" and (ep2 & 0xFF) == 0x01:
                if len(data2) == 1 and data2 == b"\xd0":
                    pass
                elif len(data2) == 10 and data2[0] == 0x28 and data2[2] == 0x00:
                    break
                else:
                    break
            elif d2 == "IN" and (ep2 & 0xFF) == BULK_IN and len(data2) not in (1, 8):
                lengths.append(len(data2))
            i += 1
        yield start_fn, cmd, alloc, lengths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--pcap",
        type=Path,
        default=_REPO / "ls40-single-bw.pcapng",
        help="Input pcapng",
    )
    ap.add_argument(
        "--min-alloc",
        type=int,
        default=0,
        help="Only print rows with CDB allocation length >= this value.",
    )
    args = ap.parse_args()

    if not args.pcap.is_file():
        print(f"Missing {args.pcap}", file=sys.stderr)
        return 1

    pkts = extract_usb_traffic(str(args.pcap))
    if not pkts:
        print("No packets (tshark missing?)", file=sys.stderr)
        return 1

    print(f"{'frame':>6}  {'alloc':>7}  {'sum_in':>7}  {'ok':^4}  chunk_count  lengths (head)")
    for frame, cmd, alloc, lengths in iter_image_read_batches(pkts):
        if alloc < args.min_alloc:
            continue
        s = sum(lengths)
        ok = "yes" if s == alloc else "no"
        head = str(lengths[:8])
        more = "…" if len(lengths) > 8 else ""
        print(f"{frame:6d}  {alloc:7d}  {s:7d}  {ok:^4}  {len(lengths):11d}  {head}{more}")
        if ok == "no":
            print(f"         CDB {cmd.hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
