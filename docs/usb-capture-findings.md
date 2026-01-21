# USB Capture Analysis - Key Findings

## Overview
Analysis of USB traffic capture from Nikon Scan software communicating with LS-40 scanner.

## Critical Discovery: Command Format

### Our Current Format (WRONG)
We've been using standard SCSI command format, but the scanner expects a **different 6-byte format**:

### Actual Working Format (FROM CAPTURE)
Commands are **6 bytes** with this structure:
```
Byte 0: Command code (0x12 = INQUIRY, 0x00 = TEST_UNIT_READY, etc.)
Byte 1: Page/Subcommand code (for INQUIRY variants)
Byte 2: Reserved/Parameter
Byte 3: Reserved/Parameter
Byte 4: Allocation length (how many bytes to read)
Byte 5: Control byte (0x80 for most commands, 0x00 for simple ones)
```

### Examples from Capture

**INQUIRY (standard):**
```
12 00 00 00 24 80
│  │  │  │  │  └─ Control byte (0x80)
│  │  │  │  └──── Allocation length (0x24 = 36 bytes)
│  │  │  └─────── Reserved (0x00)
│  │  └────────── Reserved (0x00)
│  └───────────── Page code (0x00 = standard inquiry)
└──────────────── Command code (0x12 = INQUIRY)
```

**INQUIRY (page 0x01, length 4):**
```
12 01 00 00 04 80
│  │  │  │  │  └─ Control byte (0x80)
│  │  │  │  └──── Allocation length (0x04 = 4 bytes)
│  │  │  └─────── Reserved (0x00)
│  │  └────────── Reserved (0x00)
│  └───────────── Page code (0x01)
└──────────────── Command code (0x12 = INQUIRY)
```

**TEST_UNIT_READY:**
```
00 00 00 00 00 00
│  │  │  │  │  └─ Control byte (0x00)
│  │  │  │  └──── Allocation length (0x00)
│  │  │  └─────── Reserved (0x00)
│  │  └────────── Reserved (0x00)
│  └───────────── Reserved (0x00)
└──────────────── Command code (0x00 = TEST_UNIT_READY)
```

**RESERVE_UNIT:**
```
16 00 00 00 00 00
│  │  │  │  │  └─ Control byte (0x00)
│  │  │  │  └──── Allocation length (0x00)
│  │  │  └─────── Reserved (0x00)
│  │  └────────── Reserved (0x00)
│  └───────────── Reserved (0x00)
└──────────────── Command code (0x16 = RESERVE_UNIT)
```

## Communication Protocol Pattern

### Standard Command Sequence
1. **Send command** (6 bytes) to endpoint 0x01 (OUT)
2. **Send phase check** (0xd0) to endpoint 0x01 (OUT)
3. **Read phase response** (1 byte) from endpoint 0x82 (IN)
   - 0x01 = Status phase
   - 0x03 = Data in phase
4. **Read data/status** from endpoint 0x82 (IN)
   - If phase was 0x03: Read data bytes
   - Then read 8-byte status
5. **Read final status** (8 bytes) from endpoint 0x82 (IN)
   - Status byte, sense key, ASC, ASCQ, etc.

### Phase Check Frequency
- **572 phase checks** in a single scan session!
- Phase check (0xd0) is sent **after every command**
- This is critical for proper communication

## Initialization Sequence (From Capture)

1. **INQUIRY (standard)** - `120000002480`
   - Get 36-byte device identification
   - Response contains "Nikon   LS-40 ED" string

2. **TEST_UNIT_READY** (multiple times) - `000000000000`
   - Wait for scanner to be ready
   - Sent 4 times in a row initially

3. **INQUIRY (page 0x01, length 4)** - `120100000480`
   - Get 4 bytes of page 0x01 data

4. **INQUIRY (page 0x01, length 21)** - `120100001580`
   - Get 21 bytes of page 0x01 data
   - Response: `06000011000140414650516061c1d1e1f0f8e2fbfc`

5. **INQUIRY (page 0xd1, length 4)** - `1201d1000480`
   - Get 4 bytes of page 0xd1 data

6. **INQUIRY (page 0xd1, length 28)** - `1201d1001c80`
   - Get 28 bytes of page 0xd1 data
   - Response contains measurement unit divisor (MUD) info

7. **INQUIRY (page 0xc1, length 4)** - `1201c1000480`
   - Get 4 bytes of page 0xc1 data

8. **INQUIRY (page 0xc1, length 85)** - `1201c1005580`
   - Get 85 bytes of page 0xc1 data
   - Response contains scanner configuration

9. **INQUIRY (page 0xe1, length 4)** - `1201e1000480`
   - Get 4 bytes of page 0xe1 data

10. **INQUIRY (page 0xe1, length 39)** - `1201e1002780`
    - Get 39 bytes of page 0xe1 data

11. **INQUIRY (page 0xf0, length 4)** - `1201f0000480`
    - Get 4 bytes of page 0xf0 data

12. **INQUIRY (page 0xf0, length 53)** - `1201f0003580`
    - Get 53 bytes of page 0xf0 data

13. **INQUIRY (page 0xf8, length 4)** - `1201f8000480`
    - Get 4 bytes of page 0xf8 data

14. **INQUIRY (page 0xf8, length 15)** - `1201f8000f80`
    - Get 15 bytes of page 0xf8 data

15. **RESERVE_UNIT** - `160000000000`
    - Reserve the scanner unit

16. **READ_CAPACITY** - `25000000000000003a80` (10 bytes)
    - Get capacity information

## Command Statistics

From the capture (single scan session):
- **TEST_UNIT_READY (0x00)**: 346 times
- **Phase check (0xd0)**: 572 times
- **READ(10) (0x28)**: 172 times (with datatype codes)
- **INQUIRY (0x12)**: 19 times
- **READ_CAPACITY (0x25)**: 16 times
- **SET_WINDOW (0x24)**: 18 times (10-byte command + 58-byte WDB)
- **WRITE (0x2a)**: 12 times
- **START_STOP_UNIT (0x1b)**: 7 times

## Key Insights

1. **Command format is NOT standard SCSI** - It's a 6-byte format specific to the scanner's USB protocol (vendor-specific, not PyUSB's format)
2. **SANE's USB layer translates commands** - SANE backend shows standard SCSI, but `sanei_usb_*` functions translate to USB-specific format
3. **PyUSB has no translation layer** - We must send commands in the exact format the scanner expects
4. **Future: Translation layer planned** - See `docs/refactoring-translation-layer.md` for plan to add SCSI→USB translation for future SCSI/Firewire support
4. **Phase checking is mandatory** - Must check phase after every command
5. **TEST_UNIT_READY is sent frequently** - Used to poll scanner status
6. **INQUIRY with page codes** - Used to read different configuration pages
7. **Allocation length in byte 4** - Specifies how many bytes to read
8. **Control byte in byte 5** - 0x80 for most commands, 0x00 for simple ones (KEY DIFFERENCE from standard SCSI)

## Window Setting Sequence and Data Types

### MODE_SELECT + WRITE Pattern

From USB capture analysis, setting the window uses a two-step process:

1. **MODE_SELECT (0x15)**
   - Command: `151000001400` (6 bytes)
   - Phase check returns 0x02 (Data OUT)
   - Send 20 bytes: `000000080000000000000001030600000b540000`
   - Check phase again, then read status

2. **WRITE (0x2a)** - Originally misinterpreted as sending WDB chunks; capture and SANE
   code analysis show it is actually used for LUT and other data types. WDBs are sent
   by SET_WINDOW (0x24), not via WRITE.

**Key Discovery**: SET_WINDOW (0x24) sends the 58-byte Window Descriptor Block (WDB).
WRITE (0x2a) with datatype 0x03 is used for LUT data (8192 bytes per channel).

### READ/WRITE Datatypes Observed (0x28 / 0x2a)

From `usb_capture_timing.txt` we see several distinct datatype usages:

- `0x00` (READ): Image data blocks (`28000000000001fec080`, `280000000000002d0080`)
- `0x87` (READ): Internal status / progress (`28008700000000000680`, `...21 80`, `...18 80`)
- `0x8e` (READ): Exposure / calibration tables (`28008e00000000000680`, `28008e000000000d8880`)
- `0x8f` (WRITE): Small control blocks (`2a008f00000300003400`)
- `0x03` (WRITE): LUT data (`2a000300010100200000`, etc.)

These align with the unified spec section on READ/WRITE datatypes and help explain
the blocks that appear after START_SCAN in the prescan capture.

## Prescan Post-START_SCAN Timeline (Summarised)

After the prescan `START_SCAN` (`1b0000000300` + `010203`), the capture shows:

1. **Immediate status / progress reads** using datatype `0x87` (small 6–33 byte blocks)
2. **Polling loop** using TEST_UNIT_READY (`000000000000`) until the scanner
   transitions from PROCESSING (`0202040100000000`) to READY (`0000000000000000`)
   - **Implementation**: `poll_until_ready()` method polls every ~100ms
   - **Timing**: ~13 seconds from START_SCAN to READY (dynamic, not fixed)
3. **Image data transfer** via READ(10) with datatype `0x00`:
   - Two large blocks of 130752 bytes (`28000000000001fec080`)
   - One tail block of 11520 bytes (`280000000000002d0080`)
   - **Implementation**: `read_prescan_image_data()` method reads all three blocks
   - **Total**: 273024 bytes of prescan image data
4. **Exposure / calibration phase**:
   - INQUIRY page `0xc1` (short then long) to read back configuration/WDB (optional)
   - READ(10) with datatype `0x8e` (6-byte header + 3464-byte table)
   - **Implementation**: `read_exposure_data()` method reads header and table
   - **Note**: Table size is 3464 bytes (0x0d88), not 3456 bytes
5. **Control writeback** (optional):
   - WRITE(10) with datatype `0x8f` and 52-byte payload (`2a008f00000300003400`)

On the SANE side this corresponds roughly to `cs3_scan()` followed by
`cs3_get_exposure()`: SANE uses `GET_WINDOW` (0x25) to read 58-byte WDBs and
extract exposure from bytes 54–57, while the LS-40 USB capture shows Nikon Scan
using INQUIRY `0xc1` + datatype `0x8e` instead. Both routes ultimately obtain the
same exposure information that prescan is designed to measure.

**Implementation Methods:**
- `poll_until_ready(timeout=30, poll_interval=0.1)` - Dynamic polling until ready
- `read_prescan_image_data()` - Reads all image data blocks (273024 bytes total)
- `read_exposure_data()` - Reads exposure header (6 bytes) and table (3464 bytes)

## Implementation Status

✅ **ALL FIXED** - Communication barrier resolved!

1. ✅ **Command format updated** - Using 6-byte format with `_build_6byte_command()`
2. ✅ **Phase checking implemented** - Send 0xd0 after every command, read phase, then status
3. ✅ **Allocation length encoding** - Correctly placed in byte 4
4. ✅ **Control byte** - Using 0x80 for most commands, 0x00 for simple ones
5. ✅ **INQUIRY implementation** - Supports page codes in byte 1
6. ✅ **Endpoint discovery** - Using `get_configuration_descriptor()` to get real endpoints
7. ✅ **Configuration handling** - Properly setting configuration and claiming interface
8. ✅ **Window setting** - MODE_SELECT + WRITE sequence with 32-byte chunks
9. ✅ **Phase handling** - Check phase again after sending data in phase 0x02

## Solution Summary

The communication barrier was solved by:
1. **Analyzing USB traffic capture** from working Nikon Scan software
2. **Discovering the 6-byte command format** (not standard SCSI)
3. **Implementing the phase checking pattern** (send 0xd0 after every command)
4. **Using proper endpoint discovery** (from configuration descriptor)
5. **Fixing configuration/interface setup** (proper error handling for macOS quirks)

**Result**: Scanner now responds correctly with status codes (READY, NO_DOCS, etc.)
