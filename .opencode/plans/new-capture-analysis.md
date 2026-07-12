# New Capture Analysis: Nikon Scan (Windows) Protocol Discoveries

**Date**: 2025-07-12
**Captures**: `ls40-batch-session.pcapng`, `ls40-batch-neg.pcapng`, `ls40-single-negs.pcapng`
**Software**: Nikon Scan on Windows
**Scanner**: Nikon Coolscan LS-40 ED

This document records protocol discoveries from three new pcapng captures, comparing against existing captures (`ls40-single-bw.pcapng`, `ls40-batch.pcapng`).

---

## Table of Contents

1. [Capture Descriptions](#capture-descriptions)
2. [VENDOR_E0 Command Family](#vendor_e0-command-family)
3. [VENDOR_E1 Command Family](#vendor_e1-command-family)
4. [Channel 9 (Infrared) for Autofocus](#channel-9-infrared-for-autofocus)
5. [Batch Mode State Machine](#batch-mode-state-machine)
6. [Post-Eject Prescan](#post-eject-prescan)
7. [WDB Variants and Scan Modes](#wdb-variants-and-scan-modes)
8. [Frame Position Table (READ/WRITE 0x8f)](#frame-position-table-readwrite-0x8f)
9. [Autofocus Position Tracking](#autofocus-position-tracking)
10. [READ Capacity Channel Usage](#read-capacity-channel-usage)
11. [Differences from Existing Captures](#differences-from-existing-captures)
12. [Open Questions](#open-questions)

---

## Capture Descriptions

### ls40-batch-session.pcapng (41.8 MB, 8579 events, 597.6s)

Positive/slide batch session with selective scanning:
1. Init + config
2. Prescan (full carrier, positive/slide)
3. Preview scan for 1 image
4. Preview scan for 6 images
5. Main scan for images 1, 2, 5, 6 (4 of 6 selected)
6. Auto eject + post-eject prescan

### ls40-batch-neg.pcapng (79.9 MB, 10965 events, 739.7s)

Negative batch session with calibration:
1. Init + config
2. Prescan
3. Calibrate (VENDOR_E0 b0 -- NEW)
4. Batch scan x6, 12-bit negative, ICE fine
5. Auto eject + post-eject prescan

### ls40-single-negs.pcapng (39.7 MB, 6030 events, 546.4s)

Single negative with advanced features:
1. Init + config
2. Prescan
3. Auto-focus (VENDOR_E0 a0)
4. Prescan densitometry (VENDOR_E1 91 + VENDOR_E0 b4)
5. ICE, ROC 5, GEM 3
6. Main scan image 1 with boundary -7, 12-bit
7. Preview image 2
8. Main scan image 2 with analog gain master 0.51, manual border
9. Manual eject

---

## VENDOR_E0 Command Family

All VENDOR_E0 commands use a 10-byte CDB followed by a 9-byte data payload and EXECUTE:

```
PHASE_CHECK (0xD0)          -> scanner responds: STATUS phase (0x01)
STATUS response (8 bytes)   -> all zeros
VENDOR_E0 (10 bytes)        -> E0 00 XX 00 00 00 00 00 09 00 (XX = subcode)
PHASE_CHECK (0xD0)          -> scanner responds: OUT phase (0x02)
DATA_OUT (9 bytes)          -> command-specific parameters
STATUS response (8 bytes)   -> all zeros
EXECUTE (6 bytes)           -> C1 00 00 00 00 00
PHASE_CHECK (0xD0)          -> scanner responds: STATUS phase (0x01)
STATUS response (8 bytes)   -> all zeros
```

The 10-byte CDB format is `E0 00 XX 00 00 00 00 00 09 00` where XX is the subcode.
The trailing `09 00` appears constant across all subcodes.

### Identified Subcodes

| Subcode | Name | Seen In | 9-byte data (hex) | Purpose |
|---------|------|---------|-------------------|---------|
| `0xb4` | ICE/densitometry setup | ALL 5 captures | `0000000e1000000001` (initial)<br>`000000025800000001` (post-eject) | ICE calibration or densitometry configuration. Called after initial prescan and after eject. |
| `0xb0` | **calibrate** | batch-neg ONLY | `000000000000000000` | Explicit calibration command. Only seen when user selected "calibrate" in Nikon Scan. |
| `0xa0` | autofocus | ALL 5 captures | `000000059b0000XXXX` | Trigger autofocus. Bytes 3-4 are always `05 9b`; the carriage position is in **bytes 7-8** (`XXXX`), increments per image. |
| `0xc1` | **frame_select** | batch-session ONLY | `00000000XX00000000` | Select frame position for main scan. The frame offset is in **byte 5** (`XX`). Only used for selective batch scanning. |
| `0xd0` | eject | ALL 5 captures | `000000001000000000` (single-negs, batch-session, old batch)<br>`000000000c0000000a` (single-bw)<br>`000000000007884ee8` (batch-neg) | Eject carrier. Variant values may reflect film holder type or post-eject carriage target. |

### Evidence

**VENDOR_E0 b0 (calibrate)** -- batch-neg, frame 827:
```
Frame 827: OUT 10B e000b000000000000900   ; VENDOR_E0 subcode 0xb0
Frame 829: OUT  1B d0                       ; PHASE_CHECK
Frame 832: IN   1B 02                        ; OUT phase
Frame 833: OUT  9B 000000000000000000       ; all-zero params
Frame 836: IN   8B 0000000000000000         ; STATUS GOOD
Frame 837: OUT  6B c10000000000              ; EXECUTE
```

**VENDOR_E0 c1 (frame_select)** -- batch-session, 4 occurrences:
```
Frame 7585:  OUT 10B e000c100000000000900  ; VENDOR_E0 subcode 0xc1
Frame 7591:  OUT  9B 00000000e000000000    ; frame offset 0xE0
Frame 7595:  OUT  6B c10000000000           ; EXECUTE

Frame 9855:  OUT 10B e000c100000000000900  ; second call
Frame 9861:  OUT  9B 00000000e500000000    ; frame offset 0xE5

Frame 11829: OUT 10B e000c100000000000900  ; third call
Frame 11835: OUT  9B 00000000e700000000    ; frame offset 0xE7

Frame 13963: OUT 10B e000c100000000000900  ; fourth call
Frame 13969: OUT  9B 00000000de00000000    ; frame offset 0xDE
```

The 4 calls correspond to the 4 main scans (images 1, 2, 5, 6). The frame offsets (0xE0, 0xE5, 0xE7, 0xDE) do NOT correspond to simple image indices -- they appear to be physical carriage positions. In the 9-byte payload the offset lives in **byte 5**.

**VENDOR_E0 d0 (eject)** -- three variants observed:
```
single-negs, batch-session, old batch:
  9B data: 000000001000000000

single-bw:
  9B data: 000000000c0000000a

Batch-neg:
  9B data: 000000000007884ee8
```

---

## VENDOR_E1 Command Family

VENDOR_E1 commands are simpler -- just the 10-byte CDB, no data payload:

```
PHASE_CHECK (0xD0)          -> scanner responds: STATUS phase (0x01)
STATUS response (8 bytes)   -> all zeros
VENDOR_E1 (10 bytes)        -> E1 00 XX 00 00 00 00 00 09 00
PHASE_CHECK (0xD0)          -> scanner responds: IN phase (0x03)
DATA_BLOCK (9 bytes)        -> response from scanner
STATUS response (8 bytes)   -> all zeros
```

### Identified Subcodes

| Subcode | Name | Seen In | Purpose |
|---------|------|---------|---------|
| `0xc1` | get_focus | ALL 5 captures | Query current focus position. Returns 9-byte response. |
| `0x91` | **densitometry?** | single-bw, single-negs, batch-neg, batch-session | NOT in old batch.pcapng. Possibly densitometry or preset configuration. |

### Evidence

**VENDOR_E1 91 absence in old batch.pcapng**: The old `ls40-batch.pcapng` (captured earlier, possibly different Nikon Scan version) does NOT contain VENDOR_E1 91. All other captures do, including both positive (`single-bw`, `batch-session`) and negative (`single-negs`, `batch-neg`) film. It is therefore **not film-type dependent**. It always returns `000000000100000000`, suggesting a status/capability check that gates the following `VENDOR_E0 b4` calibration step.

---

## Channel 9 (Infrared) for Autofocus

All five captures (both old and new) use channel 9 (IR) in addition to channels 1 (R), 2 (G), 3 (B).

### Channel Usage Patterns

| Phase | WDB channels issued | Channels read (SHORT_OUT) |
|-------|---------------------|---------------------------|
| Initial prescan | 1, 2, 3, **9 (setup)** | `010203` (RGB only) |
| Preview scan (with IR) | 9, 1, 2, 3 | `09010203` (IR+RGB) |
| Main scan data transfer | 1, 2, 3 | `010203` (RGB only) |

Channel 9 is configured during the initial prescan, but only **read** during preview scans (where autofocus positioning matters). It is NOT used for final image data extraction.

### Evidence

From `ls40-single-negs.pcapng`, preview scan for image 1:
```
Frame 3203: SCAN + WDB channel 9 (IR)
Frame 3213: SCAN + WDB channel 1 (R)
Frame 3223: SCAN + WDB channel 2 (G)
Frame 3233: SCAN + WDB channel 3 (B)
Frame 3285: START_STOP_UNIT 1b0000000400  ; 4 colors
Frame 3291: SHORT_OUT 09010203             ; channel list: 9,1,2,3
```

Main scan for image 1 (3 channels only):
```
Frame 2859: SCAN + WDB channel 1 (R)
Frame 2869: SCAN + WDB channel 2 (G)
Frame 2879: SCAN + WDB channel 3 (B)
Frame 2891: START_STOP_UNIT 1b0000000300  ; 3 colors
Frame 2895: SHORT_OUT 010203               ; channel list: 1,2,3
```

---

## Batch Mode State Machine

The `ls40-batch-session.pcapng` reveals the complete batch scan workflow with selective scanning:

```
INIT -> CONFIG -> PRESCAN -> [full-carrier preview] -> [per-image loop] -> EJECT -> POST-EJECT-PRESCAN
```

`batch-session` first issues one full-carrier preview scan before the per-image autofocus/preview loop begins. The per-image loop (for each of 6 images) is:

```
  1. VENDOR_E0 a0 (autofocus) + EXECUTE
  2. VENDOR_E1 c1 (get_focus) -- read focus result
  3. SCAN + WDB x4 (IR, R, G, B) -- preview scan
  4. WRITE 0x03 x4 (LUT for each channel) + 8192B each
  5. START_STOP_UNIT(4 colors) + SHORT_OUT(09010203) x2
  6. READ_CAPACITY ch 9,1,2,3
  7. READ 0x00 (image data) -- preview image transfer
  [If user selected this image for main scan:]
  8. VENDOR_E0 c1 (frame_select) + EXECUTE -- position carriage
  9. SCAN + WDB x3 (R, G, B) -- main scan
  10. WRITE 0x03 x3 (LUT for RGB) + 8192B each
  11. START_STOP_UNIT(3 colors) + SHORT_OUT(010203) x2
  12. READ_CAPACITY ch 1,2,3
  13. READ 0x00 (image data) -- main scan data transfer
```

Images 3 and 4 were previewed but NOT main-scanned (no VENDOR_E0 c1 for them).

---

## Post-Eject Prescan

All batch captures (`ls40-batch.pcapng`, `ls40-batch-neg.pcapng`, `ls40-batch-session.pcapng`) and `ls40-single-bw.pcapng` show activity AFTER the eject command:

```
VENDOR_E0 d0 (eject) + EXECUTE
  -> multiple TUR polling (000000000000 + PHASE_CHECK d0)
VENDOR_E0 b4 (ICE/densitometry) + EXECUTE
  ; 9B data: 000000025800000001 (different from initial b4)
SCAN + WDB x4 (channels 1,2,3,9)
```

This post-eject prescan likely checks if there are more frames loaded after the carrier advances. The different VENDOR_E0 b4 data (`000000025800000001` vs `0000000e1000000001`) suggests a different configuration for this secondary prescan.

---

## WDB Variants and Scan Modes

The 58-byte Window Descriptor Block layout derived from the captures is:

| Bytes | Field | Notes |
|-------|-------|-------|
| 0-3 | reserved | always `00000000` |
| 4-7 | window id | always `00000032` (0x32 = 50) |
| 8 | channel | 1=R, 2=G, 3=B, 9=IR |
| 9 | reserved | `00` |
| 10-11 | X resolution (DPI) | e.g. `0B54`=2900, `0060`=96, `0122`=290 |
| 12-13 | Y resolution (DPI) | same as X |
| 14-17 | reserved | `00000000` |
| 18-21 | frame / boundary offset | copied from the `WRITE 0x8f` frame table |
| 22-25 | image width in pixels | `00000B36` = 2870 |
| 26-29 | reserved | zeros |
| 30-31 | line count / height | `10EC`=4332, `8760`=34656, `100A`=4106 |
| 32-33 | mode | `0002`=prescan, `0005`=preview/main |
| 34 | transfer/mode byte | `08` for prescan and main scan, `0C` for low-res preview; **not** a simple bits-per-pixel field |
| 35-47 | reserved | zeros |
| 48 | status / post-eject variation | `00` normally; `03` seen in post-eject prescan channel 1 |
| 49 | film/preview flag | `81` prescan and low-res preview, `80` negative IR preview, `00` main scan |
| 50 | sub-mode | `01` prescan and main scan, `02` low-res 96 DPI preview |
| 51-53 | constant tail | `02 02 ff` |
| 54-57 | exposure | 32-bit big-endian, varies per channel and scan |

Three WDB variants are commonly seen:

### Prescan WDB (high resolution)
```
Bytes 10-11: 0B54 (= 2900 DPI)
Bytes 12-13: 0B54 (= 2900 DPI)
Bytes 30-31: 10EC (= 4332 lines)
Bytes 32-33: 0002
Bytes 49-50: 8101
```

### Preview WDB
Two resolutions occur:
* **96 DPI thumbnail preview:** `0060` resolution, `8760` lines, tail `8102`
* **290 DPI IR preview:** `0122` resolution, `10EC` lines, tail `8001` (negative) or `8101` (positive)

### Main scan WDB
```
Bytes 10-11: 0B54 (= 2900 DPI)
Bytes 12-13: 0B54 (= 2900 DPI)
Bytes 30-31: 10EC or 100A (crop-dependent line count)
Bytes 32-33: 0005
Bytes 49-50: 0001
```

### Full WDB hex (prescan, channel 1, single-negs)
Correct byte grouping:
```
00000000 00000032 01 00 0B54 0B54 00000000 00000000 00000B36
000010EC 00000002 08 00 0000 0000 0000 0000 0000 0000 008101 0202FF
00009A34
```

### Full WDB hex (96 DPI preview, channel 1, single-negs)
```
00000000 00000032 01 00 0060 0060 00000000 00000000 00000B36
00008760 00000005 0C 00 0000 0000 0000 0000 0000 0000 008102 0202FF
00009AC0
```

### Implementation note
`coolscan/protocol.py` contains a hardcoded 58-byte WDB builder that matches the layout above, but the `WindowDescriptorBlock` dataclass uses a 117-byte SANE-style layout with different offsets. The two should not be treated as equivalent.

---

## Frame Position Table (READ/WRITE 0x8f)

`READ 0x8f` returns a 58-byte default frame table. The first 6 bytes are a header (`8f 00 00 00 00 34`); the remaining 52 bytes are six 8-byte entries:

```
READ 0x8f response (all captures):
8f0000000034 0032 06 00
  00000000 00000000 0000   (entry 0)
  000010ec 00000000 0000   (entry 1)
  000021d8 00000000 0000   (entry 2)
  000032c4 00000000 0000   (entry 3)
  000043b0 00000000 0000   (entry 4)
  0000549c 00000000 0000   (entry 5)
```

The default positions are spaced by 4332 units (`0x10ec`), matching the inter-frame spacing seen in the autofocus commands.

`WRITE 0x8f` then writes back a modified 52-byte table. Each entry appears to be:

| Bytes | Meaning |
|-------|---------|
| 0-3 | frame / boundary offset (copied into WDB bytes 18-21) |
| 4-5 | per-frame metadata (crop/flags) |
| 6-7 | per-frame metadata (crop/flags) |

For example, in `ls40-single-negs.pcapng` the first `WRITE 0x8f` sets entry 0 to `0000010e`, which matches the IR preview WDB offset `0000010e` for image 1.

`WRITE 0x92` is **not** the border-position control. Its payload is always `04000000`, it is sent once after `VENDOR_E0 b4`, and it does not change when crop/boundary settings change. Crop and frame selection are encoded in the `WRITE 0x8f` table instead.

---

## Autofocus Position Tracking

The `VENDOR_E0 a0` (autofocus) 9-byte payload is `00 00 00 00 05 9b 00 00 XX YY`. Bytes 3-4 are always `05 9b`; the monotonically increasing carriage position is in **bytes 7-8** (`XX YY`):

### batch-neg (6 images, negatives)
| Image | Position (hex) | Decimal | Delta |
|-------|---------------|---------|-------|
| 1 | 0x000984 | 2436 | -- |
| 2 | 0x001A64 | 6756 | +4320 |
| 3 | 0x002B58 | 11096 | +4340 |
| 4 | 0x003C38 | 15416 | +4320 |
| 5 | 0x004D04 | 19716 | +4300 |
| 6 | 0x005DA8 | 24008 | +4292 |

### batch-session (6 images, positives)
| Image | Position (hex) | Decimal | Delta |
|-------|---------------|---------|-------|
| 1 | 0x00092A | 2346 | -- |
| 2 | 0x001A1E | 6686 | +4340 |
| 3 | 0x002B08 | 11016 | +4330 |
| 4 | 0x003BF2 | 15442 | +4426 |
| 5 | 0x004CDC | 19772 | +4330 |
| 6 | 0x005DC6 | 24102 | +4330 |

The ~4300 unit increment between images is consistent across captures. The slightly different starting positions (0x092A vs 0x0984) may reflect different carrier loading positions or film types.

---

## READ Capacity Channel Usage

READ_CAPACITY (opcode 0x25) is called during init. The channel number appears in **byte 1 and byte 5** (duplicated):

| Channel | Hex CDB | Purpose |
|---------|---------|---------|
| 0 | `25000000000000003a80` | Default/unknown |
| 1 | `25010000000100003a80` | Red channel |
| 2 | `25020000000200003a80` | Green channel |
| 3 | `25030000000300003a80` | Blue channel |
| 4 | `25040000000400003a80` | Unknown / reserved (queried but never used) |
| 9 | `25090000000900003a80` | Infrared channel |

All six channels are queried during init in all captures. During scan phases, READ_CAPACITY is called for channels 1,2,3 (RGB) or 9,1,2,3 (IR+RGB) depending on whether IR is needed. Channel 4 is never used in any scan.

---

## Differences from Existing Captures

### ls40-single-bw.pcapng (old, positive/B&W)
- Same VENDOR_E0 subcodes: b4, a0, d0
- Same VENDOR_E1 subcodes: c1, 91
- Uses IR channel (9) for preview scans
- SCAN count: 18 (single image)

### ls40-batch.pcapng (old, batch positive)
- Same VENDOR_E0 subcodes: b4, a0, d0
- **MISSING VENDOR_E1 91** -- this is the key difference
- Uses IR channel (9) for preview scans
- SCAN count: 67 (multiple images)

### New captures (all three)
- **VENDOR_E0 b0** (calibrate) -- new in batch-neg
- **VENDOR_E0 c1** (frame_select) -- new in batch-session
- **VENDOR_E1 91** present (unlike old batch.pcapng)
- Post-eject prescan is also visible in the old captures; it is not unique to the new batch captures

---

## Open Questions

1. **VENDOR_E1 91** -- Partially answered. It is present in both positive and negative captures and missing only in the old `batch.pcapng`. It always returns `000000000100000000`, so it is best understood as a status/capability gate before `VENDOR_E0 b4`, not a film-type selector.

2. **VENDOR_E0 b4** -- Two timing-dependent payloads: `0000000e1000000001` for the initial prescan and `000000025800000001` after eject. The difference is likely a different integration/exposure configuration for the secondary prescan.

3. **WRITE 0x8f (control frame)** -- Partially answered. It is a 52-byte frame-position table with six 8-byte entries. The first 4 bytes of each entry are the frame offset copied into the WDB at bytes 18-21. The remaining 4 bytes per entry carry per-frame metadata (crop, mode, possibly film-specific settings).

4. **WRITE 0x92** -- Reclassified. It is not a border-position command. Its payload is always `04000000`, it is sent once after `VENDOR_E0 b4`, and it never varies with boundary settings. Borders/crops are encoded in the `WRITE 0x8f` table.

5. **12-bit mode encoding** -- Not found in `SET_WINDOW` CDBs or WDB fields. Main-scan WDBs for the 12-bit negative capture are byte-identical to 8-bit captures except for offset/exposure. The bit depth is likely a host-side interpretation of the 16-bit raw samples, possibly influenced by the `WRITE 0x03` LUT.

6. **Analog gain** -- Not isolated. The 21 iterative `WRITE 0x8f` operations in `single-negs` around 147-152 s are the most likely place where user adjustments (including analog gain) are reflected, but a direct mapping to "0.51" is not yet established.

7. **ROC/GEM settings** -- Not isolated. Likely containers are the metadata portion of the `WRITE 0x8f` entries and/or the `WRITE 0x03` LUT contents (main-scan LUTs differ markedly between captures).

8. **VENDOR_E0 d0 eject variants** -- Three variants now observed. The `batch-neg` value `000000000007884ee8` may be a post-eject carriage target; the `single-bw` value `000000000c0000000a` is a third distinct form.

9. **Channel 4** -- Answered as far as the captures allow: it is queried during init but never used in scans. It appears to be a reserved or diagnostic channel.

10. **WDB byte layout** -- Answered for the 58-byte capture WDB (see the table in [WDB Variants and Scan Modes](#wdb-variants-and-scan-modes)). Note that `coolscan/protocol.py`'s `WindowDescriptorBlock` dataclass uses a 117-byte SANE-style layout that is not directly aligned with the capture WDB.

---

## Cross-Reference: Command Timeline

### ls40-single-negs.pcapng (key OUT commands, timestamps relative to start)

| Time (s) | Command | Notes |
|----------|---------|-------|
| 6.87 | INQUIRY x 13 | Standard init |
| 7.16 | RESERVE_UNIT | Lock scanner |
| 7.16-7.18 | READ_CAPACITY x 6 | Channels 0,1,2,3,4,9 |
| 7.19 | MODE_SELECT + DATA_OUT(20B) | Config |
| 7.20 | INQUIRY (page 0xe2, 0x01) | Config queries |
| 7.32 | SCAN + WDB x 4 | Initial prescan (ch 1,2,3 + ch9 setup window) |
| 7.45 | VENDOR_E1 c1 | get_focus |
| 7.56 | VENDOR_E1 91 | densitometry? |
| 7.67 | VENDOR_E0 b4 | ICE setup |
| 7.67 | EXECUTE c1 | Execute b4 |
| 7.78 | WRITE 0x92 + SHORT_OUT(4B) | Fixed parameter (`04000000`) after VENDOR_E0 b4 |
| 8.79-26.00 | READ 0x8e, 0x8f, 0x8c | Calibration data reads |
| 26.13 | SCAN + WDB x 3 | Preview scan (ch 1,2,3) |
| 26.26 | WRITE 0x03 x 3 + 8192B | LUT for RGB |
| 26.29 | START_STOP_UNIT(3) + SHORT_OUT x 3 | Start scan |
| 28.85 | READ_CAPACITY ch 1,2,3 | Query channels |
| 31-38 | READ 0x00 (image data) | Preview image transfer |
| 39.72 | INQUIRY c1 | Post-scan query |
| 39.81 | WRITE 0x8f + DATA_OUT(52B) | Control frame |
| 53.09 | VENDOR_E0 a0 | Autofocus for image 1 |
| 69.47 | VENDOR_E1 c1 | get_focus for image 1 |
| 86.55 | SCAN + WDB x 4 | Preview scan for image 1 (with IR) |
| 87.01 | WRITE 0x03 x 4 + 8192B | LUT for IR+RGB |
| 87.05 | START_STOP_UNIT(4) + SHORT_OUT | Start with IR |
| 87.96 | READ_CAPACITY ch 9,1,2,3 | Query all channels |
| 146.98-152.01 | WRITE 0x8f x 21 + 52B | Iterative frame/boundary adjustment for image 1 |
| ~200.75 | SCAN + WDB x 4 | Main scan image 1 (IR+RGB, offset 0x1e) |
| 216.77 | START_STOP_UNIT(4) | Resume main scan image 1 |
| 217.71 | READ_CAPACITY ch 9,1,2,3 | Query channels |
| 227.38 | SCAN + WDB x 4 | Preview/main scan pass for image 2 (IR+RGB) |
| 230.39 | WRITE 0x03 x 4 + 8192B | LUT for IR+RGB |
| 230.43 | START_STOP_UNIT(4) | Start with IR |
| 385.73 | VENDOR_E0 a0 | Autofocus for image 2 |
| 392.29 | VENDOR_E1 c1 | get_focus for image 2 |
| 392.47 | SCAN + WDB x 4 | Preview scan for image 2 |
| 392.62 | WRITE 0x03 x 4 + 8192B | LUT for IR+RGB |
| 393.87 | START_STOP_UNIT(4) | Start with IR |
| 466.36 | SCAN + WDB x 3 | Main scan image 2 (RGB only) |
| 466.50 | WRITE 0x03 x 3 + 8192B | LUT for RGB |
| 466.53 | START_STOP_UNIT(3) | Start RGB only |
| 525.05 | VENDOR_E0 d0 | Eject |
| 525.05 | EXECUTE c1 | Execute eject |

---

## Analysis Tools Used

- `scripts/analyze_capture.py` -- high-level command summary and phase detection
- `tshark` (`-Y 'usb.transfer_type==0x03' -T fields -e frame.number -e frame.time_relative -e usb.endpoint_address -e usb.data_len -e usb.capdata`) -- raw bulk packet extraction with timestamps
- Custom Python scripts for payload comparison, WDB decoding, and pattern extraction
