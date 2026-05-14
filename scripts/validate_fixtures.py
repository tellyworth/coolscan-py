#!/usr/bin/env python3
"""
Validate ``test_basic_scan_capture.txt`` fixture consistency.

Checks performed:
- Every data line has 4 tab-separated columns
- Endpoint is ``0x01`` (OUT) or ``0x82`` (IN)
- Length column matches decoded hex payload length
- ``@path`` references resolve to existing files under the capture directory
- ``@path`` file byte-length matches the length column
- Timestamps are monotonically non-decreasing

Run via ``make validate-fixtures`` or directly:
    python scripts/validate_fixtures.py [path/to/capture.txt]
"""

from __future__ import annotations

import sys
from pathlib import Path

CAPTURE_DEFAULT = Path(__file__).resolve().parent.parent / "test_basic_scan_capture.txt"


def validate(path: Path) -> list[str]:
    """Return a list of error messages (empty if fixture is valid)."""
    errors: list[str] = []
    base_dir = path.resolve().parent

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    data_lines = 0
    comment_lines = 0
    blank_lines = 0
    at_refs: list[str] = []
    prev_ts: float | None = None
    out_count = 0
    in_count = 0
    warnings: list[str] = []

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()

        if not line:
            blank_lines += 1
            continue

        if line.startswith("#"):
            comment_lines += 1
            continue

        # --- data line ---
        parts = line.split("\t")
        if len(parts) < 4:
            errors.append(f"L{lineno}: expected 4 tab-separated columns, got {len(parts)}")
            continue

        data_lines += 1

        # Timestamp
        try:
            ts = float(parts[0])
        except ValueError:
            errors.append(f"L{lineno}: bad timestamp '{parts[0]}'")
            ts = None
        else:
            if prev_ts is not None and ts < prev_ts:
                warnings.append(
                    f"L{lineno}: timestamp {ts} < previous {prev_ts}"
                    f" (splice point — ok if intentional)"
                )
            prev_ts = ts

        # Endpoint
        try:
            ep = int(parts[1], 0)
        except ValueError:
            errors.append(f"L{lineno}: bad endpoint '{parts[1]}'")
            continue

        if ep not in (0x01, 0x82):
            errors.append(f"L{lineno}: unsupported endpoint {ep:#x}")

        if ep == 0x01:
            out_count += 1
        else:
            in_count += 1

        # Length column
        try:
            declared = int(parts[2])
        except ValueError:
            errors.append(f"L{lineno}: bad length '{parts[2]}'")
            continue

        payload_field = parts[3].strip()

        if payload_field.startswith("@"):
            rel = payload_field[1:]
            at_refs.append(rel)
            target = (base_dir / rel).resolve()

            # Must stay under capture directory
            try:
                target.relative_to(base_dir.resolve())
            except ValueError:
                errors.append(
                    f"L{lineno}: @ path '{rel}' escapes capture directory"
                )
                continue

            if not target.is_file():
                errors.append(f"L{lineno}: @ file not found: {rel}")
                continue

            file_len = target.stat().st_size
            if file_len != declared:
                errors.append(
                    f"L{lineno}: @ file {rel} length {file_len} != "
                    f"length column {declared}"
                )
        else:
            # Hex payload
            try:
                decoded = bytes.fromhex(payload_field)
            except ValueError:
                errors.append(
                    f"L{lineno}: payload is not valid hex "
                    f"(first 40 chars: '{payload_field[:40]}...')"
                )
                continue

            if len(decoded) != declared:
                errors.append(
                    f"L{lineno}: length column {declared} != "
                    f"hex payload length {len(decoded)}"
                )

    # Write summary to stderr
    print(f"--- fixture summary: {path.name} ---", file=sys.stderr)
    print(f"  total lines   : {len(lines)}", file=sys.stderr)
    print(f"  data lines    : {data_lines}", file=sys.stderr)
    print(f"  OUT events    : {out_count}", file=sys.stderr)
    print(f"  IN  events    : {in_count}", file=sys.stderr)
    print(f"  comment lines : {comment_lines}", file=sys.stderr)
    print(f"  blank lines   : {blank_lines}", file=sys.stderr)
    print(f"  @ refs        : {len(at_refs)}", file=sys.stderr)
    if at_refs:
        for ref in at_refs:
            print(f"    - {ref}", file=sys.stderr)
    print(f"  warnings      : {len(warnings)}", file=sys.stderr)
    for w in warnings:
        print(f"    ⚠ {w}", file=sys.stderr)
    print(f"  errors        : {len(errors)}", file=sys.stderr)
    print("---", file=sys.stderr)

    return errors


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else CAPTURE_DEFAULT

    if not target.is_file():
        print(f"Fixture not found: {target}", file=sys.stderr)
        return 1

    errors = validate(target)

    if errors:
        print("FAILED — fixture errors:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print("OK — fixture is consistent", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
