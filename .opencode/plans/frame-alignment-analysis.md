# Frame Alignment Analysis

*Derived from direct comparison of ls40-batch.pcapng (Nikon Scan),
ls40-single-bw.pcapng (single negative), and our own hardware captures
(hardware_scan_output_capture.txt).*

## How Nikon Scan Detects Frame Positions

Nikon Scan **does not use hardcoded frame positions**. It computes per-frame
Y offsets from the prescan image data for each film strip:

1. **Initial CONTROL_FRAME (nominal):** Before prescan, Nikon sends a
   CONTROL_FRAME with `y_start=0` and nominal step (4332), dividing the full
   film area into rough 3 regions:
   ```
   Entry 0: y_start=0     y_end=4332   (rough frames 0-1)
   Entry 1: y_start=8664  y_end=12996  (rough frames 2-3)
   Entry 2: y_start=17328 y_end=21660  (rough frames 4-5)
   ```

2. **Prescan analysis:** The 96 DPI prescan image (2870x~361 pixels, 12-bit)
   is analyzed to detect actual film edges and frame boundaries. Nikon looks
   for density transitions within each nominal region.

3. **Refined CONTROL_FRAME:** After prescan, Nikon sends a second
   CONTROL_FRAME with prescan-adjusted positions:
   ```
   Entry 0: y_start=30    y_end=4380   (adjusted frames 0-1)
   Entry 1: y_start=8710  y_end=13020  (adjusted frames 2-3)
   Entry 2: y_start=17380 y_end=21680  (adjusted frames 4-5)
   ```

4. **Per-frame WDB setup:** Each frame uses the prescan-derived Y offset
   (e.g. 30, 4380, 8710, ...) in the SET_WINDOW WDB's byte 18-21 field.

The batch capture uses `[30, 4380, 8710, 13020, 17380, 21680]` -- these are
specific to THAT film strip. The single-BW capture uses `y_off=590` for its
single frame, again prescan-derived. Different film strips produce different
positions (+/-20-30 device units around nominal).

## CONTROL_FRAME Structure (52 bytes)

Confirmed from pcapng comparison:

```
Offset  Size  Description
0       2     Payload length (always 0x0032 = 52)
2       2     Frame count (0x0600 = 6 for 35mm strips)

Entry 0 (bytes 4-19, covers frames 0-1):
  4  4  y_start[0]  (uint32 big-endian, prescan-adjusted)
  8  4  x1[0]       (pattern: index-dependent, not a pixel coordinate)
  12 4  y_end[0]    (uint32, end of frame 1 / start of frame 2)
  16 4  x2[0]       (pattern: index-dependent)

Entry 1 (bytes 20-35, covers frames 2-3): [same structure]
Entry 2 (bytes 36-51, covers frames 4-5): [same structure]
```

The x1/x2 fields follow a fixed pattern based on entry index (not used as
pixel coordinates). The y_start/y_end values carry the actual frame boundary
information. Each entry covers 2 frames in an "every-2-frames" pattern.

## Structural Differences: Nikon Scan vs Our Implementation

| Aspect | Nikon Scan | Our Implementation | Impact |
|--------|-----------|-------------------|--------|
| **Initial nominal CF** | Sent before prescan (`y_start=0`) | Not sent | Scanner may lack full-film boundary context |
| **Frame positions** | Computed from prescan data | Hardcoded golden values | Off by 20-30 device units per film |
| **Cmd_28 wait after prescan** | 5 iterations (~10 s) | 2 iterations (~5 s) | Scanner may not have settled position |
| **Setup/teardown WDBs** | R/G/B/IR @ 2900dpi, y=0, mode=0x0002 (4 before, 4 after) | Not sent | Scanner internal state may differ |
| **Stage A exposure** | Varies per-frame between passes | Fixed from prescan cal | Image quality, not alignment |
| **Full-res exposure** | Varies per-frame (density compensation) | Fixed from prescan cal | Image quality, not alignment |

## Root Cause of Misalignment

Our code uses `_GOLDEN_BATCH_POSITIONS = [30, 4380, 8710, 13020, 17380, 21680]`
-- positions extracted from one specific Nikon Scan capture. These are correct
for that film strip but wrong for others. Each user's film strip has slightly
different frame positions, resulting in:

- **Top of image blank/off edge:** y_start is too small (scan begins before
  the actual emulsion area for that frame)
- **Portion of next image at top:** y_start is too large (scan begins into
  the area belonging to a previous frame)

The error compounds across frames because the step between our hardcoded
values (4330, 4330, 4310, 4360, 4300) may not match the actual step for the
user's specific film strip.

## Action Plan

### 1. [CRITICAL] Prescan Image Analysis for Frame Detection

Implement frame boundary detection from prescan data. The prescan image
(2870x~361 pixels at 96 DPI, 12-bit RGB) shows the full film strip with dark
frame separators visible as density drops.

Algorithm sketch:
- Convert prescan image to a grayscale luminance profile
- Average horizontally to get a 1-column Y-axis density curve
- Identify frame edges by finding transitions from dark (separator) to
  lighter (emulsion) regions within each nominal region
- Compute per-frame y_start as the center or top edge of each detected frame
- Update CONTROL_FRAME positions from detected boundaries

Pseudocode:
```python
def detect_frame_positions(prescan_image_data: bytes, frame_count: int) -> List[int]:
    """Analyze prescan image to find actual frame boundaries."""
    # Decode prescan: 2870x361, 12-bit RGB, plane-interleaved
    # Average horizontally to get per-row luminance
    luminance = horizontal_average(prescan_image_data)  # ~361 values

    # Find dark regions (frame separators) and bright regions (emulsion)
    # within each nominal region (divided by step=4330)
    nominal_step = prescan_height // frame_count
    positions = []
    for i in range(frame_count):
        region_start = i * nominal_step
        region_end = (i + 1) * nominal_step
        # Find the actual frame start within this region
        frame_start = find_emulsion_start(luminance, region_start, region_end)
        positions.append(frame_start)
    return positions
```

### 2. [MEDIUM] Send Initial Nominal CONTROL_FRAME

Before prescan, send a CONTROL_FRAME with nominal positions (`y_start=0`,
step=4332, 3 entries covering rough film area). This provides the scanner
with full-film boundary context before the refined positions are set.

```python
# In batch_scan_to_frames(), before prescan():
self.set_boundary(
    params=None, batch=True,
    frame_count=frame_count,
    first_y=0,           # nominal start
    frame_height=4332,   # nominal per region
    step=4332,           # nominal step
)
```

### 3. [MEDIUM] Add Setup/Teardown WDBs (mode=0x0002)

Send R/G/B/IR WDBs at 2900 DPI, y=0, mode=0x0002, film=0x81 before prescan
and after full scan completion. These appear to initialize/clean up scanner
internal state.

### 4. [LOW] Extend Post-Prescan Wait

Increase CMD_28 polling (`28000000000001fec080`) iterations from 2 to 5 to
match Nikon's ~10 second wait, ensuring the scanner has fully settled into
position before the full scan begins.
