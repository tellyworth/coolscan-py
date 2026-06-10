# Coolscan Command Reference

This document provides a detailed reference for all commands supported by Nikon Coolscan scanners.

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
Command: 00 00 00 00 00 00
Response: Status (8 bytes)
```

**Status Codes**:
- `0x00`: Ready
- `0x02`: Not ready
- `0x09`: Vendor-specific

### INQUIRY (0x12)
**Purpose**: Get device information
```
Command: 12 00 00 00 [length] 00
Response: Device descriptor (variable length)
```

**Response Format**:
```
Bytes 0-7:   Standard INQUIRY data
Bytes 8-15:  Vendor identification
Bytes 16-31: Product identification  
Bytes 32-35: Product revision level
Bytes 36+:   Additional data
```

### MODE SENSE (0x1a)
**Purpose**: Get device configuration
```
Command: 1a 00 [page] 00 [length] 00
Response: Mode data (variable length)
```

### START STOP UNIT (0x1b)
**Purpose**: Control device power state
```
Command: 1b 00 00 00 00 00
Response: Status (8 bytes)
```

## Scanner Control Commands

### Reset Scanner (0xe0, subcode 0x80)
**Purpose**: Reset scanner to initial state
```
Command: e0 00 80 00 00 00 00 00 0d 00
Response: Status (8 bytes)
```

### Execute Command (0xc1)
**Purpose**: Execute pending operations
```
Command: c1 00 00 00 00 00
Response: Status (8 bytes)
```

### Load Medium (0xe0, subcode 0xd1)
**Purpose**: Load next slide/film
```
Command: e0 00 d1 00 00 00 00 00 0d 00
Data: 13 bytes of load parameters
Response: Status (8 bytes)
```

### Eject Medium (0xe0, subcode 0xd0)
**Purpose**: Eject loaded medium
```
Command: e0 00 d0 00 00 00 00 00 0d 00
Data: 13 bytes of eject parameters
Response: Status (8 bytes)
```

### Manual Focus (0xe0, subcode 0xc1)
**Purpose**: Set manual focus position
```
Command: e0 00 c1 00 00 00 00 00 0d 00
Data: Focus value (4 bytes, big-endian)
Response: Status (8 bytes)
```

### Auto Focus (0xe0, subcode 0xa0)
**Purpose**: Perform auto focus at specified coordinates
```
Command: e0 00 a0 00 00 00 00 00 0d 00
Data: X coordinate (4 bytes) + Y coordinate (4 bytes)
Response: Status (8 bytes)
```

### Get Focus Position (0xe1, subcode 0xc1)
**Purpose**: Get current focus position
```
Command: e1 00 c1 00 00 00 00 00 0d 00
Response: Focus value (4 bytes) + Status (8 bytes)
```

## Scanning Commands

### Normal Scan (0x24)
**Purpose**: Perform normal scan operation
```
Command: 24 00 00 00 00 00 00 00 3a 00
Data: Scan parameters (variable length)
Response: Status (8 bytes)
```

**Scan Parameters Structure**:
```
Bytes 0-1:   Color channel (1=Red, 2=Green, 3=Blue, 9=Infrared)
Bytes 2-3:   Reserved
Bytes 4-5:   X resolution
Bytes 6-7:   Y resolution
Bytes 8-11:  X offset
Bytes 12-15: Y offset
Bytes 16-19: Width
Bytes 20-23: Height
Bytes 24-27: Brightness/contrast settings
Bytes 28:    Image composition
Bytes 29:    Pixel composition (bit depth)
Bytes 30-42: Reserved
Bytes 43:    Multi-read and ordering
Bytes 44:    Averaging and positive/negative
Bytes 45:    Scan type (01=normal, 20=AE, 40=AE+WB)
Bytes 46:    Scan mode (02=single, 10=multi)
Bytes 47:    Color interleaving
Bytes 48:    Auto-exposure flag
Bytes 49-52: Exposure time (4 bytes, big-endian)
```

### Auto-Exposure Scan (0x24 with scan type 0x20)
**Purpose**: Perform auto-exposure scan
```
Command: 24 00 00 00 00 00 00 00 3a 20
Data: Scan parameters (same as normal scan)
Response: Status (8 bytes)
```

### Auto-Exposure with White Balance (0x24 with scan type 0x40)
**Purpose**: Perform auto-exposure scan with white balance
```
Command: 24 00 00 00 00 00 00 00 3a 40
Data: Scan parameters (same as normal scan)
Response: Status (8 bytes)
```

### Read Scan Data (0x28)
**Purpose**: Read scanned image data
```
Command: 28 00 00 00 [length] 00 00 00 00 00
Response: Image data (variable length) + Status (8 bytes)
```

### Write Configuration (0x2a)
**Purpose**: Write configuration data
```
Command: 2a 00 00 00 [length] 00 00 00 00 00
Data: Configuration data (variable length)
Response: Status (8 bytes)
```

## Configuration Commands

### Set Device Unit (0x15)
**Purpose**: Set device units and parameters
```
Command: 15 10 00 00 [length] 00 00 00 00 08 00 00 00 00 00 00 00 01 03 06 00 00
Data: Device unit parameters
Response: Status (8 bytes)
```

### Set Boundary (0x2a, subcode 0x88)
**Purpose**: Set scan boundaries
```
Command: 2a 00 88 00 00 03 [length] 00
Data: Boundary data (variable length)
Response: Status (8 bytes)
```
**Note:** The SANE coolscan3 backend uses datatype 0x88 (IMAGE_POSITIONS) for set_boundary,
but the LS-40 ED rejects 0x88 with ILLEGAL REQUEST (sense key 5, ASC=0x26). The golden
fixture shows the LS-40 ED uses two different commands instead:
- **Prescan:** `2a009200000300000400` (0x92 BORDER_POSITION, 4-byte payload) — golden fixture line 203
- **Full scan:** `2a008f00000300003400` (0x8f CONTROL_FRAME, 52-byte payload) — golden fixture line 427

### SANE Silent Failure Analysis (0x88)

Cross-referencing SANE source (`backends-1.4.0/backend/coolscan3.c` lines 2898-2936,
`coolscan2.c` lines 2752-2803) confirms SANE uses `2a 00 88 00 00 03` for `set_boundary`
across **all** coolscan models with no per-model differentiation. SANE's error handling
(`cs3_parse_sense_data()` at line 2045) maps sense key 0x05 (ILLEGAL REQUEST) to
`SANE_STATUS_IO_ERROR`, which would abort the scan at line 3106. This indicates SANE
either **never successfully tested** `set_boundary` on the LS-40 ED, or experienced
silent failures that went unreported. Datatypes 0x92 and 0x8f are not defined anywhere
in SANE's `coolscan-scsidef.h` — SANE only defines `R_image_positions = 0x88` (line 638).
The discrepancy likely stems from SANE reverse-engineering the protocol from a different
scanner model (possibly LS-20 via coolscan2, or LS-50/LS-5000) and generalizing across
all coolscan3 variants without per-model validation.

### Download LUT (0x2a, subcode 0x03)
**Purpose**: Download lookup table for color correction
```
Command: 2a 00 03 00 [channel] [bytes_per_point-1] [length_high] [length_mid] [length_low] 00
Data: LUT data (variable length)
Response: Status (8 bytes)
```

### Set Color Sequence (0x1b)
**Purpose**: Set color scanning sequence
```
Command: 1b 00 00 00 [num_colors] 00 [color_list...]
Response: Status (8 bytes)
```

## Diagnostic Commands

### Phase Check (0xd0)
**Purpose**: Check current communication phase
```
Command: d0
Response: Phase byte (1 byte)
```

**Phase Values**:
- `0x00`: No phase
- `0x01`: Status phase
- `0x02`: Data out phase
- `0x03`: Data in phase
- `0x04`: Busy phase

### Get Exposure Values (0x25)
**Purpose**: Get auto-exposure values
```
Command: 25 01 00 00 00 [channel] 00 00 3a 00
Response: Exposure data (58 bytes) + Status (8 bytes)
```

### Get Block Padding (0x28, subcode 0x87)
**Purpose**: Get block padding information (LS-50/LS-5000)
```
Command: 28 00 87 00 00 00 00 00 06 00
Response: Block padding info (6 bytes) + Status (8 bytes)
```

## Command Sequences

### Wake-up Sequence
1. Reset: `e0 00 80 00 00 00 00 00 0d 00`
2. Execute: `c1 00 00 00 00 00`
3. Test: `00 00 00 00 00 00`

### Scan Sequence
1. Set device unit: `15 10 00 00 [length] 00...`
2. Set boundary: `2a 00 88 00 00 03 [length] 00`
3. Download LUTs: `2a 00 03 00 [channel] [bytes] [length] 00`
4. Set color sequence: `1b 00 00 00 [num_colors] 00 [colors]`
5. Perform scan: `24 00 00 00 00 00 00 00 3a 00`
6. Read data: `28 00 00 00 [length] 00 00 00 00 00`

### Focus Sequence
1. Set focus coordinates: `e0 00 a0 00 00 00 00 00 0d 00 [coords]`
2. Execute: `c1 00 00 00 00 00`
3. Get focus result: `e1 00 c1 00 00 00 00 00 0d 00`

## Error Handling

### Common Error Responses
- **Sense Key 0x02, ASC 0x04**: Device busy, retry
- **Sense Key 0x02, ASC 0x3a**: No medium present
- **Sense Key 0x09**: Vendor-specific error

### Recovery Procedures
1. Send reset command
2. Wait for ready status
3. Retry original command
4. If persistent, reinitialize connection

## Implementation Notes

### Command Timing
- Allow 500ms between commands
- Use longer delays (1-2s) after reset/execute
- Implement timeout handling (30s default)

### Data Formatting
- All multi-byte values are big-endian
- String data is ASCII
- Binary data is raw bytes

### Buffer Management
- Use appropriate buffer sizes for data transfer
- Handle large transfers in chunks
- Implement proper error recovery

## References

- SANE backend implementation (`coolscan2.c`, `coolscan3.c`)
- SCSI-3 specification
- USB mass storage specification
- Nikon technical documentation
