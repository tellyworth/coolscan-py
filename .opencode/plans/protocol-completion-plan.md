# Plan: Complete Protocol Documentation

## Status

Draft. Awaiting review before marking active.

## Goal

Document every byte of every command, data payload, and response in the
pcapng captures / golden fixtures. Fill in all gaps between what SANE knows,
what the captures show, and what our docs say. Output is **documentation only**
— no code changes.

## Scope

All gaps identified in the protocol understanding assessment, plus findings
from the [SANE man page](http://sane-project.org/man/sane-coolscan3.5.html):

| # | Area | Current state | Target |
|---|------|--------------|--------|
| 1 | WDB fields (58 bytes) | Bytes 8, 10-13, 34 parameterized; rest hardcoded | Every byte documented with bit-field meaning |
| 2 | INQUIRY page responses | Sent but not decoded | Page 0xc1, 0xd1, 0xe1, 0xe2, 0xf0, 0xf8 response format documented |
| 3 | Internal info (0xe0) | ~12 of 30+ SANE fields parsed | All fields documented |
| 4 | Channel state (0x8c) | CDB format known | 10-byte response format documented |
| 5 | CONTROL_FRAME payload (52 B) | Hardcoded from capture | Structure decoded |
| 6 | Missing commands | SABORT (0xc0), e0/b4 undocumented | Added to docs/commands.md |
| 7 | Timing rules | Known from captures but undocumented | Documented in protocol.md |
| 8 | SANE features | Multi-sampling, padding, frame offset | Documented (even if not implemented) |
| 9 | Fixture anomalies | Unknown READ lengths, WDB variation | Explained |
| 10 | Man page findings | Subframe, depth, AE/WB, load/eject semantics | Documented in protocol docs |

---

## Phase 1: WDB Field Documentation (bytes 0–57)

### What's known

`coolscan-scsidef.h` defines the WDB as 117 bytes (0x75), but the LS-40 ED
only uses 58 bytes (0x3a in the CDB transfer length). The capture-derived
WDB tables in `protocol.py:_SCAN_WINDOW_WDB_TABLES` are the ground truth.

### What to document

Add a **WDB field reference table** to `docs/unified-protocol-spec.md` (or a
new `docs/wdb-fields.md`) covering every byte:

| Offset | Size | Name | Source | Notes |
|--------|------|------|--------|-------|
| 0-1 | 2B | WDB data length | SANE | Always 0x0000 for SET_WINDOW |
| 2-5 | 4B | Reserved | SANE | Always 0x00000000 |
| 6-7 | 2B | WDB descriptor length | SANE | Always 0x0032 (=50) |
| 8 | 1B | Window ID | Capture | 1=R, 2=G, 3=B, 9=IR |
| 9 | 1B | Reserved/AUTO flag | SANE | Always 0x00 in captures |
| 10-11 | 2B | X resolution (DPI) | SANE | 0x0060=96, 0x0122=290, 0x0b54=2900 |
| 12-13 | 2B | Y resolution (DPI) | SANE | Same as X |
| 14-17 | 4B | X offset | SANE | Upper-left X in device units |
| 18-21 | 4B | Y offset | SANE | Upper-left Y in device units |
| 22-25 | 4B | Width | SANE | In device units |
| 26-29 | 4B | Height | SANE | In device units |
| 30 | 1B | Brightness | SANE | 0x00 in all captures |
| 31 | 1B | Reserved | SANE | Always 0x00 |
| 32 | 1B | Contrast | SANE | 0x00 in all captures |
| 33 | 1B | Image composition | SANE | 0x05=RGB full, 0x02=grayscale |
| 34 | 1B | Bits per pixel | SANE man page | 0x08=8-bit, 0x0a=10-bit, 0x0c=12-bit, 0x0e=14-bit. At depth=8, scanner reduces data internally (quality loss). `maxbits` from INQUIRY page 0xc1 byte 82. |
| 35-47 | 13B | Reserved | SANE | Always 0x00 in captures |
| 48 | 1B | Multiread/ordering | SANE capture | Bit 6-7: ordering (0x00=dot, 0x01=line). Bits 0-3: multiread count-1. Values seen: 0x00, 0x03 |
| 49 | 1B | Averaging + pos/neg | SANE capture | Bit 7: averaging (0x80=on). Bit 0: pos/neg (0x01=pos). Values seen: 0x80, 0x81 |
| 50 | 1B | Scan kind | SANE | 0x01=normal, 0x02=prescan/AE, 0x20=AE, 0x40=AE_WB |
| 51 | 1B | Scan mode | SANE | 0x02=single, 0x10=multi |
| 52 | 1B | Color interleave | SANE | Always 0x02 |
| 53 | 1B | AE byte | SANE | Always 0xff |
| 54-57 | 4B | Exposure value | Capture | Big-endian uint32, 10ns units. Varies per channel. |

### Undocumented bit-fields (from `coolscan-scsidef.h`)

SANE defines additional fields at offsets beyond byte 57 that the LS-40 ED
doesn't use in SET_WINDOW (since the CDB limits to 58 bytes). Document
these as **SANE-only, not used by LS-40 ED**:

- Byte 0x35: shading (bit 6), analog gamma R/G/B (bits 3-5), averaging (bits 0-2)
- Byte 0x58-0x59: maximum resolution (GET_WINDOW only)
- Byte 0x5c: LUT-R (nibble 4), LUT-G (nibble 0)
- Byte 0x5d: LUT-B (nibble 4)
- Byte 0x61-0x63: exposure time unit R/G/B
- Byte 0x65: stop flag (bit 0)
- Byte 0x66-0x68: gain R/G/B
- Byte 0x69-0x73: exposure time variable R/G/B (4 bytes each)

### Verification

Cross-check every field offset against:
- `coolscan-scsidef.h` (SANE field definitions)
- `_SCAN_WINDOW_WDB_TABLES` in `protocol.py` (actual wire bytes)
- `golden_single_bw.txt` lines 88-120 (prescan WDBs), 430-480 (full scan WDBs)

---

## Phase 2: INQUIRY Page Response Formats

### What's known

The golden fixture shows INQUIRY page queries as two-step: first get length
(4 bytes), then get full data. Pages queried: 0x01, 0xd1, 0xc1, 0xe1, 0xe2,
0xf0, 0xf8.

### What to document

Add an **INQUIRY page reference** to `docs/commands.md`:

**Page 0x01 (Page Directory)** — golden fixture line 27:
- Response: `06 00 00 11` (length=0x11=17, so full response is 21 bytes)
- Full response (line 32): `06 00 00 11 00 01 40 41 46 51 60 61 c1 d1 e1 f0 f8 e2 fb fc`
- Byte 0: response code (0x06)
- Byte 3: additional length (0x11)
- Bytes 4+: page codes available
- **Undocumented:** what pages 0x40, 0x41, 0x46, 0x51, 0x60, 0x61, 0xfb, 0xfc are

**Page 0xc1 (Device Configuration)** — golden fixture lines 44-50:
- SANE reads: maxbits (byte 82), resx_optical/max/min (18-23),
  boundaryx (36-39), resy (40-45), boundaryy (58-61),
  focus range (76-79), n_frames (75)
- **Action:** Extract the actual 85-byte response from the fixture and
  document each field offset

**Page 0xd1 (MUD Info)** — golden fixture lines 34-43:
- Response (line 42): `06 d1 00 18 07 42 02 46 00 00 0a 00 00 00 40 09 04 00 00 00 01 03 ff ff 00 00 00`
- **Undocumented:** field meanings

**Pages 0xe1, 0xe2, 0xf0, 0xf8** — present in fixture but completely undocumented:
- **Action:** Extract responses from fixture, document byte count and
  any recognizable patterns

### Verification

Extract each page response from `golden_single_bw.txt` using:
```bash
awk -F'\t' 'NR==LINE {print $4}' tests/fixtures/golden_single_bw.txt
```
Cross-reference field offsets with SANE's `cs3_full_inquiry()` at
`coolscan3.c:2430-2530`.

---

## Phase 3: Internal Info Structure (datatype 0xe0)

### What's known

SANE reads 256 bytes via `READ(10)` datatype 0xe0. Our `get_internal_info()`
parses ~12 fields. SANE's `coolscan-scsidef.h` defines 30+ accessors.

### What to document

Add an **Internal Info field reference** to `docs/commands.md`:

Fields SANE parses but we don't document:

| Offset | Size | Name | SANE macro | Our status |
|--------|------|------|-----------|-----------|
| 0x00 | 1B | AD bits | `get_DI_ADbits` | Parsed |
| 0x01 | 1B | Output bits | `get_DI_Outputbits` | Parsed |
| 0x02 | 2B | Max resolution | `get_DI_MaxResolution` | Parsed |
| 0x04 | 2B | X max | `get_DI_Xmax` | Parsed |
| 0x06 | 2B | Y max | `get_DI_Ymax` | Parsed |
| 0x08 | 2B | X max pixels | `get_DI_Xmaxpixel` | Parsed |
| 0x0a | 2B | Y max pixels | `get_DI_Ymaxpixel` | Parsed |
| 0x10 | 2B | Current Y | `get_DI_currentY` | Parsed |
| 0x12 | 2B | Current focus | `get_DI_currentFocus` | Parsed |
| 0x14 | 1B | Scan pitch | `get_DI_currentscanpitch` | Parsed |
| 0x1e | 1B | Auto feeder | `get_DI_autofeeder` | Parsed |
| 0x1f | 1B | Analog gamma | `get_DI_analoggamma` | Parsed |
| 0x40-0x47 | 8B | Device errors | `get_DI_deviceerror0-7` | Parsed |
| 0x80 | 2B | WB exposure time R | `get_DI_WBETR_R` | **Not documented** |
| 0x82 | 2B | WB exposure time G | `get_DI_WBETR_G` | **Not documented** |
| 0x84 | 2B | WB exposure time B | `get_DI_WBETR_B` | **Not documented** |
| 0x88 | 2B | Prescan result R | `get_DI_PRETV_R` | **Not documented** |
| 0x8a | 2B | Prescan result G | `get_DI_PRETV_G` | **Not documented** |
| 0x8c | 2B | Prescan result B | `get_DI_PRETV_B` | **Not documented** |
| 0x90 | 2B | Current exposure R | `get_DI_CETV_R` | **Not documented** |
| 0x92 | 2B | Current exposure G | `get_DI_CETV_G` | **Not documented** |
| 0x94 | 2B | Current exposure B | `get_DI_CETV_B` | **Not documented** |
| 0x98 | 1B | Internal exp. unit R | `get_DI_IETU_R` | **Not documented** |
| 0x99 | 1B | Internal exp. unit G | `get_DI_IETU_G` | **Not documented** |
| 0x9a | 1B | Internal exp. unit B | `get_DI_IETU_B` | **Not documented** |
| 0xa0 | 1B | Limit condition | `get_DI_limitcondition` | **Not documented** |
| 0xa1 | 1B | Offset data R | `get_DI_offsetdata_R` | **Not documented** |
| 0xa2 | 1B | Offset data G | `get_DI_offsetdata_G` | **Not documented** |
| 0xa3 | 1B | Offset data B | `get_DI_offsetdata_B` | **Not documented** |
| 0xa8 | 8B | Power-on errors | `get_DI_poweron_errors` | **Not documented** |

**Action:** Add a table to `docs/commands.md` under "Internal Info (datatype 0xe0)"
with all 30+ fields.

---

## Phase 4: Channel State Response (datatype 0x8c)

### What's known

CDB format: `28 00 8c 00 [channel] 03 00 00 0a 80` — reads 10 bytes.
Seen in golden fixture for channels 1, 2, 3, 9.

### What to document

**Action:** Extract the 10-byte response from `golden_single_bw.txt`
(lines ~236-250) and document:
- Byte layout (what each byte/field means)
- Whether values differ per channel
- Whether values change between prescan and full scan

Cross-reference: SANE does not have a datatype 0x8c defined in
`coolscan-scsidef.h`. This is LS-40 ED specific.

---

## Phase 5: CONTROL_FRAME Payload Structure (52 bytes)

### What's known

Sent via `2a 00 8f 00 00 03 00 00 34 00` (WRITE, datatype 0x8f, 52 bytes).
Two variants exist: single-BW and batch (different payloads).

Single-BW payload:
```
003206000000024e0001000a000013380009000c0000244000110014000034ee0019000a0000460a00210016000056b80029000c
```

### What to document

SANE's `cs3_set_boundary()` at `coolscan3.c:2897-2936` computes the payload
dynamatically. Man page clarifies `--subframe` shifts scan window in mm.

**Header (4 bytes):**
- Bytes 0-1: length (big-endian, = `4 + n_frames * 16`)
- Byte 2: n_frames
- Byte 3: n_frames (repeated, purpose unclear)

**Per-frame entry (16 bytes each):**
- Bytes 0-3: Y start position (`frame_offset * frame_index + subframe / unit_mm`)
- Bytes 4-7: X offset (always 0x00000000 in captures)
- Bytes 8-11: Y end position (`start + frame_offset - 1`)
- Bytes 12-15: X max (`boundaryx - 1`)

**Man page notes:**
- `frame_offset = resy_max * 1.5 + 1` (SANE source, works for LS-30, maybe not others)
- `subframe` is in mm; converted to device units via `subframe / unit_mm` where `unit_mm = 25.4 / unit_dpi`
- `--frame <n>` operates on frame at position n (1-indexed)

**Action:** Decode the 52-byte payload against SANE's formula. Document:
- How many frames the single-BW payload encodes (52 = 4 + 3*16, so 3 frames)
- What frame_offset value is implied
- Whether the batch payload uses the same structure

---

## Phase 6: Missing Commands and Load/Eject Semantics

### SABORT (0xc0)

SANE's `sane_cancel()` sends `c0 00 00 00 00 00`. Not in our docs.

**Action:** Add to `docs/commands.md` under "Scanner Control Commands":
- Purpose: abort in-progress scan
- Format: 6-byte command, no data, status-only response
- When used: SANE calls it in `sane_cancel()`

### e0/b4 (Reset variant)

Golden fixture teardown sequence uses `e0 00 b4 00 00 00 00 00 0d 00` +
13-byte payload + EXECUTE. SANE uses `e0/80` for reset.

**Man page note:** `--reset` causes the scanner to "perform the same action
as when power is turned on: it will eject the slide (with the SF-200 bulk
loader) and calibrate itself."

**Action:** Document `e0/b4` as a reset variant specific to the LS-40 ED.
Extract the 13-byte payload from the fixture. Note that reset = eject +
calibrate (not just state reset).

### e0/d0 (Eject) and e0/d1 (Load)

Already documented in `docs/commands.md`, but the 13-byte payload format
is unknown.

**Man page notes:**
- `--load` loads the next slide (SF-200 bulk loader only)
- `--eject` ejects the film strip or mounted slide
- Both require 13 bytes of data after the CDB

**Action:** Extract payload from fixture. Document whether it's all-zeros
or carries parameters (e.g., frame count, loader type).

### Infrared reading semantics

**Man page note:** "If set to 'yes', the scanner will read the infrared
channel, thus allowing defect removal in software. The infrared image is
read during a second scan, with no options altered. The backend must not
be restarted between the scans."

**Action:** Document in `docs/unified-protocol-spec.md` that IR reading
requires a separate scan pass, not a separate window. Explain why the
golden fixture shows IR window (9) being configured alongside RGB.

---

## Phase 7: Timing Rules

### What's observed but undocumented

| Rule | Source | Details |
|------|--------|---------|
| Phase check after every command | Capture | 0xd0 sent to OUT, 1-byte phase response from IN |
| TUR polling interval | Capture | ~100ms during scan |
| START_SCAN retry pattern | Both captures | REISSUE (0x09800601) → status reads → retry; transient ERROR (0x09800100) → status reads → retry; READY |
| Status reads after REISSUE | Both captures | 6 bytes (datatype 0x87), then 33 bytes |
| Status reads after transient ERROR | Both captures | 6 bytes, then 24 bytes |
| ~42s idle gap before eject | Single BW fixture | Firmware flush timing? |
| Scanner returns PROCESSING during scan | Both captures | sense_key=0x02, ASC=0x04, ASCQ=0x01 |
| Scanner returns READY when done | Both captures | sense_key=0x00 |
| Image chunk size | Both captures | Scanner returns ~65508 bytes per USB bulk IN |
| Max TUR retries | SANE | 120 attempts at 1s intervals = 120s timeout |
| Hard error limit | SANE | 3 consecutive USB/IO errors before giving up |

**Action:** Add a "Timing and Sequence Rules" section to
`docs/unified-protocol-spec.md` with the above table.

---

## Phase 8: SANE-Specific Features and Man Page Semantics

### Depth

**Man page:** "Here <n> can either be 8 or the maximum number of bits
supported by the scanner (10, 12, or 14). It specifies whether or not the
scanner reduces the scanned data to 8 bits before sending it to the backend."

**Action:** Document in `docs/unified-protocol-spec.md`:
- WDB byte 34 values: 0x08=8-bit, 0x0a=10-bit, 0x0c=12-bit, 0x0e=14-bit
- At depth 8, scanner performs internal bit-reduction (quality loss)
- `maxbits` comes from INQUIRY page 0xc1 byte 82 (SANE: `coolscan3.c:2443`)
- LS-40 ED maxbits=12 (from page 0xc1); LS-30 overridden to 10

### Multi-sampling

SANE supports `samples_per_scan` (1-16). When >1, the scanner returns
multiple passes of pixel data, which SANE averages.

**Action:** Document in `docs/unified-protocol-spec.md`:
- How multi-sampling affects WDB byte 48 (multiread field)
- How it affects data transfer size (`xfer_len_in *= samples_per_scan`)
- The averaging formula SANE uses
- Whether the LS-40 ED capture shows multi-sampling (it doesn't — both
  captures use `samples_per_scan = 1`)

### AE vs AE-WB (auto-exposure modes)

**Man page:** `--ae` performs pre-scan to calculate exposure values
automatically. `--ae-wb` will maintain white balance, while `--ae` will
adjust each channel separately.

**Source behavior (coolscan3.c:2714-2736):**
- AE: WDB byte 50 = 0x20 (scan_kind=AE)
- AE-WB: WDB byte 50 = 0x40 (scan_kind=AE_WB)
- After prescan, `cs3_get_exposure()` reads back exposure from WDB via
  GET_WINDOW (bytes 54-57, 10ns units)
- Exposure multiplier (`--exposure`) scales all channels without affecting
  white balance: `real_exposure[ch] = exposure * exposure_ch * 100`

**Action:** Document the difference between AE and AE-WB in protocol docs.
Explain how exposure values flow from prescan → WDB → full scan.

### Odd padding

SANE adds 1 byte per color channel per row when width is odd (except
LS-30, LS-2000).

**Action:** Document in `docs/protocol.md` under "Image Data Format":
- Condition: `(bytes_per_pixel == 1) && (logical_width & 0x01)`
- Effect: `odd_padding = 1`
- Impact on row stride calculation

### Block padding

SANE pads transfer length to 512-byte boundary for LS-50/LS-5000.

**Action:** Document as LS-50/LS-5000 specific. Not applicable to LS-40 ED.

### Frame offset and subframe

SANE: `frame_offset = resy_max * 1.5 + 1`.

**Man page:** `--subframe <x>` shifts scan window by specified amount
(default unit is mm). `--frame <n>` specifies which frame to operate on.

**Action:** Document in `docs/unified-protocol-spec.md` under batch/multi-frame
scanning. Include the formula for y-offset computation:
`real_yoffset = ymin + (i_frame - 1) * frame_offset + subframe / unit_mm`

### Autofocus semantics

**Man page:** "Perform autofocus operation. Unless otherwise specified by
the other options (`--focus-on-centre` and friends), focusing is performed
on the centre of the selected scan area."

**Source behavior (coolscan3.c:2685-2712):**
- `cs3_autofocus()` reads current focus → sends AF command (e0/a0, 9 bytes,
  x/y coordinates) → executes → reads new focus
- Focus coordinates come from scan area center or manual focusx/focusy

**Action:** Document the autofocus command sequence including the 9-byte
payload format (x: 4 bytes, y: 4 bytes, trailing: 1 byte).

---

## Phase 9: Fixture Anomalies

### Unknown READ lengths

Golden fixture uses these READ(10) allocation lengths not covered by our code:

| Length (hex) | Decimal | Context | Status |
|-------------|---------|---------|--------|
| 0x019500 | 104736 | Full scan data | **Not explained** |
| 0x036900 | 221184 | Full scan data | **Not explained** |

**Action:** Trace these in the fixture to understand what scan phase they
belong to. Document whether they're prescan, IR preview, or full scan.

### WDB byte 48-49 variation

Some WDBs have `00 80`, others `00 81` at bytes 48-49.

**Action:** Document the difference:
- 0x80 = averaging ON, negative film
- 0x81 = averaging ON, positive film
- Confirm which scan types use which value

### Short read behavior

The scanner sometimes returns fewer bytes than requested on the final
image chunk. This signals end-of-data.

**Action:** Document in `docs/unified-protocol-spec.md` under "Image Data
Reading":
- How short reads work
- The 8-byte status that follows the final chunk
- Differences between replay mode and real hardware

---

## Deliverables

| Deliverable | Location | Content |
|------------|----------|---------|
| WDB field table | `docs/unified-protocol-spec.md` or new `docs/wdb-fields.md` | All 58 bytes + SANE-only fields |
| INQUIRY page reference | `docs/commands.md` | Pages 0x01, 0xc1, 0xd1, 0xe1, 0xe2, 0xf0, 0xf8 |
| Internal info table | `docs/commands.md` | All 30+ fields from SANE |
| Channel state format | `docs/commands.md` | 10-byte response layout |
| CONTROL_FRAME structure | `docs/commands.md` | Per-frame payload breakdown + subframe formula |
| Missing commands | `docs/commands.md` | SABORT, e0/b4, e0 payload, reset=eject+calibrate |
| Timing rules | `docs/unified-protocol-spec.md` | Table of observed timing behaviors |
| SANE features | `docs/unified-protocol-spec.md` | Depth (8/10/12/14), multi-sampling, padding, frame offset, AE vs AE-WB |
| IR semantics | `docs/unified-protocol-spec.md` | Second scan pass, no restart between scans |
| Autofocus sequence | `docs/commands.md` | 9-byte payload format, center-vs-manual focus |
| Fixture anomalies | `docs/troubleshooting.md` or new section | READ lengths, WDB variation |

## Dependencies

- **Phase 1-5** can proceed in parallel (each is a different data structure)
- **Phase 6** depends on Phase 5 (CONTROL_FRAME understanding helps with e0 commands)
- **Phase 7-9** can proceed in parallel
- All phases depend on having `golden_single_bw.txt` and `golden_batch.txt`
  available locally

## Verification

Each documentation addition should cite:
1. **Fixture line numbers** (e.g., "golden_single_bw.txt line 42")
2. **SANE source line** (e.g., "coolscan-scsidef.h:658")
3. **pcapng verification** if the field was validated against raw capture

No code changes needed. `make check-all` should continue to pass unchanged.

## Acceptance Criteria

- Every byte of the 58-byte WDB is documented with a name, size, and meaning
- Depth values (8/10/12/14-bit) and their WDB encoding are documented
- All INQUIRY pages in the fixture have response format documented
- Internal info structure has all 30+ SANE fields listed
- Channel state (0x8c) response format is documented
- CONTROL_FRAME payload is decoded field-by-field with subframe formula
- SABORT (0xc0) and e0/b4 are in `docs/commands.md`
- Reset semantics (eject + calibrate) are documented
- Load/eject 13-byte payload format is documented
- AE vs AE-WB difference is explained (channel-independent vs white-balance-preserving)
- IR reading semantics (second scan pass, no restart) are documented
- Autofocus command sequence and 9-byte payload format are documented
- Timing rules table exists in protocol docs
- SANE-specific features (multi-sampling, padding, frame offset) are documented
- Fixture anomalies are explained
