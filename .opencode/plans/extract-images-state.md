# State of `--extract-images` feature in `scripts/analyze_capture.py`

## Current goal
Extract image frames from pcapng captures and re-emit them as TIFF/JPEG so
that capture-driven image regressions can be reproduced without the scanner.

## What is implemented
- `extract_image_frames(events, output_dir, depth=12, width=2880, height=4332,
  num_channels=3, fmt="both")` in `scripts/analyze_capture.py`.
- CLI flags: `--extract-images DIR`, `--extract-depth {8,12}`,
  `--extract-width`, `--extract-height`, `--extract-channels`,
  `--extract-format {tiff,jpeg,both}`.
- Frame detection heuristic:
  - A new frame starts at `SCAN` (0x24).
  - Subsequent `READ(10)` with datatype=0x00 collects following `DATA_BLOCK`
    IN payloads.
  - Any other OUT command (except `TEST_UNIT_READY` and `PHASE_CHECK`) flushes
    the current frame.
  - Frames with computed height < 100 pixels are skipped as prescan/preview
    fragments.
- Uses `coolscan.scanner._parse_scan_data` and
  `coolscan.cli._apply_auto_adjust / _save_jpeg / _save_tiff_dual_ifd`.
- Fixture-free tests in `tests/test_analyze_capture.py` cover two-frame,
  tiff-only, jpeg-only, no-frames, and small-frame-skipping cases.

## Current status
**Partially usable for pcapng 8-bit preview strips with manual overrides.
Not production-ready for full 12-bit scans or arbitrary captures.**

## What works
- Synthetic captures with known width/height/depth pass tests and produce valid
  TIFF/JPEG files.
- `ls40-single-bw.pcapng` and `ls40-batch.pcapng` produce usable output when
  forced to `--extract-depth 8` and `--extract-width 2870`.
- The batch capture yields 6 main frames, matching the 6 batch frames from the
  `logs/scan_20260724_091248.txt` hardware run.

## Known problems
1. **Wrong default width.** `--extract-width` defaults to `2880`, but the WDB in
   the repo captures declares `2870` pixels. Using `2880` causes visible diagonal
   inter-channel offsets.
2. **Wrong default depth for repo captures.** `--extract-depth` defaults to `12`,
   but the actual bulk payloads in the repo pcapngs are 8-bit. With `depth=12`
   the vertical dimension is halved and the image is corrupt.
3. **Wrong default height.** `--extract-height` defaults to `4332` (from the
   WDB), but the actual captured data per frame is only about `1103` lines. The
   function recomputes actual height from the payload, but the defaults are
   misleading.
4. **No WDB/control-frame driven geometry.** Width, height, depth, and channel
   layout are not parsed from the capture; they must be supplied by the user.
5. **Reuses live-scan decoder for capture data.** `_parse_scan_data` was written
   for live scanning, assumes line-plane RGB interleaving, `format="plane"`, and
   `LS40_CHANNEL_OFFSETS`. This may not match the actual layout stored in the
   pcapngs.
6. **Text-format captures cannot be extracted.** The text log
   `logs/scan_20260724_091248.txt` truncates bulk payloads, so the analyzer
   finds no image frames.
7. **JPEG auto-adjust is still fragile.** The extraction down-converts 16-bit
   data to 8-bit before calling `_apply_auto_adjust`, which is a workaround. The
   underlying function has a known bug with 16-bit input (see
   `.opencode/plans/batch-jpeg-tiff-fix.md`).
8. **No IR / multi-IFD support.** The IR channel is ignored; `--infrared` is not
   supported.
9. **No payload-size mismatch warning.** The WDB declares ~39 MB of image data
   but the actual payload is only ~10 MB; the user has no clear signal that the
   data is a preview/thumbnail.

## Workaround for current repo captures
To extract the 6 preview frames from the repo batch capture without diagonal
artifacts:

```bash
python3 scripts/analyze_capture.py ls40-batch.pcapng \
  --extract-images extract-test \
  --extract-depth 8 \
  --extract-width 2870 \
  --extract-format tiff
```

For the single scan:

```bash
python3 scripts/analyze_capture.py ls40-single-bw.pcapng \
  --extract-images extract-test \
  --extract-depth 8 \
  --extract-width 2870 \
  --extract-format tiff
```

## Next steps
1. Parse WDBs and the `CONTROL_FRAME` table to derive width, height, bit depth,
   and channel layout automatically.
2. Determine the actual image data layout in the pcapng payloads and either
   reuse or replace `_parse_scan_data`.
3. Warn clearly when the captured payload is much shorter than the WDB-declared
   frame.
4. Stop hardcoding `LS40_CHANNEL_OFFSETS` and `format="plane"`; derive them from
   the WDB or command context.
5. Keep the fixture-free tests in `tests/test_analyze_capture.py` passing.
6. Once the decoder is correct, address the underlying JPEG auto-adjust and TIFF
   compression bugs described in `.opencode/plans/batch-jpeg-tiff-fix.md`.

## Related files
- `scripts/analyze_capture.py` — `extract_image_frames()` and CLI flags.
- `tests/test_analyze_capture.py` — fixture-free tests.
- `coolscan/scanner.py` — `_parse_scan_data`, `LS40_CHANNEL_OFFSETS`.
- `coolscan/cli.py` — `_apply_auto_adjust`, `_save_jpeg`, `_save_tiff_dual_ifd`.
- `coolscan/protocol.py` — WDB and `CONTROL_FRAME` definitions.
- `reference/golden_single_bw.txt`, `ls40-single-bw.pcapng`, `ls40-batch.pcapng`
  — reference captures.
- `logs/scan_20260724_091248.txt` — successful batch run text log, not usable
  for image extraction.
- `.opencode/plans/batch-jpeg-tiff-fix.md` — plan for live-scan output-quality
  bugs.
