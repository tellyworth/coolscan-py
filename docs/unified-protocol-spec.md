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

#### READ_CAPACITY (10 bytes)
- **USB format**: `25 00 00 00 00 00 00 00 3a 80`
  - 10-byte command (not 6-byte)
  - Byte 8: Allocation length high (0x3a = 58 bytes)
  - Byte 9: Allocation length low | control (0x80)

#### START_STOP_UNIT (start scan)
- **USB format**: `1b 00 00 00 03 00`
  - Byte 4: Action (0x03 = start, 0x04 = stop)
  - Control byte is 0x00

## Communication Protocol Pattern

### Standard Command Sequence (from USB capture)

1. **Send command** (6 or 10 bytes) to endpoint 0x01 (OUT)
2. **Send phase check** (0xd0) to endpoint 0x01 (OUT)
3. **Read phase response** (1 byte) from endpoint 0x82 (IN)
   - `0x01` = Status phase
   - `0x03` = Data in phase
   - `0x04` = Busy phase
4. **Read data/status** from endpoint 0x82 (IN)
   - If phase was `0x03`: Read data bytes (allocation length)
   - Then read 8-byte status
5. **Read final status** (8 bytes) from endpoint 0x82 (IN)
   - Status byte, sense key, ASC, ASCQ, etc.

### Phase Checking (from both sources)

- **SANE**: Uses `cs2_phase_check()` / `cs3_phase_check()` before reading status
- **USB capture**: Shows 572 phase checks in a single scan session
- **Frequency**: Phase check (0xd0) is sent **after every command**
- **Critical**: This is mandatory for proper communication

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
- **Prescan timing**: 8 second sleep after starting prescan
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
Byte 0: Status byte (0x00 = READY, 0x02 = ERROR)
Byte 1: Sense key (0x00 = no sense, 0x06 = unit attention)
Byte 2: ASC (Additional Sense Code)
Byte 3: ASCQ (Additional Sense Code Qualifier)
Bytes 4-7: Additional sense information
```

### Status Types

- **READY (0x00)**: Scanner is ready
- **NO_DOCS**: No film loaded (sense key 0x06, ASC 0x28)
- **BUSY**: Scanner is busy (sense key 0x06, ASC 0x40 or 0x41)
- **ERROR**: Error condition (sense key 0x02)

## Scan Operations

### Prescan Sequence (from SANE)

1. Set window with WDB (scan_mode = 0x01 for prescan)
2. Start scan (`1b 00 00 00 03 00`)
3. Wait 8 seconds
4. Wait for scanner ready

### Scan Sequence (from USB capture)

1. **WRITE commands** (`2a 00 92 00 00 03 00 00 04 00`) - Send window/parameters
2. **START_STOP_UNIT** (`1b 00 00 00 03 00`) - Start scan
3. **READ commands** (`24 00 00 00 00 00 00 00 [len] 80`) - Read scan data
4. **TEST_UNIT_READY** - Poll for completion
5. **START_STOP_UNIT** (`1b 00 00 00 04 00`) - Stop scan

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
