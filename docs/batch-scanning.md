# Batch Scanning and Frame Detection

Derived from analysis of `ls40-batch.pcapng` via `tests/fixtures/golden_batch.txt` (6869 events).
Primary oracle: pcapng capture. Cross-referenced with `coolscan/protocol.py` WDB tables
and SANE backend (`backends-1.4.0/backend/coolscan3.c`).

## Overview

Batch scanning captures multiple frames from a film strip (e.g. 35mm negative with 6+ exposures).
Unlike a single-slide scan, batch mode scans the full strip sequentially, repositioning the
scan window and refocusing between each frame.

## Capture Summary

The batch capture was made with **color negative film** (positive film flag in WDB byte 49 = 0x01).
IR window (window 9) is active throughout for dust/scratch detection.

The scan proceeds in phases:
1. **Prescan** at 96 DPI (windows 1/2/3, no IR) -- auto-exposure calibration
2. **CONTROL_FRAME write** (0x8f, 52 bytes) -- defines frame boundary positions
3. **290 DPI strip scan** (windows 9/1/2/3) -- low-res preview of first frame region
4. **Full-res capture** -- 6 segments at 2900 DPI, separated by autofocus

## Scan Windows (WDB) in Batch Mode

Batch mode introduces two additional scan types beyond the single-scan types
(`prescan`, `setup`, `single_bw`, `normal`):

| Scan type | Resolution | Windows | Description |
|-----------|-----------|---------|-------------|
| `batch` | 290 DPI | 9, 1, 2, 3 | Initial 290 DPI configuration after prescan |
| `batch_between` | 290 DPI | 1, 2, 3 | Lightweight reconfig between full-res frames |

Both use `scan_kind=0x01` (normal), `scan_mode=0x02`, `image_comp=0x05` (RGB full),
`bpp=0x0c` (12-bit). Y offset and height are parameterized per frame.

### WDB Byte 50-51 Clarification

Byte 50 (scan_kind) and byte 51 (scan_mode) are consistent across all 5 analyzed
captures (single-bw, batch, batch-neg, single-negs, batch-session):

- **Byte 50 (scan_kind)**: `0x01` = normal/full-scan, `0x02` = prescan
- **Byte 51 (scan_mode)**: `0x02` in all observed cases

Prescan WDBs (96 DPI) always have byte 50 = `0x02`. All full-scan WDBs
(290 DPI setup, 2900 DPI capture) have byte 50 = `0x01`. This is consistent
across single-scan and batch mode. The `docs/unified-protocol-spec.md` mapping
(0x01=normal, 0x02=prescan) is confirmed correct.

**Initial WDBs sent during init**: The scanner sends 4 WDBs (windows 1/2/3/9) at
2900 DPI with `scan_kind=0x01` during initialization, before prescan. These appear
to configure the scanner's full-scan parameters in advance. They are NOT prescan
WDBs -- prescan WDBs follow later at 96 DPI with `scan_kind=0x02`.

## CONTROL_FRAME Payload (0x8f, 52 bytes)

The CONTROL_FRAME command (`2a 00 8f 00 00 03 00 00 34 00`) writes frame boundary
information. Sent multiple times per session:

- **single-bw**: 1 set (after prescan)
- **batch**: 2 sets (init placeholder + post-prescan)
- **batch-neg**: 5 sets (4 placeholder + 1 real)
- **single-negs**: 20 sets (one per slide/adjustment)
- **batch-session**: 2 sets (init placeholder + post-prescan)

### Header (4 bytes)

```
Bytes 0-1: 0x0032 (50) -- meaning unclear, not payload length (actual = 52)
Byte  2:   0x06     -- scanner's max frame capacity (from INQUIRY page 0xc1)
Byte  3:   0x00     -- purpose unknown
```

Byte 2 is the scanner's maximum frame capacity (6 for LS-40 ED), NOT the number of
entries in the payload. The payload always contains exactly 3 entries (48 bytes of
entry data + 4-byte header = 52 bytes total). This value is constant across all
captures regardless of how many frames are actually scanned.

### Per-Frame Entries (16 bytes each, 3 entries)

```
Bytes 0-3:  Y start position (big-endian uint32, device units)
Bytes 4-7:  X-related field (pattern: frame_index * 8 + constant, meaning unclear)
Bytes 8-11: Y end position (big-endian uint32, device units)
Bytes 12-15: X-related field (pattern: frame_index * 8 + constant, meaning unclear)
```

**Decoded batch payload** (after prescan, `golden_batch.txt` line 281):

| Entry | Y start | Y end | Height |
|-------|---------|-------|--------|
| 1 | 30 | 4380 | 4350 |
| 2 | 8710 | 13020 | 4310 |
| 3 | 17380 | 21680 | 4300 |

**Decoded single-BW payload** (`golden_single_bw.txt` line 430):

| Entry | Y start | Y end | Height |
|-------|---------|-------|--------|
| 1 | 590 | 4920 | 4330 |
| 2 | 9280 | 13550 | 4270 |
| 3 | 17930 | 22200 | 4270 |

The Y positions define 3 scan regions. In batch mode with 6 frames, each region covers
2 frames (region 1: frames 0-1, region 2: frames 2-3, region 3: frames 4-5). The
scanner steps through these regions sequentially, scanning each frame within a region
before moving to the next.

CONTROL_FRAME is sent multiple times per session with updated boundaries. The first
transmission (during init) often has placeholder values (y_start=0, y_end=4332).
Subsequent transmissions refine boundaries based on prescan analysis. In multi-slide
captures (single-negs), CONTROL_FRAME is sent anew for each slide with adjusted y_start
values while y_end remains constant.

**X-related fields** (bytes 4-7 and 12-15) follow a pattern of `frame_index * 8 + constant`
but the meaning is unknown. Values are large (65546-2.6M for single-BW, 6-2.6M for batch)
and don't correspond to obvious pixel coordinates.

## Full-Resolution Batch Capture Frame Structure

After the initial 290 DPI strip scan, the scanner enters the full-res phase. The capture
(`golden_batch.txt` lines 406-6807) shows 6 image segments separated by 5 autofocus
operations. Each segment has a **three-stage scan pipeline**:

### Three-Stage Scan Pipeline (per segment)

Every segment executes three sequential scan stages, each with its own window
configuration, LUT upload, and SIMPLE_SET activation:

**Stage A: 290 DPI batch scan (IR + RGB, 4 windows)**
- Only for segments 1-5 (segment 0 skips this; uses initial strip scan instead)
- SET_WINDOW windows 9/1/2/3 at 290 DPI (`batch` type)
- LUT upload for all 4 windows (8192 bytes each)
- SIMPLE_SET `1b 00 00 00 04 00` + `09 01 02 03` (activate 4 windows)
- READ datatype 0x87 (status/progress query, 6-byte + 33-byte response)
- SIMPLE_SET reissue (REISSUE handling)
- Processing wait (scanner returns PROCESSING status)
- GET_WINDOW windows 9/1/2/3 at 290 DPI (verifies config)
- **4 image READ blocks**: 3x258048 + 1x223488 (each returns 65508 bytes)

**Stage B: 290 DPI batch_between scan (RGB only, 3 windows)**
- SET_WINDOW windows 1/2/3 at 290 DPI (`batch_between` type, no IR)
- LUT upload for 3 windows
- SIMPLE_SET `1b 00 00 00 03 00` + `01 02 03` (activate 3 windows)
- READ datatype 0x87 (status/progress query)
- SIMPLE_SET reissue
- Processing wait
- GET_WINDOW windows 1/2/3 at 290 DPI (verifies config)
- **3 image READ blocks**: 2x259200 + 1x229824 (each returns 65508 bytes)

**Stage C: 2900 DPI full-res scan (RGB only, 3 windows)**
- SET_WINDOW windows 1/2/3 at 2900 DPI (`normal` type, 8-bit)
- LUT upload for 3 windows
- SIMPLE_SET `1b 00 00 00 03 00` + `01 02 03`
- READ datatype 0x87 (status/progress query)
- SIMPLE_SET reissue
- Processing wait
- **145 image READ blocks**: 144x259200 + 1x103680 (each returns 65508 bytes)
- **No STOP_SCAN between segments.** The scanner returns to READY naturally after the exact byte count is consumed; the next segment begins with auto-focus and TUR polling.

### Segment 0 (initial) -- Modified Pipeline

Segment 0 differs from segments 1-5:
- **Skips Stage A** (uses the initial 290 DPI strip scan from lines 426-444 instead)
- Executes Stage B (batch_between at 290 DPI, fixture lines 454-534)
- Executes Stage C (2900 DPI full-res, fixture lines 535-1367)
- Total READ blocks: 3 (Stage B) + 145 (Stage C) = **148 blocks**

### Segments 1-5 (after autofocus) -- Full Pipeline

Each follows the complete three-stage pattern:
1. **Wait / TUR polling** after the previous segment's Stage C; no STOP_SCAN is issued
2. **Autofocus** -- `e0 00 a0` + 9-byte payload + `c1` execute + `e1 00 c1` + 9-byte response
3. **Stage A** (290 DPI with IR): 4 READ blocks
4. **Stage B** (290 DPI RGB): 3 READ blocks
5. **Stage C** (2900 DPI full-res): 145 READ blocks
- Total READ blocks: 4 + 3 + 145 = **152 blocks**

### READ Block Allocation Pattern

Each READ(10) command uses `28 00 00 00 00 00 XX XX XX 80` format, where bytes 6-8
are big-endian allocation length. The scanner always returns 65508 bytes per block
(until the final block of each stage, which may be shorter).

| Stage | Alloc sizes | Block count | Total returned |
|-------|------------|-------------|----------------|
| A (290 DPI, 4W) | 3x258048 + 1x223488 | 4 | 262,032 |
| B (290 DPI, 3W) | 2x259200 + 1x229824 | 3 | 196,524 |
| C (2900 DPI) | 144x259200 + 1x103680 | 145 | 9,498,660 |

The varying allocation lengths within a stage suggest the scanner computes per-line
transfer sizes and batches them into ~64KB chunks. The final chunk of each stage
has a smaller allocation because it covers the remaining lines.

### What Are Stages A and B Reading?

Both Stage A (4 windows, with IR) and Stage B (3 windows, RGB only) scan at 290 DPI
over the same Y range as the full-res frame. The data returned is **actual image pixel
data** at low resolution, not status metadata:

- Stage A: 262,032 bytes from 4 windows at 290 DPI
- Stage B: 196,524 bytes from 3 windows at 290 DPI

At 290 DPI with width=2870 device units and height=4332:
- Pitch = 2900/290 = 10, so actual pixels: 287 x 433
- Stage B (3 channels, 1 byte/pixel): 287 * 433 * 3 = 372,984 bytes expected
- Actual returned: 196,524 bytes (significantly less than expected)

The discrepancy suggests either: (a) the 290 DPI scan uses a narrower width,
(b) data is compressed/packed differently, or (c) not all lines are transferred.
The datatype for these reads is 0x00 (IMAGE_DATA), same as full-res reads.

**Open question:** Why does the scanner perform two intermediate-resolution scans
before each full-res frame? Hypotheses:
- Exposure calibration update (but no AE command is issued between stages)
- Focus verification (but no AF command between stages)
- Shading calibration (but no shading datatype is used)
- Firmware requirement for internal state machine progression

### Y Offset Progression

| Segment | Y offset | Y end | Height | READ blocks | Full-res data |
|---------|----------|-------|--------|-------------|---------------|
| 0 (initial) | 30 | 4362 | 4332 | 148 | 9.5 MB |
| 1 | 4380 | 8712 | 4332 | 152 | 9.5 MB |
| 2 | 8710 | 13042 | 4332 | 152 | 9.5 MB |
| 3 | 13020 | 17352 | 4332 | 152 | 9.5 MB |
| 4 | 17380 | 21712 | 4332 | 152 | 9.5 MB |
| 5 | 21680 | 26012 | 4332 | 152 | 9.5 MB |

Y increment between segments is **constant at 4330 device units** (1 device unit = 1 pixel
at 2900 DPI). Segments are essentially contiguous with tiny gaps/overlaps of 18-32 pixels
(likely autofocus drift or rounding).

Total coverage: 21,632 pixels = 189.5 mm = 7.46 inches at 2900 DPI.

### Frame Spacing Is Fixed

Critically, the Y offset increment is exactly 4330 for every segment. There is **no evidence**
in the capture of dynamic frame detection -- the scanner uses fixed, pre-computed spacing.
This suggests the software (Nikon Scan) assumes a standard film format (35mm frames at
~36mm spacing) rather than analyzing prescan data to find frame borders.

## 290 DPI Strip Scan (Initial Preview)

Before the full-res phase, after prescan and CONTROL_FRAME write, the scanner performs
a 290 DPI scan of the first frame region (fixture lines 406-444):

- Windows active: 9/1/2/3 (IR + RGB, `batch` type)
- WDB: yoff=30, height=4332, 290 DPI, RGB full, 12-bit
- 4 READ(10) blocks: 3x258048 + 1x223488 allocation (each returns 65508 bytes)
- Total data: 262,032 bytes

This scan only covers the first frame region (yoff=30 to yend=4362), not the full strip.
Purpose is likely to generate a preview image for the software UI. Segment 0 uses this
initial strip scan data in place of Stage A (the per-frame 290 DPI batch scan).

Segments 1-5 repeat a similar 290 DPI scan with IR (Stage A) before each full-res frame,
suggesting the scanner needs fresh low-res data for some internal calibration or state
machine requirement before proceeding to full-res capture.

## Prescan and Exposure Data

The prescan phase (`golden_batch.txt` lines 66-75) reads exposure data via READ(10)
datatype 0x8e:

- 6-byte header: `00 8e 00 00 0d 7c` (datatype 0x8e, additional length 0x0d7c = 3452)
- 3392-byte exposure/calibration table

The exposure table contains structured data (repeating 4-byte patterns with incrementing
values), but no obvious frame boundary markers. The data appears to be per-channel
exposure statistics and calibration coefficients.

### Can Prescan Data Reveal Frame Borders?

The prescan scans the full strip at 96 DPI (WDB height=34656). The resulting image data
is returned via READ blocks at 130752 allocation (5 blocks: 5x130752, each returning
65508 bytes, fixture lines 210-235). Total: ~327 KB of 96 DPI strip data.

At 96 DPI, pitch = 2900/96 ≈ 30.2. The 34656 device units = ~1148 actual lines.
Width at 96 DPI: 2870/30.2 ≈ 95 pixels. With 3 channels: 95 * 1148 * 3 = 328,440 bytes.

**Frame detection hypothesis:** If we analyze the prescan image data, we could detect
frame borders by looking for:
- Per-frame density changes (different exposures on the strip)
- Physical film borders (perforation patterns, frame dividers)
- Edge detection on the low-res preview

However, the SANE backend does NOT do this -- it uses fixed spacing computed from
`frame_offset = resy_max * 1.5 + 1 = 4351`. Nikon Scan likely does the same.
Dynamic frame detection would be a software feature, not a scanner capability.

## Autofocus Sequence

The batch capture performs autofocus before each full-res frame. There are **6 autofocus
operations total**: 1 before the 290 DPI preview scan, and 5 during the full-res phase
(before segments 1-5). Segment 0 uses the focus position from the first autofocus.

### Command Format (from SANE `cs3_autofocus()`, `coolscan3.c:2685-2707`)

```
CDB:  e0 00 a0 00 00 00 00 00 09 00    (WRITE, datatype 0xa0, 9 bytes)
Data: [focusx: 4 bytes BE] [focusy: 4 bytes BE] [trailing: 1 byte]
Exec: c1 00 00 00 00 00                (EXECUTE)
```

SANE computes focus coordinates as:
```c
s->real_focusx = s->real_xoffset + s->real_width / 2;   // center of scan window
s->real_focusy = s->real_yoffset + s->real_height / 2;  // center of scan window
```

### Autofocus Payload Values from Capture

| AF # | Fixture line | focusx | focusy | Target |
|------|-------------|--------|--------|--------|
| 0 | 287 | 1435 | 2196 | Frame 0 center (yoff=30 + 4332/2) |
| 1 | 1380 | 1435 | 6546 | Frame 1 center (yoff=4380 + 4332/2) |
| 2 | 2468 | 1435 | 10876 | Frame 2 center (yoff=8710 + 4332/2) |
| 3 | 3556 | 1435 | 15186 | Frame 3 center (yoff=13020 + 4332/2) |
| 4 | 4644 | 1435 | 19546 | Frame 4 center (yoff=17380 + 4332/2) |
| 5 | 5732 | 1435 | 23846 | Frame 5 center (yoff=21680 + 4332/2) |

`focusx = 1435` is the center of the 2870-pixel scan width. `focusy` increments by
~4330 per frame, matching the Y offset progression.

### Autofocus Timing

Each autofocus operation takes ~15 seconds (from TUR PROCESSING to READY). The scanner
returns `0202040100000000` (PROCESSING) during the operation, then `0000000000000000`
(READY) when done.

### Autofocus Response (e1/c1, 9 bytes)

After each autofocus, the scanner returns a 9-byte response via READ(10) datatype 0xc1.
Bytes 4-5 contain a focus position value that varies slightly per frame:

| AF # | Response focus value | Delta from first |
|------|---------------------|------------------|
| 0 | 61184 | -- |
| 1 | 60416 | -768 |
| 2 | 60160 | -1024 |
| 3 | 60928 | -256 |
| 4 | 60928 | -256 |
| 5 | 62208 | +1024 |

The variation is small (+/- 1024 out of ~61000), suggesting the film strip is mostly
flat with slight warping. SANE reads back focus via `cs3_read_focus()` after each
autofocus call.

### Teardown

## Open Questions

~~1. **CONTROL_FRAME entry count vs actual segments**: 3 entries define 3 regions, but~~
~~   6 segments are scanned. [Resolved: each region covers 2 frames.]~~
2. **X-related fields in per-frame entries**: Pattern is `frame_index * 8 + constant` but
   meaning is unknown.
3. **Why multiple CONTROL_FRAME transmissions**: The scanner accepts the same CONTROL_FRAME
   payload multiple times with varying boundaries. Is this required for the firmware state
   machine, or does the scanner use only the last transmission?
4. **Dynamic frame detection**: Fixed Y spacing suggests no frame border detection from
   prescan data, but this needs confirmation from SANE source analysis.
5. **Purpose of Stage A/B (290 DPI intermediate scans)**: Every segment (except the
   initial strip scan for segment 0) performs two 290 DPI scans before the full-res
   capture. Stage A uses 4 windows (with IR), Stage B uses 3 windows (RGB only).
   Both return actual image pixel data (datatype 0x00). Neither stage is accompanied
   by AE, AF, or shading commands. Hypotheses:
   - Internal firmware state machine requirement (scanner must progress through
     resolution stages before allowing full-res read)
   - Exposure/shading calibration at low resolution before committing to full-res
   - Data returned is discarded by host software (Nikon Scan) and serves only
     to advance the scanner state
   - To test: try skipping Stage A/B and going directly to Stage C after AF
6. **IR window in Stage B**: Stage B omits IR (windows 1/2/3 only) while Stage A
   includes it. Why the two-stage approach instead of one 290 DPI scan?
7. **Stage B data byte count mismatch**: Expected 372,984 bytes (287x433x3) but only
   196,524 returned. Either the scan area is smaller than the WDB suggests, or data
   is packed/compressed differently at 290 DPI.
 8. **Segment 0 lacks Stage A**: Segment 0 skips the 4-window 290 DPI scan (Stage A),
    using the initial strip scan instead. This confirms Stage A is redundant with the
    initial preview scan for the first frame.
 9. **Hardware test preview decoding is speculative**: `test_hardware_full_scan.py`
    saves Stage A/B previews as PNGs using assumed 287×433×12-bit dimensions, but the
    returned byte counts (~262 KB for Stage A, ~197 KB for Stage B) do not match those
    assumptions. The PNGs may be garbage until the packing/format is understood; raw
    `.raw` files are saved alongside for analysis.

## Investigation: Black Frames in Batch Mode (July 2026)

**Symptom:** During initial hardware testing, frames 1, 2, and 4 produced
almost entirely black images (~20 lines of real image at the top, remainder black),
while frames 0, 3, and 5 produced complete images.

### Initial Hypothesis

The code used `frame_y = first_y + i * step` (with `first_y=30, step=4330`) to compute
frame positions, producing: 30, 4360, 8690, 13020, 17350, 21680.

The golden fixture from `ls40-batch.pcapng` showed Nikon Scan used different positions:
30, 4380, 8710, 13020, 17380, 21680 — the CONTROL_FRAME entry boundaries.

The hypothesis was: "the scanner requires y-positions at CONTROL_FRAME entry boundaries."

### Changes Made

A fix was implemented (`commit 677ab5d`) that:

1. Added `_GOLDEN_BATCH_POSITIONS = [30, 4380, 8710, 13020, 17380, 21680]` — hardcoded
   golden positions from the pcapng capture
2. Added `_control_frame_positions()` method that returns these positions for default
   geometry (6 frames, first_y=30, frame_height=4332, step=4330)
3. Modified `batch_scan_to_frames()` to use `frame_positions[i]` instead of `first_y + i*step`

### Hardware Test Results

After the fix, all 6 frames produced complete image data. The logs confirmed
the correct y-positions were being used:
- Frame 1: y=4380 (was 4360)
- Frame 2: y=8710 (was 8690)
- Frame 4: y=17380 (was 17350)

### Uncertainty: Was the Y-Position Change the Actual Fix?

**This is uncertain.** Comparative analysis of the old and new hardware logs reveals
two differences:

| Factor | Old Log (broken) | New Log (fixed) |
|--------|------------------|------------------|
| Y-positions | 4360, 8690, 17350 | **4380, 8710, 17380** |
| Exposure calibration | **4 bytes** (empty) | 1904 bytes (full) |

The exposure calibration difference is NOT a code change — it's scanner state.
The old log shows the scanner returning only 4 bytes of calibration data
vs 1904 bytes in the new log. This suggests the scanner was pre-calibrated
from the previous run when the new log was captured.

**Hypothesis (uncertain):** Both factors may have contributed:

1. **Y-positions must be within CONTROL_FRAME regions.** The old positions
   (4360, 8690, 17350) fell slightly outside their respective CONTROL_FRAME
   entry ranges (entry 0: 30-4380, entry 1: 8710-13020, entry 2: 17380-21680).
   The 20-pixel deviation is tiny (~0.5% of frame height) but could cause the
   scanner to clip or reject image data for frames starting outside their
   designated regions.

2. **Exposure calibration state may have been decisive.** Without proper
   calibration (4 bytes vs 1904 bytes), the scanner's A/D conversion and
   image processing may produce dark/garbage output regardless of y-position.

### Open Question

**Did the y-position fix work because of correct positions, or because the
scanner happened to be pre-calibrated?**

To test this definitively:
1. Disconnect and reconnect the scanner (cold start)
2. Run batch scan with the fixed code
3. Verify the exposure calibration returns 1904 bytes (not 4)
4. If frames are still black with 4 bytes of calibration, there's a second
   bug requiring investigation

### Lessons Learned

1. **Hardware test state carries over.** Scanner calibration persists across
   USB sessions. Always test with cold-start conditions to isolate bugs.

2. **The golden y-positions encode Nikon Scan's prescan-adjusted film edge
   detection.** The variation from `first_y + i*step` (±20 pixels) suggests
   Nikon Scan analyzes the 96 DPI prescan to find actual frame borders,
   then adjusts CONTROL_FRAME entries accordingly. We cannot replicate this
   without implementing similar film-edge detection.

3. **CONTROL_FRAME entry boundaries are not arbitrary.** The scanner may
   enforce that per-frame y-offsets fall within the ranges defined by
   CONTROL_FRAME entries. Using `first_y + i*step` with step=4330 produces
   values that drift outside these ranges.

### Status

- [x] Y-position fix implemented (uses golden positions for default geometry)
- [x] All 6 frames produce image data with fixed code + pre-calibrated scanner
- [ ] Confirmed: Does fix work with cold-start scanner?
- [ ] Confirmed: Does fix work with non-default geometry?

## Could We Scan the Full Strip Continuously at 2900 DPI?

This is an open experimental question. The frame-by-frame approach used by Nikon Scan
and SANE may be a software choice, not a hardware requirement.

### What we know

- **INQUIRY page 0xc1** reports `n_frames=6` and `boundaryy=4332` device units (37.9 mm
  at 2900 DPI, roughly one 35mm frame height)
- **SANE's `frame_offset`** formula: `resy_max * 1.5 + 1 = 4351` -- close to the capture's
  4330 but not exact (SANE comment: "works for LS-30, maybe not for others")
- **Prescan WDB uses height=34656** at 96 DPI, which exceeds `boundaryy=4332` -- so
  `boundaryy` may NOT be a hard limit on WDB height
- **Device units are resolution-independent**: WDB height=34656 at 96 DPI returns
  1147 actual lines (pitch = 2900/96 = 30.2), covering 303.5 mm of film strip

### Hypothesis

If the scanner accepts a WDB with `height > boundaryy` at 2900 DPI (as it does for
prescan), we could theoretically scan the entire ~228mm strip in one continuous operation:

- SET_WINDOW: yoff=30, height=26012 (or larger), 2900 DPI
- Single autofocus at center of strip
- One START_SCAN, read ~298 MB of continuous image data
- Detect frame borders in software from the prescan or image data

### Risks

- **Firmware may reject it**: The scanner might enforce `boundaryy` as a hard limit for
  normal scans (scan_kind=0x01) even though it allows larger heights for prescan (0x02)
- **Focus variation**: Film strips aren't perfectly flat. Per-frame autofocus compensates
  for this. A single continuous scan would use one focus position for the entire strip
- **Exposure variation**: Different frames on the same strip may have different lighting.
  Per-frame AE compensates for this
- **Memory**: ~298 MB of raw data (2870 x 26012 x 3 channels) needs to be buffered
- **Error recovery**: If the scan fails mid-strip, you lose everything rather than just
  one frame

### Experiment Design: Continuous Scan Test

Test whether the scanner accepts WDB height > boundaryy (4332) at 2900 DPI.

**Test 1: Boundary probe**
- SET_WINDOW: yoff=30, height=8664 (2 frames), 2900 DPI, windows 1/2/3
- LUT upload + SIMPLE_SET
- READ datatype 0x87 (status query)
- Observe: Does the scanner accept the WDB? Does it return READY or error?

**Test 2: Full strip continuous**
- SET_WINDOW: yoff=30, height=26012 (full strip), 2900 DPI
- Single autofocus at strip center
- START_SCAN and read continuous image data
- Expected data: ~2870 x 26012 x 3 = ~223 MB raw

**Expected outcomes:**
- If accepted: We can scan the full strip continuously, detecting frames in software
- If rejected (ILLEGAL REQUEST / sense key 0x05): boundaryy is a hard firmware limit
  for scan_kind=0x01 (normal scans), but not for prescan
- If accepted but produces garbage: firmware allows it but doesn't handle multi-frame
  exposure/focus correctly

**Prerequisites for hardware test:**
- Implement `_build_scan_window_wdb()` with parameterized yoff/height in protocol.py
- Implement continuous scan read loop (handle REISSUE, short reads)
- Need physical scanner connected
