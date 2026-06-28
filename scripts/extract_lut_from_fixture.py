#!/usr/bin/env python3
"""
Extract LUT payloads from pcapng captures or golden fixture.

Usage:
    # From golden fixture (using pre-extracted .bin files):
    python3 scripts/extract_lut_from_fixture.py

    # From pcapng (requires tshark):
    python3 scripts/extract_lut_from_fixture.py --pcapng ls40-single-bw.pcapng

Outputs:
    - Summary of LUT structure and values
    - ASCII plots of LUT curves
    - Per-channel JSON data to stdout
"""

import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
FIXTURE_DIR = _REPO / "tests" / "fixtures"


def _hex_to_bytes(hex_str: str) -> bytes:
    """Convert hex string (with optional spaces/colons) to bytes."""
    return bytes.fromhex(hex_str.replace(":", "").replace(" ", ""))


def _parse_fixture_bin_files() -> dict:
    """Read pre-extracted LUT binary files from the golden fixture directory.

    Returns dict mapping channel to list of (upload_index, bytes) tuples.
    """
    lut_files = {
        # First LUT upload batch (after prescan WDBs, before prescan START)
        9: "golden_data_0457.bin",  # IR (not present in single-bw; IR is channel 9)
        1: "golden_data_0739.bin",  # R
        2: "golden_data_0749.bin",  # G
        3: "golden_data_0759.bin",  # B
        # Second LUT upload batch (after full scan WDBs, before full scan START)
        # These are separate files for each channel
    }

    # Map fixture binary files by checking which ones are 8192 bytes (LUT size)
    lut_size = 8192  # 2 * 2^12 bytes
    channels = {}

    # Known LUT file patterns from golden_single_bw.txt:
    # First batch (lines 282-296): IR not present, R/G/B only
    # golden_data_0739.bin -> R (channel 1), golden_data_0749.bin -> G (channel 2), golden_data_0759.bin -> B (channel 3)
    # Second batch (lines 503-522): IR + R/G/B
    # golden_data_2221.bin -> IR (channel 9), golden_data_2231.bin -> R, golden_data_2241.bin -> G, golden_data_2251.bin -> B
    # Third batch (lines 626-636): R/G/B only
    # golden_data_10347.bin -> R, golden_data_10357.bin -> G, golden_data_10367.bin -> B
    # Fourth batch (lines 688-698): R/G/B only
    # golden_data_10625.bin -> R, golden_data_10635.bin -> G, golden_data_10645.bin -> B

    lut_file_map = [
        (1, "golden_data_0739.bin"),   # First batch R
        (2, "golden_data_0749.bin"),   # First batch G
        (3, "golden_data_0759.bin"),   # First batch B
        (9, "golden_data_2221.bin"),   # Second batch IR
        (1, "golden_data_2231.bin"),   # Second batch R
        (2, "golden_data_2241.bin"),   # Second batch G
        (3, "golden_data_2251.bin"),   # Second batch B
        (1, "golden_data_10347.bin"),  # Third batch R
        (2, "golden_data_10357.bin"),  # Third batch G
        (3, "golden_data_10367.bin"),  # Third batch B
        (1, "golden_data_10625.bin"),  # Fourth batch R
        (2, "golden_data_10635.bin"),  # Fourth batch G
        (3, "golden_data_10645.bin"),  # Fourth batch B
    ]

    for channel, filename in lut_file_map:
        filepath = FIXTURE_DIR / filename
        if filepath.exists() and filepath.stat().st_size == lut_size:
            with open(filepath, "rb") as f:
                data = f.read()
            if channel not in channels:
                channels[channel] = []
            channels[channel].append(data)

    return channels


def _parse_lut_bytes(data: bytes) -> list:
    """Parse LUT bytes into list of 16-bit big-endian values.

    Each entry is 2 bytes (16-bit), big-endian.
    For a 12-bit LUT: 4096 entries, values 0-4095.
    """
    if len(data) % 2 != 0:
        raise ValueError(f"LUT data length {len(data)} is not even")
    entries = []
    for i in range(0, len(data), 2):
        val = (data[i] << 8) | data[i + 1]
        entries.append(val)
    return entries


def _is_identity_lut(entries: list) -> bool:
    """Check if LUT is an identity mapping (output == input)."""
    return all(entries[i] == i for i in range(len(entries)))


def _ascii_plot(entries: list, width: int = 80, height: int = 24, title: str = "") -> str:
    """Generate an ASCII plot of the LUT curve.

    Args:
        entries: List of output values (one per input index).
        width: Plot width in characters.
        height: Plot height in lines.
        title: Optional title line.

    Returns:
        Multi-line string with ASCII plot.
    """
    n = len(entries)
    max_val = max(entries) if entries else 0
    min_val = min(entries) if entries else 0

    if not entries:
        return "  (empty LUT)"

    # Scale to plot dimensions
    plot_h = height - 2  # Leave room for axis labels
    plot_w = width - 10  # Leave room for Y axis labels

    lines = []
    if title:
        lines.append(f"  {title}")
        lines.append(f"  Input range: 0..{n-1}, Output range: {min_val}..{max_val}")
        lines.append("")

    # Build grid
    grid = [[" "] * plot_w for _ in range(plot_h)]

    # Plot points
    for i, val in enumerate(entries):
        x = int(i / n * plot_w)
        if max_val == min_val:
            y = plot_h // 2
        else:
            y = plot_h - 1 - int((val - min_val) / (max_val - min_val) * (plot_h - 1))
        if 0 <= y < plot_h and 0 <= x < plot_w:
            grid[y][x] = "*"

    # Add axis labels and plot
    lines.append("  max |")
    for j, row in enumerate(grid):
        label = f"{max_val - j * (max_val - min_val) // plot_h:>5} |"
        lines.append(f"{label}{''.join(row)}|")
    lines.append(f"  min |{'_' * plot_w}|")
    lines.append(f"        {'0':<{plot_w // 2}}{'mid':<{plot_w // 2 - 3}}{n - 1:>4}")
    lines.append(f"        Input index (0 to {n - 1})")

    return "\n".join(lines)


def _summarize_lut(entries: list, channel: int, index: int) -> dict:
    """Generate summary statistics for a LUT."""
    n = len(entries)
    return {
        "channel": channel,
        "upload_index": index,
        "entries": n,
        "min_val": min(entries),
        "max_val": max(entries),
        "is_identity": _is_identity_lut(entries),
        "first_16": entries[:16],
        "last_16": entries[-16:],
        "mean": sum(entries) / n if n else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Extract and analyze LUT data from Coolscan captures")
    parser.add_argument("--pcapng", type=str, help="Path to pcapng file (uses tshark)")
    parser.add_argument("--fixture", action="store_true", help="Use golden fixture data (default)")
    parser.add_argument("--plot", action="store_true", help="Generate ASCII plots")
    parser.add_argument("--json", action="store_true", help="Output JSON summary")
    args = parser.parse_args()

    if args.pcapng:
        print("PCAPNG extraction requires tshark and additional parsing logic.", file=sys.stderr)
        print("Using fixture data instead.", file=sys.stderr)

    channels = _parse_fixture_bin_files()

    if not channels:
        print("ERROR: No LUT data files found in fixture directory.", file=sys.stderr)
        sys.exit(1)

    summaries = []
    for channel in sorted(channels.keys()):
        for idx, data in enumerate(channels[channel]):
            entries = _parse_lut_bytes(data)
            ch_names = {1: "Red", 2: "Green", 3: "Blue", 9: "IR"}
            name = ch_names.get(channel, f"Ch{channel}")
            summary = _summarize_lut(entries, name, idx)
            summaries.append(summary)

            if args.plot:
                title = f"{name} Channel (upload #{idx})"
                print(_ascii_plot(entries, title=title))
                print()

            if args.json:
                print(json.dumps(summary, indent=2))
            else:
                is_id = "IDENTITY" if summary["is_identity"] else "MODIFIED"
                print(f"  {name} (upload #{idx}): {summary['entries']} entries, "
                      f"range [{summary['min_val']}, {summary['max_val']}], "
                      f"mean={summary['mean']:.1f} -- {is_id}")

    # Exposure calibration data (inline in golden fixture, line 216)
    fixture_path = FIXTURE_DIR / "golden_single_bw.txt"
    if fixture_path.exists():
        with open(fixture_path) as f:
            fixture_lines = f.readlines()
        # Line 216 (0-indexed: 215) contains the 3392-byte exposure calibration response
        if len(fixture_lines) > 215:
            parts = fixture_lines[215].split('\t')
            if len(parts) >= 4:
                exp_hex = parts[3].strip()
                exp_data = bytes.fromhex(exp_hex)
                header = exp_data[:6]
                cal_value = struct.unpack(">I", exp_data[6:10])[0]
                print(f"\n  Exposure calibration (READ 0x8e response, line 216):")
                print(f"    Header: {header.hex()} (datatype=0x{header[0]:02x}{header[1]:02x}, length={struct.unpack('>I', header[2:6])[0]})")
                print(f"    Calibration value at offset 6: 0x{cal_value:08x} = {cal_value} (10ns units) = {cal_value*10/1e6:.3f} ms")
                print(f"    Total response: {len(exp_data)} bytes")

    # WDB exposure values from the capture
    wdb_exposures = {
        "prescan_R": 0x0000a381,
        "prescan_G": 0x00008452,
        "prescan_B": 0x00004e29,
        "fullscan_IR": 0x0001c305,
        "fullscan_R": 0x0000ea05,
        "fullscan_G": 0x0000b4ed,
        "fullscan_B": 0x000073bc,
    }
    print("\n  WDB Exposure Values (10ns units):")
    for label, val in wdb_exposures.items():
        us = val * 10 / 1000  # Convert 10ns units to microseconds
        ms = us / 1000
        print(f"    {label:15s}: 0x{val:08x} = {val:>6d} * 10ns = {ms:.3f} ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())
