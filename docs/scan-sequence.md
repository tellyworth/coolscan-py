# End-to-End Scan Sequence Reference

**Ground truth: `ls40-single-bw.pcapng`** (primary oracle) and
**`reference/golden_single_bw.txt`** (1472 events, derived from pcapng).

This document provides the complete command-by-command walkthrough for each scan
phase, with golden fixture line ranges and cross-references to the implementation.
For command format details, see `docs/commands.md`. For byte-level protocol format,
see `docs/unified-protocol-spec.md`.

---

## Overview

A complete single-BW scan session follows this high-level flow:

```
Initialization → Prescan Frame → Post-Prescan Transition → Full-Scan Setup →
IR Preview → Full-Scan Capture → Image Data Read → Teardown
```

Each phase is validated against the golden fixture and has a corresponding
scenario method in `coolscan/protocol.py`.

---

## Phase 1: Scanner Initialization

**Protocol method:** `CoolscanProtocol.initialize_scanner()` (`protocol.py:4707`)
**Golden fixture:** lines 1–85

| Step | Fixture Line | Command | Params | Purpose |
|------|-------------|---------|--------|---------|
| 1 | ~1 | INQUIRY (standard) | `12 00 00 00 24 80` | Get device ID ("Nikon LS-40 ED") |
| 2 | ~7 | TEST_UNIT_READY ×4 | `00 00 00 00 00 00` | Wait for scanner readiness |
| 3 | ~20 | INQUIRY page 0x01 | `12 01 00 00 04 80` → `12 01 00 00 15 80` | Capabilities (2-step: length then full) |
| 4 | ~28 | INQUIRY page 0xd1 | `12 01 d1 00 04 80` → `12 01 d1 00 1c 80` | MUD info (28 bytes) |
| 5 | ~36 | INQUIRY page 0xc1 | `12 01 c1 00 04 80` → `12 01 c1 00 55 80` | Configuration (85 bytes) |
| 6 | ~48 | INQUIRY page 0xe1 | `12 01 e1 00 04 80` → `12 01 e1 00 27 80` | 39 bytes |
| 7 | ~56 | INQUIRY page 0xf0 | `12 01 f0 00 04 80` → `12 01 f0 00 35 80` | 53 bytes |
| 8 | ~64 | INQUIRY page 0xf8 | `12 01 f8 00 04 80` → `12 01 f8 00 0f 80` | 15 bytes |
| 9 | ~85 | RESERVE_UNIT | `16 00 00 00 00 00` | Reserve scanner for exclusive use |
| 10 | ~86 | READ_CAPACITY | `25 00 00 00 00 00 00 00 3a 80` | 58-byte response |

**Key points:**
- Each INQUIRY page is read in two steps: first a 4-byte length query, then the full page
- `RESERVE_UNIT` appears **once** at the start of the session; the unit stays reserved through teardown
- After initialization, the scanner is ready for scan parameter setup

---

## Phase 2: Prescan Frame (Low-Resolution Auto-Exposure)

**Protocol method:** `CoolscanProtocol.prescan_frame()` (`protocol.py:4140`)
**Golden fixture:** lines ~203–343

The prescan performs auto-exposure (AE) at 96 DPI to determine optimal exposure
values for the full scan.

| Step | Fixture Line | Command | Key Params | Purpose |
|------|-------------|---------|------------|---------|
| 1 | 203 | SEND BORDER_POSITION | `2a 00 92 00 00 03 00 00 04 00` + 4-byte payload | Set prescan border offset |
| 2 | 208 | READ exposure header | `28 00 8e 00 00 00 00 00 06 80` | 6-byte calibration header |
| 3 | 214 | READ exposure table | `28 00 8e 00 00 00 00 0d 88 80` | 3464-byte calibration table |
| 4 | 219 | READ CONTROL_FRAME | `28 00 8f 00 00 03 00 00 34 80` | 52-byte frame data |
| 5 | 224-235 | TEST_UNIT_READY ×3 | `00 00 00 00 00 00` | TUR polling |
| 6 | 236 | READ channel state R | `28 00 8c 00 01 03 00 00 0a 80` | 10-byte response (calibrated exposure) |
| 7 | 241 | READ channel state G | `28 00 8c 00 02 03 00 00 0a 80` | 10-byte response |
| 8 | 246 | READ channel state B | `28 00 8c 00 03 03 00 00 0a 80` | 10-byte response |
| 9 | 251-262 | TEST_UNIT_READY ×3 | `00 00 00 00 00 00` | TUR polling |
| 10 | 263 | SET_WINDOW (win 1) | `24 00 00 00 00 00 00 00 3a 80` + 58-byte prescan WDB | R channel, 96 DPI |
| 11 | 268 | SET_WINDOW (win 2) | same CDB format | G channel, 96 DPI |
| 12 | 273 | SET_WINDOW (win 3) | same CDB format | B channel, 96 DPI |
| 13 | 278 | TEST_UNIT_READY | `00 00 00 00 00 00` | Required before LUT upload |
| 14 | 282 | WRITE LUT R | `2a 00 03 00 01 01 00 20 00 00` + 8192 bytes | Identity LUT |
| 15 | 288 | WRITE LUT G | `2a 00 03 00 02 01 00 20 00 00` + 8192 bytes | Identity LUT |
| 16 | 294 | WRITE LUT B | `2a 00 03 00 03 01 00 20 00 00` + 8192 bytes | Identity LUT |
| 17 | 297 | START_SCAN | `1b 00 00 00 03 00` + 3-byte data `01 02 03` | Start scan pass |
| 18 | 297-331 | Retry handling | REISSUE → ERROR → READY pattern | 3-attempt retry |
| 19 | 332-343 | TEST_UNIT_READY poll | `00 00 00 00 00 00` (repeated) | Poll until READY |

**Prescan WDB parameters (96 DPI):**
- Resolution: `0x0060` × `0x0060`
- Image composition: `0x05` (RGB full)
- Depth: `0x0c` (12-bit)
- Scan kind: `0x02` (AE)
- Windows: 1, 2, 3 only (no IR)

**Timing:**
- START_SCAN to first READY: ~13 seconds (dynamic polling)
- Total prescan cycle: ~25+ seconds

---

## Phase 3: Post-Prescan Transition

**Protocol method:** `CoolscanProtocol.prescan()` (post-frame section, `protocol.py:4298`)
**Golden fixture:** lines ~344–426

After reading prescan image data, the scanner enters a transitional state.
Skipping this transition causes `set_boundary` to be rejected with
ILLEGAL REQUEST (sense `0x052c`).

| Step | Fixture Line | Command | Purpose |
|------|-------------|---------|---------|
| 1 | ~344 | READ image data | Prescan pixels (273024 bytes total) |
| 2 | ~360 | TEST_UNIT_READY poll | Wait through transitional `02063f03` status |
| 3 | ~380 | INQUIRY page 0xc1 | Re-read configuration |
| 4 | ~390 | TEST_UNIT_READY | TUR poll |
| 5 | ~395 | READ exposure data (0x8e) | Re-read calibration table |
| 6 | ~410 | TEST_UNIT_READY | TUR poll |
| 7 | ~415 | GET_WINDOW ×3 | Read back WDBs for exposure values |

**Key point:** The transitional `02063f03` status after prescan is expected.
Poll through it until READY before issuing the next CONTROL_FRAME command.

---

## Phase 4: Full-Scan Setup (Low-Res IR/RGB Preview Setup)

**Protocol method:** `CoolscanProtocol.full_scan_setup_frame()` (`protocol.py:4347`)
**Golden fixture:** lines ~427–542

This phase configures the scanner at 290 DPI for an IR/RGB preview and
establishes the scan boundaries via CONTROL_FRAME.

| Step | Fixture Line | Command | Key Params | Purpose |
|------|-------------|---------|------------|---------|
| 1 | 427 | SEND CONTROL_FRAME | `2a 00 8f 00 00 03 00 00 34 00` + 52-byte payload | Frame boundary positions |
| 2 | 432 | TEST_UNIT_READY | `00 00 00 00 00 00` | TUR poll |
| 3 | 436 | Auto focus cmd | `e0 00 a0 00 00 00 00 00 0d 00` + 13-byte coords | e0/a0 + execute |
| 4 | 440 | EXECUTE | `c1 00 00 00 00 00` | Execute focus |
| 5 | 445-456 | TEST_UNIT_READY ×3 | `00 00 00 00 00 00` | TUR polling |
| 6 | 457 | READ focus result | `e1 00 c1 00 00 00 00 00 0d 00` | Read focus position |
| 7 | 462 | TEST_UNIT_READY | `00 00 00 00 00 00` | TUR poll |
| 8 | 466 | READ channel state IR | `28 00 8c 00 09 03 00 00 0a 80` | IR channel exposure (channel 9) |
| 9 | 471-478 | TEST_UNIT_READY ×2 | `00 00 00 00 00 00` | TUR polling |
| 10 | 479 | SET_WINDOW (win 9) | `24 00 00 00 00 00 00 00 3a 80` + 58-byte "setup" WDB | IR window, 290 DPI |
| 11 | 484 | SET_WINDOW (win 1) | same CDB format | R channel, 290 DPI |
| 12 | 489 | SET_WINDOW (win 2) | same CDB format | G channel, 290 DPI |
| 13 | 494 | SET_WINDOW (win 3) | same CDB format | B channel, 290 DPI |
| 14 | 499 | TEST_UNIT_READY | `00 00 00 00 00 00` | TUR poll |
| 15 | 503 | WRITE LUT IR | `2a 00 03 00 09 01 00 20 00 00` + 8192 bytes | IR identity LUT |
| 16 | 509 | WRITE LUT R | `2a 00 03 00 01 01 00 20 00 00` + 8192 bytes | R identity LUT |
| 17 | 515 | WRITE LUT G | `2a 00 03 00 02 01 00 20 00 00` + 8192 bytes | G identity LUT |
| 18 | 521 | WRITE LUT B | `2a 00 03 00 03 01 00 20 00 00` + 8192 bytes | B identity LUT |
| 19 | 523-542 | STOP_SCAN | `1b 00 00 00 04 00` (with retries) | Finalize setup |

**Setup WDB parameters (290 DPI, "setup" scan_type):**
- Resolution: `0x0122` (290 DPI)
- Includes IR window (9) + RGB windows (1, 2, 3)
- 4 LUTs uploaded (IR + RGB)

---

## Phase 5: IR Preview (Low-Res Read)

**Protocol method:** `CoolscanProtocol.read_ir_preview_data()` (`protocol.py`)
**Golden fixture:** lines ~542–598

Between setup and high-res capture, the scanner produces a 290 DPI IR+RGB
preview image.

| Step | Fixture Line | Command | Notes |
|------|-------------|---------|-------|
| 1 | ~545 | START_SCAN | `1b 00 00 00 03 00` |
| 2 | ~550 | Poll to READY | TEST_UNIT_READY loop |
| 3 | ~565 | READ image data | Multiple 130752-byte blocks + residual |
| 4 | ~598 | STOP_SCAN | `1b 00 00 00 04 00` |

**IR Preview Data:**
- Total: 997632 bytes of 12-bit plane-interleaved R/G/B/IR data
- Resolution: 288×433 pixels (290 DPI effective)
- See `docs/protocol.md` for verified decoding recipe

---

## Phase 6: Full-Scan Capture (High-Res RGB)

**Protocol method:** `CoolscanProtocol.full_scan_capture_frame()` (`protocol.py:4435`)
**Golden fixture:** lines ~599–672

This phase reconfigures the scanner at 2900 DPI and starts the high-resolution
RGB scan.

| Step | Fixture Line | Command | Key Params | Purpose |
|------|-------------|---------|------------|---------|
| 1 | 599-606 | TEST_UNIT_READY ×2 | `00 00 00 00 00 00` | TUR polling |
| 2 | 607 | SET_WINDOW (win 1) | `24 00 00 00 00 00 00 00 3a 80` + 58-byte full-res WDB | R channel, 2900 DPI |
| 3 | 612 | SET_WINDOW (win 2) | same CDB format | G channel, 2900 DPI |
| 4 | 617 | SET_WINDOW (win 3) | same CDB format | B channel, 2900 DPI |
| 5 | 622 | TEST_UNIT_READY | `00 00 00 00 00 00` | TUR poll |
| 6 | 626 | WRITE LUT R | `2a 00 03 00 01 01 00 20 00 00` + 8192 bytes | Identity LUT |
| 7 | 632 | WRITE LUT G | `2a 00 03 00 02 01 00 20 00 00` + 8192 bytes | Identity LUT |
| 8 | 638 | WRITE LUT B | `2a 00 03 00 03 01 00 20 00 00` + 8192 bytes | Identity LUT |
| 9 | 641 | START_SCAN | `1b 00 00 00 03 00` + 3-byte data | Start scan |
| 10 | 641-660 | Retry handling | REISSUE → ERROR → READY pattern | 3-attempt retry |
| 11 | 661-672 | TEST_UNIT_READY poll | `00 00 00 00 00 00` (repeated) | Poll until READY |

**Full-res WDB parameters (2900 DPI, "single_bw" scan_type):**
- Resolution: `0x0b54` × `0x0b54`
- Image composition: `0x02` (RGB)
- Depth: `0x08` (8-bit)
- Scan kind: `0x01` (normal)
- Windows: 1, 2, 3 only (no IR at full res in single-BW)

---

## Phase 7: Image Data Read

**Protocol method:** `CoolscanProtocol.read_scan_data()` (`protocol.py:2482`)
**Golden fixture:** lines ~673–1420

After the scanner is READY, read the high-resolution scan data in stripes.

| Step | Description | CDB Pattern | Typical Size |
|------|-------------|-------------|-------------|
| 1 | Stripe 1 | `28 00 00 00 00 00 03 f0 00 80` | 258048 bytes |
| 2 | Stripe 2 | `28 00 00 00 00 00 03 69 00 80` | 223488 bytes |
| 3 | Stripe 3 | `28 00 00 00 00 00 03 f4 80 80` | 259200 bytes |
| 4 | Stripe 4 | `28 00 00 00 00 00 01 95 00 80` | 103680 bytes |
| 5 | Residual | `28 00 00 00 00 00 00 2d 00 80` | 11520 bytes |

**Scanner chunking behavior:**
- The scanner returns data in increments of up to 65508 bytes per USB chunk
- `read_scan_data()` automatically handles chunking and stripe reassembly
- The allocation length in the CDB is the total stripe size; the scanner
  returns it in multiple chunks

**Image data format:**
- 8-bit plane-interleaved: all R rows, then all G rows, then all B rows
- See `docs/protocol.md` lines 135-213 for verified width/height and decoding

---

## Phase 8: Teardown

**Protocol method:** `CoolscanProtocol.scan_teardown()` / `CoolscanScanner.disconnect()`
**Golden fixture:** lines ~1420–1472

| Step | Command | Purpose |
|------|---------|---------|
| 1 | STOP_SCAN | `1b 00 00 00 04 00` — stop any active scan |
| 2 | RELEASE_UNIT | `17 00 00 00 00 00` — release scanner reservation |
| 3 | TEST_UNIT_READY | Final readiness check |

---

## Batch Scan Sequence

**Protocol method:** `CoolscanProtocol.batch_scan_to_frames()` (`protocol.py:2880`)
**Golden fixture:** `ls40-batch.pcapng` / `reference/golden_batch.txt`

The batch scan performs multi-frame scanning with auto-focus between frames.
It uses a state machine architecture:

```
idle → setup → stage_a_capture → between → stage_b_capture →
full_res_setup → full_res_start → full_res_capture →
(loop back to setup for next frame) → teardown → done
```

### Per-Frame Transitions

| # | Transition | Protocol Method | Description |
|---|-----------|----------------|-------------|
| 1 | setup → stage_a_capture | `batch_full_scan_setup_frame()` | IR+RGB 290 DPI setup (similar to Phase 4 but no `stop_scan`) |
| 2 | stage_a_capture → scanning | `start_scan(BATCH)` | Start batch scan for Stage A |
| 3 | scanning → data | `batch_full_scan_capture_frame()` | Read Stage A IR+RGB 290 DPI data |
| 4 | data → between | `_wait_ready_or_replay_once()` ×2 | TUR polls |
| 5 | between → stage_b_capture | `batch_between_scan_setup_frame()` | Configure Stage B |
| 6 | stage_b_capture → data | `batch_preview_capture_frame()` | Read Stage B preview data |
| 7 | data → full_res_setup | `batch_full_res_setup_frame()` | Configure 2900 DPI at per-frame offset |
| 8 | full_res_setup → full_res_start | `batch_full_res_start_frame()` | START_SCAN + poll |
| 9 | full_res_start → full_res_capture | `batch_full_res_capture_frame()` | Read full-res RGB data |
| — | (before loop) | `post_prescan_autofocus()` + `_wait_ready_or_replay_once()` ×2 | Auto-focus at next frame center |

### Teardown

| Transition | Protocol Method | Description |
|-----------|----------------|-------------|
| _ → teardown | `scan_teardown()` | STOP_SCAN + RELEASE_UNIT |
| teardown → done | — | Session complete |

**Key differences from single-BW:**
- Batch setup does NOT call `stop_scan()` after LUT upload (the next event is `start_scan()`)
- Stage A, Stage B, and full-res stages are three separate scan passes per frame
- Auto-focus runs between frames at the next frame's center coordinates
- Per-frame Y offset is applied during `batch_full_res_setup_frame()` WDB configuration
- IR LUT is always uploaded with RGB (4 total) in batch mode

---

## START_SCAN Retry Pattern

`start_scan()` (`protocol.py:2414`) implements a 3-attempt retry pattern
validated against golden fixture lines 297-331:

| Attempt | Response | Sense Key/ASC/ASCQ | Action |
|---------|----------|--------------------|--------|
| 1 | REISSUE | `09 80 06` | Read 6-byte status, then 33-byte status; retry |
| 2 | ERROR | `09 80 01` | Read 6-byte status, then 24-byte status; retry |
| 3 | READY | `00 00 00 00 00 00 00 00` | Scan started successfully |

This pattern is consistent across prescan, full-scan, and batch START_SCAN operations.

---

## Cross-Reference: Fixture Lines to Protocol Methods

| Golden Fixture Lines | Phase | Protocol Method | File:Line |
|---------------------|-------|----------------|-----------|
| 1-85 | Initialization | `initialize_scanner()` | `protocol.py:4707` |
| 86-202 | Capacity + mode setup | `read_capacity()`, MODE_SELECT | `protocol.py:4668` |
| 203-343 | Prescan frame | `prescan_frame()` | `protocol.py:4140` |
| 344-426 | Post-prescan transition | `prescan()` (post-frame) | `protocol.py:4298` |
| 427-542 | Full-scan setup | `full_scan_setup_frame()` | `protocol.py:4347` |
| 542-598 | IR preview read | `read_ir_preview_data()` | `protocol.py` |
| 599-672 | Full-scan capture | `full_scan_capture_frame()` | `protocol.py:4435` |
| 673-1420 | Image data read | `read_scan_data()` | `protocol.py:2482` |
| 1420-1472 | Teardown | `scan_teardown()` | `protocol.py` |

---

## Related Documents

- **Command format details:** `docs/commands.md`
- **Byte-level protocol spec:** `docs/unified-protocol-spec.md`
- **Image data decoding:** `docs/protocol.md`
- **Hardware diagnostics:** `HARDWARE_DIAGNOSTICS.md`
- **Sequence alignment plan:** `.opencode/plans/golden-fixture-sequence-alignment.md`
- **Batch state machine tests:** `tests/test_batch_state_machine.py`
