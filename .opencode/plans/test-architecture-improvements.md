# Plan: Test Architecture Improvements

## Status

**Completed.** All 4 changes implemented and verified (`make check-all`: 356 passed, 3 skipped).

## Overview

The test suite has 11 files across ~350 tests. The architecture is sound overall
(contract → property → hardware tiers), but there are concrete improvements that
will reduce maintenance burden and increase coverage of error paths.

Four changes, ordered by impact:

| # | Change | Effort | Impact |
|---|--------|--------|--------|
| 1 | Migrate replay tests → contract pattern | Medium | High — eliminates 1000+ lines of brittle byte-level event construction |
| 2 | Consolidate protocol factories into `fakes.py` | Small | Medium — prevents drift across 4+ duplicate factories |
| 3 | Add scanner integration tests | Medium | High — fills gap between contract tests and hardware smoke |
| 4 | Clean up pytest markers | Small | Low — housekeeping |

---

## PR 1: Migrate `test_protocol_properties.py` to contract pattern

### Problem

`test_protocol_properties.py` (1360 lines) constructs `UsbCaptureReplay` events
by hand — e.g. `test_reissue_causes_resend()` builds 30+ lines of
`("out", bytes([0x1B, ...]))` tuples. These are brittle (any USB dispatch change
breaks them), hard to read (requires understanding USB bulk transfer phases), and
overlap significantly with `test_protocol_contracts.py`.

### Approach

Keep a **minimal replay subset** (~4-5 tests) that genuinely exercise the USB
dispatch path. Migrate the rest to contract tests using `_make_protocol()` +
mocked `_issue_command`.

#### Tests to KEEP as replay (USB dispatch path)

These exercise the full `CoolscanProtocol` with `UsbCaptureReplay` — the only way
to test the USB bulk transfer dispatch loop:

- `test_reissue_causes_resend` — full retry sequence through USB dispatch
- `test_poll_until_ready_returns_on_ready` — polling loop with USB reads
- `test_poll_until_ready_handles_many_busy` — many BUSY cycles
- `test_poll_until_ready_timeout_returns_false` — timeout behavior

#### Tests to MIGRATE to contract pattern

Move to a new section in `test_protocol_contracts.py` (or a new file
`test_protocol_behavior.py`). Each becomes a ~10-line test that mocks
`_issue_command` and asserts call patterns:

**CDB construction** (verify command bytes sent):
- `test_inquiry_cdb_standard_36_bytes`
- `test_read_capacity_cdb_format`
- `test_read_scan_data_cdb_10_byte`
- `test_read_focus_info_cdb_format`
- `test_read_control_params_cdb_format`

**Status parsing** (no USB needed, pure logic):
- `test_status_parse_ready`
- `test_status_parse_reissue`
- `test_status_parse_processing`

**Sequence verification** (call ordering):
- `test_focus_setup_includes_read_focus_info`
- `test_post_prescan_autofocus_sequence`
- `test_scanner_ready_succeeds_after_tur_retries`

**WDB / LUT structure** (payload content):
- `test_lut_upload_sends_correct_size`
- `test_lut_upload_11bit_size`
- `test_set_window_called_for_rgb`
- `test_auto_focus_payload_is_9_bytes`
- `test_wdb_depth_byte_8bit`
- `test_wdb_depth_byte_12bit`
- `test_wdb_prescan_depth_unchanged`
- `test_set_scan_window_wdb_length_and_window_id`
- `test_upload_identity_luts_sends_three_or_four_8192_byte_chunks`
- `test_read_scan_data_uses_correct_datatype`

**WDB builder / control frame** (table consistency, no USB):
- `test_build_scan_window_wdb_matches_hardcoded_tables`
- `test_build_scan_window_wdb_depth_12bit_normal`
- `test_build_scan_window_wdb_preserves_ir_window_depth`
- `test_build_scan_window_wdb_unknown_combination_returns_none`
- `test_build_scan_window_wdb_set_scan_window_integration`
- `test_build_scan_window_wdb_y_offset_and_height_offsets`
- `test_build_scan_window_wdb_batch_window_9_matches_golden_geometry`
- `test_batch_scan_frame_count_estimation_uses_wdb_length_field`
- `test_build_control_frame_payload_*` (4 tests)
- `test_session_has_one_reserve_unit_before_first_scan`
- `test_start_scan_retries_on_reissue_and_transient_error` — **migrate**, since
  `test_reissue_causes_resend` already covers the USB dispatch path

After migration, `test_protocol_properties.py` should be ~150 lines (the replay
subset). The migrated tests go to `test_protocol_contracts.py` (appended, or
split into `test_protocol_behavior.py` if the file grows too large).

### File changes

- `tests/test_protocol_properties.py` — reduce to replay-only tests (~150 lines)
- `tests/test_protocol_contracts.py` — append migrated tests (~40 new tests)
  OR create `tests/test_protocol_behavior.py` if contracts file exceeds 1500 lines
- `tests/conftest.py` — remove `replay_consistency` marker

---

## PR 2: Consolidate protocol factories into `fakes.py`

### Problem

`_make_protocol()` (creates a bare `CoolscanProtocol` for contract testing) is
defined in 4 files:
- `tests/test_protocol_contracts.py:34`
- `tests/test_protocol_properties.py:31` (as `MockDevice` + inline construction)
- `tests/test_protocol_hypothesis.py:200`
- `tests/test_batch_parameters.py:18` (imports from contracts)

They're near-identical. Drift risk if `CoolscanProtocol.__init__` adds new state.

### Approach

Add to `tests/fakes.py`:

```python
def make_bare_protocol(**kwargs) -> CoolscanProtocol:
    """Create a CoolscanProtocol bypassing __init__ (for contract testing).

    Returns a protocol instance with mock device and default state attributes.
    Override any attribute via kwargs.
    """
```

And a companion:

```python
def make_mock_device(**kwargs) -> Mock:
    """Create a minimal ScannerDevice mock for protocol construction."""
```

Then update all 4 callers to import from `fakes`. Delete local definitions.

### File changes

- `tests/fakes.py` — add `make_bare_protocol()` and `make_mock_device()`
- `tests/test_protocol_contracts.py` — import from fakes, delete local
- `tests/test_protocol_properties.py` — import from fakes, delete local
- `tests/test_protocol_hypothesis.py` — import from fakes, delete local
- `tests/test_batch_parameters.py` — already imports from contracts; update to fakes

---

## PR 3: Add scanner integration tests

### Problem

There's a gap between:
- Contract tests (verify individual protocol helpers)
- Scanner tests (verify scanner API with mocked protocol)
- Hardware smoke (full hardware)

`test_scan_read_integration.py` is shallow — it calls mock methods in sequence
rather than exercising the scanner's actual scan methods.

### Approach

New file: `tests/test_scanner_integration.py`

Uses `CoolscanScanner` with `FakeCoolscanProtocol` to exercise full sequences:

**Happy path tests:**
- `test_prescan_full_flow` — connect → initialize → prescan → verify prescan image captured
- `test_full_scan_flow` — connect → initialize → set params → scan → verify data returned
- `test_batch_scan_flow` — connect → initialize → batch scan → verify frame count

**Error injection tests** (configure mock to fail at specific call counts):
- `test_prescan_handles_init_failure` — `initialize_scanner` returns False
- `test_scan_handles_read_failure` — `read_scan_data` returns short/empty data
- `test_scan_cleanup_after_error` — `scan_in_progress` reset after failed scan
- `test_prescan_cleanup_after_error` — protocol state after failed prescan

**State management:**
- `test_context_manager_cleans_up` — `with scanner:` cleans up on exception
- `test_disconnect_resets_state` — `scanner.disconnect()` resets all state

### Implementation

Extend `fakes.py` with `configure_failure(mock, method_name, call_index)` —
configures a mock method to raise/return-false on the Nth call.

### File changes

- `tests/test_scanner_integration.py` — new file (~25 tests)
- `tests/fakes.py` — add `configure_failure()` helper

---

## PR 4: Clean up pytest markers

### Problem

`conftest.py` defines 4 markers, but `replay_consistency` has no tests using it
(after PR 1, it won't be needed). `hardware_correctness` overlaps with `hardware`.

### Approach

After PR 1, reduce to 2 markers:
- `property_test` — fixture-agnostic invariants (keep)
- `hardware` — requires real scanner (keep)

Remove:
- `replay_consistency` — no tests use it
- `hardware_correctness` — redundant with `hardware`

Update any test decorators that use the removed markers.

### File changes

- `tests/conftest.py` — reduce to 2 markers
- `tests/test_hardware_smoke.py` — remove `hardware_correctness` decorator

---

## Execution order

PRs 1-3 are independent and can land in any order. PR 4 depends on PR 1
(marker removal). Suggested order:

1. **PR 2** (factories) — small, low-risk, enables cleaner code in PR 1
2. **PR 1** (replay → contract) — largest change, biggest maintenance win
3. **PR 3** (integration tests) — additive, uses factories from PR 2
4. **PR 4** (marker cleanup) — housekeeping after PR 1

## Verification

After each PR: `make check-all` must pass.
After all PRs: `make check-all` + `make smoke-test-hardware` (if scanner available).

Target: same or higher test count, significantly lower line count,
no regressions in coverage.
