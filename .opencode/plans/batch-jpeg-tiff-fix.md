# Plan: Fix batch JPEG/TIFF image-quality issues

## Goal
Fix the image-quality regressions observed in the 2026-07-24 hardware batch scan
(`coolscan scan -o slidetest --depth 12 --batch`, no `--infrared`):

1. JPEG shows false colour, halos, and posterization.
2. 16-bit TIFF looks over-exposed.
3. TIFF file size doubled (~36 MB → ~71 MB).

## Background

- The batch scan completed all 6 frames in `logs/scan_20260724_091248.txt`.
- The previous commit (`dfc3276`) removed erroneous inter-frame `stop_scan()`
  calls; that part is unrelated to the image-output issues below.
- Output files are in `slidetest/`:
  - `img__021.jpg` / `img__021.tiff` (frame 1 of 6)
  - `img__022.jpg` / `img__022.tiff`
  - ... through `img__026.jpg` / `img__026.tiff`

## Analysis

### 1. JPEG false-colour / posterizing / halos — clear bug

`_apply_auto_adjust()` in `coolscan/cli.py` is called on the **uint16** scaled
RGB array (values 0–65535), but the function is written for 8-bit input:

```python
arr = 255.0 - arr          # subtracts 65535-range values from 255
# then per-channel histogram stretch with min/max
```

This produces large negative values, wildly wrong ranges, and independent
per-channel min/max stretching creates colour casts and posterization. The
"halo" effect is exacerbated by `LS40_CHANNEL_OFFSETS` (0, 10, 20) shifting
channels against each other while the values are blown out.

**Fix:** rewrite `_apply_auto_adjust()` to:
1. First down-convert uint16 → uint8 with `>> 4` (or normalize to 0–1).
2. Invert in the correct range.
3. Use percentile-based stretch (e.g. 0.5% and 99.5% instead of min/max) to
   avoid outliers causing posterization.
4. Apply gamma.

### 2. TIFF over-exposure

The 16-bit scaling `value * 65535 // 4095` in `_do_batch_scan()` is
mathematically correct. The question is whether the raw 12-bit values are
already too high.

The log shows full-res WDB exposure values such as `0x1c91e`, `0x1847e`,
`0x0ac49`. These are the table-default exposures used in batch mode, not
per-frame calibrated exposures. For the hardware/film combo used on 2026-07-24,
those defaults may simply over-expose the frames.

**Diagnostic to add:** before scaling to 16-bit, print `min/max/mean` per
channel of the raw 12-bit data. If the means are already high (e.g. > 3000 of
4095), the issue is analog over-exposure. If the means are low, the scaling is
wrong.

**Fix options:**
- Short-term: add the diagnostic so the next hardware run tells us which it is.
- Medium-term: implement the per-frame exposure read-back strategy described in
  `.opencode/plans/exposure-per-frame-fix.md`.
- Optional digital workaround: add `--tiff-brightness` multiplier or an option
  to save unscaled raw 12-bit TIFFs for comparison.

### 3. TIFF file size and IR layer

Inspection of the actual files:
- `img__001.tiff` (older, ~36 MB): 8-bit RGB (`BitsPerSample = 8,8,8`).
- `img__021.tiff` (new, ~71 MB): 16-bit RGB (`BitsPerSample = 16,16,16`),
  uncompressed.
- `SamplesPerPixel = 3` in the new TIFFs, so **no IR layer is present**.

Since `--infrared` was not passed, `ir_arr` is `None` and the IR code path is
not used. The size increase is therefore correct and expected: 12-bit data
scaled to 16-bit doubles the bytes.

**However, the IR code path has two latent bugs that will crash if `--infrared`
is used:**
- `_do_batch_scan()` parses Stage A with `channel_offsets=(0, 1, 2, 0)`, which
  horizontally shifts the R and G channels — wrong for IR extraction.
- `_write_tiff_16bit_rgb()` reshapes the 288×433 IR array to the 2880×4332 RGB
  dimensions, which will raise a shape mismatch error.

**Fix:**
- Correct the Stage A channel offsets for IR extraction.
- Do not reshape low-res IR to full-res dimensions. Either save IR as a proper
  second IFD (dual IFD) at native resolution, or do not pack IR into the RGB
  TIFF until it has been upsampled.

**Also:** `_write_tiff_16bit_rgb()` accepts a `compression` parameter but
ignores it and writes uncompressed data. Either implement zstd/deflate
compression (would cut ~71 MB to roughly 30–40 MB) or remove the misleading
parameter.

## Implementation steps

1. **Fix JPEG auto-adjust for 16-bit input**
   - Update `_apply_auto_adjust()` in `coolscan/cli.py`.
   - Keep it fixture-free: add a unit test in `tests/` with synthetic uint16
     data and assert output is sensible uint8.

2. **Add raw 12-bit statistics logging**
   - In `_do_batch_scan()`, print `min/max/mean` per channel of `rgb_arr`
     before the 16-bit scaling line.
   - Guard with `if self.verbose` or only emit a single summary line.

3. **Fix 16-bit TIFF compression**
   - Update `_write_tiff_16bit_rgb()` to honour the `compression` argument,
   - or remove the argument and document that 16-bit TIFFs are uncompressed.
   - Prefer implementing compression for smaller files.

4. **Fix IR handling bugs**
   - Fix `channel_offsets` in Stage A IR parsing.
   - Fix IR reshape/IFD handling in `_write_tiff_16bit_rgb()`.
   - Add a test that calls the batch-scan path with `--infrared` mocked to
     ensure it no longer crashes.

## Verification

- Run `make check-all`.
- Re-run a hardware batch scan (`--depth 12`, no `--infrared`) and compare:
  - JPEG should no longer show false colour / posterization.
  - TIFF size should be smaller if compression is enabled.
  - Raw 12-bit statistics should reveal whether over-exposure is analog or
    digital.

## Open questions

- Should 16-bit TIFFs remain uncompressed or use zstd by default?
- Do we want an option to save unscaled raw 12-bit TIFFs for debugging?
- Is the film being scanned negative or positive? (This affects whether the
  JPEG inversion logic is correct.)
