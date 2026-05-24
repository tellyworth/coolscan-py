# Prescan Sequence Verification

## USB Capture Sequence (usb_capture_timing.txt, lines 687-763)

1. **Line 687**: `TEST_UNIT_READY` (000000000000) - right before prescan starts
2. **Line 695**: `SET_WINDOW` window 1 (24000000000000003a80 + 58-byte WDB)
3. **Line 705**: `SET_WINDOW` window 2 (24000000000000003a80 + 58-byte WDB)
4. **Line 715**: `SET_WINDOW` window 3 (24000000000000003a80 + 58-byte WDB)
5. **Line 725**: `TEST_UNIT_READY` (000000000000) - before LUTs
6. **Line 733**: `WRITE LUT R` (2a000300010100200000 + 8192 bytes)
7. **Line 743**: `WRITE LUT G` (2a000300020100200000 + 8192 bytes)
8. **Line 753**: `WRITE LUT B` (2a000300030100200000 + 8192 bytes)
9. **Line 763**: `START_SCAN` (1b0000000300 + 3 bytes 010203)
10. **Line 773**: `READ status/progress` (28008700000000000680) - 6 bytes, datatype 0x87
11. **Line 783**: `READ status/progress` (28008700000000002180) - 33 bytes, datatype 0x87
12. **After line 783**: Polling with `TEST_UNIT_READY` until READY, then data reads

## Our Implementation Sequence

1. ✅ `test_unit_ready()` - initial check (matches line 687)
2. ✅ `reserve_unit()` - **Note: NOT in USB capture before prescan** (RESERVE_UNIT is at line 171, ~36s, during initialization)
3. ✅ `set_scan_window(1, 'prescan')` (matches line 695)
4. ✅ `set_scan_window(2, 'prescan')` (matches line 705)
5. ✅ `set_scan_window(3, 'prescan')` (matches line 715)
6. ✅ `test_unit_ready()` - before LUTs (matches line 725)
7. ✅ `upload_identity_luts()` - R, G, B (matches lines 733, 743, 753)
8. ✅ `start_scan()` (matches line 763)
9. ✅ `read_scan_data(6, DataType.STATUS_PROGRESS)` - immediate status read (matches line 773)
10. ✅ `read_scan_data(33, DataType.STATUS_PROGRESS)` - second status read (matches line 783)
11. ✅ `poll_until_ready()` - dynamic polling with TEST_UNIT_READY
12. ✅ `read_prescan_image_data()` - read image blocks
13. ✅ `read_exposure_data()` - read exposure/calibration data
14. ✅ `get_exposure_values()` - extract exposure from WDBs
15. ✅ `release_unit()` - cleanup

## Key Observations

### RESERVE_UNIT Placement
- **USB Capture**: RESERVE_UNIT happens at line 171 (~36 seconds) during initialization, NOT right before prescan
- **Our Implementation**: We call `reserve_unit()` inside `prescan()` for proper resource management
- **Conclusion**: This is correct - the scanner must be reserved before scan operations, even if it was done earlier in the session. Our implementation ensures the unit is reserved for each prescan operation.

### Missing Commands
- ✅ All commands from USB capture are present in our implementation
- ✅ We include additional steps (status reads, polling, data reads) that occur after START_SCAN

### Test Expectations
- ✅ Tests correctly expect `reserve_unit()` to be called (for resource management)
- ✅ Tests correctly expect `test_unit_ready()` twice (lines 687 and 725)
- ✅ Tests correctly expect `set_scan_window()` 3 times (windows 1, 2, 3)
- ✅ Tests correctly verify NO `MODE_SELECT` in prescan (happens earlier at line 239)
- ✅ Tests correctly verify NO `TEST_UNIT_READY` after LUTs (direct transition to START_SCAN)

## Conclusion

Our implementation matches the USB capture sequence correctly. The only difference is that we call `reserve_unit()` inside `prescan()` for proper resource management, which is a good practice even though it's not visible in the USB capture (because it was done earlier in that session).

All required commands for a prescan are present:
- ✅ TEST_UNIT_READY (initial check)
- ✅ RESERVE_UNIT (resource management)
- ✅ SET_WINDOW x3 (windows 1, 2, 3)
- ✅ TEST_UNIT_READY (before LUTs)
- ✅ WRITE LUT x3 (R, G, B)
- ✅ START_SCAN
- ✅ Status/progress reads
- ✅ Polling until ready
- ✅ Data reads (image + exposure)
- ✅ RELEASE_UNIT (cleanup)

Nothing is missing for a complete prescan operation.
