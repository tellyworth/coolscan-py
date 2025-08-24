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
- `0x24`: READ
- `0x25`: READ CAPACITY
- `0x28`: READ (10)
- `0x2a`: WRITE (10)
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

### Scan Commands
```c
// Normal scan
24 00 00 00 00 00 00 00 3a 00 + scan parameters

// Auto-exposure scan
24 00 00 00 00 00 00 00 3a 20 + scan parameters

// Auto-exposure with white balance
24 00 00 00 00 00 00 00 3a 40 + scan parameters
```

## Data Transfer

### Read Operations
```c
// Read data
28 00 00 00 [length] 00 00 00 00 00
```

### Write Operations
```c
// Write data
2a 00 00 00 [length] 00 00 00 00 00 + data
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
