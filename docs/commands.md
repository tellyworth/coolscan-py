# Coolscan Command Reference

**Format: LS-40 ED USB Wire Format (verified against pcapng captures)**

This document uses the actual USB-specific command format observed in pcapng
captures. Unlike SANE's internal SCSI abstraction layer, PyUSB sends raw USB
CDBs. Control bytes are `0x80` for most 6-byte and 10-byte commands (not
`0x00` as in standard SCSI). All examples below come from `ls40-single-bw.pcapng`
and the golden fixture (`reference/golden_single_bw.txt`).

For the full byte-level protocol spec, WDB layout, and phase checking patterns,
see `docs/unified-protocol-spec.md`.

## Command Categories

### 1. Basic SCSI Commands
### 2. Scanner Control Commands
### 3. Scanning Commands
### 4. Configuration Commands
### 5. Diagnostic Commands

## Basic SCSI Commands

### TEST UNIT READY (0x00)
**Purpose**: Check if scanner is ready for commands
```
Command: 00 00 00 00 00 00  (6 bytes)
Response: Status (8 bytes)
```
Control byte is `0x00` for this simple command. Used extensively for polling
(346 times in a single scan session per the pcapng capture).

**Status Bytes**:
- `00 00 00 00 00 00 00 00`: Ready
- `02 02 04 01 00 00 00 00`: Not ready / processing

### INQUIRY (0x12)
**Purpose**: Get device information
```
Command: 12 [page] 00 00 [length] 80  (6 bytes)
Response: Device descriptor (variable length)
```

**Examples (from golden fixture)**:
- Standard inquiry (36 bytes): `12 00 00 00 24 80`
- Page 0x01 (4 bytes): `12 01 00 00 04 80`
- Page 0xd1 (28 bytes): `12 01 d1 00 1c 80`

### MODE SENSE (0x1a)
**Purpose**: Get device configuration
```
Command: 1a 00 [page] 00 [length] 80  (6 bytes)
Response: Mode data (variable length)
```

### RESERVE_UNIT (0x16)
**Purpose**: Reserve the scanner unit for exclusive use
```
Command: 16 00 00 00 00 00  (6 bytes)
Response: Status (8 bytes)
```

### RELEASE_UNIT (0x17)
**Purpose**: Release the scanner unit
```
Command: 17 00 00 00 00 00  (6 bytes)
Response: Status (8 bytes)
```

## Scanner Control Commands

### Reset Scanner (0xe0, subcode 0x80)
**Purpose**: Reset scanner to initial state
```
Command: e0 00 80 00 00 00 00 00 0d 00  (10 bytes)
Data: 13-byte payload (sent during DATA_OUT phase)
Response: Status (8 bytes)
```

### Execute Command (0xc1)
**Purpose**: Execute pending operations
```
Command: c1 00 00 00 00 00  (6 bytes)
Response: Status (8 bytes)
```

### Load Medium (0xe0, subcode 0xd1)
**Purpose**: Load next slide/film
```
Command: e0 00 d1 00 00 00 00 00 0d 00  (10 bytes)
Data: 13-byte load parameters
Response: Status (8 bytes)
```

### Eject Medium (0xe0, subcode 0xd0)
**Purpose**: Eject loaded medium
```
Command: e0 00 d0 00 00 00 00 00 0d 00  (10 bytes)
Data: 13-byte eject parameters
Response: Status (8 bytes)
```

### Auto Focus (0xe0, subcode 0xa0)
**Purpose**: Perform auto focus at specified coordinates
```
Command: e0 00 a0 00 00 00 00 00 0d 00  (10 bytes)
Data: X coordinate (4 bytes big-endian) + Y coordinate (4 bytes big-endian) + 5 zero bytes
Response: Status (8 bytes)
```

### Get Focus Position (0xe0, subcode 0xc1)
**Purpose**: Get current focus position
```
Command: e0 00 c1 00 00 00 00 00 0d 00  (10 bytes, subclass 0x06)
Data: 1-byte focus value
Response: Status (8 bytes)
```
See also: `e1 00 c1 00 00 00 00 00 0d 00` for reading focus result (DATA_IN phase).

### START_STOP_UNIT (0x1b)
**Purpose**: Start/stop a scan pass
```
Start scan: 1b 00 00 00 03 00  (6 bytes, byte 4 = 0x03 = start)
Stop scan:  1b 00 00 00 04 00  (6 bytes, byte 4 = 0x04 = stop)
```
After START_SCAN, poll with TEST_UNIT_READY until status returns READY
(`00 00 00 00 00 00 00 00`). While scanning, the scanner returns
PROCESSING status (`02 02 04 01 00 00 00 00`).

## Scanning Commands

### SET_WINDOW (0x24) — Send Window Descriptor Block
**Purpose**: Configure a scan window (resolution, offsets, dimensions, exposure)
```
Command: 24 00 00 00 00 00 00 00 3a 80  (10 bytes)
         ^^                      ^^  ^^
         opcode                  0x3a=58 bytes  0x80=control
Data: 58-byte WDB (sent during DATA_OUT phase)
Response: Status (8 bytes)
```

**WDB Data Format** (58 bytes, verified against pcapng capture):
```
Bytes 0-6:   Header (always 00 00 00 00 00 00 00)
Byte 7:      Data length (always 0x32 = 50)
Byte 8:      Window ID (0x01=R, 0x02=G, 0x03=B, 0x09=IR)
Byte 9:      Reserved (0x00)
Bytes 10-11: X resolution (big-endian)
Bytes 12-13: Y resolution (big-endian)
Bytes 14-17: X offset (4 bytes, big-endian)
Bytes 18-21: Y offset (4 bytes, big-endian)
Bytes 22-25: Width (4 bytes, big-endian)
Bytes 26-29: Height (4 bytes, big-endian)
Bytes 30-32: Brightness, Threshold, Contrast
Byte 33:     Image composition (0x05=prescan, 0x02=normal)
Byte 34:     Pixel composition/depth (0x0c=12-bit, 0x08=8-bit)
Bytes 35-47: Reserved zeros (13 bytes)
Byte 48:     Multiread / ordering
Byte 49:     Averaging (0x80) | Positive/Negative (0x01=positive)
Byte 50:     Scan kind (0x01=normal, 0x02=prescan/AE, 0x20=AE, 0x40=AE_WB)
Byte 51:     Scan mode (0x02=single, 0x10=multi)
Byte 52:     Color interleave (0x02)
Byte 53:     AE byte (0xff)
Bytes 54-57: Exposure value (4 bytes big-endian, 10ns units)
```

**Prescan vs Normal Scan WDB Parameters**:
| Parameter | Prescan (AE) | Normal (Full) |
|-----------|-------------|---------------|
| Resolution (bytes 10-13) | `0060 0060` (96 DPI) | `0b54 0b54` (2900 DPI) |
| Scan kind (byte 50) | `02` | `01` |
| Image comp (byte 33) | `05` | `02` |
| Depth (byte 34) | `0c` (12-bit) | `08` (8-bit) |
| Windows | 1, 2, 3 only | 1, 2, 3 (+ IR via window 9) |

**Example Prescan WDB** (window 1, from golden fixture):
```
0000000000000032 01 0060 0060 00000000 00000000 00000b36 00008760
00 00 00 05 0c 00000000000000000000000000 00 81 02 02 02 ff 0000a381
```

**Example Full Scan WDB** (window 1, from golden fixture):
```
0000000000000032 01 0b54 0b54 00000000 00000000 00000b36 000010ec
00 00 00 02 08 00000000000000000000000000 00 81 01 02 02 ff 00009ce6
```

For the complete field-by-field layout, see `docs/unified-protocol-spec.md` lines 67-111.

### READ (0x28) — Read Data from Scanner
**Purpose**: Read image data, status, or calibration data
```
Command: 28 00 [datatype] [channel] [reserved] [len_hi] [len_lo] 80  (10 bytes)
         ^^      ^^          ^^        ^^
         opcode  data type   params    transfer length (big-endian)
```

**Datatype Codes** (byte 2):
- `0x00`: Image data blocks (prescan / full scan pixels)
- `0x87`: Internal status / progress blocks (6–33 byte payloads)
- `0x8c`: Per-channel state (10-byte response with calibrated exposure)
- `0x8e`: Exposure / calibration tables

**Examples**:
- Read image data (0x1fec0 = 130752 bytes): `28 00 00 00 00 00 01 fe c0 80`
- Read status/progress (6 bytes): `28 00 87 00 00 00 00 00 06 80`
- Read channel state for R (10 bytes): `28 00 8c 00 01 03 00 00 0a 80`
- Read exposure header (6 bytes): `28 00 8e 00 00 00 00 00 06 80`

For image data decoding (12-bit → 8-bit, plane interleaving, verified widths),
see `docs/protocol.md` lines 135-213.

### WRITE (0x2a) — Write Data to Scanner
**Purpose**: Upload LUTs, control frames, or configuration data
```
Command: 2a 00 [datatype] [channel] [reserved] [len_hi] [len_lo] 00  (10 bytes)
         ^^      ^^          ^^        ^^
         opcode  data type   params    transfer length (big-endian)
```

**Datatype Codes** (byte 2):
- `0x03`: LUT data (8192 bytes per channel, 4096 entries × 16-bit)
- `0x8f`: Control frame write (52-byte payload, full scan boundary)
- `0x92`: Border position write (4-byte payload, prescan boundary)
- `0xe0`: Internal data (256 bytes)

### WRITE LUT (0x2a, datatype 0x03)
**Purpose**: Upload identity Look-Up Table for color correction

```
Command: 2a 00 03 00 [channel] 01 00 [len_hi] [len_lo] 00  (10 bytes)
         Byte 2: 0x03 = LUT datatype
         Byte 4: Channel index (0x01=R, 0x02=G, 0x03=B)
         Bytes 7-8: Transfer length (0x20 0x00 = 8192 bytes)
Data: 8192-byte identity LUT (sent during DATA_OUT phase)
Response: Status (8 bytes)
```

**Identity LUT Data** (8192 bytes):
```
0000 0001 0002 0003 ... 0ffe 0fff
```
4096 entries × 2 bytes big-endian per entry. Must be uploaded for R, G, B
channels before starting a scan. The IR channel may also require a LUT upload
(batch capture shows `include_ir=True` for full scans).

### SET_WINDOW BORDER POSITION (0x2a, datatype 0x92)
**Purpose**: Set border/offset for prescan
```
Command: 2a 00 92 00 00 03 00 00 04 00  (10 bytes)
         Byte 2: 0x92 = BORDER_POSITION datatype
         Bytes 7-8: 0x04 = 4-byte payload
Data: 4-byte border position value (big-endian)
Response: Status (8 bytes)
```
Golden fixture reference: line 203.

### WRITE CONTROL FRAME (0x2a, datatype 0x8f)
**Purpose**: Set scan boundaries / control frame for full scan
```
Command: 2a 00 8f 00 00 03 00 00 34 00  (10 bytes)
         Byte 2: 0x8f = CONTROL_FRAME datatype
         Bytes 7-8: 0x34 = 52-byte payload
Data: 52-byte control frame payload (see below)
Response: Status (8 bytes)
```
Golden fixture reference: line 427.

**Control Frame Payload** (52 bytes):
```
Bytes 0-3:   Frame count (typically number of scan stripes)
Bytes 4+:    Per-frame entries: y_start (2 bytes), y_end (2 bytes)
```

**Important: The LS-40 ED rejects datatype 0x88 (IMAGE_POSITIONS).** The SANE
backend uses `2a 00 88 00 00 03` for `set_boundary` across all coolscan models
(coolscan3.c lines 2898-2936), but the LS-40 ED returns ILLEGAL REQUEST
(sense key 5, ASC 0x26). The golden fixture confirms the hardware uses 0x92
for prescan and 0x8f for full scan. Datatypes 0x92 and 0x8f are not defined
anywhere in SANE's `coolscan-scsidef.h` — SANE only defines `R_image_positions =
0x88` (line 638). The discrepancy likely stems from SANE reverse-engineering
from a different scanner model and generalizing without per-model validation.

### GET_WINDOW / READ_CAPACITY (0x25)
**Purpose**: Read window capacity / scanner state
```
Command: 25 00 00 00 00 00 00 00 3a 80  (10 bytes)
         Bytes 8-9: 0x3a = 58-byte response, control 0x80
Response: 58-byte capacity data
```
See `coolscan/protocol.py::read_capacity()` for parsed response format.

### MODE_SELECT (0x15)
**Purpose**: Set scanner mode and measurement units
```
Command: 15 10 00 00 [length] 00  (6 bytes)
Data: Mode parameters (typically 20 bytes, sent during DATA_OUT phase)
Response: Status (8 bytes)
```

**Typical Mode Parameters** (20 bytes, from golden fixture):
```
00 00 00 08 00 00 00 00 00 00 00 01 03 06 00 00 0b 54 00 00
```
Byte 16-17 encodes the Measurement Unit Divisor (`0x0b54` = 2900 DPI).

### SET COLOR SEQUENCE (0x1b variant)
**Purpose**: Set color scanning sequence
```
Command: 1b 00 00 00 [num_colors] 00 [color_list]  (6+ bytes)
Response: Status (8 bytes)
```

## Command Sequences

### Wake-up Sequence
1. Reset scanner: `e0 00 80 00 00 00 00 00 0d 00` + 13-byte data
2. Execute: `c1 00 00 00 00 00`
3. Poll ready: `00 00 00 00 00 00` (repeated)

### Standard Initialization (from golden fixture)
1. INQUIRY standard (36 bytes): `12 00 00 00 24 80`
2. TEST_UNIT_READY × 4+: `00 00 00 00 00 00`
3. INQUIRY pages: 0x01, 0xd1, 0xc1, 0xe1, 0xf0, 0xf8
4. RESERVE_UNIT: `16 00 00 00 00 00`
5. READ_CAPACITY: `25 00 00 00 00 00 00 00 3a 80`

### Prescan Sequence (from golden fixture lines ~80-340)
1. MODE_SELECT: `15 10 00 00 14 00` + 20-byte mode data
2. BORDER_POSITION: `2a 00 92 00 00 03 00 00 04 00` + 4-byte data
3. SET_WINDOW × 4 (windows 1, 2, 3 for RGB + window 9 for IR) with prescan WDBs
4. WRITE LUT × 3 (R, G, B): `2a 00 03 00 [ch] 01 00 20 00 00` + 8192 bytes each
5. START_SCAN: `1b 00 00 00 03 00` + 3-byte data (`01 02 03`)
6. Poll until READY (TEST_UNIT_READY)
7. READ image data (0x00): ~273024 bytes total (12-bit, 96 DPI)
8. READ exposure data (0x8e): 6-byte header + 3456-byte table

### Full Scan Sequence (from golden fixture lines ~340-1472)
1. MODE_SELECT: `15 10 00 00 14 00` + 20-byte mode data
2. SET_WINDOW × 3-4 (windows 1, 2, 3 + optional IR window 9) with full-res WDBs
3. CONTROL_FRAME: `2a 00 8f 00 00 03 00 00 34 00` + 52-byte payload
4. WRITE LUT × 3-4 (R, G, B + optional IR): `2a 00 03 00 [ch] 01 00 20 00 00` + 8192 bytes each
5. START_SCAN: `1b 00 00 00 03 00` + 3-byte data
6. Poll until READY
7. READ image data: multiple stripes of varying sizes
8. STOP_SCAN: `1b 00 00 00 04 00`

### Focus Sequence
1. Set focus coordinates: `e0 00 a0 00 00 00 00 00 0d 00` + 13-byte coordinate data
2. Execute: `c1 00 00 00 00 00`
3. Read focus result: `e1 00 c1 00 00 00 00 00 0d 00` (DATA_IN, 1 byte)

## Diagnostic Commands

### Phase Check (0xd0)
**Purpose**: Check current communication phase
```
Command: d0  (1 byte, sent to endpoint 0x01 OUT)
Response: Phase byte (1 byte, read from endpoint 0x82 IN)
```
Phase checking is mandatory — sent after every command.

**Phase Values**:
- `0x01`: Status phase (read status)
- `0x02`: Data out phase (send data, then re-check phase)
- `0x03`: Data in phase (read data)
- `0x04`: Busy phase (retry)

### Read Channel State (0x28, datatype 0x8c)
**Purpose**: Read calibrated exposure per channel
```
Command: 28 00 8c 00 [channel] 03 00 00 0a 80  (10 bytes)
         Byte 4: Channel (0x01=R, 0x02=G, 0x03=B, 0x09=IR)
         Bytes 7-8: 0x0a = 10-byte response
Response: 10 bytes (bytes 6-9 = exposure in 10ns units, big-endian uint32)
```

### Read Exposure Table (0x28, datatype 0x8e)
**Purpose**: Read exposure / calibration tables from prescan
```
Header read: 28 00 8e 00 00 00 00 00 06 80  (6-byte response)
Table read:  28 00 8e 00 00 00 00 0d 88 80  (3464-byte response)
```

## Error Handling

### Common Status Responses (8 bytes)
- `00 00 00 00 00 00 00 00`: READY
- `02 02 04 01 00 00 00 00`: PROCESSING (scanner is scanning; poll)
- `06 28 00 00 00 00 00 00`: NO_DOCS (no film loaded)
- `06 40 00 00 00 00 00 00` / `06 41 00 00 00 00 00 00`: BUSY
- `09 80 06 00 00 00 00 00`: REISSUE (retry command)
- `05 26 00 00 00 00 00 00`: ILLEGAL REQUEST (wrong datatype)

**Status Field Layout**:
```
Byte 0: Status byte (0x00=READY, 0x02=ERROR)
Byte 1: Sense key
Byte 2: ASC (Additional Sense Code)
Byte 3: ASCQ (Additional Sense Code Qualifier)
Bytes 4-7: Additional sense info
```

### Recovery Procedures
1. On PROCESSING: poll with TEST_UNIT_READY until READY
2. On REISSUE: re-send the original command (observe 3-attempt retry pattern)
3. On BUSY: wait and retry
4. On persistent errors: send reset (`e0 00 80`), then re-initialize

## Implementation Notes

### Command Timing
- Phase check (0xd0) after every command
- After DATA_OUT phase, re-check phase before reading status
- Use dynamic polling (`poll_until_ready()`) instead of fixed sleeps
- START_SCAN retry: 3 attempts with REISSUE → ERROR → READY pattern

### Data Formatting
- All multi-byte values are big-endian
- String data is ASCII
- Image data is plane-interleaved (all R rows, then all G rows, then all B rows)
- See `docs/protocol.md` for verified image decoding recipes

### Buffer Management
- The scanner returns data in increments of up to 65508 bytes per chunk
- `read_scan_data()` handles automatic chunking and stripe reassembly
- Large READ commands must specify the total allocation length; the scanner
  returns chunks up to its maximum transfer size

## References

- **Primary protocol spec**: `docs/unified-protocol-spec.md` (58-byte WDB layout, phase checking, CDB format)
- **Image data decoding**: `docs/protocol.md` (verified widths, heights, 12-bit → 8-bit conversion)
- **SANE backend analysis**: `docs/sane-image-data.md` (SANE internals vs verified hardware format)
- **Golden fixture**: `reference/golden_single_bw.txt` (1472 events, ground truth for single-BW scan)
- **Pcapng capture**: `ls40-single-bw.pcapng` (primary oracle)
- **Implementation**: `coolscan/protocol.py` (scenario methods with golden fixture line references)
