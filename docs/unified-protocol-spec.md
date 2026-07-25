# Unified Protocol Specification
## Combining SANE Backend Analysis and USB Capture Findings

This document combines insights from both SANE backend code analysis and USB traffic capture to provide a complete protocol specification.

## Command Format: The Translation Layer

### The Discovery

SANE backend code shows **standard SCSI CDB format**, but USB captures show a **USB-specific format**. This is because:

1. **SANE's USB infrastructure (`sanei_usb_*`) performs translation** from standard SCSI to USB-specific format
2. **PyUSB has no translation layer** - we must send commands in the exact format the scanner expects
3. **The USB capture revealed the actual format** that bypasses SANE's abstraction

### USB-Specific 6-Byte Command Format

```
Byte 0: Command code (0x12 = INQUIRY, 0x00 = TEST_UNIT_READY, etc.)
Byte 1: Page/Subcommand code (for INQUIRY variants)
Byte 2: Parameter 2
Byte 3: Parameter 3
Byte 4: Allocation length (how many bytes to read)
Byte 5: Control byte (0x80 for most commands, 0x00 for simple ones)
```

**Key Difference from Standard SCSI**: Control byte is `0x80` (not `0x00`) for most commands.

### Command Examples

#### TEST_UNIT_READY
- **SANE shows**: `{0x00, 0x00, 0x00, 0x00, 0x00, 0x00}` (standard SCSI)
- **USB format**: `00 00 00 00 00 00` (same, control byte is 0x00 for simple commands)

#### INQUIRY (standard, 36 bytes)
- **SANE shows**: `{0x12, 0x00, 0x00, 0x00, 0x1f, 0x00}` (standard SCSI, 0x1f = 31 bytes)
- **USB format**: `12 00 00 00 24 80` (USB-specific, 0x24 = 36 bytes, control = 0x80)

#### INQUIRY (page 0x01, length 4)
- **USB format**: `12 01 00 00 04 80`
  - Byte 1: Page code (0x01)
  - Byte 4: Allocation length (0x04 = 4 bytes)
  - Byte 5: Control byte (0x80)

#### RESERVE_UNIT
- **USB format**: `16 00 00 00 00 00`
  - Control byte is 0x00 (simple command)

#### READ_CAPACITY / GET_WINDOW (0x25)

**Purpose**: Read the current window descriptor block (WDB) state for a given
window. Despite the SCSI name "READ_CAPACITY", this command functions as
GET_WINDOW — it returns the same 58-byte WDB format sent via SET_WINDOW (0x24).

##### CDB Format

```
Byte 0:   0x25 (READ_CAPACITY / GET_WINDOW)
Byte 1:   Flags (0x00 = window 0 / global state, 0x01 = specific window)
Byte 2-4: 0x00 (reserved)
Byte 5:   Window ID (ignored when byte 1 = 0x00)
Byte 6-7: 0x00 (reserved)
Byte 8:   Allocation length (0x3a = 58 bytes)
Byte 9:   Control byte (0x80)
```

**Examples from golden fixture:**
- Window 0 (global state): `25 00 00 00 00 00 00 00 3a 80` — line 89
- Window 1 (R channel): `25 01 00 00 00 01 00 00 3a 80` — line 94
- Window 2 (G channel): `25 01 00 00 00 02 00 00 3a 80` — line 99
- Window 3 (B channel): `25 01 00 00 00 03 00 00 3a 80` — line 104
- Window 9 (IR channel): `25 01 00 00 00 09 00 00 3a 80` — line 114

##### Response Format (58 bytes)

The response mirrors the WDB format sent by SET_WINDOW (0x24). The data starts
at byte 8 with the same 50-byte WDB payload (bytes 8-57 of the SET_WINDOW data).

**Per-window response** (byte 1 of CDB = 0x01):
```
Byte 0:       Status / flags
Bytes 1-7:    Header (varies)
Byte 8:       Data length (always 0x32 = 50)
Byte 9:       Window ID (0x01=R, 0x02=G, 0x03=B, 0x09=IR)
Bytes 10-11:  X resolution (big-endian uint16)
Bytes 12-13:  Y resolution (big-endian uint16)
Bytes 14-17:  X offset (big-endian uint32)
Bytes 18-21:  Y offset (big-endian uint32)
Bytes 22-25:  Width (big-endian uint32)
Bytes 26-29:  Height (big-endian uint32)
Byte 30:      Brightness
Byte 31:      Threshold
Byte 32:      Contrast
Byte 33:      Image composition (0x05=prescan, 0x02=normal)
Byte 34:      Pixel composition/depth (0x0c=12-bit, 0x08=8-bit)
Bytes 35-47:  Reserved zeros
Byte 48:      Multiread / ordering
Byte 49:      Averaging | Positive/Negative
Byte 50:      Scan kind (0x01=normal, 0x02=prescan/AE, 0x20=AE, 0x40=AE_WB)
Byte 51:      Scan mode (0x02=single, 0x10=multi)
Byte 52:      Color interleave (0x02)
Byte 53:      AE byte (0xff)
Bytes 54-57:  Exposure value (big-endian uint32, 10ns units)
```

**Window 0 response** (byte 1 of CDB = 0x00):
The window-0 response returns global scanner state rather than a per-window WDB.
The format differs slightly: bytes 0-7 contain a header, byte 8 is 0x32, and
bytes 10-13 typically hold the current Measurement Unit Divisor (MUD).

**Example — window 0 response** (golden fixture line 93):
```
01 00 00 00 00 00 00 32 00 00 0b 54 0b 54 ...
                          ^^ ^^  ^^ ^^ ^^ ^^
                          len=50  MUD=0x0b54 (2900 DPI)
```

**Example — window 1 response** (golden fixture line 97, after setting full-res WDB):
```
00 38 00 00 00 00 00 32 01 00 0b 54 0b 54 00 00
                       ^^    ^^ ^^ ^^ ^^
                       len=50 wid=1  x_res=2900 y_res=2900
```

##### Per-Window vs Global

| Window | CDB byte 1 | Returns |
|--------|-----------|---------|
| 0 | 0x00 | Global state: MUD, scanner config |
| 1+ | 0x01 | Per-window WDB mirror of last SET_WINDOW for that window |

The per-window READ_CAPACITY responses are used after prescan to read back the
calibrated exposure values (bytes 54-57) that the scanner determined during
auto-exposure. See `CoolscanProtocol.get_exposure_values()` in `protocol.py`.

##### Known Issues

The `read_capacity()` method at `protocol.py:4668` parses the response as a
standard SCSI READ_CAPACITY format (capacity + block size). This does not
match the actual 58-byte response layout described above. The
`extract_read_capacity()` function in `scripts/analyze_capture.py` uses the
correct WDB-based offsets.

#### START_STOP_UNIT (start scan)
- **USB format**: `1b 00 00 00 03 00`
  - Byte 4: Action (0x03 = start, 0x04 = stop)
  - Control byte is 0x00

#### SET_WINDOW (0x24) - Send Window Descriptor Block
- **USB format**: `24 00 00 00 00 00 00 00 3a 80` (10 bytes)
  - Byte 0: 0x24 (SET_WINDOW)
  - Byte 1-7: 0x00 (reserved)
  - Byte 8: 0x3a = 58 (transfer length)
  - Byte 9: 0x80 (control)

**WDB Data Format** (58 bytes):
- Bytes 0-6: Header (zeros)
- Byte 7: 0x32 = 50 (length of WDB data)
- Byte 8: Window ID (0x01=R, 0x02=G, 0x03=B, 0x09=IR)
- Byte 9: Reserved (0x00)
- Bytes 10-11: X resolution (big-endian)
- Bytes 12-13: Y resolution (big-endian)
- Bytes 14-17: X offset (4 bytes, big-endian)
- Bytes 18-21: Y offset (4 bytes, big-endian)
- Bytes 22-25: Width (4 bytes, big-endian)
- Bytes 26-29: Height (4 bytes, big-endian)
- Byte 30: Brightness
- Byte 31: Threshold
- Byte 32: Contrast
- Byte 33: Image composition (0x05 for prescan, 0x02 for normal)
- Byte 34: Pixel composition/depth (0x0c=12-bit prescan, 0x08=8-bit normal)
- Bytes 35-47: Reserved zeros (13 bytes)
- Byte 48: Multiread/ordering
- Byte 49: Averaging (0x80) | Positive/Negative (0x01=positive)
- Byte 50: Scan kind (0x01=normal, 0x02=prescan/AE, 0x20=AE, 0x40=AE_WB)
- Byte 51: Scan mode (0x02=single, 0x10=multi)
- Byte 52: Color interleave (0x02)
- Byte 53: AE byte (0xff)
- Bytes 54-57: **Exposure value** (4 bytes, big-endian, in 10ns units) - NOT a checksum!

**Prescan vs Normal Scan WDBs:**
| Parameter | Prescan (AE) | Normal (Full) |
|-----------|-------------|---------------|
| Resolution | 0x0060 (96 DPI) | 0x0b54 (2900 DPI) |
| Scan kind (byte 50) | 0x02 | 0x01 |
| Image comp (byte 33) | 0x05 | 0x02 |
| Depth (byte 34) | 0x0c (12-bit) | 0x08 (8-bit) |
| Windows | 1, 2, 3 only | 1, 2, 3 (+ 9 for IR) |

**Example Prescan WDB (from USB capture):**
```
0000000000000032 01 0060 0060 00000000 00000000 00000b36 00008760
00 00 00 05 0c 00000000000000000000000000 00 81 02 02 02 ff 0000a381
```

**Example Normal WDB:**
```
0000000000000032 01 0b54 0b54 00000000 00000000 00000b36 000010ec
00 00 00 02 08 00000000000000000000000000 00 81 01 02 02 ff 00009ce6
```

#### WRITE (0x2a) - Send LUT (Look-Up Table) Data
- **USB format**: `2a 00 03 00 [channel] 01 00 [len_hi] [len_lo] 00` (10 bytes)
  - Byte 0: 0x2a (WRITE)
  - Byte 1: 0x00 (LUN)
  - Byte 2: 0x03 (datatype = LUT)
  - Byte 3: 0x00 (reserved)
  - Byte 4: Channel index (0x01=R, 0x02=G, 0x03=B)
  - Byte 5: 0x01 (fixed)
  - Byte 6: 0x00 (reserved)
  - Byte 7-8: Transfer length big-endian (0x20 0x00 = 0x2000 = 8192 bytes)
  - Byte 9: 0x00 (control)

**LUT Data Format**:
- 8192 bytes per channel (4096 entries × 2 bytes each)
- 16-bit big-endian values
- Identity LUT: `0000 0001 0002 0003 ... 0fff`
- Three channels must be uploaded: R, G, B

**Example from USB capture:**
- R channel: `2a000300010100200000` → send 8192 bytes
- G channel: `2a000300020100200000` → send 8192 bytes
- B channel: `2a000300030100200000` → send 8192 bytes

#### READ/WRITE Datatypes (0x28 / 0x2a)

The scanner uses **datatype codes in byte 2** of READ(10) / WRITE(10) commands to
distinguish what is being transferred:

- `0x00` (READ): Image data blocks (prescan / full scan pixels)
- `0x03` (WRITE): LUT data (as described above)
- `0x87` (READ): Internal status / progress blocks (6–33 byte payloads)
- `0x8c` (READ): Per-channel state (10-byte response; bytes 6–9 = calibrated
  exposure in 10ns units, big-endian uint32)
- `0x8e` (READ): Exposure / calibration tables (prescan statistics)
- `0x8f` (WRITE): Small control blocks (e.g. frame / exposure program writeback)

Examples from `usb_capture_timing.txt`:

- Image data:
  - `28000000000001fec080` → READ 0x1fec0 bytes of scan data
  - `280000000000002d0080` → READ 0x2d00 bytes (final tail block)
- Status / progress:
  - `28008700000000000680` → READ 6 bytes (datatype 0x87)
  - `28008700000000002180` → READ 0x21 bytes (datatype 0x87)
  - `28008700000000001880` → READ 0x18 bytes (datatype 0x87)
- Channel state (auto-exposure calibration):
  - `28008c00010300000a80` → READ 10 bytes for channel 1 (R)
  - `28008c00020300000a80` → READ 10 bytes for channel 2 (G)
  - `28008c00030300000a80` → READ 10 bytes for channel 3 (B)
  - Response format: `8c 20 [header 4B] [exposure 4B big-endian]`
- Exposure / calibration:
  - `28008e00000000000680` → READ 6 bytes (header)
  - `28008e000000000d8880` → READ 0x0d88 bytes (3456-byte table)
- Control / writeback:
  - `2a008f00000300003400` → WRITE 0x34 bytes (datatype 0x8f)

## Communication Protocol Pattern

### Standard Command Sequence (from USB capture)

1. **Send command** (6 or 10 bytes) to endpoint 0x01 (OUT)
2. **Send phase check** (0xd0) to endpoint 0x01 (OUT)
3. **Read phase response** (1 byte) from endpoint 0x82 (IN)
   - `0x01` = Status phase
   - `0x02` = Data out phase (send data)
   - `0x03` = Data in phase (read data)
   - `0x04` = Busy phase
4. **Handle phase**:
   - If phase is `0x02` (Data OUT): Send data, then check phase again (send 0xd0, read phase)
   - If phase is `0x03` (Data IN): Read data bytes (allocation length)
5. **Read status** (8 bytes) from endpoint 0x82 (IN)
   - Status byte, sense key, ASC, ASCQ, etc.

### Phase Checking (from both sources)

- **SANE**: Uses `cs2_phase_check()` / `cs3_phase_check()` before reading status
- **USB capture**: Shows 572 phase checks in a single scan session
- **Frequency**: Phase check (0xd0) is sent **after every command**
- **Critical**: This is mandatory for proper communication
- **After data transfer**: When phase is 0x02 (Data OUT) and data is sent, check phase again before reading status

## Initialization Sequence

### From USB Capture (Actual Working Sequence)

1. **INQUIRY (standard)** - `120000002480` (36 bytes)
   - Get device identification ("Nikon   LS-40 ED")

2. **TEST_UNIT_READY** (multiple times) - `000000000000`
   - Wait for scanner to be ready
   - Sent 4 times initially, then 346 times total in scan session

3. **INQUIRY pages** (two-step: get length, then full data):
   - Page 0x01 (capabilities): `120100000480` → `120100001580`
   - Page 0xd1 (MUD info): `1201d1000480` → `1201d1001c80` (28 bytes)
   - Page 0xc1 (configuration): `1201c1000480` → `1201c1005580` (85 bytes)
   - Page 0xe1: `1201e1000480` → `1201e1002780` (39 bytes)
   - Page 0xf0: `1201f0000480` → `1201f0003580` (53 bytes)
   - Page 0xf8: `1201f8000480` → `1201f8000f80` (15 bytes)

4. **RESERVE_UNIT** - `160000000000`
   - Reserve the scanner unit

5. **READ_CAPACITY** - `25000000000000003a80` (10 bytes, 58-byte response)

### From SANE Backend (High-Level Logic)

1. **Open device** - `sanei_usb_open()` or `sanei_scsi_open()`
2. **INQUIRY** - Identify scanner
3. **wait_scanner()** - Send TEST_UNIT_READY repeatedly (up to 40 attempts, 0.5s delays)
4. **RESERVE_UNIT** - Reserve scanner
5. **MODE_SENSE** - Get Measurement Unit Divisor (MUD)
6. **get_internal_info()** - Read internal info (datatype 0xe0, 256 bytes)
7. **RELEASE_UNIT** - Release scanner

### Combined Sequence (Recommended)

1. **INQUIRY (standard)** - Get device identification
2. **wait_scanner()** - TEST_UNIT_READY with retry logic (SANE pattern)
3. **INQUIRY pages** - Get configuration data (USB capture pattern)
4. **RESERVE_UNIT** - Reserve scanner
5. **READ_CAPACITY** - Get capacity info (USB capture)
6. **MODE_SENSE** - Get MUD (SANE pattern, if needed)
7. **get_internal_info()** - Read internal info (SANE pattern, if needed)

## Timing and Retry Logic

### From SANE Backend

- **wait_scanner()**: Up to 40 attempts with 0.5 second delays (20 seconds max)
- **Prescan timing**: Originally used 8 second sleep, now uses dynamic polling (`poll_until_ready()`)
- **Handles DEVICE_BUSY**: Retries on busy status

### From USB Capture

- **TEST_UNIT_READY frequency**: 346 times in a single scan session
- **Phase check frequency**: 572 times in a single scan session
- **Command polling**: Frequent status checks during operations

### Combined Approach

- Use SANE's retry logic (40 attempts, 0.5s delays) for `wait_scanner()`
- Use USB capture's command format for actual commands
- Follow USB capture's phase checking pattern (after every command)

## Status Handling

### Status Format (8 bytes) - Both Sources Agree

```
Byte 0: Status byte (0x00 = READY, 0x02 = CHECK_CONDITION)
Byte 1: Sense key (lower nibble)
Byte 2: ASC (Additional Sense Code)
Byte 3: ASCQ (Additional Sense Code Qualifier)
Bytes 4-7: Additional sense information (byte 4 used for REISSUE aux code)
```

### Sense Key / ASC / ASCQ Reference

This table is extracted from `_parse_status()` at `coolscan/protocol.py:1168`
and cross-referenced with SANE `coolscan3.c:2045-2083`.

| Key | ASC | ASCQ | Byte 4 | Protocol Status | Meaning | Example from Golden Fixture |
|-----|-----|------|--------|-----------------|---------|-----------------------------|
| `0x00` | — | — | — | `READY` | No sense — scanner is ready | `00 00 00 00 00 00 00 00` (line 332) |
| `0x01` | `0x37` | `0x00` | — | `READY` | Recovered error — rounded parameter | |
| `0x01` | other | — | — | `ERROR` | Recovered error (unexpected ASC) | |
| `0x02` | `0x04` | `0x01` | — | `PROCESSING` | Not ready — becoming ready (scan in progress) | `02 02 04 01 00 00 00 00` (line 306) |
| `0x02` | `0x3A` | `0x00` | — | `NO_DOCS` | Not ready — no medium present | |
| `0x02` | other | — | — | `PROCESSING` | Not ready — unknown ASC (tolerate firmware quirks) | |
| `0x03` | — | — | — | `ERROR` | Medium error | |
| `0x04` | — | — | — | `ERROR` | Hardware error | |
| `0x05` | — | — | — | `ERROR` | Illegal request (e.g. wrong datatype) | `05 26 00 00 ...` (SANE's 0x88 rejected) |
| `0x06` | `0x28` | `0x00` | — | `NO_DOCS` | Unit attention — no document | |
| `0x06` | `0x40` | — | — | `BUSY` | Unit attention — busy | |
| `0x06` | `0x41` | — | — | `BUSY` | Unit attention — busy alt | |
| `0x06` | other | — | — | `ERROR` | Unit attention (unexpected ASC) | |
| `0x09` | `0x80` | `0x06` | `0x00` | `REISSUE` | Vendor-specific — resend command | `09 80 06 00 ...` (line 297, attempt 1) |
| `0x09` | `0x80` | `0x06` | `0x01` | `REISSUE` | Vendor-specific — resend command alt | |
| `0x09` | `0x80` | `0x01` | — | `READY` | Vendor-specific — command acknowledged (after REISSUE retry) | `09 80 01 00 ...` (line 303, attempt 2) |
| `0x09` | other | — | — | `ERROR` | Vendor-specific (unexpected ASC) | |
| `0x0B` | — | — | — | `ERROR` | Aborted command | |

### REISSUE Pattern (3-Attempt Retry)

The scanner uses sense key `0x09` (vendor-specific) for a 3-attempt
handshake on `START_SCAN`:

| Attempt | Status Bytes | Meaning | Action |
|---------|-------------|---------|--------|
| 1 | `09 80 06 00 ...` | REISSUE — scanner wants command resent | Read 6-byte status (0x87), then 33-byte status; retry |
| 2 | `09 80 01 00 ...` | Vendor-specific acknowledge (treated as ERROR) | Read 6-byte status (0x87), then 24-byte status; retry |
| 3 | `00 00 00 00 00 00 00 00` | READY — scan started successfully | Continue to polling |

This matches golden fixture lines 297-331 and is implemented in
`start_scan()` at `protocol.py:2414`. The pattern is consistent across
prescan, full scan, and batch `START_SCAN` operations.

### TUR Polling Pattern

While a scan is running, `TEST_UNIT_READY` (`00 00 00 00 00 00`) returns:
- `02 02 04 01 00 00 00 00` — PROCESSING (scanner is scanning)
- `00 00 00 00 00 00 00 00` — READY (scan pass complete)

The implementation uses `poll_until_ready()` (`protocol.py:2547`) for
dynamic polling at 500ms intervals rather than a fixed sleep. The CLI
analysis tool (`scripts/analyze_capture.py`) suppresses NOT_READY status
during TUR polling as expected background noise.

### StatusType Enum

```python
class StatusType(Enum):
    READY      = 0   # 0x00 key — scanner is ready
    BUSY       = 1   # 0x06 key, ASC 0x40/0x41 — scanner is busy
    NO_DOCS    = 2   # 0x02 key ASC 0x3A or 0x06 key ASC 0x28 — no film
    PROCESSING = 4   # 0x02 key ASC 0x04 — scan in progress
    ERROR      = 8   # all other non-READY, non-REISSUE statuses
    REISSUE    = 16  # 0x09 key ASC 0x80 ASCQ 0x06 — resend command
```

## Scan Operations

### Setting Scan Parameters and LUT

The scan is prepared using a multi-step process:

1. **MODE_SELECT (0x15)** - Set mode parameters
   - Command: `15 10 00 00 14 00` (6 bytes)
   - Phase check returns 0x02 (Data OUT)
   - Send 20 bytes of mode parameters: `000000080000000000000001030600000b540000`
   - Read status

2. **WRITE LUT (0x2a)** - Upload Look-Up Tables for R, G, B channels
   - **CRITICAL**: Scanner requires LUT data before scanning!
   - Command format: `2a 00 03 00 [channel] 01 00 20 00 00` (10 bytes)
     - Byte 2: 0x03 = datatype (LUT)
     - Byte 4: channel (0x01=R, 0x02=G, 0x03=B)
     - Byte 7-8: length big-endian (0x20 0x00 = 0x2000 = 8192 bytes)
   - Phase check returns 0x02 (Data OUT)
   - Send 8192 bytes of LUT data (identity LUT: 0000-0fff in 16-bit big-endian)
   - Read status
   - Repeat for each channel (R, G, B)

**LUT Commands from USB capture:**
- R channel: `2a000300010100200000` + 8192 bytes
- G channel: `2a000300020100200000` + 8192 bytes
- B channel: `2a000300030100200000` + 8192 bytes

**Identity LUT Data**:
```
0000 0001 0002 0003 0004 0005 ... 0ffe 0fff
```
(4096 entries × 2 bytes = 8192 bytes per channel)

### Prescan Sequence (Verified Working - January 2026)

The prescan performs auto-exposure (AE) at low resolution to determine optimal exposure values.

**Command Sequence:**
1. **MODE_SELECT** (`15 10 00 00 14 00`) + 20-byte mode params
2. **Wait** ~150ms for scanner to process
3. **TEST_UNIT_READY** - Ensure scanner is ready
4. **SET_WINDOW** × 4 (windows 1, 2, 3 for RGB + window 9 for IR)
    - Uses prescan WDBs: 96 DPI, scan_kind=0x02
5. **TEST_UNIT_READY** - Required before LUT upload
6. **WRITE LUT R/G/B** × 3 - Upload identity LUTs
7. **START_SCAN** (`1b 00 00 00 03 00`) + 3 bytes (`01 02 03`)
8. **Polling Loop** - `poll_until_ready()` polls with TEST_UNIT_READY every ~500ms
   - Status `0202040100000000` = PROCESSING (scanner is scanning)
   - Status `0000000000000000` = READY (scan pass complete)
9. **Read Image Data** - `read_prescan_image_data()` reads:
   - Two 130752-byte blocks (`28000000000001fec080`)
   - One 11520-byte residual block (`280000000000002d0080`)
   - Total: 273024 bytes of prescan image data
   - Decode as 12-bit RGB, 96×474, plane-interleaved. See `docs/protocol.md` and
     `docs/sane-image-data.md` for the verified low-res decoding recipe.
10. **Read Exposure Data** - `read_exposure_data()` reads:
    - 6-byte header (`28008e00000000000680`)
    - 3464-byte exposure/calibration table (`28008e000000000d8880`)
11. Process may repeat for multiple passes

**Timing (from USB capture):**
- START_SCAN to first READY: ~13 seconds (dynamic polling, not fixed sleep)
- Full prescan cycle: ~25+ seconds with data reading

**Key Insight:** The scanner returns status with sense_key=0x02 (PROCESSING) while scanning.
Poll with TEST_UNIT_READY until status returns sense_key=0x00 (READY). The implementation uses
`poll_until_ready()` for dynamic polling instead of a fixed 8-second sleep.

**Test coverage:** Prescan sequence contracts are validated in
`tests/test_protocol_contracts.py` (`test_prescan_frame_contract`, which
asserts call order for `set_boundary_for_prescan`, `read_exposure_data`,
`read_control_frame`, `read_channel_state`, `set_scan_window` ×3,
`upload_identity_luts(include_ir=False)`, `start_scan`, and `poll_until_ready`).
The prescan image data format and CDB allocation lengths are validated by
`tests/test_read_scan_data_cdb.py`. For the complete phase-by-phase
walkthrough, see `docs/scan-sequence.md`.

### Full Scan Sequence (from USB capture)

1. **MODE_SELECT** (`15 10 00 00 14 00`) + 20-byte mode params
2. **SET_WINDOW** (`24 00 00 00 00 00 00 00 3a 80`) + 58-byte WDB (window 1)
3. **SET_WINDOW** (`24 00 00 00 00 00 00 00 3a 80`) + 58-byte WDB (window 2)
4. **SET_WINDOW** (`24 00 00 00 00 00 00 00 3a 80`) + 58-byte WDB (window 3)
5. **(Optional) SET_WINDOW** for window 9 (infrared channel)
6. **TEST_UNIT_READY** - Required before LUT upload
7. **WRITE LUT R** (`2a 00 03 00 01 01 00 20 00 00`) + 8192-byte identity LUT
8. **WRITE LUT G** (`2a 00 03 00 02 01 00 20 00 00`) + 8192-byte identity LUT
9. **WRITE LUT B** (`2a 00 03 00 03 01 00 20 00 00`) + 8192-byte identity LUT
10. **START_SCAN** (`1b 00 00 00 03 00`) + 3 bytes (`01 02 03` for RGB)
11. **Polling Loop** - TEST_UNIT_READY until scanner is ready
12. **READ** commands to get scan data
13. **STOP_SCAN** (`1b 00 00 00 04 00`) when complete

> **Single-BW full scan nuance:** The capture-driven `full_scan_frame()` sequence
> runs a 290 DPI IR/RGB preview between setup and the high-res capture. The
> `read_ir_preview_data()` helper reads 997632 bytes of 12-bit plane-interleaved
> R/G/B/IR data (288×433). See `docs/protocol.md` for the verified decoding
> recipe and channel order.

**Test coverage:** Full-scan helper contracts are validated in
`tests/test_protocol_contracts.py` (`test_full_scan_setup_frame_contract`
and `test_full_scan_capture_frame_contract`) covering `set_boundary()`
(CONTROL_FRAME), `read_focus()`, `read_channel_state(9)`,
`upload_identity_luts(include_ir=True)`, `stop_scan()`, and the capture
frame sequence. CDB-level contracts are in `tests/test_protocol_behavior.py`.
Full-sequence replay will be restored once `perform_scan_sequence()`
is rewritten as composable scenario methods (see
`.opencode/plans/golden-fixture-sequence-alignment.md`).

**Full scan image data replay:** First-stripe replay is temporarily removed
with the legacy full-sequence test. It will be restored when `full_scan_frame()`
is composed. The CDB allocation lengths (258048, 223488, 259200, 103680) and the
scanner's 65508-byte-per-chunk return behavior are still validated by
`tests/test_read_scan_data_cdb.py`.

**Remaining full scan validation:** (A) `tests/test_read_scan_data_cdb.py` proves `read_scan_data()` emits correct READ(10) CDBs for all stripe sizes (258048, 223488, 259200, 103680) plus status/exposure datatypes; (B) `tests/test_get_window_cdb.py` validates GET_WINDOW CDBs and WDB exposure extraction; (C) `tests/test_scan_read_integration.py` covers full control flow from setup through `read_scan_data(64)` to release_unit with synthetic IN data.

## Batch Mode (Multi-Frame Scanning)

Batch mode scans multiple film frames in sequence with auto-focus between
frames. It uses a three-stage scan pipeline per frame: a low-resolution
IR+RGB preview (Stage A), an intermediate preview (Stage B), and a
full-resolution RGB capture (Stage C).

**Oracle:** `ls40-batch.pcapng` / `reference/golden_batch.txt`

### State Machine

```
idle -> setup -> stage_a_capture -> between -> stage_b_capture ->
full_res_setup -> full_res_start -> full_res_capture ->
(loop back to setup for next frame) -> teardown -> done
```

### Per-Frame Transitions

| # | Transition | Method | Stage |
|---|-----------|--------|-------|
| 1 | setup -> stage_a_capture | `batch_full_scan_setup_frame()` | 290 DPI IR+RGB setup (similar to single-BW setup, but no `stop_scan`) |
| 2 | -> scanning | `start_scan(BATCH)` | Start batch scan for Stage A |
| 3 | -> data | `batch_full_scan_capture_frame()` | Read Stage A IR+RGB 290 DPI data |
| 4 | -> between | `_wait_ready_or_replay_once()` x2 | Transition polls (TUR) |
| 5 | between -> stage_b_capture | `batch_between_scan_setup_frame()` | Configure Stage B windows |
| 6 | -> data | `batch_preview_capture_frame()` | Read Stage B preview data |
| 7 | -> full_res_setup | `batch_full_res_setup_frame()` | Configure 2900 DPI at per-frame Y offset |
| 8 | -> full_res_start | `batch_full_res_start_frame()` | START_SCAN + poll until READY |
| 9 | -> full_res_capture | `batch_full_res_capture_frame()` | Read full-res RGB data |
| 10 | -> next setup | `poll_until_ready()` | Wait for scanner to finish naturally; **no STOP_SCAN between frames** |
| -- | (before loop) | `post_prescan_autofocus()` + TUR x2 | Auto-focus at next frame center |
| 11 | -> done | `scan_teardown()` | STOP_SCAN + RELEASE_UNIT |

### Key Differences from Single-BW

- **Setup does not call `stop_scan()`** -- batch `batch_full_scan_setup_frame()`
  uploads LUTs and configures windows but skips `stop_scan()`; the next event
  is `start_scan(BATCH)` rather than `stop_scan`.
- **No `stop_scan()` between full-res frames.** After each full-res capture the
  driver polls until READY; the scanner returns to READY naturally once the exact
  byte count is consumed. The next frame then starts with auto-focus and TUR
  polling. This matches the golden batch pcapng.
- **Three scan passes per frame** -- Stage A (290 DPI IR+RGB), Stage B (290 DPI
  preview), Stage C (2900 DPI full res) run as separate `START_SCAN` -> poll ->
  read -> next sequence.
- **Per-frame auto-focus** -- Between frames, autofocus runs at the next frame's
  center coordinates. Frame 0 autofocus happens during setup; frames 1+ use
  `post_prescan_autofocus()`.
- **Per-frame Y offset** -- Each frame's full-res WDBs are parameterized with a
  Y offset computed as `first_y + frame_index * step`.
- **IR LUT always uploaded** -- Batch mode uploads 4 LUTs (IR + RGB) per frame;
  single-BW uploads 3 (RGB only) for the capture frame.
- **`skip_autofocus` flag** -- For frames 1+, the setup frame replaces
  autofocus with 4 TUR polls since focus was already set by
  `post_prescan_autofocus()`.

### Batch WDB Tables

| Scan Type | DPI | Windows | Used For |
|-----------|-----|---------|----------|
| `"batch"` | 290 | 9, 1, 2, 3 | Stage A (IR+RGB setup) |
| `"batch_between"` | 290 | 1, 2, 3 | Stage B (RGB preview, no IR) |
| `"normal"` (per-frame offset) | 2900 | 1, 2, 3 | Stage C (full-res RGB) |

### Orchestration

`batch_scan_to_frames()` (`protocol.py:2880`) conducts the full flow:

1. `prescan()` -- auto-exposure calibration
2. Estimate `frame_count` from prescan image height
3. `set_boundary(batch=True)` -- generated CONTROL_FRAME with per-frame entries
4. For each frame `i`:
   - If `i > 0`: reconfigure Stage A, start scan, capture Stage A
   - Stage B: between setup -> start -> capture
   - Stage C: full-res setup (per-frame Y offset) -> start -> capture
   - `poll_until_ready()` after capture (no `stop_scan()` between frames)
   - If not last frame: autofocus at next center
   - Yield `(frame_index, full_res_bytes, previews_dict)`
5. `scan_teardown()` after all frames

See `docs/scan-sequence.md` for the complete batch phase table and
`tests/test_batch_state_machine.py` for the state-machine validation tests.

## Key Differences: SANE vs USB Capture

| Aspect | SANE Backend Shows | USB Capture Shows | Our Implementation |
|--------|-------------------|-------------------|-------------------|
| **Command Format** | Standard SCSI CDB | USB-specific format | USB-specific (from capture) |
| **Control Byte** | 0x00 (standard) | 0x80 (USB-specific) | 0x80 (from capture) |
| **Translation** | Hidden in `sanei_usb_*` | Raw USB format | Direct (no translation) |
| **Phase Checking** | `cs2_phase_check()` | 0xd0 after every command | 0xd0 pattern (from capture) |
| **Retry Logic** | `wait_scanner()` documented | Frequency shown | SANE pattern |
| **Initialization** | High-level sequence | Exact command bytes | Combined approach |

## Conclusion

**Both sources are essential:**

- **SANE backend**: Provides high-level logic, retry patterns, and timing
- **USB capture**: Provides exact command format and communication pattern
- **Our implementation**: Uses USB-specific format (from capture) with SANE's retry logic

The USB capture was critical because it revealed the actual format the scanner expects, bypassing SANE's translation layer that we don't have access to in PyUSB.
