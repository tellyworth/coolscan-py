# Refactoring Plan: SCSI-to-USB Translation Layer

## Overview

This document outlines a refactoring plan to introduce a translation layer between high-level SCSI command building and interface-specific command formatting. This will enable future support for SCSI/Firewire interfaces while maintaining the current USB functionality.

## Current Architecture

### Current State

```
High-Level Methods (inquiry, test_unit_ready, etc.)
    ↓
Direct USB Format Building (_build_6byte_command)
    ↓
USB-Specific Commands (control byte 0x80, custom layout)
    ↓
PyUSB (raw bulk transfers)
```

**Issues:**
- USB-specific format is hardcoded in high-level methods
- No abstraction for different interfaces
- SCSI/Firewire support would require duplicating logic
- Protocol logic is mixed with interface-specific formatting

### Current Code Structure

```python
class CoolscanProtocol:
    def inquiry(self, page: int = -1) -> bytes:
        # Directly builds USB-specific format
        cmd = self._build_6byte_command(0x12, page=0x01, param2=page,
                                       alloc_length=4, control=0x80)
        # ...

    def _build_6byte_command(self, cmd_code, page=0, param2=0, param3=0,
                            alloc_length=0, control=0x80):
        # USB-specific format
        return struct.pack('BBBBBB', cmd_code, page, param2, param3,
                          alloc_length, control)
```

## Proposed Architecture

### Target State

```
High-Level Methods (inquiry, test_unit_ready, etc.)
    ↓
SCSI Command Builder (builds standard SCSI CDB)
    ↓
Translation Layer (interface-specific)
    ├─ USB Translator (SCSI → USB format)
    └─ SCSI Translator (SCSI → SCSI, pass-through)
    ↓
Interface-Specific Commands
    ├─ USB Format (control 0x80, custom layout)
    └─ SCSI Format (standard SCSI CDB)
    ↓
Transport Layer
    ├─ PyUSB (raw USB bulk)
    └─ SCSI device file (raw SCSI)
```

### Benefits

1. **Single Source of Truth**: Protocol logic in one place (SCSI command builder)
2. **Interface Abstraction**: Translation layer handles USB vs SCSI differences
3. **Easier Maintenance**: Changes to protocol logic only need to happen once
4. **Future-Proof**: Adding new interfaces only requires a new translator
5. **Testability**: Can test protocol logic independently of interface

## Refactoring Steps

### Phase 1: Create SCSI Command Builder

**Goal**: Extract protocol logic into standard SCSI CDB builder

**Changes:**
1. Create `_build_scsi_cdb()` method that builds standard SCSI Command Descriptor Blocks
2. Keep existing `_build_6byte_command()` for backward compatibility (mark as deprecated)
3. Update high-level methods to use `_build_scsi_cdb()` internally

**Example:**

```python
def _build_scsi_cdb(self, opcode: int, **params: dict) -> bytes:
    """
    Build standard SCSI 6-byte CDB (Command Descriptor Block).

    Standard SCSI format:
    Byte 0: Operation code
    Byte 1: LUN/EVPD/Page code (varies by command)
    Byte 2: Reserved/Page code
    Byte 3: Reserved
    Byte 4: Allocation length / Transfer length
    Byte 5: Control (usually 0x00)

    Args:
        opcode: SCSI operation code
        **params: Command-specific parameters

    Returns:
        bytes: 6-byte SCSI CDB
    """
    # Command-specific building logic
    if opcode == 0x12:  # INQUIRY
        evpd = params.get('evpd', 0)
        page_code = params.get('page_code', 0)
        alloc_length = params.get('alloc_length', 36)
        return struct.pack('BBBBBB',
            opcode,      # 0: Operation code
            evpd,        # 1: EVPD flag
            page_code,   # 2: Page code
            0x00,        # 3: Reserved
            alloc_length, # 4: Allocation length
            0x00         # 5: Control (standard SCSI)
        )
    elif opcode == 0x00:  # TEST_UNIT_READY
        return struct.pack('BBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    elif opcode == 0x16:  # RESERVE_UNIT
        return struct.pack('BBBBBB', 0x16, 0x00, 0x00, 0x00, 0x00, 0x00)
    # ... other commands
```

### Phase 2: Create Translation Layer

**Goal**: Add interface-specific translators

**Changes:**
1. Create `_translate_command()` method that routes to appropriate translator
2. Create `_translate_to_usb()` method (SCSI → USB format)
3. Create `_translate_to_scsi()` method (SCSI → SCSI, pass-through for now)
4. Update `_issue_command()` to use translation layer

**Example:**

```python
def _translate_command(self, scsi_cdb: bytes) -> bytes:
    """
    Translate standard SCSI CDB to interface-specific format.

    Args:
        scsi_cdb: Standard SCSI Command Descriptor Block (6 bytes)

    Returns:
        bytes: Interface-specific command format
    """
    if self.interface.value == "usb":
        return self._translate_to_usb(scsi_cdb)
    else:  # SCSI/Firewire
        return self._translate_to_scsi(scsi_cdb)

def _translate_to_usb(self, scsi_cdb: bytes) -> bytes:
    """
    Translate standard SCSI CDB to USB-specific format.

    USB format differences:
    - Control byte: 0x00 → 0x80 (for most commands)
    - Parameter layout: Page codes in different positions
    - Some commands have different allocation length encoding

    Args:
        scsi_cdb: Standard SCSI CDB (6 bytes)

    Returns:
        bytes: USB-specific command format (6 or 10 bytes)
    """
    if len(scsi_cdb) < 6:
        raise ValueError("SCSI CDB must be at least 6 bytes")

    opcode = scsi_cdb[0]

    # Parse standard SCSI format
    byte1 = scsi_cdb[1]  # LUN/EVPD/Page code
    byte2 = scsi_cdb[2]  # Reserved/Page code
    byte3 = scsi_cdb[3]  # Reserved
    byte4 = scsi_cdb[4]  # Allocation length
    byte5 = scsi_cdb[5]  # Control (0x00 in standard SCSI)

    # Translate to USB format
    if opcode == 0x12:  # INQUIRY
        # USB format: [Cmd] [Page] [Param2] [Param3] [AllocLen] [Control=0x80]
        page_code = byte2 if byte2 != 0 else byte1
        return struct.pack('BBBBBB',
            opcode,      # 0: Command code
            page_code,  # 1: Page code (USB format)
            0x00,        # 2: Parameter 2
            0x00,        # 3: Parameter 3
            byte4,       # 4: Allocation length
            0x80         # 5: Control byte (USB-specific)
        )
    elif opcode == 0x00:  # TEST_UNIT_READY
        # Simple commands keep control byte 0x00
        return struct.pack('BBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    elif opcode == 0x16:  # RESERVE_UNIT
        return struct.pack('BBBBBB', 0x16, 0x00, 0x00, 0x00, 0x00, 0x00)
    elif opcode == 0x1b:  # START_STOP_UNIT
        # USB format: [Cmd] [Param1] [Param2] [Param3] [Action] [Control=0x00]
        action = byte4  # Action is in byte 4 for START_STOP_UNIT
        return struct.pack('BBBBBB', 0x1b, 0x00, 0x00, 0x00, action, 0x00)
    elif opcode == 0x25:  # READ_CAPACITY
        # 10-byte command in USB format
        # Format: 25 00 00 00 00 00 00 00 [len_high] [len_low|0x80]
        alloc_len = byte4
        len_high = (alloc_len >> 8) & 0xff
        len_low = alloc_len & 0xff
        return struct.pack('BBBBBBBBBB',
            0x25, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            len_high, len_low | 0x80
        )
    else:
        # Default translation: keep opcode, rearrange parameters, set control to 0x80
        return struct.pack('BBBBBB',
            opcode,      # 0: Command code
            byte1,       # 1: Parameter 1
            byte2,       # 2: Parameter 2
            byte3,       # 3: Parameter 3
            byte4,       # 4: Allocation length
            0x80         # 5: Control byte (USB-specific)
        )

def _translate_to_scsi(self, scsi_cdb: bytes) -> bytes:
    """
    Translate SCSI CDB for SCSI/Firewire interface.

    For SCSI/Firewire, the format is standard SCSI, so this is mostly
    a pass-through. May need adjustments for specific SCSI variants.

    Args:
        scsi_cdb: Standard SCSI CDB

    Returns:
        bytes: SCSI-formatted command (same as input for now)
    """
    # For now, SCSI/Firewire uses standard SCSI format
    # This may need adjustments when we implement SCSI support
    return scsi_cdb
```

### Phase 3: Update High-Level Methods

**Goal**: Refactor high-level methods to use SCSI builder + translation

**Changes:**
1. Update `inquiry()`, `test_unit_ready()`, etc. to use `_build_scsi_cdb()`
2. Route through `_translate_command()` before sending
3. Keep method signatures the same (backward compatibility)

**Example:**

```python
def inquiry(self, page: int = -1) -> bytes:
    """
    Send INQUIRY command to get device information.

    Uses SCSI command builder + translation layer for interface-specific format.
    """
    if page >= 0:
        # Two-step process: get length, then full data
        # Step 1: Get length (4 bytes)
        scsi_cdb = self._build_scsi_cdb(0x12, evpd=0, page_code=page, alloc_length=4)
        usb_cmd = self._translate_command(scsi_cdb)
        data, status = self._issue_command(usb_cmd, data_in_length=4)

        if status == StatusType.READY and len(data) >= 4:
            # Extract actual length from response
            length = data[3] + 4  # Length is in byte 3, add 4 for header

            # Step 2: Get full data
            scsi_cdb = self._build_scsi_cdb(0x12, evpd=0, page_code=page,
                                           alloc_length=length)
            usb_cmd = self._translate_command(scsi_cdb)
            data, status = self._issue_command(usb_cmd, data_in_length=length)
    else:
        # Standard inquiry (36 bytes)
        scsi_cdb = self._build_scsi_cdb(0x12, evpd=0, page_code=0, alloc_length=36)
        usb_cmd = self._translate_command(scsi_cdb)
        data, status = self._issue_command(usb_cmd, data_in_length=36)

    if status == StatusType.READY:
        return data
    else:
        raise RuntimeError(f"INQUIRY failed with status {status}")

def test_unit_ready(self) -> bool:
    """Test if the scanner is ready."""
    scsi_cdb = self._build_scsi_cdb(0x00)  # TEST_UNIT_READY
    usb_cmd = self._translate_command(scsi_cdb)
    _, status = self._issue_command(usb_cmd)
    return status == StatusType.READY
```

### Phase 4: Update Command Issuing

**Goal**: Route commands through translation layer

**Changes:**
1. Update `_issue_command()` to accept SCSI CDB format
2. Translate before sending to interface-specific layer
3. Keep `_issue_usb_command()` and `_issue_scsi_command()` as interface-specific

**Example:**

```python
def _issue_command(self, command: bytes, data_out: bytes = b'',
                  data_in_length: int = 0) -> Tuple[bytes, StatusType]:
    """
    Issue a command to the scanner.

    This method now expects a standard SCSI CDB and translates it
    to the appropriate interface format.

    Args:
        command: Standard SCSI CDB (will be translated)
        data_out: Data to send (if any)
        data_in_length: Expected data length (if any)

    Returns:
        Tuple of (data received, status)
    """
    # Translate to interface-specific format
    interface_cmd = self._translate_command(command)

    if self.interface.value == "usb":
        return self._issue_usb_command(interface_cmd, data_out, data_in_length)
    else:
        return self._issue_scsi_command(interface_cmd, data_out, data_in_length)
```

### Phase 5: Deprecate Old Methods

**Goal**: Mark old USB-specific methods as deprecated

**Changes:**
1. Add deprecation warnings to `_build_6byte_command()`
2. Keep method for backward compatibility during transition
3. Document migration path

**Example:**

```python
def _build_6byte_command(self, cmd_code: int, page: int = 0,
                       param2: int = 0, param3: int = 0,
                       alloc_length: int = 0, control: int = 0x80) -> bytes:
    """
    Build a 6-byte command in USB-specific format.

    .. deprecated:: 0.2.0
        Use `_build_scsi_cdb()` + `_translate_command()` instead.
        This method is kept for backward compatibility.

    This method will be removed in a future version.
    """
    import warnings
    warnings.warn(
        "_build_6byte_command() is deprecated. "
        "Use _build_scsi_cdb() + _translate_command() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    # Implementation remains the same for now
    return struct.pack('BBBBBB', cmd_code, page, param2, param3,
                      alloc_length, control)
```

## Implementation Checklist

### Phase 1: SCSI Command Builder
- [ ] Create `_build_scsi_cdb()` method
- [ ] Implement standard SCSI CDB format for all commands
- [ ] Add unit tests for SCSI CDB building
- [ ] Document command parameters

### Phase 2: Translation Layer
- [ ] Create `_translate_command()` router
- [ ] Implement `_translate_to_usb()` with all command mappings
- [ ] Implement `_translate_to_scsi()` (pass-through for now)
- [ ] Add unit tests for translation
- [ ] Verify USB format matches current working implementation

### Phase 3: High-Level Methods
- [ ] Refactor `inquiry()` to use SCSI builder
- [ ] Refactor `test_unit_ready()` to use SCSI builder
- [ ] Refactor `reserve_unit()` to use SCSI builder
- [ ] Refactor `release_unit()` to use SCSI builder
- [ ] Refactor `start_scan()` to use SCSI builder
- [ ] Refactor all other command methods
- [ ] Add integration tests

### Phase 4: Command Issuing
- [ ] Update `_issue_command()` to use translation
- [ ] Verify all commands still work with USB
- [ ] Add logging for translation steps (debug mode)

### Phase 5: Cleanup
- [ ] Mark `_build_6byte_command()` as deprecated
- [ ] Update documentation
- [ ] Remove deprecated methods in next major version

## Testing Strategy

### Unit Tests

1. **SCSI CDB Builder Tests**
   - Test each command type builds correct SCSI CDB
   - Verify parameter encoding
   - Test edge cases

2. **Translation Tests**
   - Test SCSI → USB translation for each command
   - Verify USB format matches current working format
   - Test SCSI → SCSI pass-through

3. **Integration Tests**
   - Test full command flow (build → translate → send)
   - Verify USB scanner still responds correctly
   - Test backward compatibility

### Validation

- **USB Format Verification**: Compare translated commands with USB capture data
- **Functional Testing**: Ensure all scanner operations still work
- **Performance**: Ensure translation doesn't add significant overhead

## Migration Notes

### Backward Compatibility

- Keep `_build_6byte_command()` during transition
- High-level method signatures remain unchanged
- Existing code continues to work

### Breaking Changes

- None in initial refactoring
- Deprecated methods will be removed in future major version

### Rollback Plan

- Keep old implementation in git history
- Can revert if issues arise
- Translation layer can be disabled via flag if needed

## Future Enhancements

### SCSI/Firewire Support

Once translation layer is in place:
1. Implement `_issue_scsi_command()` for SCSI device files
2. Test with SCSI/Firewire scanner
3. Verify `_translate_to_scsi()` works correctly

### Additional Interfaces

Translation layer makes it easy to add:
- Network-attached scanners
- Virtual interfaces for testing
- Protocol converters

## References

- **USB Capture Format**: `docs/usb-capture-findings.md`
- **SANE Backend Analysis**: `docs/wakeup-sequence-analysis.md`
- **Translation Discovery**: `docs/command-format-translation.md`
- **Unified Protocol Spec**: `docs/unified-protocol-spec.md`

## Timeline Estimate

- **Phase 1**: 2-3 days (SCSI builder + tests)
- **Phase 2**: 3-4 days (Translation layer + tests)
- **Phase 3**: 4-5 days (Refactor methods + integration tests)
- **Phase 4**: 1-2 days (Command issuing updates)
- **Phase 5**: 1 day (Documentation + cleanup)

**Total**: ~2-3 weeks for complete refactoring

## Notes

- This refactoring should be done when we're ready to add SCSI/Firewire support
- Current USB implementation works fine - this is for future extensibility
- Can be done incrementally (one phase at a time)
- Should maintain 100% backward compatibility during transition
