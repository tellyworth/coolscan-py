# CoolscanProtocol vs SANE Backend Audit Report

## P0 (Blocker): Will cause scan failure or hardware damage

### P0-1: Sense data byte layout mismatch
**SANE:** `coolscan3.c:2315-2318` — `sense_key = status_buf[1] & 0x0f`, `sense_asc = status_buf[2]`, `sense_ascq = status_buf[3]`
**Ours:** `protocol.py:756-758` — `sense_key = status_data[1] & 0x0F` (matches), BUT `coolscan.c:154-157` uses `get_RS_sense_key()` which reads from `b[0x02] & 0x0f` (byte 2), and `get_RS_ASC()` from `b[0x0c]`, `get_RS_ASCQ()` from `b[0x0d]`

The `coolscan.c` sense handler (`coolscan.c:151-266`) parses a full 18-byte REQUEST_SENSE response where sense_key is at byte 2, ASC at byte 12, ASCQ at byte 13. Our `_parse_status()` parses an 8-byte USB status block where sense_key is at byte 1. **These are different formats.** Our implementation correctly parses the USB 8-byte status (matching `coolscan3.c:2315`), but the ASC/ASCQ values we check in `start_scan()` (e.g., sense_key=0x09, ASC=0x80, ASCQ=0x06) may be wrong if the byte positions don't match the actual protocol. The USB capture comment at `protocol.py:1545` says `0209800601000000` — if byte[0]=0x02, byte[1]=0x09, then SANE's parsing (key=byte[1]&0x0f=9) agrees with our code. **However**, the `coolscan.c` REQUEST_SENSE handler reads sense_key from byte 2, not byte 1, suggesting the full SCSI sense format differs from the USB-abbreviated format. This is likely P3 (cosmetic difference between SCSI and USB sense formats), but worth verifying against captures.

**Verdict on re-examination**: Our `_parse_status` byte positions (key@1, asc@2, ascq@3) match `coolscan3.c:2315-2318` exactly. The `coolscan.c` handler uses a different 18-byte SCSI sense format. **Not a mismatch for USB path.** Downgrading to P3.

---

### P0-2: Missing `set_boundary()` call before scan
**SANE:** `coolscan3.c:3106` — `cs3_set_boundary(s)` is called in `cs3_scan()` between `cs3_convert_options()` and `cs3_set_focus()`. The boundary command sends `2a 00 88 00 00 03` followed by frame count and boundary coordinates (`coolscan3.c:2898-2936`).
**Ours:** `protocol.py:2316-2361` — `perform_scan_sequence()` goes: scanner_ready → reserve_unit → read_capacity → set_window → upload_luts → start_scan → poll. **No `set_boundary()` call exists anywhere in our codebase.**

The `set_boundary()` command (SEND with datatype 0x88, IMAGE_POSITIONS) tells the scanner the scan area boundaries and frame count. Without this, the scanner may not know where to scan or how many frames to expect. This is a **structural gap** in our scan sequence.

**Fix needed:** Add a `set_boundary()` method that sends the 0x2a/0x88 command with frame boundary data before `start_scan()`.

---

## P1 (Bug): Will produce incorrect results or protocol errors

### P1-1: Missing REISSUE status handling after START_SCAN
**SANE:** `coolscan3.c:3147-3151` — After issuing START_SCAN, SANE checks `if (s->status == CS3_STATUS_REISSUE)` and re-issues the command. The REISSUE status is set when `sense_code == 0x09800600 || 0x09800601` (`coolscan3.c:2081-2083`).
**Ours:** `protocol.py:1535-1631` — `start_scan()` checks for ASCQ=0x06 (treats as success) and ASCQ=0x01 (treats as failure), but doesn't re-issue the command. The `StatusType.REISSUE` enum exists (`protocol.py:52`) but is never set by `_parse_status()` (`protocol.py:751-795`).

The REISSUE path is critical for LS-50/LS-5000 scanners. SANE handles it by re-issuing the same command. Our code may silently fail on hardware that requires re-issuing.

**Fix needed:** Map sense_code `0x09800600`/`0x09800601` to `StatusType.REISSUE` in `_parse_status()`, then handle REISSUE in `start_scan()` by re-issuing the command.

### P1-2: LUT upload command byte 4 mismatch
**SANE:** `coolscan3.c:2972-2978` — LUT SEND command: `2a 00 03 00 [channel] [bytes_per_point-1] [len_hi] [len_mid] [len_lo] 00`. Byte 4 is the channel ID (1/2/3/9).
**Ours:** `protocol.py:1375-1376` — `struct.pack("BBBBBBBBBB", 0x2A, 0x00, 0x03, 0x00, channel, 0x01, 0x00, 0x20, 0x00, 0x00)`. Byte 4 is channel, byte 5 is `0x01` (bytes_per_point-1 = 1, meaning 2 bytes per point = 16-bit).

SANE computes `2 - 1 = 1` for byte 5 (commented "number of bytes per data point - 1"). We hardcode `0x01`. These agree. **However**, SANE computes the transfer length as `2 * s->n_lut` where `n_lut = 1 << maxbits` (from inquiry page 0xc1). For a 10-bit scanner, `n_lut = 1024`, so length = 2048 bytes. But our `_generate_identity_lut()` generates 8192 bytes (4096 × 2 bytes), assuming 12-bit depth. This is a **data size mismatch** if the scanner has fewer bits.

**Fix needed:** Read maxbits from inquiry page 0xc1 (byte 82, per `coolscan3.c:2443`) and generate LUT of correct size.

### P1-3: `get_exposure()` missing after `set_window()` in scan sequence
**SANE:** `coolscan3.c:3121-3123` — `cs3_get_exposure(s)` is called after `cs3_set_window()` and before START_SCAN. It reads back WDBs via GET_WINDOW (0x25) for each color channel and extracts exposure from bytes 54-57.
**Ours:** `protocol.py:2316-2361` — `perform_scan_sequence()` does: set_window → upload_luts → start_scan. No `get_exposure()` call.

SANE reads exposure values after SET_WINDOW to validate the scanner's accepted exposure times. Without this, we don't know if the scanner accepted our exposure settings or clamped them.

### P1-4: WDB `negative_dropout` field at wrong byte offset
**SANE:** `coolscan-scsidef.h:349-358` — WDB byte 0x30 contains: bit 4 = negative/positive flag, bits 0-1 = dropout color. The `set_WD_negative()` macro uses `setbitfield(sb + 0x30, 0x1, 4, val)`.
**Ours:** `protocol.py:135-136` — `data[0x30] = self.negative_dropout`. We write the full byte at offset 0x30.

The WDB definition (`coolscan-scsidef.h:278-510`) shows byte 0x30 is a composite field. SANE sets bit 4 for negative mode (value 0x10) and bits 0-1 for dropout color. Our code writes `0x00` or `0x01` to the full byte. If we write `0x01` for negative, we're setting the dropout color to Red (0x00) + bit 4 = 0, not negative. The negative flag should be bit 4 (0x10), not the whole byte.

**Fix needed:** Use `data[0x30] = 0x10` for negative mode, not `0x01`. Or better, use bit manipulation like SANE.

### P1-5: WDB `scan_mode` field interpretation differs from SANE
**SANE:** `coolscan-scsidef.h:362-367` — WDB byte 0x31 bits 4-5 = scan mode (0x00 = normal scan, 0x01 = prescan). Uses `setbitfield(sb + 0x31, 0x3, 4, val)`.
**Ours:** `protocol.py:136-137` — `data[0x31] = self.scan_mode`. We set `scan_mode = 0x00` for normal, `0x01` for prescan.

If we write `0x01` to byte 0x31 for prescan, we're setting bits 0-1 = 0x01, not bits 4-5 = 0x01. SANE expects the value shifted to bits 4-5, so prescan should be `0x10` (0x01 << 4), not `0x01`.

**Fix needed:** For prescan, `data[0x31]` should be `0x10`, not `0x01`.

---

## P2 (Gap): Missing feature that SANE handles

### P2-1: Missing `cs3_set_boundary()` / frame boundary support
**SANE:** `coolscan3.c:2898-2936` — Sends SEND(0x2a) with datatype 0x88 (IMAGE_POSITIONS), containing frame count, frame offsets, and boundary coordinates. Required before scan.
**Ours:** Not implemented.

### P2-2: Missing `cs3_set_focus()` before scan
**SANE:** `coolscan3.c:2649-2657` — `cs3_set_focus()` sends command `e0 00 c1 00 00 00 00 00 09 00` + 8 bytes of focus data. Called in `cs3_scan()` at line 3110.
**Ours:** `auto_focus()` exists (`protocol.py:1981-1998`) but `set_focus()` with a specific focus value is not called in the scan sequence.

### P2-3: Missing `cs3_convert_options()` resolution/pitch calculation
**SANE:** `coolscan3.c:2781-2894` — Computes `real_pitchx = resx_max / real_resx`, then `real_resx = resx_max / real_pitchx`. This ensures resolution is always an integer divisor of max resolution. Also handles `odd_padding` for odd-width images on non-LS30/LS2000 scanners.
**Ours:** `protocol.py:76-105` — WDB uses raw resolution values without pitch calculation. `scanner.py:275-284` calculates pixel dimensions but doesn't apply pitch rounding.

### P2-4: Missing `cs3_convert_options()` exposure clamping
**SANE:** `coolscan3.c:2879-2881` — `for (i_color = 0; i_color < 3; i_color++) if (s->real_exposure[cs3_colors[i_color]] < 1) s->real_exposure[...] = 1;`
**Ours:** No minimum exposure enforcement.

### P2-5: Missing multi-frame / subframe support
**SANE:** `coolscan3.c:222-224` — Has `i_frame`, `frame_count`, `subframe` fields. `cs3_convert_options()` computes `yoffset = ymin + (i_frame-1) * frame_offset + subframe / unit_mm`.
**Ours:** No multi-frame support.

### P2-6: Missing `cs3_load()` / `cs3_eject()` / `cs3_reset()` commands
**SANE:** `coolscan3.c:2574-2624` — Implements LOAD (0xe0/0xd1), EJECT (0xe0/0xd0), RESET (0xe0/0x80) commands.
**Ours:** Not implemented.

### P2-7: Missing `cs3_execute()` command
**SANE:** `coolscan3.c:2533-2541` — `cs3_execute()` sends `c1 00 00 00 00 00`. Used after certain operations.
**Ours:** Not implemented.

### P2-8: Missing `cs3_autoexposure()` / `cs3_autofocus()` in scan flow
**SANE:** `coolscan3.c:1501-1515` — `sane_start()` calls `cs3_autofocus()` and `cs3_autoexposure()` before `cs3_scan()`.
**Ours:** `auto_focus()` exists but isn't called in `perform_scan_sequence()`. No `autoexposure()` equivalent.

### P2-9: Missing data reassembly (interleaved → planar → RGB)
**SANE:** `coolscan3.c:1626-1698` — `sane_read()` reads interleaved data from scanner, handles `odd_padding`, `block_padding`, multi-sample averaging, and reassembles into RGB pixel format. Handles both 8-bit and 16-bit depths.
**Ours:** `scanner.py:296-320` reads raw chunks and reshapes directly to RGB. No padding handling, no multi-sample averaging, no 16-bit support.

### P2-10: Missing independent X/Y resolution support
**SANE:** `coolscan3.c:2798-2804` — Has `res_independent` flag that allows different X and Y resolutions.
**Ours:** Only supports same resolution for both axes.

### P2-11: `mode_select()` sent in both init and scan sequence
**SANE:** `coolscan3.c:419` — `cs3_mode_select()` called once during `sane_open()`. For CS2 scanners, `coolscan2.c:2822-2833` sends MODE_SELECT again inside `cs2_scan()`.
**Ours:** `protocol.py:2290-2303` sends MODE_SELECT during init, AND `protocol.py:1407-1441` `set_window_wdb()` sends another MODE_SELECT. The second MODE_SELECT in `set_window_wdb()` may be redundant or harmful depending on scanner model.

### P2-12: Missing `cs3_release_unit()` in scan teardown
**SANE:** `coolscan3.c` doesn't explicitly release unit after scan (unit is released on close). But `coolscan2.c` has different behavior.
**Ours:** `scanner.py:328` calls `release_unit()` after scan. This may be fine, but worth noting the behavioral difference.

---

## P3 (Cosmetic): Different but both work

### P3-1: `scanner_ready()` timeout and interval
**SANE:** `coolscan3.c:2349-2378` — 1-second sleep between retries, 120-second max timeout.
**Ours:** `protocol.py:689-732` — 0.5-second delay, configurable timeout (default 30s via `scanner_ready()`). Our timeout is shorter but more responsive.

### P3-2: `poll_until_ready()` vs SANE's inline polling
**SANE:** `coolscan3.c:2349-2378` — `cs3_scanner_ready()` is called inline throughout scan flow. No dedicated "poll until scan complete" function.
**Ours:** `protocol.py:1687-1748` — `poll_until_ready()` with 100ms interval, 30s timeout. More granular but different from SANE's approach.

### P3-3: INQUIRY page sequence differs
**SANE:** `coolscan3.c:2431-2530` — `cs3_full_inquiry()` reads page 0xc1, then parses specific bytes for device capabilities.
**Ours:** `protocol.py:2248-2274` — Reads pages 0x01, 0xd1, 0xc1, 0xe1, 0xf0, 0xf8. We read more pages but don't parse as many fields from 0xc1.

### P3-4: WDB construction approach differs
**SANE:** `coolscan3.c:2993-3070` — Dynamically constructs 50-byte WDB per color channel.
**Ours:** `protocol.py:1454-1508` — Uses hardcoded 58-byte WDBs from USB capture. Both approaches produce valid WDBs, but ours includes 8 extra bytes (exposure values at bytes 50-57) that SANE doesn't set explicitly.

### P3-5: LUT upload timing differs
**SANE:** `coolscan3.c:3114-3115` — LUTs uploaded BEFORE `set_window()` (only for NORMAL scan).
**Ours:** `protocol.py:2338-2340` — LUTs uploaded AFTER `set_window()`. USB captures show both orderings work, so this is model-dependent.

### P3-6: `read_scan_data()` chunk size
**SANE:** `coolscan3.c:1556-1618` — Reads one line at a time: `xfer_len_in = n_colors * logical_width * bytes_per_pixel`. For 2592px width RGB 8-bit, that's ~7776 bytes per READ.
**Ours:** `scanner.py:298` — 64KB chunks. Larger chunks are fine and may be faster. No protocol issue.

### P3-7: `cancel_scan()` command
**SANE:** `coolscan3.c:1722-1724` — Uses `c0 00 00 00 00 00` (SABORT).
**Ours:** `protocol.py:1976-1979` — Same command. Matches.

### P3-8: `wait_scanner()` retry count
**SANE:** `coolscan.c:273-306` — Max 40 retries (20 seconds at 500ms intervals).
**Ours:** `protocol.py:689` — Default 10 attempts (5 seconds at 500ms intervals). Shorter but configurable.

---

## Summary by Priority

| Priority | Count | Items |
|----------|-------|-------|
| P0 | 1 | P0-2: Missing `set_boundary()` |
| P1 | 5 | P1-1: REISSUE handling, P1-2: LUT size, P1-3: get_exposure, P1-4: WDB negative bit, P1-5: WDB scan_mode bit |
| P2 | 11 | P2-1 through P2-12 |
| P3 | 8 | P3-1 through P3-8 |

**Most critical action items:**
1. Add `set_boundary()` before scan (P0-2)
2. Fix WDB negative/scan_mode bit positions (P1-4, P1-5)
3. Add REISSUE status handling (P1-1)
4. Compute correct LUT size from maxbits (P1-2)
5. Add `get_exposure()` after `set_window()` (P1-3)
