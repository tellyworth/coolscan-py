# Plan: Align Scan Sequences with Pcapng Captures

## Status

Active. The immediate single-BW and batch fixture decomposition is complete and
all replay/property tests pass (`make check-all`: 205 passed, 3 skipped). Work
now focuses on composing the batch helpers into a full scenario method,
strengthening cross-capture property tests, and cleaning up legacy artifacts.

## Background and principles

Per `AGENTS.md`, the pcapng captures are the ground truth. The derived text
fixtures (`golden_single_bw.txt`, `golden_batch.txt`) are oracles for regression
testing. Any contradiction between code and fixture means the code is wrong.

Two captures are available:

- `ls40-single-bw.pcapng` (~2,500 bulk events): one black-and-white scan.
- `ls40-batch.pcapng` (~9,600 bulk events): batch-mode scan with multiple
  frames, including low-resolution preview scans and higher-resolution RGB+IR
  scans.

Implementation goals:

1. **Capture-informed**: command bytes and state transitions come from the captures.
2. **Capture-general**: methods compose, not hard-code, one specific sequence so
   the same code can service single-frame, batch-frame, RGB, and RGB+IR scenarios.
3. **Invariant-tested**: the test suite verifies patterns that hold across captures,
   not just replay one capture byte-for-byte.

## Strategic shift

### Old (rejected) approach

Rewrite `perform_scan_sequence()` and `prescan()` to byte-match
`golden_single_bw.txt` lines 219-343 and 203-400. Maintain full-sequence replay
tests against that one fixture.

### New approach

1. **Fix structural session bugs** that are unambiguous in both captures
   (single reservation per session, no per-operation reserve/release).
2. **Decompose** scan setup into small, independently testable helpers that each
   match a capture-derived command/state pattern.
3. **Compose** those helpers into scenario methods (`prescan`, `full_scan`,
   `batch_scan`) parameterized by frame count, channels, and resolution.
4. **Test with focused replay slices** from *both* captures rather than
   full-sequence replay against one fixture.
5. **Keep property tests** for cross-capture invariants (retry counts, WDB
   structure, LUT sizes, datatype usage).
6. **Use hardware smoke tests** as the final validator for end-to-end correctness.

## Cross-capture invariants identified so far

These patterns hold in both `ls40-single-bw.pcapng` and `ls40-batch.pcapng`:

- `START_SCAN` (`1b 00 00 00 03 00` with data `01 02 03`) may need up to 3
  attempts. The fixture shows `REISSUE` (0x09800601), transient `ERROR`
  (0x09800100), then `READY`. Status/progress reads between attempts use
  datatype `0x87`: 6 bytes, then 33 bytes after `REISSUE` and 24 bytes after
  the transient `ERROR`.
- `STOP_SCAN` uses `1b 00 00 00 04 00`.
- `SET_WINDOW` (`0x24`) always sends a 58-byte WDB. Window ID is at a fixed
  offset and distinguishes R/G/B/IR channels.
- Identity LUT uploads (`0x2a` datatype `0x03`) are 8192 bytes per channel.
- `READ` status uses datatype `0x87`; image data uses datatype `0x00`;
  exposure uses `0x8e`; control frame uses `0x8f`; channel state uses `0x8c`.
- `RESERVE_UNIT` happens once per session, immediately after initialization.

Differences between captures (these are parameters, not hard-coded):

- Batch mode repeats the preview/full-scan cycle per frame.
- Batch full scans include window 9 (IR); single BW does not in the captured slice.
- Allocation lengths for image-data `READ(10)` vary by resolution and scenario.

## Phases

### Phase 1: Fix the unambiguous session model

Both captures show `RESERVE_UNIT` exactly once, near the start of the session.

1. Keep `reserve_unit()` at the end of `initialize_scanner()`.
2. Remove `reserve_unit()` / `release_unit()` from:
   - `CoolscanProtocol.prescan()`
   - `CoolscanProtocol.perform_scan_sequence()` / any new scan method
   - `CoolscanScanner.prescan()`
   - `CoolscanScanner.auto_focus()`
3. Keep `release_unit()` in `CoolscanScanner.disconnect()` and in the explicit
   teardown path.
4. Update unit tests that mock per-operation reserve/release.

**Status: complete.** Session-level reservation is only in `initialize_scanner()`;
high-level scanner operations no longer reserve/release per call.

### Phase 2: Decompose scan setup into capture-informed helpers

Make each helper emit the bytes observed in the captures and nothing extra.
Helpers to verify/complete:

- `read_control_frame()` — `0x28/0x8f`, 58-byte response.
- `read_channel_state(channel)` — `0x28/0x8c`, 10-byte response.
- `read_exposure_header()` / `read_exposure_table()` — `0x28/0x8e`.
- `set_boundary_for_prescan()` — `0x2a/0x92` + 4-byte payload.
- `set_scan_window(window_id, scan_type, depth, ...)` — parameterized WDB.
- `upload_identity_luts(include_ir=False)` — `0x2a/0x03`, 8192 bytes/channel.
- `auto_focus(focus_x, focus_y)` — `0xe0/0xa0` + 9-byte payload + `EXECUTE`.
- `read_focus()` — `0xe1/0xc1`, 9- or 13-byte response.
- `start_scan()` — verified against both captures.
- `stop_scan()` — `0x1b/0x04`.

Each helper has a focused replay test against a slice from the appropriate capture.

**Status: complete.** All helpers above are implemented and have focused golden
replay tests in `tests/test_usb_replay_prescan_helpers_golden.py`,
`tests/test_usb_replay_fullscan_helpers_golden.py`, and
`tests/test_usb_replay_batch_helpers_golden.py`.

Notable fixes along the way:

- `read_control_params()` now uses MODE SENSE(10) opcode `0x1a` (committed
  `f88dea9`).
- `read_exposure_data()` derives table length from the 6-byte header instead of
  a hardcoded value.
- `read_focus()` requests 9 bytes, matching the golden fixture.
- `stop_scan()` retries on `REISSUE` with the same status/progress reads used by
  `start_scan()`.
- Property tests updated to use the 9-byte `read_focus()` allocation.

**Status: complete.** `set_scan_window()` now builds WDBs via
`_build_scan_window_wdb()`, which parameterizes window ID (byte 8), resolution
(bytes 10-13), and bits-per-pixel (byte 34) while preserving the remaining
pcapng-derived bytes from `_SCAN_WINDOW_WDB_TABLES`. Unit tests verify the
builder output matches the previous hardcoded tables byte-for-byte.

Verified WDB field offsets:
- Byte 8: window ID
- Bytes 10-13: x/y resolution (big-endian uint16)
- Byte 34: bits_per_pixel

### Phase 3: Compose scenario methods

Replace monolithic `perform_scan_sequence()` and `prescan()` with composable
scenario methods. The single-BW capture shows a clear split: a low-res IR
preview/setup phase (lines ~427-542), an optional IR data read, and then the
high-res RGB capture phase (lines ~599-672). We mirror that split rather than
forcing it into one method:

- `prescan_frame()` — preview scan for one frame (low-res RGB, no IR).
- `full_scan_setup_frame()` — low-res IR preview setup + `stop_scan()`.
- `full_scan_capture_frame()` — high-res RGB scan start.
- `full_scan_frame()` — compose setup + IR preview read + capture.
- `batch_scan(frames, ...)` — iterate preview and full-scan frames, with
  between-frame setup and teardown.

**Status: single-frame composition complete.** `prescan_frame()`,
`full_scan_setup_frame()`, `full_scan_capture_frame()`, `full_scan_frame()`, and
`read_ir_preview_data()` are implemented and tested against `golden_single_bw.txt`.
`CoolscanScanner._perform_scan()` now calls `full_scan_frame()` instead of
`perform_scan_sequence()`.

**Batch composition partially complete.** The following batch helpers are
implemented and tested against `golden_batch.txt`:

- `batch_scan_setup()` — initial RGB+IR setup.
- `batch_scan_teardown()` — final RGB+IR teardown.
- `batch_full_scan_setup_frame()` — IR preview setup for a batch frame.
- `batch_full_scan_capture_frame()` — IR preview data read.
- `batch_between_scan_setup_frame()` — RGB preview setup between frames.
- `batch_preview_capture_frame()` — RGB preview data read.
- `batch_full_res_setup_frame()` — full-resolution RGB+IR setup.
- `batch_full_res_start_frame()` — full-resolution scan start.
- `batch_full_res_capture_frame()` — full-resolution data read (dispatches the
  interleaved 628-6807 slice of `golden_batch.txt`).

**Status: complete.** `batch_scan()` is implemented in `coolscan/protocol.py` and
composes the batch helpers into a per-frame pipeline:
`batch_full_scan_setup_frame` → `start_scan(BATCH)` →
`batch_full_scan_capture_frame` → transition TUR polls →
`batch_between_scan_setup_frame` → `batch_preview_capture_frame` →
`batch_full_res_setup_frame` → `batch_full_res_start_frame` →
`batch_full_res_capture_frame`, followed by `scan_teardown()`. A focused replay
test against `golden_batch.txt` lines 278-6807 is in
`tests/test_usb_replay_batch_scan_golden.py`.

`perform_scan_sequence()` is now deprecated (emits a `DeprecationWarning`) and
replaced by `full_scan_frame()` / `batch_scan()` for new callers.

### Phase 4: Build fixtures from both captures

1. Generate a normalized text fixture from `ls40-batch.pcapng` using
   `scripts/generate_fixture_from_pcapng.py` or an equivalent `tshark` pipeline.
2. Validate both fixtures with `make validate-fixtures`.
3. Keep `golden_single_bw.txt` as the primary single-frame oracle and
   `golden_batch.txt` as the batch oracle.

**Status: complete.** Both `golden_single_bw.txt` and `golden_batch.txt` exist,
are validated by `make validate-fixtures`, and are used by the focused replay
suite.

### Phase 5: Add focused replay tests from both captures

Instead of full-sequence replay, add small tests that replay a *slice* and
verify one behavior:

- `test_start_scan_matches_golden_fixture_3_attempt_pattern.py` (single BW) — done.
- Batch frame helpers — done (`tests/test_usb_replay_batch_helpers_golden.py`).
- `test_set_window_wdb_bytes.py` — WDB bytes match fixture for prescan vs
  full-res vs IR windows.
- `test_lut_upload_sizes.py` — 8192 bytes/channel, RGB vs RGB+IR.

**Status: complete.** Focused slice tests exist for single-BW and batch
helpers. The WDB/LUT invariants are covered by property tests in
`tests/test_protocol_properties.py`
(`test_set_scan_window_wdb_length_and_window_id` and
`test_upload_identity_luts_sends_three_or_four_8192_byte_chunks`), which verify
WDB length, window ID offset, and LUT chunk counts/sizes across all capture
scenarios without requiring per-fixture byte tables.

### Phase 6: Strengthen property tests from capture invariants

Extend `tests/test_protocol_properties.py` with cross-capture properties:

- `START_SCAN` always retries on `0x09800601` and `0x09800100`.
- `SET_WINDOW` WDB length is always 58; window ID is at the expected offset.
- `upload_identity_luts()` sends exactly 3 or 4 chunks of 8192 bytes.
- Image-data `READ(10)` uses datatype `0x00`; status reads use `0x87`.
- Session has exactly one `RESERVE_UNIT` before the first scan operation.

**Status: complete.** The cross-capture invariants are now explicit property
tests in `tests/test_protocol_properties.py`:

- `test_start_scan_retries_on_reissue_and_transient_error`
- `test_set_scan_window_wdb_length_and_window_id`
- `test_upload_identity_luts_sends_three_or_four_8192_byte_chunks`
- `test_read_scan_data_uses_correct_datatype`
- `test_session_has_one_reserve_unit_before_first_scan`

### Phase 7: Hardware validation

1. Run single-BW scan, capture, and compare to `ls40-single-bw.pcapng`.
2. Run batch scan, capture, and compare to `ls40-batch.pcapng`.
3. Use `tshark`-based diffing to flag mismatches outside dynamic fields.

**Status: not started.**

## Cleanup

- ~~Remove `coolscan/protocol.py.backup` and `coolscan/scanner.py.backup` (stale
  per `AGENTS.md`).~~ Done.
- ~~Remove or deprecate `protocol.perform_scan_sequence()` once all callers are
  migrated to `full_scan_frame()` / `batch_scan()`.~~ Deprecated with
  `DeprecationWarning`; `CoolscanScanner._perform_scan()` already uses
  `full_scan_frame()`.

## What to drop

- Do **not** rewrite `perform_scan_sequence()` to byte-match one fixture slice.
  It is misnamed and misaligned; replace it with composable scenario methods.
- Do **not** migrate legacy replay tests (`test_usb_replay_full_scan_sequence.py`,
  `test_usb_replay_prescan_sequence.py`) — they no longer exist.
- Do **not** maintain `test_basic_scan_capture.txt` as an oracle. It is legacy
  and has simplified behavior.

## Known hardware issues to resolve

- **Teardown eject fails on real hardware (mitigated).** `scan_teardown()`
  follows the `golden_single_bw.txt` sequence (TUR polls, `e0/d0` eject +
  execute, TUR polls, `e0/b4` reset + execute, final SET_WINDOW). On a real
  LS-40 ED the eject command was rejected with command sequence error
  (`02052c0000000000`) because residual image data remained buffered in the
  scanner. The golden fixture has a ~42-second idle gap before eject that
  lets the firmware flush internally; the hardware test does not reproduce
  that gap.

  **Implemented mitigation (two-pronged):**
  1. `CoolscanScanner._perform_scan()` now runs a **drain loop** after the
     main image read loop: it reads 64 KB chunks via
     `read_scan_data(65536, datatype)` until a short read (fewer bytes than
     requested) signals end-of-data. Any trailing data is appended to the
     image buffer. This only runs on real hardware
     (`_usb_capture_replay is None`); replay tests are unaffected.
  2. `scan_teardown()` now has a **retry path** for eject: if the first
     `eject_medium()` fails, it issues `stop_scan()` once, polls until
     ready, and retries `eject_medium()`. This only runs on real hardware.

  **Remaining risk:** the drain loop appends trailing bytes to the image
  buffer; the downstream image reshape uses the original `total_bytes`
  calculation. If the trailing data is significant, the image will be
  corrupted. The 5120-byte trailing observed in the user's log suggests the
  scanner over-scans by a few lines. A future improvement could recalculate
  image dimensions from the actual byte count.

  Next steps: validate with a real hardware run using
  `test_hardware_full_scan.py` and confirm eject succeeds and the saved image
  is correct.

## Risks

- **Public API change**: replacing `perform_scan_sequence()` and adding
  `batch_scan()` affects `CoolscanScanner` callers.
- **Design risk**: the decomposition must be correct. A wrong helper boundary
  will produce subtle sequence bugs that only hardware catches.
- **Fixture generation**: `ls40-batch.pcapng` is large; regenerating and
  validating a text fixture must not bloat the repo or CI time.
- **Timing**: batch mode may have timing-dependent behavior (film advance) that
  fixtures cannot perfectly reproduce.

## Acceptance criteria

- `make check-all` passes.
- `make validate-fixtures` passes for both single-BW and batch fixtures.
- Focused replay tests exist for both captures and pass.
- Property tests cover the cross-capture invariants listed above.
- `batch_scan()` composes the batch helpers and has a passing replay test.
- Hardware smoke tests run successfully against both single-BW and batch scans
  and produce captures that replay without mismatches.
