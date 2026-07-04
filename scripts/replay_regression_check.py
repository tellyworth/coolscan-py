#!/usr/bin/env python3
"""Ad-hoc replay regression check against golden fixture.

Run when hardware is unavailable to catch wire-format drift.
Validates fixture structure, command coverage, and basic replay
consistency without requiring the exact scan sequence.

Usage: python3 scripts/replay_regression_check.py
"""

import sys
from pathlib import Path


def main():
    fixture = Path("tests/fixtures/golden_single_bw.txt")
    if not fixture.exists():
        print(f"SKIP: {fixture} not found")
        return 0

    from coolscan.usb_replay import UsbCaptureReplay, _parse_capture_lines

    text = fixture.read_text(encoding="utf-8")
    lines = text.splitlines()
    events = _parse_capture_lines(
        lines, base_dir=fixture.parent.resolve()
    )

    replay = UsbCaptureReplay(events=events)
    total = replay.total

    errors = []

    def check(name, condition, msg=""):
        if not condition:
            errors.append(f"FAIL: {name} -- {msg}")
            print(f"  FAIL: {name} -- {msg}")
        else:
            print(f"  OK:   {name}")

    # Basic event count check
    check("event_count", 1400 <= total <= 1600,
          f"expected 1400-1600 events, got {total}")

    # Collect OUT command codes
    out_cmds = []
    for kind, data in events:
        if kind == "out" and len(data) >= 1:
            out_cmds.append(data[0])

    # Check for expected command codes from the golden fixture
    expected_cmds = {
        0x00: "TEST_UNIT_READY",
        0x12: "INQUIRY",
        0x15: "MODE_SELECT",
        0x16: "RESERVE_UNIT",
        0x1b: "START_SCAN/STOP_SCAN",
        0x24: "SET_WINDOW",
        0x25: "READ_CAPACITY",
        0x28: "READ(10)",
        0x2a: "SEND_LUT",
        0xc1: "EXECUTE",
        0xe0: "WRITE_FOCUS",
        0xe1: "READ_FOCUS/READ_FOCUS_INFO",
    }

    for code, name in expected_cmds.items():
        found = code in out_cmds
        check(f"cmd_{name}", found, f"0x{code:02x} not found in OUT commands")

    # Verify direction alternation (OUT/IN pairs)
    direction_changes = 0
    for i in range(1, len(events)):
        if events[i][0] != events[i - 1][0]:
            direction_changes += 1
    check("direction_alternation", direction_changes > total * 0.4,
          f"only {direction_changes} direction changes in {total} events")

    # Verify IN events exist (responses)
    in_count = sum(1 for kind, _ in events if kind == "in")
    check("in_events_present", in_count > 0,
          f"no IN events found (expected ~{total // 2})")

    if errors:
        print(f"\n{len(errors)} failure(s) detected")
        return 1

    print(f"\nReplay check: OK ({total} events, {len(out_cmds)} OUT commands)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
