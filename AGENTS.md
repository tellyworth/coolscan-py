# AGENTS.md

## Trust Hierarchy (READ THIS FIRST)

- **pcapng captures are the ground truth** -- `ls40-single-bw.pcapng` (primary oracle) and `ls40-batch.pcapng` (secondary) are the only trusted source for wire-format protocol behavior
- **Golden fixture** (`reference/golden_single_bw.txt`, 1472 events) is auto-derived from pcapng via `scripts/generate_fixture_from_pcapng.py`; trusted only when verified by `make validate-fixtures` (SHA-256 cross-check, event count bounds, command code coverage)
- **SANE backend source** (`backends-1.4.0/backend/coolscan3.c`) is known buggy and incomplete; use only for intent, naming, and edge-case discovery -- wire format ALWAYS defers to pcapng when SANE and capture disagree
- See `docs/pcapng-fixture-audit-report.md` for the full audit of why the old hand-edited fixture diverged from capture

## Key Paths

- SANE backend: `backends-1.4.0/backend/coolscan3.c` (+ `coolscan.h`, `coolscan-scsidef.h`)
- Pcapng captures: `ls40-single-bw.pcapng` (single scan), `ls40-batch.pcapng` (multi-image)
- Golden fixture: `reference/golden_single_bw.txt`
- Protocol implementation: `coolscan/protocol.py`
- Replay harness: `coolscan/usb_replay.py`
- Main hardware test: `test_hardware_full_scan.py` (standalone script, init -> prescan -> full scan -> save image)
- Capture analyzer: `scripts/analyze_capture.py` (decode, phase detect, error find, diff captures)
- Recently updated docs: `HARDWARE_DIAGNOSTICS.md`, `.opencode/plans/golden-fixture-sequence-alignment.md`, `docs/protocol.md`, `docs/sane-image-data.md`, `docs/troubleshooting.md`

## Verification Commands

- `make check-all` -- full pipeline: lint + tests (fixtures are optional diagnostics)
- `make lint` -- flake8 (E9/F63/F7/F82) + mypy (**mypy runs with `|| true`, so type errors do NOT block the pipeline**)
- `make validate-fixtures` -- fixture consistency: columns, endpoints, length-vs-hex, @path resolution, timestamp ordering, golden-vs-pcapng SHA cross-check (optional diagnostic)
- `make test` -- all pytest tests in `tests/`
- `make test-fast` -- short traceback, stop on first failure
- `make test-properties` -- fixture-agnostic invariant tests only
- `make smoke-test-hardware` -- hardware smoke tests (skip gracefully if no scanner)
- `make generate-golden-fixture` -- regenerate golden fixture from pcapng
- `make replay-check` -- ad-hoc replay regression check against golden fixture (optional)

## Capture Analysis

`scripts/analyze_capture.py` parses capture files (text or pcapng) and produces decoded
summaries, structural extractions, and diffs. WDB and CONTROL_FRAME payloads are decoded
inline in event listings (no raw hex blobs).

**Basic analysis**:

- `python3 scripts/analyze_capture.py capture.txt` -- phases, command frequency, errors
- Add `--json` for machine-parseable output; `--verbose` for all events
- Add `--group-by-phase` to surface per-phase stats + event lists
- Add `--max-events N` to limit output (default 10000, was 200)

**Structured extraction** (TSV output, works with `--diff-a`/`--diff-b` too):

- `--extract-wdbs` -- SET_WINDOW (0x24) payloads: window_id, resolution, offsets, size, scan_kind, exposure
- `--extract-control-frames` -- WRITE(0x8F) payloads: per-frame y_start, y_end, height
- `--extract-read-capacity` -- READ_CAPACITY (0x25) responses: per-window scanner state

**Filtering**:

- `--filter "cmd=SCAN"` -- select SCAN commands
- `--filter "data_type=0x8f and length>50"` -- compound expressions with `and`/`or`
- Supported fields: `cmd`, `data_type`, `endpoint`, `length`, `phase`, `direction`

**Diff mode** (`--diff-a A --diff-b B`):

- Default: aligns command sequences, reports missing/extra/changed commands
- `--diff-wdbs` -- structural WDB diff by sequence position (per-field deltas, e.g. `offset_y: 0 != 590`)
- `--diff-control-frames` -- structural CF diff by sequence position
- `--annotate` -- flag commands with no obvious `protocol.py` handler

**Typical debugging workflow**:

```bash
# Compare hardware capture against golden fixture with full structured diff
python3 scripts/analyze_capture.py \
  --diff-a hardware_scan_output_capture.txt \
  --diff-b reference/golden_single_bw.txt \
  --extract-wdbs --extract-control-frames \
  --diff-wdbs --diff-control-frames

# List all WDBs with their scan parameters
python3 scripts/analyze_capture.py reference/golden_single_bw.txt --extract-wdbs

# Find all CONTROL_FRAME writes
python3 scripts/analyze_capture.py capture.txt --filter "cmd=WRITE and data_type=0x8f"
```

Context-aware error detection suppresses expected NOT_READY during TUR polling and UNIT_ATTENTION after reset.

## Test Strategy (Three Tiers)

The main test suite is fixture-independent.  No test imports a fixture file.
Most tests use either `FakeCoolscanProtocol` (test double with configurable
responses) or synthetic `UsbCaptureReplay` events.  This lets `make check-all`
pass without hardware or pre-generated fixtures.

- **Contract** (`test_protocol_contracts.py`) -- each helper and scenario method
  calls the right low-level methods in the right order with the right arguments
- **Property** (`test_protocol_properties.py`, `test_command_properties.py`,
  marker `property_test`) -- fixture-agnostic invariants (CDB construction,
  REISSUE polling, LUT sizes, TUR retries, timeout resilience)
- **State-machine** (`test_batch_state_machine.py`) -- batch scan frame
  transitions are valid; parameterized over frame counts
- **Scanner** (`test_scanner.py`) -- `CoolscanScanner` uses the real
  `CoolscanProtocol` API (via `FakeCoolscanProtocol` from `tests/fakes.py`)
- **Smoke** (`test_hardware_smoke.py`, marker `hardware`) -- actual hardware
  correctness; the required verification path for protocol changes; skip if no scanner
- Markers in `tests/conftest.py`
- `validate-fixtures` and `replay-check` are optional diagnostics, not pipeline gates

## Development Plan

- See `docs/capture-driven-development-plan.md` for milestones, strategy, and SANE audit findings
- Active sequence-refactor plan: `.opencode/plans/golden-fixture-sequence-alignment.md`
- Protocol spec: `docs/unified-protocol-spec.md`; command reference: `docs/commands.md`

## Stale / Legacy Files (AVOID)

- Root `test_*.py` from Sep 2025 or earlier are experimental and superseded by `tests/` suite
- `reference/test_basic_scan_capture.txt` is legacy; `reference/golden_single_bw.txt` is the current oracle
- `sane-comparison.md` at root is stale; use `docs/sane-comparison.md` instead
- `CLEANUP_SUMMARY.md`, `COMPLETE_IMPLEMENTATION_STATUS.md`, `IMPLEMENTATION_SUMMARY.md`, `DEVELOPMENT_SUMMARY.md` are outdated status docs
- `coolscan/*.backup` files are stale copies; ignore them

## Rules

- Never trust SANE code over pcapng captures for wire-format questions
- Any protocol change must be verified against golden fixture or pcapng directly
- Run `make check-all` before claiming work is done
- One commit per logical chunk; commit message states which capture slice is enforced
- `*.pcapng` files are gitignored but must exist locally for offline fixture regeneration

## Working with Hex/Binary Strings

Long hex or binary strings in fixtures, logs, and docs are easy to corrupt. Common mistakes:

- Dropping or duplicating bytes while transcribing.
- Case-insensitive mismatches (`AB` vs `ab`) in comparisons.
- Off-by-one byte counts, especially when whitespace is involved.

Avoid manual copy/paste validation. Prefer these CLI workflows:

**Count bytes in a contiguous hex string**

```bash
printf '00112233aabbccdd' | awk '{print length/2}'
```

**Count bytes in the golden fixture payload on line N**

The fixture is tab-separated: timestamp, endpoint, length, hex. The payload is column 4:

```bash
awk -F'\t' 'NR==10 {print length($4)/2}' reference/golden_single_bw.txt
```

**Verify the fixture's length column matches the payload**

```bash
awk -F'\t' 'NR==10 {actual=length($4)/2; print ($3==actual ? "OK" : "FAIL: claimed "$3", actual "actual)}' reference/golden_single_bw.txt
```

**Normalize and compare two hex strings**

```bash
clean_hex() { tr -d '[:space:]' | tr '[:upper:]' '[:lower:]'; }
echo "00 11 22 33" | clean_hex > /tmp/a.hex
echo "00112233" | clean_hex > /tmp/b.hex
diff /tmp/a.hex /tmp/b.hex && echo "identical"
```

**Compare a fixture line against a captured/reference value**

```bash
awk -F'\t' 'NR==10 {print $4}' reference/golden_single_bw.txt | clean_hex > /tmp/fix.hex
echo "0206280001000000" | clean_hex > /tmp/ref.hex
diff /tmp/fix.hex /tmp/ref.hex && echo "identical"
```

**Never eyeball strings longer than a few bytes**

For anything beyond 8 bytes, use normalized `diff` rather than visual scanning. When in doubt, run `make validate-fixtures` -- it already checks length-vs-hex consistency and SHA-256 alignment for the golden fixture.
