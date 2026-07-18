# Documentation Fix Plan

## Priority 1: Fix `docs/commands.md` (Critical)

Replace SANE-derived 117-byte WDB format and standard SCSI CDBs with verified LS-40 ED USB wire format. Add prominent header noting LS-40 ED / USB capture format. Fix all control bytes from `0x00` to `0x80`. Replace WDB field layout (lines 122-143) with the 58-byte layout from `unified-protocol-spec.md`. Fix `set_boundary` datatype from `0x88` to `0x8f` / `0x92`. Cross-reference each section to `unified-protocol-spec.md`.

## Priority 2: Create end-to-end command sequence reference

New file `docs/scan-sequence.md` with phase-by-phase tables mapping golden fixture line numbers to commands, parameters, expected responses, and next steps. Extract from `protocol.py` scenario method docstrings, `HARDWARE_DIAGNOSTICS.md`, and golden fixture. Cover prescan, full scan, and batch sequences.

## Priority 3: Document READ_CAPACITY response format

Add section to `docs/unified-protocol-spec.md` documenting the READ_CAPACITY response byte layout. Analyze `read_capacity()` at `protocol.py:4668` and golden fixture responses. Include field interpretations and golden fixture line references.

## Priority 4: Add `protocol.py` architectural overview

Replace 6-line module docstring in `coolscan/protocol.py` with a 20-30 line overview: USB transport → command dispatch → status parsing → data transfer → scenario orchestration. Document `@sends` decorator convention and replay harness relationship.

## Priority 5: Fix stale USB replay test references

Remove references to non-existent `test_usb_replay_*_golden.py` files from `docs/capture-driven-development-plan.md` and `AGENTS.md`. Replace with current test file references.

## Priority 6: Add fixture line provenance to WDB tables

Add golden fixture line comments to ~20 hardcoded WDB hex strings at `coolscan/protocol.py:456-532`. Document the `scan_type` key names.

## Priority 7: Add batch-mode docs to the spec

Port ASCII state diagram from `tests/test_batch_state_machine.py:9-28` into `docs/unified-protocol-spec.md`. Document stage transitions and cross-reference to batch scan methods and golden batch fixture.

## Priority 8: Document status response encodings centrally

Extract sense key / ASC / ASCQ table from `_parse_status()` at `protocol.py:1108` into `docs/unified-protocol-spec.md`. Add golden fixture examples for REISSUE, PROCESSING, READY states. Document TUR polling pattern and NOT_READY suppression logic.

## Verification

- `make check-all` after each priority
- `make validate-fixtures` after any fixture-related changes
