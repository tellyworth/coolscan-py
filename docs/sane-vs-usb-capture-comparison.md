# SANE Backend vs USB Capture Comparison

## Methodology

1. **Trust SANE backend** - It works with hardware, so it's our reference implementation
2. **Cross-check with USB capture** - USB capture shows what Nikon Scan does (may differ from SANE)
3. **Document differences** - If USB capture contradicts SANE, investigate why
4. **Write tests** - Based on SANE sequence, verify with USB capture
5. **Verify against SANE** - Double-check our implementation matches SANE

## Prescan Sequence Comparison

### USB Capture Sequence (from `usb_capture_timing.txt`, lines 695-770)

**Before START_SCAN:**
1. **SET_WINDOW for window 1** (line 695): `24000000000000003a80` → sends 58-byte WDB (window_id=0x01)
2. **SET_WINDOW for window 2** (line 705): `24000000000000003a80` → sends 58-byte WDB (window_id=0x02)
3. **SET_WINDOW for window 3** (line 715): `24000000000000003a80` → sends 58-byte WDB (window_id=0x03)
4. **TEST_UNIT_READY** (line 725): `000000000000`
5. **LUT upload R** (line 733): `2a000300010100200000` + 8192 bytes
6. **LUT upload G** (line 743): `2a000300020100200000` + 8192 bytes
7. **LUT upload B** (line 753): `2a000300030100200000` + 8192 bytes
8. **START_SCAN** (line 763): `1b0000000300` + data `010203`

**Note:** MODE_SELECT (`151000001400`) occurs much earlier in the session (line 239, ~36 seconds) - it's not part of the immediate prescan sequence.

**Status after START_SCAN:**
- Line 770: Status `0209800601000000` (sense_key=9, ASC=128, ASCQ=6) - **ACCEPTED**

### Our Current Implementation

**Before START_SCAN:**
1. **MODE_SELECT** (0x15) - Set mode parameters
2. **SET_WINDOW for window 1** - Prescan WDB
3. **SET_WINDOW for window 2** - Prescan WDB
4. **SET_WINDOW for window 3** - Prescan WDB
5. **TEST_UNIT_READY**
6. **LUT upload R** - Identity LUT
7. **LUT upload G** - Identity LUT
8. **LUT upload B** - Identity LUT
9. **TEST_UNIT_READY**
10. **START_SCAN** (0x1b) + data `010203`

**Status after START_SCAN:**
- Status `0209800106000000` (sense_key=9, ASC=128, ASCQ=1) - **REJECTED**

## Key Differences

### 1. MODE_SELECT Command
- **USB Capture**: Does NOT show MODE_SELECT before prescan
- **Our Implementation**: We send MODE_SELECT first
- **SANE Backend**: Need to check if SANE uses MODE_SELECT for prescan

### 2. MODE_SELECT Timing
- **USB Capture**: MODE_SELECT happens much earlier (line 239, ~36s) - NOT right before prescan
- **Our Implementation**: We send MODE_SELECT right before SET_WINDOW commands
- **Impact**: Sending MODE_SELECT right before prescan might be putting scanner in wrong state

### 3. TEST_UNIT_READY After LUTs
- **USB Capture**: No TEST_UNIT_READY after LUT uploads (goes directly to START_SCAN)
- **Our Implementation**: We send TEST_UNIT_READY after LUTs
- **Impact**: This extra command might be causing the scanner to reject START_SCAN (ASCQ=1)

### 4. ASCQ Values
- **USB Capture (Working)**: ASCQ=6 (scan accepted)
- **Our Implementation (Failing)**: ASCQ=1 (scan rejected)
- **Meaning**: ASCQ=1 means the scanner is rejecting the scan command

## Questions to Answer

1. **Does SANE use MODE_SELECT for prescan?**
   - Check SANE backend code for prescan sequence
   - If not, we should remove it

2. **When are windows 1 and 2 set?**
   - USB capture might show them earlier in the sequence
   - Or they might not be needed for prescan

3. **Is TEST_UNIT_READY after LUTs necessary?**
   - USB capture doesn't show it
   - This might be causing state issues

4. **What causes ASCQ=1 vs ASCQ=6?**
   - Need to understand what makes scanner accept vs reject scan

## Fixes Applied

Based on USB capture analysis:

1. **Removed MODE_SELECT from prescan** - MODE_SELECT happens earlier (during initialization), not right before prescan
2. **Removed TEST_UNIT_READY after LUTs** - USB capture shows direct transition from LUT uploads to START_SCAN

**Updated Prescan Sequence:**
1. Reserve unit
2. SET_WINDOW for window 1
3. SET_WINDOW for window 2
4. SET_WINDOW for window 3
5. TEST_UNIT_READY
6. LUT upload R
7. LUT upload G
8. LUT upload B
9. START_SCAN (directly, no TEST_UNIT_READY)

This should match the USB capture sequence and fix the ASCQ=1 rejection.

## Next Steps

1. **Verify MODE_SELECT placement** - Check if MODE_SELECT should be part of `initialize_scanner()` instead
2. **Write/update tests** - Ensure tests match the corrected sequence
3. **Test with hardware** - Verify START_SCAN now returns ASCQ=6 (accepted) instead of ASCQ=1 (rejected)
4. **Check SANE backend** - Verify if SANE uses MODE_SELECT for prescan or only during initialization
