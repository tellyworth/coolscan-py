# AGENTS.md

## Trust Hierarchy (READ THIS FIRST)

- **pcapng captures are the ground truth** -- `ls40-single-bw.pcapng` (primary oracle) and `ls40-batch.pcapng` (secondary) are the only trusted source for wire-format protocol behavior
- **Golden fixture** (`tests/fixtures/golden_single_bw.txt`, 1472 events) is auto-derived from pcapng via `scripts/generate_fixture_from_pcapng.py`; trusted only when verified by `make validate-fixtures` (SHA-256 cross-check, event count bounds, command code coverage)
- **SANE backend source** (`backends-1.4.0/backend/coolscan3.c`) is known buggy and incomplete; use only for intent, naming, and edge-case discovery -- wire format ALWAYS defers to pcapng when SANE and capture disagree
- See `docs/pcapng-fixture-audit-report.md` for the full audit of why the old hand-edited fixture diverged from capture

## Key Paths

- SANE backend: `backends-1.4.0/backend/coolscan3.c` (+ `coolscan.h`, `coolscan-scsidef.h`)
- Pcapng captures: `ls40-single-bw.pcapng` (single scan), `ls40-batch.pcapng` (multi-image)
- Golden fixture: `tests/fixtures/golden_single_bw.txt`
- Protocol implementation: `coolscan/protocol.py`
- Replay harness: `coolscan/usb_replay.py`
- Main hardware test: `test_hardware_full_scan.py` (init -> prescan -> full scan -> save image)
- Recently updated docs: `docs/protocol.md`, `docs/sane-image-data.md`, `docs/troubleshooting.md`

## Verification Commands

- `make check-all` -- full pipeline: lint + validate fixtures + tests
- `make lint` -- flake8 (E9/F63/F7/F82) + mypy
- `make validate-fixtures` -- fixture consistency: columns, endpoints, length-vs-hex, @path resolution, timestamp ordering, golden-vs-pcapng SHA cross-check
- `make test` -- all pytest tests in `tests/`
- `make test-fast` -- short traceback, stop on first failure
- `make test-properties` -- fixture-agnostic invariant tests only
- `make smoke-test-hardware` -- hardware smoke tests (skip gracefully if no scanner)
- `make generate-golden-fixture` -- regenerate golden fixture from pcapng

## Test Strategy (Three Tiers)

- **Replay** (`test_usb_replay_*.py`, marker `replay_consistency`) -- fixture self-consistency only, NOT hardware correctness
- **Property** (`test_protocol_properties.py`, marker `property_test`) -- fixture-agnostic invariants (REISSUE, polling, LUT sizes, TUR retries)
- **Smoke** (`test_hardware_smoke.py`, marker `hardware`) -- actual hardware correctness, skip if no scanner
- Markers in `tests/conftest.py`; replay tests auto-marked when unmarked

## Development Plan

- See `docs/capture-driven-development-plan.md` for milestones, strategy, and SANE audit findings
- Protocol spec: `docs/unified-protocol-spec.md`; command reference: `docs/commands.md`
- All milestones 1-9 are replay-locked but not yet hardware-verified

## Stale / Legacy Files (AVOID)

- Root `test_*.py` from Sep 2025 or earlier are experimental and superseded by `tests/` suite
- `tests/fixtures/test_basic_scan_capture.txt` is legacy; `tests/fixtures/golden_single_bw.txt` is the current oracle
- `sane-comparison.md` at root is stale; use `docs/sane-comparison.md` instead
- `CLEANUP_SUMMARY.md`, `COMPLETE_IMPLEMENTATION_STATUS.md`, `IMPLEMENTATION_SUMMARY.md`, `DEVELOPMENT_SUMMARY.md` are outdated status docs

## Rules

- Never trust SANE code over pcapng captures for wire-format questions
- Any protocol change must be verified against golden fixture or pcapng directly
- Run `make check-all` before claiming work is done
- One commit per logical chunk; commit message states which capture slice is enforced
- `*.pcapng` files are gitignored but must exist locally for offline fixture regeneration
