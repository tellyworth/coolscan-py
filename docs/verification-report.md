# Documentation Verification Report

## Overview

This document cross-references all documentation against:
1. USB capture data (pcapng files)
2. SANE backend code analysis
3. Actual working implementation

## Issues Found

### 1. Command Code Mislabeling

**Issue**: `0x24` is labeled as "SCAN" but it's actually "READ"

**Location**: `docs/usb-capture-findings.md:150`

**Current Documentation**:
```
- **SCAN (0x24)**: 18 times
```

**USB Capture Evidence**:
```
Full: 24000000000000003a80
Command: 0x24 (36) → READ
```

**Correction**: Should be:
```
- **READ (0x24)**: 18 times
```

**Impact**: Medium - Misleading but doesn't break functionality

---

### 2. READ Command Format Documentation

**Issue**: READ (0x24) format is documented as 6 bytes, but capture shows 10 bytes

**Location**: `docs/unified-protocol-spec.md:179`

**Current Documentation**:
```
3. **READ commands** (`24 00 00 00 00 00 00 00 [len] 80`) - Read scan data
```

**USB Capture Evidence**:
```
Full: 24000000000000003a80
```

This is **10 bytes**: `24 00 00 00 00 00 00 00 3a 80`
- Bytes 0-7: `24 00 00 00 00 00 00 00`
- Byte 8: `3a` (allocation length high = 58)
- Byte 9: `80` (allocation length low | control)

**Correction**: Should document as 10-byte command:
```
3. **READ commands** (`24 00 00 00 00 00 00 00 [len_high] [len_low|0x80]`) - Read scan data
   Format: 10 bytes, allocation length in bytes 8-9
```

**Impact**: High - Format mismatch could cause implementation errors

---

### 3. READ(10) vs READ Command Confusion

**Issue**: Documentation doesn't clearly distinguish between READ (0x24) and READ(10) (0x28)

**USB Capture Evidence**:
- **READ (0x24)**: `24000000000000003a80` (10 bytes, simple read)
- **READ(10) (0x28)**: `28008e00000000000680` (10 bytes, with datatype codes)

**Current Documentation**:
- `docs/protocol.md` lists both but doesn't explain the difference
- `docs/usb-capture-findings.md` mentions "READ (0x28)" but doesn't mention 0x24

**Correction Needed**:
- Document that 0x24 is READ (simple)
- Document that 0x28 is READ(10) with datatype codes
- Explain when each is used

**Impact**: Medium - Could cause confusion during implementation

---

### 4. READ_CAPACITY Variants Not Documented

**Issue**: READ_CAPACITY has variants with different parameters that aren't documented

**USB Capture Evidence**:
```
Full: 25000000000000003a80  (standard READ_CAPACITY)
Full: 25010000000100003a80  (variant with parameter 0x01)
Full: 25010000000200003a80  (variant with parameter 0x02)
Full: 25010000000300003a80  (variant with parameter 0x03)
Full: 25010000000400003a80  (variant with parameter 0x04)
Full: 25010000000900003a80  (variant with parameter 0x09)
```

**Current Documentation**: Only shows standard `25000000000000003a80`

**Correction Needed**: Document READ_CAPACITY variants and their purpose

**Impact**: Low - Standard variant works, but variants may be needed for full functionality

---

### 5. WRITE Command Format Inconsistency

**Issue**: WRITE command format shown in docs doesn't match all capture examples

**Location**: `docs/unified-protocol-spec.md:177`

**Current Documentation**:
```
1. **WRITE commands** (`2a 00 92 00 00 03 00 00 04 00`) - Send window/parameters
```

**USB Capture Evidence**:
```
Full: 2a009200000300000400  (matches docs)
Full: 2a000300010100200000  (different format)
Full: 2a000300020100200000  (different format)
Full: 2a000300030100200000  (different format)
```

**Analysis**: WRITE commands have different formats for different purposes:
- `2a009200000300000400` - Window/parameter setting
- `2a000300010100200000` - Data transfer (different parameters)

**Correction Needed**: Document that WRITE has multiple formats depending on purpose

**Impact**: Medium - Could cause issues when implementing data transfer

---

### 6. READ(10) Command Format Not Fully Documented

**Issue**: READ(10) (0x28) format with datatype codes not fully documented

**USB Capture Evidence**:
```
Full: 28008e00000000000680
Full: 28008e000000000d7c80
Full: 28008f00000300003a80
Full: 28008c00010300000a80
Full: 28008c00020300000a80
Full: 28008c00030300000a80
Full: 28008700000000000680
Full: 28008700000000002180
```

**Analysis**: READ(10) format appears to be:
- Byte 0: `0x28` (READ(10))
- Byte 1: Datatype code (0x8e, 0x8f, 0x8c, 0x87)
- Bytes 2-9: Parameters and length

**Current Documentation**: Only mentions READ(10) exists, doesn't document format

**Correction Needed**: Document READ(10) format with datatype codes

**Impact**: High - Needed for reading scan data with proper datatype

---

### 7. START_STOP_UNIT Format Verification

**Status**: ✅ **CORRECT**

**USB Capture Evidence**:
```
Full: 1b0000000300  (start)
Full: 1b0000000400  (stop)
```

**Documentation**: Matches `docs/unified-protocol-spec.md:55-58`

---

### 8. INQUIRY Page Sequence Verification

**Status**: ✅ **CORRECT**

**USB Capture Evidence** matches documented sequence in `docs/usb-capture-findings.md:97-134`

---

### 9. Phase Check Frequency

**Status**: ✅ **CORRECT**

**USB Capture Evidence**: 572 phase checks matches `docs/usb-capture-findings.md:146`

---

### 10. TEST_UNIT_READY Frequency

**Status**: ✅ **CORRECT**

**USB Capture Evidence**: 346 TEST_UNIT_READY matches `docs/usb-capture-findings.md:145`

---

## Summary of Required Corrections

### High Priority (Format Errors)

1. **READ (0x24) format**: Document as 10-byte command, not 6-byte
2. **READ(10) (0x28) format**: Document full format with datatype codes
3. **Command mislabeling**: Change "SCAN (0x24)" to "READ (0x24)"

### Medium Priority (Missing Details)

4. **WRITE command variants**: Document multiple WRITE formats
5. **READ vs READ(10) distinction**: Clearly explain difference and usage

### Low Priority (Enhancements)

6. **READ_CAPACITY variants**: Document parameter variations

---

## Verification Against SANE Backend

### ✅ Verified Correct

1. **wait_scanner() logic**: 40 attempts, 0.5s delays matches SANE
2. **Prescan timing**: Originally used 8 second sleep (matches SANE), now uses dynamic polling (`poll_until_ready()`) which is more efficient
3. **Initialization sequence**: High-level flow matches SANE
4. **Phase checking**: SANE uses phase checks, matches USB pattern
5. **Prescan data reading**: Now implements full data reading phase (`read_prescan_image_data()`, `read_exposure_data()`)

### ⚠️ Differences (Expected)

1. **Command format**: SANE shows standard SCSI, USB capture shows USB-specific (expected - translation layer)
2. **MODE_SENSE**: SANE uses MODE_SENSE for MUD, USB capture uses INQUIRY page 0xd1 (both valid, different approaches)

---

## Recommendations

1. **Update command format documentation** to reflect actual 10-byte READ format
2. **Document READ(10) with datatype codes** for scan data reading
3. **Fix command code labels** (0x24 = READ, not SCAN)
4. **Document WRITE command variants** for different purposes
5. **Add READ_CAPACITY variant documentation** for completeness

---

## Files Requiring Updates

1. `docs/usb-capture-findings.md` - Fix command labels and READ format
2. `docs/unified-protocol-spec.md` - Update READ/READ(10) documentation
3. `docs/protocol.md` - Clarify READ vs READ(10) distinction
4. `docs/command-format-translation.md` - Add READ(10) format details

---

## Next Steps

1. Update documentation with corrections
2. Verify READ(10) format analysis with more capture data
3. Test READ command implementation with 10-byte format
4. Document datatype codes for READ(10) commands
