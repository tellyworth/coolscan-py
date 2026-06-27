# Coolscan Protocol Specification

This document describes the communication protocol used by Nikon Coolscan film scanners.

## Overview

The Coolscan protocol is based on SCSI commands transmitted over USB or SCSI/Firewire interfaces. The protocol uses a command-response model with specific phases for data transfer.

## Communication Interfaces

### USB Interface
- **Vendor ID**: 0x04b0 (Nikon)
- **Product IDs**:
  - 0x4000: LS-40 ED
  - 0x4001: LS-50 ED
  - 0x4002: LS-5000 ED

### SCSI/Firewire Interface
- Uses SBP2 (Serial Bus Protocol 2) over Firewire
- Standard SCSI commands with device-specific extensions

## Protocol Phases

The protocol operates in distinct phases:

1. **Command Phase**: Send command bytes
2. **Data Out Phase**: Send data to scanner (if needed)
3. **Data In Phase**: Receive data from scanner (if needed)
4. **Status Phase**: Receive status information

### Phase Types
```c
typedef enum {
  CS2_PHASE_NONE = 0x00,
  CS2_PHASE_STATUS = 0x01,
  CS2_PHASE_OUT = 0x02,
  CS2_PHASE_IN = 0x03,
  CS2_PHASE_BUSY = 0x04
} cs2_phase_t;
```

## Command Structure

### Command Format
All commands follow this structure:
```
[Command Code] [Parameters...] [Data Length]
```

### Common Command Codes
- `0x00`: TEST UNIT READY
- `0x12`: INQUIRY
- `0x15`: MODE SELECT
- `0x16`: RESERVE
- `0x17`: RELEASE
- `0x1a`: MODE SENSE
- `0x1b`: START STOP UNIT
- `0x1c`: RECEIVE DIAGNOSTIC RESULTS
- `0x1d`: SEND DIAGNOSTIC
- `0x24`: SET_WINDOW (10-byte command + 58-byte WDB)
- `0x25`: READ CAPACITY (10-byte format, has variants with parameters)
- `0x28`: READ(10) (10-byte format, with datatype codes for scan data)
- `0x2a`: WRITE(10) (10-byte format, multiple formats for different purposes)
- `0xc0`: Vendor-specific command
- `0xc1`: Vendor-specific command
- `0xd0`: Phase check
- `0xe0`: Vendor-specific command
- `0xe1`: Vendor-specific command

## Wake-up Sequence

The scanner must be woken up before normal operation:

### Step 1: Reset Command
```
e0 00 80 00 00 00 00 00 0d 00
```

### Step 2: Execute Command
```
c1 00 00 00 00 00
```

### Step 3: Test Communication
```
00 00 00 00 00 00  (TEST UNIT READY)
```

## Status Handling

### Status Format
Status responses are 8 bytes:
```
[Status Byte] [Sense Key] [ASC] [ASCQ] [Sense Info] [Reserved...]
```

### Sense Keys
- `0x00`: No sense (ready)
- `0x02`: Not ready
- `0x09`: Vendor-specific

### ASC/ASCQ Codes
- `0x04`: Not ready (processing)
- `0x3a`: Medium not present (no document)

## Scanner-Specific Commands

### Load/Eject Commands
```c
// Load next slide
e0 00 d1 00 00 00 00 00 0d 00 + 13 bytes data

// Eject loaded medium
e0 00 d0 00 00 00 00 00 0d 00 + 13 bytes data
```

### Focus Commands
```c
// Manual focus
e0 00 c1 00 00 00 00 00 0d 00 + focus value (4 bytes)

// Auto focus
e0 00 a0 00 00 00 00 00 0d 00 + focus coordinates (8 bytes)
```

### Scan / Window Commands
```c
// Set window (SET_WINDOW, 10-byte CDB + 58-byte WDB)
24 00 00 00 00 00 00 00 3a 80 + 58 bytes window descriptor block
```

The scan mode (normal vs AE vs AE_WB) is encoded in the WDB itself (e.g. byte 50,
"scan kind"), not in the opcode or final byte of the CDB.

## Image Data Format (LS-40 ED, Verified)

### Raw Data Layout

Full scan data from the LS-40 ED at 2900 DPI with 8-bit output:

- **Bit depth**: 8-bit per channel (1 byte per pixel value)
- **Pixel width**: 2880 pixels per row (verified by autocorrelation, peak at lag=8640)
- **Row stride**: 8640 bytes (3 channels x 2880 pixels, **no padding**)
- **Channel layout**: Plane-interleaved per row: `[R[2880]][G[2880]][B[2880]]`
- **Total data**: 32,768,000 bytes (500 x 65,536-byte USB bulk reads)
- **Complete rows**: 3792 (32,768,000 // 8640), with 5120 trailing bytes

### Decoding Reference

```python
width = 2880
bytes_per_line = 8640  # 3 * width, no padding
height = len(raw_data) // bytes_per_line  # 3792

for y in range(height):
    offset = y * bytes_per_line
    R_row = raw[offset:offset + width]
    G_row = raw[offset + width:offset + 2*width]
    B_row = raw[offset + 2*width:offset + 3*width]
```

### Low-Resolution Scan Data (Prescan and IR Preview)

The LS-40 ED also returns 12-bit plane-interleaved image data for the 96 DPI
prescan and the 290 DPI IR preview. The wire format is the same as the full-res
scan (plane-interleaved, no padding), but samples are packed as 12-bit values in
big-endian `uint16` containers.

#### 96 DPI Prescan

Read by `read_prescan_image_data()`:

- **Bit depth**: 12-bit per channel (2 bytes per sample, big-endian)
- **Pixel width**: 96
- **Channels**: 3 (R, G, B)
- **Height derived from data size**: `273024 / (96 * 3 * 2) = 474`
- **Channel layout**: Plane-interleaved per row: `[R[96]][G[96]][B[96]]`
- **12-bit to 8-bit conversion**: `np.frombuffer(data, dtype=">u2") >> 4`
- **Channel offsets** (scaled from full-res LS40_CHANNEL_OFFSETS by 96/2900):
  `(0, 0, 1)`

#### 290 DPI IR Preview

Read by `read_ir_preview_data()`:

- **Bit depth**: 12-bit per channel (2 bytes per sample, big-endian)
- **Pixel width**: 288
- **Channels**: 4 (R, G, B, IR — output order follows window IDs 1, 2, 3, 9)
- **Height derived from data size**: `997632 / (288 * 4 * 2) = 433`
- **Channel layout**: Plane-interleaved per row: `[R[288]][G[288]][B[288]][IR[288]]`
- **12-bit to 8-bit conversion**: `np.frombuffer(data, dtype=">u2") >> 4`
- **Channel offsets** (scaled from full-res LS40_CHANNEL_OFFSETS by 290/2900):
  `(0, 1, 2, 0)` (IR channel gets zero offset)

> **Note**: The 12-bit samples occupy the **low 12 bits** of the big-endian
> `uint16` word, not the high 12 bits. Shifting by `>> 4` keeps the top 8 bits
> of the 12-bit value; `>> 8` keeps only the top 4 bits and produces very dark
> images.

### Common Bugs

- **Wrong width** (e.g. 2624 instead of 2880): produces diagonal smear from channel
  plane misalignment. Each row shifts by the width difference.
- **Wrong bit depth** (e.g. 12-bit instead of 8-bit): produces vertical striping
  from incorrect bit unpacking. Channel statistics become inconsistent.
- **Wrong 12-bit bit selection** (`>> 8` instead of `>> 4`): produces very dark
  low-resolution images because only the top 4 bits are retained.
- **Wrong 4-channel order** (e.g. IR/R/G/B instead of R/G/B/IR): produces false
  color in the RGB preview and places a visible frame in the IR layer.
- **Assumed padding** (e.g. 128 bytes per row): the LS-40 ED at 8-bit has no per-row
  padding. The 0xFF values in the data are actual sensor values (unexposed film areas),
  not padding bytes.

### Read Operations
```c
// Read data (READ(10), USB-specific CDB with datatype in byte 2)
// Example: image data
28 00 00 00 00 00 len_hi len_mid len_lo 80
```

### Write Operations
```c
// Write data (WRITE(10), USB-specific CDB with datatype in byte 2)
// Example: LUT write
2a 00 03 00 [channel] 01 00 len_hi len_lo 00 + data
```

## Error Handling

### Common Error Scenarios
1. **Scanner not ready**: Wait and retry
2. **No document**: Check for loaded film/slide
3. **Communication timeout**: Reset connection
4. **Invalid command**: Check command format

### Recovery Procedures
1. Send reset command
2. Wait for ready status
3. Retry original command
4. If persistent, reinitialize connection

## Implementation Notes

### USB Implementation
- Use bulk transfers for data
- Handle phase checking between commands
- Implement proper timeout handling
- Buffer management for large transfers

### SCSI Implementation
- Use standard SCSI commands
- Handle sense data properly
- Implement retry logic
- Support for different SCSI transports

## Scanner Models

### LS-40 ED
- USB interface
- 4000 DPI optical resolution
- 48-bit color depth
- Infrared dust detection

### LS-50 ED
- USB interface
- 5000 DPI optical resolution
- 48-bit color depth
- Advanced features

### LS-5000 ED
- USB interface
- 5000 DPI optical resolution
- 48-bit color depth
- Multi-sampling support

### LS-4000 ED (Firewire)
- SCSI/Firewire interface
- 4000 DPI optical resolution
- 48-bit color depth
- High-speed scanning

### LS-8000 ED (Firewire)
- SCSI/Firewire interface
- 8000 DPI optical resolution
- 48-bit color depth
- Professional features

## References

- SANE backend code: `coolscan2.c`, `coolscan3.c`
- SCSI-3 specification
- USB mass storage specification
- Nikon technical documentation
