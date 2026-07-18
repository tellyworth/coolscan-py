# Exposure Per-Frame Adjustment Fix

## Context: Analysis Summary

### What We Found

Captured WDB exposure values from multiple sources across different film types:

| Source | Phase | Res | Frame | R (hex) | G (hex) | B (hex) | R (ms) |
|--------|-------|-----|-------|--------:|--------:|--------:|-------:|
| Nikon Scan (pcapng, single-bw) | Prescan | 96 DPI | — | 0x0a381 | 0x08452 | 0x04e29 | 0.42 |
| Nikon Scan (pcapng, batch) | Prescan | 96 DPI | — | 0x09ce6 | 0x0f912 | 0x0d77a | 0.40 |
| Nikon Scan (pcapng, batch) | Setup (Stage A) | 290 DPI | frame 1 | 0x0ea05 | 0x0b4ed | 0x073bc | 0.60 |
| Nikon Scan (pcapng, batch) | Setup (Stage A) | 290 DPI | frame 2 | 0x0ea05 | 0x0b4ed | 0x073bc | 0.60 |
| Nikon Scan (pcapng, batch) | Main (Stage C) | 2900 DPI | frame 1 | 0x1a452 | 0x167d3 | 0x0a4a7 | 1.08 |
| Nikon Scan (pcapng, batch) | Main (Stage C) | 2900 DPI | frame 2 | 0x1a452 | 0x167d3 | 0x0a4a7 | 1.08 |
| Our hardware capture | Prescan | 96 DPI | — | 0x07dad | 0x055fe | 0x03701 | 0.32 |
| Our hardware capture | Setup (Stage A) | 290 DPI | any | 0x09f3b | 0x06cf4 | 0x045b0 | 0.40 |
| Our hardware capture | Main (Stage C) | 2900 DPI | any | 0x09f3b | 0x06cf4 | 0x045b0 | 0.40 |
| Our log file (single) | All phases | any | any | 0x1a452 | 0x167d3 | 0x0a4a7 | 1.08 |
| WDB table defaults | prescan | 96 DPI | — | 0x00a381 | 0x008452 | 0x004e29 | 0.42 |
| WDB table defaults | setup | 290 DPI | — | 0x00ea05 | 0x00b4ed | 0x0073bc | 0.60 |
| WDB table defaults | single_bw | 2900 DPI | — | 0x01a452 | 0x167d3 | 0x00a4a7 | 1.08 |
| WDB table defaults | normal | 2900 DPI | — | 0x01c91e | 0x1847e | 0x00ac49 | 1.17 |
| WDB table defaults | batch | 290 DPI | — | 0x00d386 | 0x15ca7 | 0x12d6e | 0.54 |
| WDB table defaults | batch_between | 290 DPI | — | 0x1b773 | 0x15ca7 | 0x00b33c | 1.12 |

**Note:** Prescan exposure varies by film content and film type. The WDB table defaults (0x0a381/0x08452/0x04e29) match `ls40-single-bw.pcapng`'s 96-DPI prescan exactly. The batch capture's prescan (0x09ce6) differs because it's a different film frame with different density. Negative film captures (`ls40-batch-neg.pcapng`) show further divergence (prescan R=0x09a34, G>>R).

### Problems Identified

1. **Calibrated exposure applied uniformly to all scan types.** `read_channel_state()` measures exposure during prescan (96 DPI conditions) and stores values in `_calibrated_exposure`. Then `set_scan_window()` auto-applies these same values to setup (290 DPI), Stage B (290 DPI), and main scan (2900 DPI). The scanner needs different exposure per phase — for B&W film the prescan→main ratio is ~2.5-2.9×, but for negative film it's ~1.7×. Sending prescan-calibrated values to all phases is wrong regardless of the exact multiplier.

2. **Channel ratios vary by scan type and film.** `read_channel_state` returns R:G:B = 1.0:0.68:0.44 (our hardware). Nikon's WDB values use different ratios per phase: prescan is ~1:0.81:0.48 (G < R), batch setup is ~1:1.65:1.43 (G > R), and negative film main scan is ~1:2.0:1.0 (G >> R due to orange mask). Auto-applying a single calibrated ratio across all phases corrupts whatever the correct ratio should be for that phase.

3. **All frames get identical exposure.** `batch_scan_to_frames` never updates calibrated exposure between frames. Even if different parts of the film have different densities, we send the same WDB. Nikon Scan varies Stage B (R only) and Stage C (all channels) per frame — verified from `golden_batch.txt` where Stage C R goes 0x1c91e→0x1bdc0→0x1b6b3→0x1b3bf→0x1adf5→0x1aa60 across 6 frames.

4. **The log file scan (`scan_20260712_154045.txt`) works correctly** because it uses `full_scan_frame()` → `perform_scan_sequence()` flow, which calls `get_exposure_values()` (GET_WINDOW read-back) after SET_WINDOW and uses those scanner-computed values. It doesn't go through `batch_scan_to_frames`.

### Root Cause

`set_scan_window()` at `protocol.py:2348-2366` unconditionally auto-applies `_calibrated_exposure` when `use_calibrated_exposure=True` (default). The `_calibrated_exposure` dict is populated by `read_channel_state()` during prescan, and the values are meant for prescan conditions (96 DPI). But they leak into every subsequent `set_scan_window()` call across all scan phases.

The WDB tables (`_SCAN_WINDOW_WDB_TABLES`) have correct per-type exposure values derived from `ls40-single-bw.pcapng`. Nikon Scan (pcapng) uses these defaults and never overrides them with `read_channel_state` values.

### What Nikon Does (from pcapng)

1. Sends WDB with table-default exposure for each scan type
2. After SET_WINDOW, reads back the WDB via `GET_WINDOW` (datatype 0x25) — the scanner may recalibrate internally
3. In batch mode, Stage A (290 DPI) sends identical WDBs across all frames; per-frame variation only appears in Stage B (R varies, G/B constant) and Stage C (all channels vary)
4. Does NOT use `read_channel_state` to override exposure in main scan WDBs
5. The source of per-frame variation (software computation from preview data vs. scanner read-back) is unclear from wire captures alone — both are possible

## Plan

### Step 1: Add scan-type-aware auto-exposure policy

**File:** `coolscan/protocol.py`

Instead of the blanket auto-apply, make `set_scan_window()` only auto-apply calibrated exposure when it makes sense:

```python
# New: scan types that should NOT use calibrated exposure from read_channel_state.
# These should use WDB table defaults (pcapng-verified per-type values).
_NO_CALIBRATED_EXPOSURE_TYPES = {"prescan", "setup", "batch", "batch_between"}
```

In `set_scan_window()`, before auto-applying:

```python
if effective_type in _NO_CALIBRATED_EXPOSURE_TYPES:
    # Use WDB table default — don't override with read_channel_state values
    effective_exposure = None
elif (
    exposure is None
    and use_calibrated_exposure
    and self._usb_capture_replay is None
    and window_id in self._calibrated_exposure
):
    # ... existing logic for applying calibrated exposure ...
```

For the remaining types ("single_bw", "normal"), keep the existing auto-apply behavior. In the single-scan flow, `perform_scan_sequence()`'s `get_exposure_values()` read-back (line 4333, after prescan) already runs BEFORE `set_scan_window("normal")` (line 4902), so `_calibrated_exposure` contains setup-phase values, not prescan values. In batch mode, the GET_WINDOW read-back after each frame's setup phase similarly updates exposure before the main scan SET_WINDOW.

### Step 2: Add per-frame exposure read-back in batch mode

**File:** `coolscan/protocol.py`

In `batch_scan_to_frames`, after Stage A SET_WINDOW (inside `batch_full_scan_setup_frame`), read back the scanner's WDB to get per-frame exposure. Then for Stage C, use read-back values:

After `batch_full_scan_setup_frame()` call (and after `batch_between_scan_setup_frame()` in Stage B), add:

```python
# Read back scanner-computed exposure for this frame
_frame_exposures = self.get_exposure_values(colors=[1, 2, 3])
if _frame_exposures:
    for color_name, exp_val in _frame_exposures.items():
        channel_map = {"R": 1, "G": 2, "B": 3}
        if color_name in channel_map:
            self._calibrated_exposure[channel_map[color_name]] = exp_val
```

Then for Stage C (line ~3035), when calling `set_scan_window()`, the auto-applied exposure will be the frame-specific read-back value.

**Note:** For frames 1+, Stage A is re-run first, so the read-back naturally reflects that frame's conditions. However, Stage A sends identical WDBs across all frames (verified in `golden_batch.txt` — all 6 frames have R=0x0d386). Whether the scanner's GET_WINDOW read-back returns frame-varying values despite identical input is uncertain. Nikon's captures show per-frame variation at Stage B and C, but whether that comes from GET_WINDOW read-back or from Nikon's internal software computation (analyzing preview data between stages) cannot be determined from wire captures alone. This approach should be validated against hardware before relying on it.

### Step 3: Fix IR channel handling in batch mode

**File:** `coolscan/protocol.py`

In `batch_full_scan_setup_frame`, `read_channel_state(9)` is called to measure IR exposure. The 0.9x scaling in `set_scan_window()` should only apply to this specific measurement. The WDB table default for IR (`"batch"` type: 0x0001d1ae) already includes scanner-calibrated IR timing.

Option: Keep `read_channel_state(9) -> set_scan_window(9, "batch")` for fixture matching, but skip the 0.9x scaling when effective_type is "batch" or "setup":

```python
if window_id == 9 and effective_type not in {"batch", "setup", "prescan"}:
    effective_exposure = int(round(raw_calibrated * 0.9))
else:
    effective_exposure = raw_calibrated
```

### Step 4: Update `batch_full_scan_setup_frame` to pass exposure read-back

**File:** `coolscan/protocol.py`, method `batch_full_scan_setup_frame`

After the Stage A SET_WINDOW + START_SCAN sequence, call `get_exposure_values()` and return values so `batch_scan_to_frames` can use them:

```python
# After step 11 (upload LUTs), before returning:
if not skip_boundary:
    exposure_readback = self.get_exposure_values(colors=[1, 2, 3, 9])
    if exposure_readback:
        # Store for Stage B and Stage C to use
        ...
```

Alternatively, have the method update `_calibrated_exposure` directly and let `set_scan_window` pick up the values for Stage B (which is now a "batch_between" type that won't auto-apply).

### Step 5: Verify with capture comparison

After the fix, run a hardware batch scan and compare:

```bash
python3 scripts/analyze_capture.py \
  --diff-a hardware_scan_new_capture.txt \
  --diff-b ls40-batch.pcapng \
  --extract-wdbs --diff-wdbs
```

Expected results:
- Prescan WDB: should use WDB defaults (R ≈ 0xa381), not channel state
- Stage A WDB: should use "batch" table defaults (R ≈ 0xd386)
- Stage B WDB: should use "batch_between" table defaults (R ≈ 0x1b773)
- Stage C WDB (frame 1): should use "normal" defaults (R ≈ 0x1c91e) or read-back value
- Stage C WDB (frame 2+): should reflect per-frame read-back values

### Step 6: Run existing tests

```bash
make check-all
```

Ensure fixture replay (UsbCaptureReplay) is unaffected — `use_calibrated_exposure` is already forced to `False` when `self._usb_capture_replay is not None`.

### Step 7: Hardware validation

Run a test batch scan with the fix and compare image quality:

```bash
python3 test_hardware_full_scan.py --batch --frames 3 output.png
```

Check for:
- Consistent brightness across frames
- Proper channel balance (no color cast)
- No over/underexposure in highlights/shadows

## Risks & Considerations

1. **Fixture replay:** The `use_calibrated_exposure` check already bypasses auto-apply during replay. Adding `_NO_CALIBRATED_EXPOSURE_TYPES` is an additional guard. No fixture breakage expected.

2. **Single scan mode (`full_scan_frame()`):** Steps 1-2 don't affect `perform_scan_sequence()` directly. After prescan, `get_exposure_values()` read-back (line 4333) updates `_calibrated_exposure` with setup-phase values before `set_scan_window("normal")` is called (line 4902). Single scan flow already works (as proven by the log file scan).

3. **Per-frame read-back uncertainty:** Step 2's mechanism may not produce per-frame variation. Stage A sends identical WDBs for all frames, and GET_WINDOW read-back may return the same values regardless. Nikon's per-frame variation at Stage B/C may come from internal software computation (analyzing preview image data), not from a simple read-back. Hardware validation is required to determine which.

4. **Backward compat:** `set_calibrated_exposure()` and explicit `exposure=` parameter continue to work. Only auto-apply behavior changes.

5. **Negative film:** The 3 additional captures (`ls40-batch-neg.pcapng`, `ls40-batch-session.pcapng`, `ls40-single-negs.pcapng`) show different exposure scaling (~1.7× prescan→main for negatives vs ~2.7× for B&W) and different channel ratios (G>>R). The fix should be validated against these captures before declaring it complete.

6. **Zero-impact alternative:** If tests show the scanner internally recalculates exposure anyway (READ_CAPACITY returns same value regardless of WDB), this fix might be unnecessary. However, matching Nikon's wire protocol is the right approach per AGENTS.md trust hierarchy (pcapng is ground truth).
