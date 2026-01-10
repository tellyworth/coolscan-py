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
- **READ (0x28)**: 172 times
- **INQUIRY (0x12)**: 19 times
- **READ_CAPACITY (0x25)**: 16 times
- **SCAN (0x24)**: 18 times
- **WRITE (0x2a)**: 12 times
- **START_STOP_UNIT (0x1b)**: 7 times

## Key Insights

1. **Command format is NOT standard SCSI** - It's a 6-byte format specific to this USB implementation
2. **Phase checking is mandatory** - Must check phase after every command
3. **TEST_UNIT_READY is sent frequently** - Used to poll scanner status
4. **INQUIRY with page codes** - Used to read different configuration pages
5. **Allocation length in byte 4** - Specifies how many bytes to read
6. **Control byte in byte 5** - 0x80 for most commands, 0x00 for simple ones

## Implementation Status

✅ **ALL FIXED** - Communication barrier resolved!

1. ✅ **Command format updated** - Using 6-byte format with `_build_6byte_command()`
2. ✅ **Phase checking implemented** - Send 0xd0 after every command, read phase, then status
3. ✅ **Allocation length encoding** - Correctly placed in byte 4
4. ✅ **Control byte** - Using 0x80 for most commands, 0x00 for simple ones
5. ✅ **INQUIRY implementation** - Supports page codes in byte 1
6. ✅ **Endpoint discovery** - Using `get_configuration_descriptor()` to get real endpoints
7. ✅ **Configuration handling** - Properly setting configuration and claiming interface

## Solution Summary

The communication barrier was solved by:
1. **Analyzing USB traffic capture** from working Nikon Scan software
2. **Discovering the 6-byte command format** (not standard SCSI)
3. **Implementing the phase checking pattern** (send 0xd0 after every command)
4. **Using proper endpoint discovery** (from configuration descriptor)
5. **Fixing configuration/interface setup** (proper error handling for macOS quirks)

**Result**: Scanner now responds correctly with status codes (READY, NO_DOCS, etc.)
