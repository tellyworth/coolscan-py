# Prescan Sequence Verification

> **Note (current):** This document describes the prescan sequence against the
> **legacy** `usb_capture_timing.txt` / `test_basic_scan_capture.txt` slice. The
> canonical oracle is now `tests/fixtures/golden_single_bw.txt` derived from
> `ls40-single-bw.pcapng`. The current implementation is being refactored to
> match the golden fixture; see `.opencode/plans/golden-fixture-sequence-alignment.md`.

## Golden Fixture Prescan Sequence (golden_single_bw.txt, lines ~203–343)

1. `TEST_UNIT_READY` (line ~200)
2. `SEND BORDER_POSITION` (`2a0092...`, line 203) — `set_boundary_for_prescan()`
3. `READ` exposure header + table (`28008e...`, lines 208–216) — `read_exposure_data()`
4. `READ CONTROL_FRAME` (`28008f...`, lines 219–223) — `read_control_frame()`
5. `TEST_UNIT_READY` × 3 (lines 224–230)
6. `READ CHANNEL_STATE` for windows 1, 2, 3 (`28008c...`, lines 236–250) — `read_channel_state()`
7. `TEST_UNIT_READY` × 3 (lines 251–262)
8. `SET_WINDOW` windows 1, 2, 3 at prescan resolution (`2400...`, lines 263–276) — `set_scan_window(..., "prescan")`
9. `TEST_UNIT_READY` (line 278)
10. `WRITE LUT` R, G, B (`2a0003...`, lines 280–295) — `upload_identity_luts()`
11. `START_SCAN` (`1b0000000300`, lines 297–331) — `start_scan()` with REISSUE retry
12. `poll_until_ready()` (lines 332–343)
13. `GET_WINDOW` windows 1, 2, 3 and image/exposure reads follow.

## Key differences from the legacy slice

- `SET_WINDOW` for windows 1–3 happens **during initialization** in the golden
  fixture (lines 148–163), so the prescan block does not begin with three
  `SET_WINDOW` commands.
- The prescan block **starts** with `set_boundary_for_prescan()` (`0x92`) and
  includes `read_exposure_data()`, `read_control_frame()`, and
  `read_channel_state()` before the final `SET_WINDOW`/`LUT`/`START_SCAN` burst.
- `RESERVE_UNIT` (`0x16`) appears **once** at line 85, during session
  initialization. It is **not** emitted by `prescan()`.
- `RELEASE_UNIT` happens at session teardown (`disconnect()`), not at the end of
  each prescan.

## Current implementation status

Individual prescan helpers now match the golden fixture and are covered by
contract tests in `tests/test_protocol_contracts.py`:

- `set_boundary_for_prescan()`
- `read_exposure_data()`
- `read_control_frame()`
- `read_channel_state()`
- `upload_identity_luts(include_ir=False)`

The high-level `prescan()` method still needs restructuring to compose these
helpers in the correct order; this is Phase 3 of the refactor plan.
