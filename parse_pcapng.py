#!/usr/bin/env python3
"""
Parse pcapng file to extract USB commands and responses for Nikon Coolscan.

Uses tshark to extract USB bulk transfer data from the capture.
"""

import subprocess
import sys
import re
from typing import List, Tuple, Optional
from collections import defaultdict


def extract_usb_traffic(pcapng_file: str) -> List[Tuple[int, str, int, bytes]]:
    """
    Extract USB traffic from pcapng file using tshark.

    Returns list of (frame_num, direction, endpoint, data) tuples where:
    - frame_num: Frame number in capture
    - direction: "OUT" (host->device) or "IN" (device->host)
    - endpoint: Endpoint number
    - data: Bytes sent/received
    """
    packets = []

    # Use tshark to extract USB bulk transfer data
    # Format: frame.number, usb.endpoint_address, usb.dst, usb.capdata
    cmd = [
        'tshark',
        '-r', pcapng_file,
        '-Y', 'usb',  # All USB traffic
        '-T', 'fields',
        '-e', 'frame.number',
        '-e', 'usb.endpoint_address',
        '-e', 'usb.dst',
        '-e', 'usb.capdata'
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        lines = result.stdout.strip().split('\n')

        for line in lines:
            if not line.strip():
                continue

            parts = line.split('\t')
            if len(parts) < 3:
                continue

            frame_num = int(parts[0])
            endpoint_str = parts[1] if len(parts) > 1 else ""
            dst = parts[2] if len(parts) > 2 else ""
            capdata = parts[3] if len(parts) > 3 else ""

            # Parse endpoint address (format: 0x80, 0x01, etc.)
            try:
                if endpoint_str.startswith('0x'):
                    endpoint = int(endpoint_str, 16)
                else:
                    endpoint = 0
            except (ValueError, AttributeError):
                endpoint = 0

            # Determine direction
            # "host" means device->host (IN), device address means host->device (OUT)
            if dst == "host":
                direction = "IN"
            elif dst and dst != "":
                direction = "OUT"
            else:
                continue

            # Parse hex data
            if capdata and capdata.strip():
                # Remove colons and spaces, convert to bytes
                hex_str = re.sub(r'[: ]', '', capdata)
                try:
                    data = bytes.fromhex(hex_str)
                    if len(data) > 0:  # Only add non-empty packets
                        packets.append((frame_num, direction, endpoint, data))
                except ValueError:
                    # Skip invalid hex
                    continue

    except subprocess.TimeoutExpired:
        print("⚠️  tshark timed out - file may be very large")
        print("   Using partial results...")
    except subprocess.CalledProcessError as e:
        print(f"Error running tshark: {e}")
        print(f"stderr: {e.stderr}")
        return []
    except Exception as e:
        print(f"Error parsing tshark output: {e}")
        return []

    return packets


def analyze_sequence(packets: List[Tuple[int, str, int, bytes]]) -> None:
    """Analyze the packet sequence to identify command patterns."""
    print("=" * 80)
    print("USB Traffic Analysis - Nikon Coolscan LS-40")
    print("=" * 80)
    print()

    # Group by sequence phases
    out_commands = []
    in_responses = []

    for frame_num, direction, endpoint, data in packets:
        if direction == "OUT":
            out_commands.append((frame_num, data))
            print(f"📤 Frame {frame_num:5d} OUT (ep {endpoint}) [{len(data):3d} bytes]: {data.hex()}")
            if len(data) > 0:
                cmd_code = data[0]
                print(f"      Command: 0x{cmd_code:02x} ({cmd_code})", end="")

                # Identify command
                cmd_names = {
                    0x00: "TEST_UNIT_READY",
                    0x12: "INQUIRY",
                    0x15: "MODE_SELECT",
                    0x16: "RESERVE_UNIT",
                    0x17: "RELEASE_UNIT",
                    0x1a: "MODE_SENSE",
                    0x1b: "START_STOP_UNIT",
                    0x1c: "RECEIVE_DIAGNOSTIC",
                    0x1d: "SEND_DIAGNOSTIC",
                    0x24: "READ",
                    0x25: "READ_CAPACITY",
                    0x28: "READ(10)",
                    0x2a: "WRITE(10)",
                    0xd0: "PHASE_CHECK",
                    0xe0: "VENDOR_CMD(0xe0)",
                    0xc1: "VENDOR_CMD(0xc1)",
                }

                if cmd_code in cmd_names:
                    print(f" → {cmd_names[cmd_code]}")
                else:
                    print()

                # Show first few bytes
                if len(data) <= 16:
                    print(f"      Full: {data.hex()}")
                else:
                    print(f"      First 16: {data[:16].hex()}...")

        elif direction == "IN":
            in_responses.append((frame_num, data))
            print(f"📥 Frame {frame_num:5d} IN  (ep {endpoint}) [{len(data):3d} bytes]: {data.hex()[:64]}...")
            if len(data) >= 8:
                status_byte = data[0]
                sense_key = data[1] & 0x0f
                asc = data[2]
                ascq = data[3]
                print(f"      Status: 0x{status_byte:02x}, Sense: 0x{sense_key:02x}, ASC: 0x{asc:02x}, ASCQ: 0x{ascq:02x}")

        print()

    print("=" * 80)
    print("Command Sequence Summary")
    print("=" * 80)
    print()

    # Identify initialization sequence
    print("Initialization Sequence:")
    init_commands = []
    for i, (frame_num, data) in enumerate(out_commands[:20]):  # First 20 commands
        if len(data) > 0:
            cmd_code = data[0]
            init_commands.append((frame_num, cmd_code, data))
            print(f"  {i+1:2d}. Frame {frame_num:5d}: 0x{cmd_code:02x} - {data.hex()}")

    print()
    print("=" * 80)
    print("Key Findings")
    print("=" * 80)
    print()

    # Find unique command patterns
    unique_commands = defaultdict(list)
    for frame_num, data in out_commands:
        if len(data) > 0:
            cmd_code = data[0]
            unique_commands[cmd_code].append((frame_num, data))

    print(f"Total OUT commands: {len(out_commands)}")
    print(f"Total IN responses: {len(in_responses)}")
    print(f"Unique command codes: {len(unique_commands)}")
    print()

    print("Command frequency:")
    for cmd_code in sorted(unique_commands.keys()):
        count = len(unique_commands[cmd_code])
        print(f"  0x{cmd_code:02x}: {count:3d} times")

    return init_commands, out_commands, in_responses


def extract_initialization_sequence(packets: List[Tuple[int, str, int, bytes]]) -> List[bytes]:
    """Extract the exact initialization sequence from startup."""
    # Look for the first N commands (startup sequence)
    init_commands = []

    for frame_num, direction, endpoint, data in packets:
        if direction == "OUT" and len(data) > 0:
            init_commands.append(data)
            # Take first 30 commands as initialization
            if len(init_commands) >= 30:
                break

    return init_commands


def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_pcapng.py <pcapng_file>")
        sys.exit(1)

    pcapng_file = sys.argv[1]

    print(f"Parsing: {pcapng_file}")
    print()

    packets = extract_usb_traffic(pcapng_file)

    if not packets:
        print("❌ No USB packets found. Make sure tshark is installed and the file is valid.")
        sys.exit(1)

    print(f"Found {len(packets)} USB bulk transfer packets")
    print()

    init_commands, all_out, all_in = analyze_sequence(packets)

    # Extract initialization sequence
    print("=" * 80)
    print("Exact Initialization Sequence (First 30 Commands)")
    print("=" * 80)
    print()

    init_seq = extract_initialization_sequence(packets)
    for i, cmd in enumerate(init_seq, 1):
        print(f"{i:2d}. {cmd.hex()}")
        if len(cmd) > 0:
            print(f"    → 0x{cmd[0]:02x} ({len(cmd)} bytes)")

    # Save to file for easy reference
    with open('extracted_init_sequence.txt', 'w') as f:
        f.write("# Nikon Coolscan LS-40 Initialization Sequence\n")
        f.write("# Extracted from USB capture\n\n")
        for i, cmd in enumerate(init_seq, 1):
            f.write(f"{cmd.hex()}\n")

    print()
    print(f"✅ Initialization sequence saved to: extracted_init_sequence.txt")


if __name__ == "__main__":
    main()
