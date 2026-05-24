# SANE Backend Comparison for START_SCAN Sequence

## Issue: Scanner Reports READY Immediately After START_SCAN

**Problem**: After sending START_SCAN, the scanner reports READY immediately instead of PROCESSING, indicating the scan isn't starting.

**USB Capture Shows**:
- START_SCAN returns: `0209800601000000` (sense_key=9, ASC=128, ASCQ=6)
- Then immediately reads status/progress blocks (datatype 0x87)
- Then polls with TEST_UNIT_READY until PROCESSING status
- Scanner should be PROCESSING for ~13 seconds, then READY

**Our Implementation Gets**:
- START_SCAN returns: `0209800100000000` (sense_key=9, ASC=128, ASCQ=1)
- Scanner reports READY immediately (no PROCESSING state)
- Status/progress reads fail or timeout

## SANE Backend Behavior (from docs)

### From `new-recommendations.md`:
- SANE uses `wait_scanner()` after START_SCAN
- `wait_scanner()` sends TEST_UNIT_READY repeatedly (up to 40 attempts, 0.5s delays)
- SANE originally used 8-second sleep for prescan
- Handles DEVICE_BUSY status with retries

### From `unified-protocol-spec.md`:
- After START_SCAN, scanner should return PROCESSING status (`0202040100000000`)
- Poll with TEST_UNIT_READY until status returns READY (`0000000000000000`)
- Implementation uses `poll_until_ready()` for dynamic polling

## USB Capture Sequence (from `usb-capture-findings.md`)

1. **START_SCAN** (`1b0000000300`) + data (`010203`)
2. **Status response**: `0209800601000000` (sense_key=9, ASC=128, ASCQ=6)
3. **Immediate status/progress reads** (datatype 0x87):
   - Read 6 bytes: `28008700000000000680`
   - Read 33 bytes: `28008700000000002180`
4. **Polling loop** with TEST_UNIT_READY:
   - Status `0202040100000000` = PROCESSING (scanner is scanning)
   - Status `0000000000000000` = READY (scan complete)
5. **Read image data** (datatype 0x00)
6. **Read exposure data** (datatype 0x8e)

## Key Differences: ASCQ=1 vs ASCQ=6

**USB Capture (Working)**:
- ASCQ=6: Scanner accepts START_SCAN, scan begins
- Status/progress reads succeed
- Scanner transitions to PROCESSING

**Our Implementation (Failing)**:
- ASCQ=1: Different error code - scan may not be starting
- Status/progress reads fail
- Scanner reports READY immediately (no scan started)

## Possible Causes

1. **Missing prerequisite steps**:
   - SANE docs mention unit reservation cycle
   - SANE docs mention object feed step
   - SANE docs mention internal info read

2. **WDB configuration issue**:
   - Prescan WDBs might be incorrect
   - Window IDs might be wrong
   - Scan kind might be wrong

3. **LUT upload issue**:
   - LUTs might not be uploaded correctly
   - Wrong datatype or channel IDs

4. **Command format issue**:
   - START_SCAN command format might be wrong
   - Data bytes (`010203`) might be wrong

## Recommended Investigation

1. **Check actual sense codes**: Extract and log the full 8-byte status response from START_SCAN
2. **Verify WDB values**: Compare our prescan WDBs byte-by-byte with USB capture
3. **Verify LUT upload**: Check if LUTs are actually uploaded (maybe add verification read)
4. **Check SANE source**: Look at actual SANE backend code for `cs3_scan()` function
5. **Add more logging**: Log all status responses with full sense codes

## Phase Handling and Data Reading (Current Issue)

**Problem**: After scan completes (READY), reading image data fails with Overflow error on phase read, then timeouts.

**USB Capture Shows**:
- READ command → phase check (0xd0) → phase response (0x03 = DATA_IN) → read data → read status
- Phase check is always done before reading data
- No Overflow errors in working capture

**Our Implementation Gets**:
- Overflow error when trying to read 1-byte phase response
- This suggests data is already available when we try to read phase
- Subsequent data reads timeout

**SANE Backend Behavior** (from docs):
- Uses `cs2_phase_check()` / `cs3_phase_check()` before reading status
- Phase check (0xd0) is sent after every command (572 times in scan session)
- For DATA_IN phase (0x03): Read data bytes directly
- **Key**: SANE always checks phase before reading data

**Possible Causes**:
1. **Leftover data in USB buffer**: After polling with TEST_UNIT_READY, there might be leftover data
2. **Phase + data sent together**: Scanner might send phase byte + data together
3. **Buffer not drained**: We might need to drain/clear USB buffer before reading

**Our Fix**:
- When Overflow occurs on phase read for READ commands:
  - Read a small chunk (up to 64 bytes) to get phase byte + any available data
  - Extract phase byte from first byte
  - Store any remaining data and prepend it to full data read
  - This handles cases where phase + data are sent together

**Verification Needed**:
- Check if SANE drains USB buffer before reading data
- Check if SANE handles Overflow errors differently
- Verify if phase check is always done before data read (or if it's skipped for READ commands)

## Next Steps

1. ✅ Extract and log the full status response from START_SCAN - **DONE**
2. ✅ Compare our WDB bytes with USB capture - **MATCHES**
3. ✅ Add verification that LUTs were uploaded correctly - **DONE**
4. ⚠️ **CURRENT**: Fix Overflow handling for data reads after scan completes
5. Verify if USB buffer needs draining before data reads
6. Check if additional steps needed before START_SCAN (object feed, etc.)
