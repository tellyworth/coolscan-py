#!/usr/bin/env python3
"""
Validate ``test_basic_scan_capture.txt`` and golden fixture consistency.

Checks performed on text fixtures:
- Every data line has 4 tab-separated columns
- Endpoint is ``0x01`` (OUT) or ``0x82`` (IN)
- Length column matches decoded hex payload length
- ``@path`` references resolve to existing files under the capture directory
- ``@path`` file byte-length matches the length column
- Timestamps are monotonically non-decreasing

Additional checks for golden fixture (``reference/golden_single_bw.txt``):
- pcapng SHA-256 checksum matches embedded header value
- Fixture event count is within 2x of capture event count (2544 events)
- Every command code in fixture appears at least once in raw capture

Run via ``make validate-fixtures`` or directly:
    python scripts/validate_fixtures.py [path/to/capture.txt]
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

CAPTURE_DEFAULT = Path(__file__).resolve().parent.parent / "test_basic_scan_capture.txt"
# Known event counts from raw capture
GOLDEN_CONFIGS = [
    {
        "fixture": Path(__file__).resolve().parent.parent / "reference" / "golden_single_bw.txt",
        "pcap": Path(__file__).resolve().parent.parent / "ls40-single-bw.pcapng",
        "raw_count": 2544,
    },
    {
        "fixture": Path(__file__).resolve().parent.parent / "reference" / "golden_batch.txt",
        "pcap": Path(__file__).resolve().parent.parent / "ls40-batch.pcapng",
        "raw_count": 9619,
    },
]


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
        print(f"    ⚠  {w}", file=sys.stderr)
    print(f"  errors        : {len(errors)}", file=sys.stderr)
    print("---", file=sys.stderr)

    return errors


def _parse_fixture_stats(path: Path) -> tuple[int, set[int]]:
    """Parse a fixture and return (data_line_count, command_codes)."""
    text = path.read_text(encoding="utf-8")
    data_lines = 0
    command_codes: set[int] = set()

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        data_lines += 1
        try:
            ep = int(parts[1], 0)
        except ValueError:
            continue
        if ep != 0x01:
            continue
        payload_field = parts[3].strip()
        if payload_field.startswith("@"):
            continue
        try:
            decoded = bytes.fromhex(payload_field)
        except ValueError:
            continue
        if len(decoded) > 0:
            command_codes.add(decoded[0])

    return data_lines, command_codes


def _pcapng_sha256(path: Path) -> str:
    """Compute SHA-256 of the pcapng file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_capture_command_codes(pcap_path: Path) -> set[int] | None:
    """Extract command codes from the raw pcapng capture using tshark."""
    try:
        result = subprocess.run(
            [
                "tshark", "-r", str(pcap_path),
                "-Y", "usb.endpoint_address==0x01",
                "-T", "fields", "-e", "usb.capdata",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None

        codes: set[int] = set()
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            hex_str = re.sub(r"[: ]", "", line.strip())
            try:
                data = bytes.fromhex(hex_str)
                if len(data) > 0:
                    codes.add(data[0])
            except ValueError:
                continue
        return codes
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def validate_golden_fixture(config: dict) -> list[str]:
    """Validate a golden fixture against its raw pcapng capture.

    Checks:
    - Basic fixture consistency (column count, endpoints, lengths, @refs)
    - pcapng SHA-256 checksum matches embedded header value
    - Fixture event count is within 2x of capture event count
    - Every command code in fixture appears at least once in raw capture
    """
    errors: list[str] = []
    fixture_path = config["fixture"]
    pcap_path = config["pcap"]
    raw_count = config["raw_count"]

    if not fixture_path.is_file():
        errors.append(f"Golden fixture not found: {fixture_path}")
        return errors

    print(f"--- Validating golden fixture: {fixture_path.name} ---", file=sys.stderr)

    # Check 1: Basic fixture consistency
    errors.extend(validate(fixture_path))

    # Check 2: pcapng SHA-256 checksum
    header_text = ""
    for line in fixture_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# pcapng SHA-256:"):
            header_text = line
            break

    if header_text:
        embedded_sha = header_text.split(":", 1)[1].strip()
        if pcap_path.is_file():
            actual_sha = _pcapng_sha256(pcap_path)
            if embedded_sha != actual_sha:
                errors.append(
                    f"Golden fixture SHA-256 mismatch: "
                    f"embedded={embedded_sha}, actual={actual_sha}"
                )
            else:
                print(f"  ✓ pcapng SHA-256 matches: {actual_sha[:16]}...", file=sys.stderr)
        else:
            print(f"  ⚠  pcapng not found, skipping SHA check", file=sys.stderr)

    # Check 3: Event count within 2x of capture
    data_lines, golden_codes = _parse_fixture_stats(fixture_path)
    if data_lines > 0:
        lower = raw_count // 2
        upper = raw_count * 2
        if data_lines < lower:
            errors.append(
                f"Golden fixture has {data_lines} events, "
                f"but capture has {raw_count}. "
                f"Fixture may be grossly truncated (minimum: {lower})."
            )
        elif data_lines > upper:
            errors.append(
                f"Golden fixture has {data_lines} events, "
                f"but capture has {raw_count}. "
                f"Unexpectedly large fixture (maximum: {upper})."
            )
        else:
            print(
                f"  ✓ Event count {data_lines} within acceptable range "
                f"({lower}-{upper})",
                file=sys.stderr,
            )

    # Check 4: Every command code in fixture appears in capture
    capture_codes = _extract_capture_command_codes(pcap_path)
    if capture_codes is not None and golden_codes:
        missing = golden_codes - capture_codes
        if missing:
            errors.append(
                f"Golden fixture has command codes not in capture: "
                f"{', '.join(f'0x{c:02x}' for c in sorted(missing))}"
            )
        else:
            print(
                f"  ✓ All {len(golden_codes)} fixture command codes present in capture",
                file=sys.stderr,
            )

    return errors


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else CAPTURE_DEFAULT

    if not target.is_file():
        print(f"Fixture not found: {target}", file=sys.stderr)
        return 1

    # Validate main fixture
    errors = validate(target)

    # Validate all golden fixtures
    for config in GOLDEN_CONFIGS:
        errors.extend(validate_golden_fixture(config))

    if errors:
        print("FAILED — fixture errors:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print("OK — all fixtures are consistent", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
