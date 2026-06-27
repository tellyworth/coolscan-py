# LUT and Exposure Analysis for Nikon Coolscan Protocol

**Date**: 2026-06-27
**Scope**: Investigation of LUT (lookup table) and exposure handling in the coolscan-py project
**Trust hierarchy**: pcapng captures (ground truth) > golden fixture > SANE source code

---

## Summary

The Nikon Coolscan LS-40 ED scanner uses two independent mechanisms for tonal control:

1. **Exposure time** — set per-channel in the Window Descriptor Block (WDB) via the SET_WINDOW (0x24) command. Measured in 10-nanosecond units. The scanner determines optimal exposure through a prescan (auto-exposure) phase.

2. **LUTs (gamma/tonal curves)** — uploaded per-channel via the SEND (0x2a) command with datatype 0x03. Each LUT is 8192 bytes (4096 entries × 2 bytes, big-endian), mapping 12-bit input ADC values to 16-bit output values. In the golden fixture, all LUTs are identity mappings (`output = input`).

**Key finding**: Exposure and LUTs are completely separate mechanisms. Exposure controls how long the CCD integrates light; LUTs apply post-ADC tonal transformation. The golden fixture captures a scan with default identity LUTs and auto-calibrated exposure times.

---

## Exposure

### How Exposure Is Measured and Adjusted

Exposure time is a 32-bit big-endian integer stored at **bytes 54–57** of the 58-byte WDB (Window Descriptor Block). The unit is **10 nanoseconds**.

The exposure workflow follows this sequence:

1. **Initial calibration read** (READ datatype 0x8e, fixture lines 208–216): A two-step read. First, a 6-byte header read (line 208) returns `008e00000d7c` (datatype 0x8e, length 3452). Then a second read (line 213) with the specified length returns 3392 bytes (line 216). The response contains a 4-byte calibration value at offset 6: `0x000d7904` = 882,948 × 10ns = 8.829ms, followed by 3382 zero bytes. This appears to be a factory-calibrated reference exposure time.

2. **Prescan with auto-exposure** (SET_WINDOW with scan kind 0x02, fixture lines 263–277): The host sends WDBs for R, G, B windows with scan kind `0x02` (AE/preview mode). The exposure bytes in these WDBs are initial guesses:
   - R: `0x0000a381` = 41,857 × 10ns = 0.419ms
   - G: `0x00008452` = 33,874 × 10ns = 0.339ms
   - B: `0x00004e29` = 20,009 × 10ns = 0.200ms

3. **START scan** (START_STOP_UNIT, fixture line 297): Initiates the prescan.

4. **Read calibrated exposure/state** (READ 0x8c and READ 0x87, fixture lines 236–246 and 302–322): After the prescan, the host reads channel state/progress data. The scanner has updated the exposure bytes based on the prescan measurement; these are later reflected in the full-scan WDBs.

5. **Full scan setup** (SET_WINDOW with scan kind 0x01, fixture lines 482–498): The host sends new WDBs for IR, R, G, B windows with the calibrated exposure values:
    - IR: `0x0001c305` = 115,461 × 10ns = 1.155ms
    - R: `0x0000ea05` = 59,909 × 10ns = 0.599ms
    - G: `0x0000b4ed` = 46,317 × 10ns = 0.463ms
    - B: `0x000073bc` = 29,628 × 10ns = 0.296ms

### Exposure Values from the Golden Fixture

| Phase | Channel | Hex Value | 10ns Units | Milliseconds |
|-------|---------|-----------|------------|--------------|
| Prescan | R | `0x0000a381` | 41,857 | 0.419ms |
| Prescan | G | `0x00008452` | 33,874 | 0.339ms |
| Prescan | B | `0x00004e29` | 20,009 | 0.200ms |
| Full scan | IR | `0x0001c305` | 115,461 | 1.155ms |
| Full scan | R | `0x0000ea05` | 59,909 | 0.599ms |
| Full scan | G | `0x0000b4ed` | 46,317 | 0.463ms |
| Full scan | B | `0x000073bc` | 29,628 | 0.296ms |

Green requires the longest RGB exposure (consistent with typical film sensitivity), followed by blue, red; IR uses the longest overall exposure.

### SANE Backend Exposure Handling

From `coolscan3.c` lines 2874–2876:
```c
s->real_exposure[1] = s->exposure * s->exposure_r * 100.;
s->real_exposure[2] = s->exposure * s->exposure_g * 100.;
s->real_exposure[3] = s->exposure * s->exposure_b * 100.;
```

SANE computes `real_exposure[color]` as `exposure × exposure_channel × 100`, producing a value in 10ns units. Default values: `exposure=1.0`, `exposure_r=1200.0`, `exposure_g=1200.0`, `exposure_b=1000.0` (line 1035–1038).

After auto-exposure, SANE reads back from the scanner (line 2731–2733):
```c
s->exposure_r = s->real_exposure[1] / 100.;
s->exposure_g = s->real_exposure[2] / 100.;
s->exposure_b = s->real_exposure[3] / 100.;
```

**Discrepancy**: SANE's default `real_exposure` values are R=120,000, G=120,000, B=100,000 in 10ns units (= 1.2ms, 1.2ms, 1.0ms). These differ significantly from the capture's auto-calibrated values. This is expected for AE mode and not a discrepancy per se.

---

## LUTs (Lookup Tables)

### LUT Structure

- **Size**: 8192 bytes per channel
- **Entries**: 4096 (2^12, matching the scanner's 12-bit ADC)
- **Entry format**: 16-bit big-endian unsigned integer
- **Input**: ADC code 0–4095 (implicit index)
- **Output**: Mapped value 0–65535 (the 16-bit entry value)

### LUT Transfer Command

LUTs are uploaded via the **SEND (0x2a)** command:

```
2a 00 03 00 [channel] 01 [len_hi] [len_mid] [len_lo] 00
```

| Byte | Value | Meaning |
|------|-------|---------|
| 0 | `0x2a` | SEND command |
| 1 | `0x00` | LUN |
| 2 | `0x03` | Data type (LUT/gamma table) |
| 3 | `0x00` | Reserved |
| 4 | Channel | 1=R, 2=G, 3=B, 9=IR |
| 5 | `0x01` | Bytes per data point - 1 (=2-1) |
| 6–8 | `00 20 00` | Transfer length (big-endian, 8192 = 0x2000) |
| 9 | `0x00` | Control byte |

Followed by 8192 bytes of LUT data (4096 × 2-byte entries).

### LUT Upload Sequence in the Golden Fixture

The fixture shows **four distinct LUT upload batches**:

| Batch | Fixture Lines | Channels | Context |
|-------|--------------|----------|---------|
| 1 | 282–296 | R, G, B | After prescan WDBs, before prescan START |
| 2 | 503–522 | IR, R, G, B | After full scan WDBs, before full scan START |
| 3 | 626–636 | R, G, B | After first image data, before re-scan |
| 4 | 688–698 | R, G, B | Later in multi-pass sequence |

All LUTs in all batches are **identity mappings** (output = input for every entry).

### Endpoint

LUT uploads use **endpoint 0x01** (OUT, host-to-device bulk transfer). The scanner acknowledges on endpoint 0x82 (IN).

---

## Extraction Method

LUT data was extracted from the golden fixture's pre-extracted binary files:

| File | Channel | Upload Batch |
|------|---------|-------------|
| `golden_data_0739.bin` | R (1) | Batch 1 |
| `golden_data_0749.bin` | G (2) | Batch 1 |
| `golden_data_0759.bin` | B (3) | Batch 1 |
| `golden_data_2221.bin` | IR (9) | Batch 2 |
| `golden_data_2231.bin` | R (1) | Batch 2 |
| `golden_data_2241.bin` | G (2) | Batch 2 |
| `golden_data_2251.bin` | B (3) | Batch 2 |
| `golden_data_10347.bin` | R (1) | Batch 3 |
| `golden_data_10357.bin` | G (2) | Batch 3 |
| `golden_data_10367.bin` | B (3) | Batch 3 |
| `golden_data_10625.bin` | R (1) | Batch 4 |
| `golden_data_10635.bin` | G (2) | Batch 4 |
| `golden_data_10645.bin` | B (3) | Batch 4 |

All files are exactly 8192 bytes. The extraction script `scripts/extract_lut_from_fixture.py` parses these files and generates ASCII plots.

---

## Curves

All 13 LUT files extracted from the golden fixture are **identity mappings**. The curve for every channel, in every upload batch, is:

```
  Output = Input (y = x diagonal)

  max |
 4095 |                                                                     *|
 3909 |                                                                  ****|
 3723 |                                                               ****   |
 3537 |                                                           *****      |
 3351 |                                                        ****          |
 3165 |                                                     ****             |
 2979 |                                                 *****                |
 2793 |                                              ****                    |
 2606 |                                           ****                       |
 2420 |                                       *****                          |
 2234 |                                    ****                              |
 2048 |                                 ****                                 |
 1862 |                             *****                                    |
 1676 |                          ****                                        |
 1490 |                       ****                                           |
 1303 |                   *****                                              |
 1117 |                ****                                                  |
  931 |             ****                                                     |
  745 |         *****                                                        |
  559 |      ****                                                            |
  373 |   ****                                                               |
  187 |****                                                                  |
  min |______________________________________________________________________|
        0                                  mid                             4095
        Input index (0 to 4095)
```

This is expected for a "golden" fixture that captures a default scan with no gamma correction, contrast adjustment, or tonal modification applied. The scanner's internal tone curve is the identity function; any gamma/contrast adjustments would be applied by modifying these LUT entries before upload.

---

## SANE Comparison

### SANE's LUT Architecture

From `coolscan3.c`:

```c
// LUT arrays (coolscan.h lines 257-267)
int lutlength;              /* length of gamma table */
int max_lut_val;            /* maximum value in lut */
int luti[4096];             /* lut value for infrared */
int lutr[4096];             /* lut value for red */
int lutg[4096];             /* lut value for green */
int lutb[4096];             /* lut value for blue */
```

SANE initializes LUTs to identity in `cs3_full_inquiry()` (line 2470–2473):
```c
for (pixel = 0; pixel < s->n_lut; pixel++) {
    s->lut_r[pixel] = s->lut_g[pixel] = s->lut_b[pixel] =
        s->lut_neutral[pixel] = pixel;
}
```

### SANE's LUT Upload (`cs3_send_lut`, lines 2938–2990)

```c
cs3_parse_cmd(s, "2a 00 03 00");
cs3_pack_byte(s, cs3_colors[color]);
cs3_pack_byte(s, 2 - 1);    /* bytes per data point - 1 */
cs3_pack_byte(s, ((2 * s->n_lut) >> 16) & 0xff);
cs3_pack_byte(s, ((2 * s->n_lut) >> 8) & 0xff);
cs3_pack_byte(s, (2 * s->n_lut) & 0xff);
cs3_pack_byte(s, 0x00);

for (pixel = 0; pixel < s->n_lut; pixel++) {
    cs3_pack_word(s, lut[pixel]);
}
```

This produces the exact same wire format as the golden fixture. **SANE's LUT upload is consistent with the capture.**

### SANE's Scan Sequence

From `cs3_scan()` (line 3074):
1. `cs3_convert_options()` — computes dimensions, exposure, etc.
2. `cs3_set_boundary()` — sends image boundary via SEND 0x88
3. `cs3_set_focus()` — sets focus position
4. **`cs3_send_lut()`** — uploads LUTs (only for NORMAL scan, not AE)
5. `cs3_set_window()` — sends WDBs via SET_WINDOW
6. **`cs3_get_exposure()`** — reads back exposure via GET_WINDOW
7. START_STOP_UNIT — starts the scan

**Discrepancy with capture**: In the golden fixture, LUTs are uploaded BEFORE the prescan START (batch 1, lines 282–296) and again before the full scan START (batch 2, lines 503–522). SANE's code only uploads LUTs before the normal (full) scan, not before the AE prescan. This suggests the capture was made by a different client (possibly the Nikon utility) that uploads LUTs in a slightly different sequence.

### SANE's GET_WINDOW for Exposure

SANE uses GET_WINDOW (0x25) to read back the calibrated exposure values (lines 2749–2765):
```c
cs3_parse_cmd(s, "25 01 00 00 00");
cs3_pack_byte(s, cs3_colors[i_color]);
cs3_parse_cmd(s, "00 00 3a 00");
s->n_recv = 58;
// ...
s->real_exposure[cs3_colors[i_color]] =
    65536 * (256 * s->recv_buf[54] + s->recv_buf[55]) +
    256 * s->recv_buf[56] + s->recv_buf[57];
```

The golden fixture does NOT use GET_WINDOW to read exposure. Instead, it uses READ (0x28) with datatype 0x8c (channel state, lines 236–246) and 0x87 (status/progress, lines 302–322). This is a **protocol-level discrepancy** between SANE and the capture.

**Trust decision**: Per AGENTS.md, the capture is ground truth. The capture's use of READ 0x8c/0x87 instead of GET_WINDOW 0x25 is the correct wire format for the LS-40 ED.

---

## Protocol Code Notes

### `coolscan/protocol.py` — LUT Implementation

**`_upload_lut()` (line 1665)**: Correctly implements the SEND 0x2a command with datatype 0x03. The command format matches the golden fixture exactly:
```python
cmd = struct.pack("BBBBBBBBBB",
    0x2A, 0x00, 0x03, 0x00, channel, 0x01, 0x00, 0x20, 0x00, 0x00)
```
Verified: `2a000300010100200000` matches fixture line 282.

**`_generate_identity_lut()` (line 1649)**: Correctly generates 8192-byte identity LUTs (2 bytes per entry, big-endian). Matches fixture data.

**`send_lut()` (line 1623)**: Uses datatype 0xC0 (USER_REG_GAMMA) — **this does NOT match the capture**. This method appears to be dead code or an alternative implementation. No calls to `send_lut()` exist in the codebase; `upload_identity_luts()` calls `_upload_lut()` instead.

### `coolscan/protocol.py` — WDB Tables

The `_SCAN_WINDOW_WDB_TABLES` dictionary (line 282) contains hardcoded WDB templates derived from the pcapng capture. The exposure values at bytes 54–57 are preserved from the capture:
- Prescan R: `0x0000a381` (418.6ms)
- Full scan R: `0x0000ea05` (59.9ms)
- etc.

These match the capture exactly.

### `WindowDescriptorBlock` class

The WDB dataclass (line 74) includes `exposure_r`, `exposure_g`, `exposure_b` fields and serializes them to bytes 0x49–0x4B (73–75). However, the actual capture uses bytes 54–57 (0x36–0x39) for exposure in the 58-byte WDB. This is a **layout discrepancy** — the `WindowDescriptorBlock` class uses a different byte layout than the capture.

**Trust decision**: The capture's 58-byte WDB format (exposure at bytes 54–57) is authoritative. The `WindowDescriptorBlock` class may be based on the SANE backend's WDB structure rather than the wire format.

---

## Open Questions

1. **Why does the capture upload LUTs before the prescan?** SANE only uploads LUTs before the full scan. The capture uploads identity LUTs before both phases. This might be required for the scanner to operate correctly, or it might be an artifact of the Nikon utility's more conservative initialization sequence.

2. **What is the READ 0x8e calibration data used for?** The 3392-byte response (fixture line 216) contains a 4-byte value at offset 6 (`0x000d7904` = 882,948 × 10ns ≈ 8.83ms) followed by zeros. Is this a factory calibration constant? SANE does not read this value; it computes exposure from user settings.

3. **Why are LUTs re-uploaded between scan passes?** The golden fixture shows 4 LUT upload batches. Batches 3 and 4 occur after image data has been read. This might be required for multi-pass scanning (e.g., dust/scratch removal passes).

4. **How does the scanner use LUTs internally?** The LUT maps 12-bit ADC codes to 16-bit output values. For identity LUTs, the scanner passes through the ADC value unchanged (padded to 16 bits). For non-identity LUTs, the scanner applies the tone curve before output.

5. **Does the scanner support per-channel LUTs?** Yes — each channel (R, G, B, IR) has its own LUT upload command. The batch capture confirms all channels receive LUT uploads.

---

## Discrepancies Summary

| Issue | SANE Code | Capture (pcapng) | Verdict |
|-------|-----------|-------------------|---------|
| LUT datatype | 0x03 | 0x03 | Match |
| LUT command format | `2a 00 03 00 ch (n-1) len...` | `2a 00 03 00 ch 01 00 20 00 00` | Match |
| Exposure read method | GET_WINDOW (0x25) | READ 0x8c + READ 0x87 | **Capture wins** |
| LUT upload timing | Only before full scan | Before prescan AND full scan | **Capture wins** |
| WDB exposure bytes | Bytes 54–57 | Bytes 54–57 | Match |
| WDB byte layout | 117-byte WDB | 58-byte WDB | SANE uses different internal layout |

---

## Helper Script

A reusable extraction script has been created at `scripts/extract_lut_from_fixture.py`:
- Reads pre-extracted LUT binary files from the golden fixture
- Parses 16-bit big-endian entries
- Generates ASCII plots of LUT curves
- Outputs JSON summaries and exposure calibration data

Run with `--plot` for ASCII plots, `--json` for machine-readable output.
