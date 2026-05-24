# SANE Backend Phase Handling Verification

## Current Issue: Overflow Error on Data Read

**Problem**: After scan completes (READY status), reading image data fails with:
- `[Errno 84] Overflow` when trying to read 1-byte phase response
- Subsequent timeouts on data reads

## SANE Backend Behavior (from Documentation)

### Phase Checking Protocol
- **SANE uses**: `cs2_phase_check()` / `cs3_phase_check()` functions
- **Frequency**: Phase check (0xd0) sent after **every command** (572 times in scan session)
- **Pattern**: Command → Phase check (0xd0) → Read phase (1 byte) → Handle phase → Read status (8 bytes)

### For READ Commands Specifically
From `unified-protocol-spec.md`:
1. Send READ command (10 bytes)
2. Send phase check (0xd0)
3. Read phase response (1 byte) - should be `0x03` (DATA_IN)
4. Read data bytes (allocation length)
5. Read status (8 bytes)

**Key Point**: SANE **always checks phase** before reading data - it doesn't skip phase check for READ commands.

## USB Capture Verification

### Working Sequence (from `usb_capture_timing.txt`):
```
Line 999: READ command: 28000000000001fec080 (130752 bytes)
Line 1000: Phase check: d0
Line 1004: Phase response: 03 (DATA_IN)
Line 1006: Data: 130752 bytes
Line 1008: Status: 0000000000000000 (READY)
```

**No Overflow errors** in the working capture - phase check always succeeds.

### What Happens Before Image Data Read
- Line 976-998: GET_WINDOW commands (0x25) reading back WDBs
- These commands might naturally clear the USB buffer
- Then immediately: First image data READ command

## Our Implementation vs SANE

### What We're Doing (Correct)
- ✅ Sending phase check (0xd0) after every command
- ✅ Reading phase response (1 byte)
- ✅ Handling DATA_IN phase (0x03) for READ commands
- ✅ Reading data after phase check

### The Problem
- ❌ **Overflow error** suggests leftover data in USB buffer when we try to read phase
- This happens **after polling completes** - likely leftover from TEST_UNIT_READY commands
- SANE might drain the buffer or the GET_WINDOW commands clear it naturally

## Our Fix

### 1. Improved Overflow Handling
When Overflow occurs on phase read for READ commands:
- Read a small chunk (up to 64 bytes) to get phase byte + any available data
- Extract phase byte from first byte
- Store remaining data and prepend to full data read
- This handles cases where phase + data are sent together

### 2. Buffer Draining Before Data Read
Added aggressive buffer draining after polling completes:
- Clear halt on IN endpoint
- Drain up to 5 chunks (4096 bytes each) with 50ms timeout
- This removes leftover data from TEST_UNIT_READY polling

## SANE Backend Code Verification

### What We Couldn't Verify (No Source Access)
- Exact implementation of `cs3_phase_check()` function
- How SANE handles Overflow errors (if at all)
- Whether SANE drains USB buffer before data reads
- Whether SANE skips phase check for READ commands (unlikely based on docs)

### What We Know from Documentation
1. **Phase checking is mandatory** - SANE always checks phase after commands
2. **Phase check frequency** - 572 times in a scan session (very frequent)
3. **No Overflow in working capture** - suggests proper buffer management
4. **GET_WINDOW commands** - Sent right before image data read (might clear buffer)

## Recommendations

1. ✅ **Buffer draining** - Implemented aggressive draining before data reads
2. ✅ **Overflow handling** - Read chunk and extract phase when Overflow occurs
3. ⚠️ **Verify**: Test if GET_WINDOW commands are needed before data read (USB capture shows them)
4. ⚠️ **Monitor**: Check if buffer draining actually removes leftover data

## Next Test

The next run should:
1. Drain any leftover data from polling before first READ command
2. Handle Overflow gracefully if it still occurs (read chunk, extract phase)
3. Successfully read image data blocks

If Overflow still occurs, we may need to:
- Send a dummy command (like GET_WINDOW) to clear buffer
- Or drain buffer more aggressively
- Or check if phase check can be skipped for READ commands (unlikely based on SANE docs)
