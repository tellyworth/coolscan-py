# Hardware Diagnostics Progress

## Current Status (updated)

The most recent hardware capture (`test_hardware_scan_capture.txt`) shows a
**prescan/full-scan `START_SCAN` retry regression**. The older focus-setup
failure notes below are likely stale — this capture was made after those
reports and does not reach the focus-setup path.

## Observed Failure

- **`START_SCAN` (`0x1b 00 00 00 03 00`) fails:**
  - Attempt 1: `REISSUE` (Key 9, ASC 0x80, ASCQ 0x06)
  - Attempt 2: `ERROR`  (Key 9, ASC 0x80, ASCQ 0x01)
  - Driver then gives up and sends `RELEASE_UNIT` (`0x17`) instead of trying
    again.

## Root Cause

`coolscan/protocol.py::start_scan()` treated the transient `0x09800100` status
as a terminal `ERROR`. The pcapng-derived golden fixture
(`tests/fixtures/golden_single_bw.txt`) shows the same first two responses,
but the scanner becomes `READY` on the **third** attempt.

## Fix Applied

- `start_scan()` now retries up to 3 attempts on both `REISSUE` and the
  transient `0x09800100` `ERROR`, reading the `0x87` status/progress blocks
  between attempts to match the golden fixture.
- Status/progress read lengths are now status-dependent:
  - After `REISSUE`: READ 6 bytes, then 33 bytes.
  - After transient `ERROR`: READ 6 bytes, then 24 bytes.
- `max_attempts` is now 3 for all scan types (previously 1 for non-NORMAL).

## Test Updates

- Fixed contradictory assertion in
  `tests/test_prescan_sequence_verification.py::test_prescan_no_test_unit_ready_after_luts`.
- Updated `tests/test_protocol_properties.py::test_reissue_causes_resend` to
  exercise the real 3-attempt `REISSUE → ERROR → READY` pattern.
- Added `tests/test_usb_replay_start_scan_golden.py`, which replays the
  canonical 3-attempt `START_SCAN` slice from
  `tests/fixtures/golden_single_bw.txt` (lines 297-331).

## Structural Code / Fixture Mismatches Found

You are right: the golden fixture is the ground truth, and the divergences below
show the code is based on outdated/incorrect analysis. I reverted a broad edit
that tried to paper over these differences, because fixing them properly is a
larger refactor that should be deliberate and hardware-verified.

Key mismatches against `tests/fixtures/golden_single_bw.txt`:

1. **Session reservation model** *(fixed in Phase 1)*
   - Code: `CoolscanScanner.prescan()` / `auto_focus()` reserve and release the
     unit per operation; `perform_scan_sequence()` reserves internally.
   - Fixture: `RESERVE_UNIT` (`0x16`) appears **once** at line 85, at the start
     of the whole session. The unit stays reserved through focus setup,
     prescan, full scan, and teardown.
   - Fix: removed per-operation `reserve_unit()` / `release_unit()` from
     `CoolscanProtocol.prescan()`, `CoolscanProtocol.perform_scan_sequence()`,
     `CoolscanScanner.prescan()`, `CoolscanScanner.auto_focus()`, and
     `CoolscanScanner._perform_scan()`. Reservation now happens once in
     `initialize_scanner()` and is released in `disconnect()` / teardown.

2. **`perform_scan_sequence()` does not match the full-scan slice**
   - Code: begins with `scanner_ready → read_capacity`, then
     `read_control_frame`, 3x TUR, 3x `read_channel_state`, 3x TUR,
     `SET_WINDOW ×3` with **normal/full-res** WDB.
   - Fixture (the actual full-scan setup, around lines 427-660): begins with
     `SEND CONTROL_FRAME + EXECUTE`, then **autofocus** (`0xe0/a0 + EXECUTE`),
     3x TUR, `read_focus` (`0xe1/c1`), `read_channel_state(9)` for IR,
     `SET_WINDOW ×4` (windows 9,1,2,3), TUR, LUT uploads (IR+RGB),
     `STOP_SCAN` retries, then later a higher-resolution `SET_WINDOW` and
     `START_SCAN`.
   - The slice the code's docstring calls "full scan" (lines 219-343) actually
     uses **prescan-resolution** WDBs (`0x0060` = 96 DPI), so the current
     `perform_scan_sequence()` cannot replay against the golden fixture without
     either renaming it or switching it to the real full-scan slice.
   - Individual full-scan helpers now match the fixture:
     `set_boundary()`, `read_focus()`, `read_channel_state(9)`,
     `upload_identity_luts(include_ir=True)`, and `stop_scan()`.

3. **`prescan()` does not match the prescan slice**
   - Code: calls `set_scan_window(1/2/3, 'prescan')`, then
     `set_boundary_for_prescan()`, then LUTs and `start_scan()`.
   - Fixture: `SET_WINDOW` for windows 1-3 already happens during
     initialization (lines 148-163). The prescan block starts at line 203 with
     `set_boundary_for_prescan()` (`0x92`), followed by exposure reads,
     `CONTROL_FRAME`, channel-state reads, then `SET_WINDOW` and LUTs before
     the first `START_SCAN`.
   - Code also redundantly issued `read_scan_data(0x87)` after `start_scan()`;
     those reads now live inside `start_scan()` itself.
   - Individual prescan helpers now match the fixture:
     `set_boundary_for_prescan()`, `read_exposure_data()`,
     `read_control_frame()`, `read_channel_state()`, and
     `upload_identity_luts()`.

## Recommended Follow-Up

See `.opencode/plans/golden-fixture-sequence-alignment.md` for the full
refactor plan. Summary:

- Redesign session reservation: reserve once in `initialize_scanner()`, release
  once in teardown/disconnect; remove per-operation reserve/release from
  `CoolscanScanner` wrappers and from `perform_scan_sequence()` / `prescan()`.
- Rewrite `perform_scan_sequence()` against the **real** full-scan slice
  (golden fixture lines ~427-660+): include autofocus, IR channel,
  `SET_WINDOW ×4`, IR+RGB LUTs.
- Rewrite `prescan()` against the prescan slice (golden fixture lines
  ~203-343): drop the redundant `SET_WINDOW` calls, include the
  `CONTROL_FRAME` / channel-state reads the fixture shows before the final
  `SET_WINDOW`/`START_SCAN`.
- After the methods match the fixture, migrate the replay tests to
  `golden_single_bw.txt` with the corrected line ranges.

## Remaining Testing-Strategy Work (short term)

- The legacy full-sequence replay tests that loaded `test_basic_scan_capture.txt`
  (`tests/test_usb_replay_full_scan_sequence.py` and
  `tests/test_usb_replay_prescan_sequence.py`) were removed; they depended on
  the old per-operation reservation model and on a legacy fixture that is
  superseded by `tests/fixtures/golden_single_bw.txt`. Future coverage will use
  focused slice tests and cross-capture property tests rather than full-sequence
  replay against a single capture.
- The focused golden-fixture `START_SCAN` test now covers the critical retry
  behavior that caused the current hardware failure.

## Historical Notes (possibly stale)

Earlier reports also mentioned:

1. **Focus Setup**:
   - `SET FOCUS PARAM` (`0xe0`) failed: Sense Key 5, ASC 38, ASCQ 0.
   - `EXECUTE` (`0xc1`) failed: Sense Key 5, ASC 44, ASCQ 0.
2. **Prescan**:
   - `START_SCAN` (`0x1b`) failed with the same REISSUE/ERROR pattern above.

These pre-date the current capture. Re-evaluate if a fresh capture reaches
focus setup and still shows those sense codes.
