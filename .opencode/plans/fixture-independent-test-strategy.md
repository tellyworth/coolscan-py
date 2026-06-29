# Plan: Replace Replay Tests with Property and Contract Tests

**Status:** Approved in principle. Implementation blocked pending hardware validation run.  
**Date:** 2026-06-29  
**Scope:** Eliminate golden-fixture replay tests as direct test dependencies while keeping `*.pcapng` files and golden fixtures as reference/debug artifacts.

## Decision summary

Based on the review in the prior session, the existing replay tests are now more rigid than valuable. The protocol decomposition is stable (`prescan_frame`, `full_scan_frame`, `batch_scan`, and helpers), the target hardware is a single scanner model (Nikon LS-40 ED), and the suite is green (236 passed, 3 skipped). The replay tests have served their purpose of locking capture-derived bytes during refactoring; they can now be retired in favor of:

- **Property tests** for wire-format invariants.
- **Contract tests** for helper and scenario method composition.
- **Model-based/state-machine tests** for batch scan transitions.
- **Hardware smoke tests** as the only true wire-format correctness proof.

### Decisions from follow-up questions

| Question | Decision |
|----------|----------|
| Hardware availability? | Yes, but intermittent. Keep an optional ad-hoc replay diagnostic for periods when hardware is unavailable. |
| Add `hypothesis`? | Deferred. Start with deterministic tests only. Revisit after the new suite is stable. |
| `_SCAN_WINDOW_WDB_TABLES` in code? | Keep as capture-derived defaults for now. Document possible future first-principles computation. |
| `coolscan/usb_replay.py`? | Keep in the package as a debug/ad-hoc tool. |
| Batch LUT payloads in tests? | Use synthetic identity LUTs (consistent with Nikon Scan behavior). Drop `golden_data_*.bin` test dependencies. |

## Principles

1. **No test imports a fixture file.** `golden_single_bw.txt`, `golden_batch.txt`, and `test_basic_scan_capture.txt` become reference material only.
2. **No test uses line numbers.** All capture-derived knowledge is embedded as implementation constants or contract assertions.
3. **Hardware is the oracle.** The only tier that proves bytes are correct on the wire is the hardware smoke tier.
4. **Replay stays as a debug tool.** `UsbCaptureReplay` remains available for ad-hoc regression checks but is not part of `make test`.
5. **Deterministic first.** New tests do not require property-based frameworks until the architecture is proven.

## Proposed test architecture

| Tier | Purpose | Replaces |
|------|---------|----------|
| **Command property tests** | CDB construction is correct for all opcodes, lengths, datatypes. | `test_protocol_commands.py`, `test_protocol_module.py`, `test_get_window_cdb.py`, `test_read_scan_data_cdb.py` |
| **Protocol contract tests** | Each high-level method calls helpers in the right order with the right arguments. | `test_usb_replay_*_helpers_golden.py`, `test_prescan_sequence_verification.py` |
| **Resilience property tests** | Retries, polling, timeouts, status parsing behave correctly under varied inputs. | Parts of `test_protocol_properties.py` (strengthened) |
| **State-machine / model tests** | Batch scan frame transitions are valid; no illegal sequences. | `test_usb_replay_batch_scan*.py` |
| **Scanner contract tests** | `CoolscanScanner` uses the real `CoolscanProtocol` API. | `test_scanner.py` |
| **Hardware smoke tests** | Real wire-format correctness on an actual LS-40 ED. | `test_hardware_smoke.py` (expanded) |
| **Debug replay harness** | Optional ad-hoc regression check, not part of `make test`. | `test_usb_replay_transport.py` |

## Replacement mapping

### Command builders → parameterized property tests

Replace `struct.pack == bytes.fromhex(...)` assertions with parameterized tables and round-trip checks:

```python
@pytest.mark.parametrize("opcode,page,param2,alloc,control,expected", [
    (0x12, 0x00, 0x00, 0x24, 0x80, "120000002480"),
    (0x12, 0x01, 0xD1, 0x04, 0x80, "1201d1000480"),
    ...
])
def test_build_6byte_command(...):
    ...
```

Add deterministic generative checks for:
- `READ(10)` length bytes are big-endian and round-trip.
- Datatype values land at CDB byte 2.
- 6-byte and 10-byte commands have correct lengths.

### Helper replay tests → contract tests

For every helper currently replayed, mock `_issue_command` and assert:

| Helper | Contract |
|--------|----------|
| `set_boundary_for_prescan()` | Sends exactly one `WRITE(10)` with datatype `0x92`, length 4, and returns `True` on `READY`. |
| `read_exposure_data()` | Sends `READ(10)` datatype `0x8e`, length 6; parses header; sends second `READ(10)` with derived length. |
| `read_control_frame()` | Sends `READ(10)` datatype `0x8f`, length 58; returns 58 bytes. |
| `read_channel_state(n)` | Sends `READ(10)` datatype `0x8c`, length 10, window ID encoded; returns dict with `exposure` and `raw`. |
| `upload_identity_luts(include_ir)` | Sends 3 or 4 `WRITE(10)` datatype `0x03`, each with 8192 bytes, channels in order. |
| `start_scan()` | Sends `START_STOP_UNIT` action 0x03, then 3-byte channel payload; retries on `REISSUE`/transient `ERROR`; polls with datatype `0x87`. |
| `stop_scan()` | Sends `START_STOP_UNIT` action 0x04; retries on `REISSUE`. |
| `auto_focus(x, y)` | Sends `0xe0/0xa0`, 9-byte payload, `EXECUTE`, polls, reads focus. |
| `set_boundary()` (full scan) | Sends `WRITE(10)` datatype `0x8f` with 52-byte `CONTROL_FRAME` payload. |
| `read_focus()` | Sends `0xe1/0xc1`, length 9; returns parsed focus position. |

These tests live in a new `tests/test_protocol_contracts.py`.

### Sequence replay tests → composition contract tests

For `initialize_scanner`, `prescan_frame`, `full_scan_frame`, `batch_scan`, etc.:

- Mock every helper method.
- Assert exact call order and argument values.
- Assert no unexpected helper calls.
- Assert that the method returns `True`/`False`/data as documented.

Example:

```python
def test_prescan_frame_calls_helpers_in_order(protocol):
    protocol.set_boundary_for_prescan = Mock(return_value=True)
    protocol.read_exposure_data = Mock(return_value={"header": ..., "table": ...})
    ...

    protocol.prescan_frame()

    assert [c[0] for c in protocol.mock_calls] == [
        "set_boundary_for_prescan",
        "read_exposure_data",
        "read_control_frame",
        "read_channel_state",
        "set_scan_window",
        "upload_identity_luts",
        "start_scan",
        "poll_until_ready",
    ]
```

### Batch scan → state-machine / parameterized transition tests

Represent the batch scan as a state machine:

- States: `idle`, `setup`, `stage_a_capture`, `between`, `stage_b_capture`, `full_res_setup`, `full_res_start`, `full_res_capture`, `teardown`.
- Transitions: verified per frame.
- Parameterize over `frames ∈ [1, 2, 3]` to prove scaling.

Because `hypothesis` is deferred, implement this as deterministic parameterized tests rather than `RuleBasedStateMachine`.

### Scanner tests → fake protocol layer

Create `tests/fakes.py` with a `FakeCoolscanProtocol` that:
- Records every method call and arguments.
- Returns configurable responses.
- Enforces the real `CoolscanProtocol` method signatures.

Rewrite `test_scanner.py` to use the fake for most tests, reserving mocks only for exception injection. This turns `test_scanner.py` into a contract test between layers.

### Hardware smoke tests → expanded wire-format validation

Add real-hardware tests for the paths the replay tests currently cover:

- `test_full_scan_frame_saves_image`
- `test_batch_scan_one_frame`
- `test_prescan_returns_exposure_values`
- `test_teardown_eject_succeeds`
- `test_drain_loop_terminates`

Use a session-scoped scanner fixture to avoid repeated `initialize_scanner` overhead.

## What happens to existing files

| File | Action |
|------|--------|
| `tests/test_usb_replay_*_helpers_golden.py` | Delete. Replace with `tests/test_protocol_contracts.py`. |
| `tests/test_usb_replay_init_sequence.py` | Delete. Cover `initialize_scanner` in contract tests. |
| `tests/test_usb_replay_start_scan_golden.py` | Delete. Cover `start_scan` retry behavior in resilience property tests. |
| `tests/test_usb_replay_batch_scan.py` | Delete. Cover batch transitions in state-machine tests. |
| `tests/test_usb_replay_batch_scan_golden.py` | Delete. |
| `tests/test_usb_replay_transport.py` | Move to `tests/debug/test_replay_harness.py` or delete. Not run by `make test`. |
| `tests/test_prescan_sequence_verification.py` | Delete. Absorbed into contract tests. |
| `tests/test_scan_read_integration.py` | Rewrite with fake transport or contract-style mocks. |
| `tests/test_protocol_commands.py` | Consolidate into parameterized property tests in `tests/test_protocol_properties.py` or a new `tests/test_command_properties.py`. |
| `tests/test_protocol_module.py` | Same. |
| `tests/test_get_window_cdb.py` | Same. |
| `tests/test_read_scan_data_cdb.py` | Same. |
| `tests/test_scanner.py` | Rewrite using `tests/fakes.py`. |
| `tests/test_hardware_smoke.py` | Expand. |
| `tests/test_protocol_properties.py` | Keep as the home for cross-capture invariants; strengthen. |
| `tests/fixtures/golden_data_*.bin` | Remove from `tests/` if only used by replay tests. If any remain useful for reference, move to `reference/`. |
| `test_basic_scan_capture.txt` | Move to `reference/` or delete. |

## Capture-derived implementation constants

The following capture-derived data stays in implementation code. It is not a test dependency, but it should be documented:

| Constant | Location | Notes |
|----------|----------|-------|
| `_SCAN_WINDOW_WDB_TABLES` | `coolscan/protocol.py` | Capture-derived WDB defaults. Test invariants only (58-byte length, window IDs, resolutions). Document as candidate for future first-principles computation. |
| `_SCAN_WINDOW_RESOLUTIONS` | `coolscan/protocol.py` | Same. |
| Batch computed LUTs | No longer in tests | Use synthetic identity LUTs in contract tests. |

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Wire-format drift (code emits wrong bytes) | Hardware smoke tests become the canonical check. Run before releases. |
| Hard to debug a regression that replay would have caught | Keep `usb_replay.py` and fixtures for ad-hoc `scripts/replay_regression_check.py`. |
| Batch sequences are complex and timing-dependent | State-machine tests + real hardware batch run. |
| WDB tables in code are wrong | Hardware prescan/full scan will fail. Add invariant tests for table consistency. |
| Intermittent hardware availability | Keep an optional replay diagnostic under `tests/debug/` or `scripts/` for offline sanity checks. |

## Makefile and `AGENTS.md` changes

### Makefile

```makefile
# Default check path no longer validates fixtures
check-all: lint test
	@echo "All checks passed!"

# Fixture validation kept as an optional reference/debug step
validate-fixtures:
	@echo "Validating capture fixtures (reference only)..."
	python3 scripts/validate_fixtures.py

# Optional ad-hoc capture regression check
replay-check:
	python3 scripts/replay_regression_check.py
```

### `AGENTS.md`

Update the trust hierarchy:
- Keep "pcapng captures are the ground truth" for protocol *design*.
- Change the test-strategy section to state that the main suite is fixture-independent and hardware smoke tests are the required verification path.
- Document that `validate-fixtures` and replay checks are optional diagnostics, not gates.

## Implementation phases

| Phase | Work | Deliverable |
|-------|------|-------------|
| 0 | **Hardware validation run.** Run current `make smoke-test-hardware` and `test_hardware_full_scan.py` to establish a baseline before removing replay tests. | Hardware baseline report. |
| 1 | Create `tests/fakes.py` and rewrite `test_scanner.py`. | Scanner contract tests pass. |
| 2 | Create `tests/test_protocol_contracts.py` covering all helpers and scenario methods. | Delete helper replay tests. |
| 3 | Consolidate CDB tests into parameterized command property tests. | Delete/merge `test_protocol_commands.py`, `test_protocol_module.py`, `test_get_window_cdb.py`, `test_read_scan_data_cdb.py`. |
| 4 | Add batch state-machine transition tests. | Delete batch replay tests. |
| 5 | Strengthen `test_protocol_properties.py` with deterministic resilience tests. | Delete `test_usb_replay_start_scan_golden.py`. |
| 6 | Rewrite `test_scan_read_integration.py` with fake transport. | No fixture dependency. |
| 7 | Expand `test_hardware_smoke.py`. | Hardware path covers prescan, full scan, batch, teardown. |
| 8 | Move/delete replay harness tests, update `Makefile` and `AGENTS.md`. | `make test` passes with no fixture imports. |

## Pre-implementation hardware test checklist

Before starting implementation, run:

```bash
make smoke-test-hardware
python3 test_hardware_full_scan.py
```

Record:
- Pass/fail status of each test.
- Any scanner-specific quirks (e.g. eject retry count, trailing bytes, timing).
- Whether batch scan can be exercised.

This baseline ensures that any regressions introduced during the refactor are detectable by the expanded hardware smoke tests.

## Open decisions

1. **Hypothesis:** Revisit after phase 4. If the deterministic property tests are verbose, replace some with Hypothesis strategies.
2. **WDB first-principles computation:** Document as a future improvement in `AGENTS.md` or `docs/protocol.md`. Not in scope now.
3. **Optional replay diagnostic:** Decide whether to keep `scripts/replay_regression_check.py` as a one-off script or as part of a `tests/debug/` directory.
4. **Fixture cleanup:** Decide whether to move `golden_single_bw.txt` and `golden_batch.txt` to `reference/` or leave them in `tests/fixtures/` with a clear "reference only" note.
