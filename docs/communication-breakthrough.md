# Communication Breakthrough - Solution Summary

## Problem
The scanner was not responding to commands - all operations timed out with "Other error" or "I/O error". No bidirectional communication was possible.

## Root Cause
After analyzing USB traffic captures from working Nikon Scan software, we discovered:

1. **Non-standard command format**: The scanner uses a 6-byte command format, NOT standard SCSI
2. **Mandatory phase checking**: Must send phase check (0xd0) after every command
3. **Endpoint discovery issues**: Couldn't get endpoint addresses without proper configuration
4. **macOS-specific quirks**: libusb0 backend has various error quirks on macOS

## Solution

### 1. Command Format (6-byte)
```
Byte 0: Command code (0x12 = INQUIRY, 0x00 = TEST_UNIT_READY, etc.)
Byte 1: Page/Subcommand code (for INQUIRY variants)
Byte 2: Reserved/Parameter
Byte 3: Reserved/Parameter
Byte 4: Allocation length (how many bytes to read)
Byte 5: Control byte (0x80 for most commands, 0x00 for simple ones)
```

**Example**: TEST_UNIT_READY = `00 00 00 00 00 00`

### 2. Phase Checking Pattern
After every command:
1. Send command (6 bytes) to endpoint 0x01 (OUT)
2. Send phase check (0xd0) to endpoint 0x01 (OUT)
3. Read phase response (1 byte) from endpoint 0x82 (IN)
   - 0x01 = Status phase
   - 0x03 = Data in phase
4. If phase is 0x03 and data expected: Read data bytes
5. Read status (8 bytes) from endpoint 0x82 (IN)

### 3. Endpoint Discovery
Use `usb.util.find_descriptor()` to get configuration descriptor, then extract endpoints:
- OUT endpoint: 0x01 (endpoint 1, OUT direction)
- IN endpoint: 0x82 (endpoint 2, IN direction = 0x02 | 0x80)

### 4. Configuration Handling
- Use `get_configuration_descriptor()` to get endpoint info without requiring active config
- Properly handle macOS libusb quirks ("Result too large", "Other error")
- Don't call `device.reset()` - it causes disconnection

## Implementation

### Key Code Changes

**Command Building**:
```python
def _build_6byte_command(self, cmd_code: int, page: int = 0,
                        param2: int = 0, param3: int = 0,
                        alloc_length: int = 0, control: int = 0x80) -> bytes:
    """Build a 6-byte command in the format used by the scanner."""
    return struct.pack('BBBBBB', cmd_code, page, param2, param3, alloc_length, control)
```

**Command Sequence**:
```python
def _issue_usb_command(self, command: bytes, data_out: bytes = b'',
                      data_in_length: int = 0) -> Tuple[bytes, StatusType]:
    # 1. Send command
    self._usb_write_bulk(command)

    # 2. Send phase check
    phase_check = self._pack_byte(0xd0)
    self._usb_write_bulk(phase_check)

    # 3. Read phase response
    phase_response = self._usb_read_bulk(1)
    phase_byte = phase_response[0]

    # 4. Read data if phase indicates data in
    if phase_byte == 0x03 and data_in_length > 0:
        data_in = self._usb_read_bulk(data_in_length)

    # 5. Read status
    status_data = self._usb_read_bulk(8)
    status, parsed_status = self._parse_status(status_data)

    return data_in, status
```

## Results

✅ **Scanner responds correctly**:
- TEST_UNIT_READY returns status codes (READY, NO_DOCS, ERROR)
- Phase checking works (receives 0x01 for status phase)
- Status parsing works (8-byte status responses decoded correctly)
- Works without sudo (no root permissions required)

**Status Codes Received**:
- `0000000000000000` = READY (all zeros)
- `02023a0001000000` = NO_DOCS (sense key 2, ASC 0x3a)
- `0206280001000000` = ERROR (sense key 6, ASC 0x28)

## Files Modified

- `coolscan/protocol.py`:
  - Added `_build_6byte_command()` method
  - Updated `_issue_usb_command()` with phase checking pattern
  - Fixed endpoint discovery using `get_configuration_descriptor()`
  - Updated `inquiry()`, `test_unit_ready()`, `wait_scanner()` to use 6-byte format
  - Improved error handling for macOS libusb quirks

## References

- USB capture analysis: `docs/usb-capture-findings.md`
- Protocol details: `docs/protocol.md`
- USB capture files: `ls40-single-bw.pcapng`, `ls40-batch.pcapng`

## Next Steps

1. ✅ Communication working
2. ⏭️ Implement full initialization sequence from USB capture
3. ⏭️ Test INQUIRY command with page codes
4. ⏭️ Implement scan commands
5. ⏭️ Create scanner status reporting script
