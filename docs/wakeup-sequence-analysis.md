# Wake-Up Sequence Analysis from SANE Backend

## Overview
After analyzing all three Coolscan driver files (`coolscan.c`, `coolscan2.c`, `coolscan3.c`), here are the findings about initialization and wake-up sequences.

## Key Findings

### 1. `coolscan.c` (Original Driver)
**Initialization Sequence:**
1. `attach_scanner()` - Opens device using `sanei_scsi_open()` or USB equivalent
2. `coolscan_identify_scanner()` - Sends INQUIRY command
3. `coolscan_initialize_values()` - Initializes values including:
   - `select_MUD()` - Select Measurement Unit Divisor
   - `coolscan_mode_sense()` - Get MUD via MODE_SENSE
   - `get_internal_info()` - Read internal info (datatype 0xe0, 256 bytes)
   - For LS-30: `get_inquiery_LS30()` and `get_feeder_type_LS30()`

**Wait Scanner Logic:**
- `wait_scanner()` - Waits for scanner to be ready
  - Sends TEST_UNIT_READY repeatedly
  - Up to 40 attempts with 0.5 second delays (20 seconds max)
  - Handles `SANE_STATUS_DEVICE_BUSY` by waiting
  - **This is the key wake-up sequence!**

### 2. `coolscan2.c` (USB-focused Driver)
**Initialization Sequence:**
1. `sane_init()` - Calls `sanei_usb_init()`
2. `sane_open()` → `cs2_open()`:
   - Opens USB device with `sanei_usb_open()`
   - Calls `cs2_page_inquiry(s, -1)` to identify scanner
   - No explicit wake-up sequence visible in open
3. `cs2_full_inquiry()` - Called during `sane_open()` after device open
4. **No RESERVE_UNIT/RELEASE_UNIT cycle visible in initialization**

**Command Structure:**
- Uses `cs2_issue_cmd()` for all commands
- Uses `cs2_phase_check()` before reading status
- `cs2_scanner_ready()` - Checks scanner status but doesn't show retry logic

### 3. `coolscan3.c` (Latest Driver)
**Initialization Sequence:**
1. `sane_init()` - Initializes backend
2. `sane_open()` → `cs3_open()`:
   - Opens device (SCSI or USB) using `sanei_scsi_open()` or `sanei_usb_open()`
   - Calls `cs3_page_inquiry(s, -1)` to identify scanner
   - **No explicit wake-up sequence visible**

**Command Structure:**
- Uses `cs3_issue_cmd()` for all commands
- Uses phase checking similar to coolscan2

## Critical Missing Elements

### 1. **WAIT_SCANNER Sequence (from coolscan.c)**
The original driver has a crucial `wait_scanner()` function that:
- Sends TEST_UNIT_READY repeatedly
- Waits up to 40 attempts (20 seconds)
- Handles DEVICE_BUSY status by retrying
- **This is likely the wake-up sequence we're missing!**

```c
static int
wait_scanner (Coolscan_t * s)
{
  int ret = -1;
  int cnt = 0;
  DBG (10, "wait_scanner: Testing if scanner is ready\n");

  while (ret != 0)
    {
      ret = do_scsi_cmd (s->sfd, test_unit_ready.cmd,
			 test_unit_ready.size, 0, 0);

      if (ret == SANE_STATUS_DEVICE_BUSY)
	{
	  usleep (500000);	/* wait 0.5 seconds */
	  if (cnt++ > 40)
	    {			/* 20 sec. max (prescan takes up to 15 sec. */
	      DBG (1, "wait_scanner: scanner does NOT get ready\n");
	      return -1;
	    }
	}
      else if (ret == SANE_STATUS_GOOD)
	{
	  DBG (10, "wait_scanner: scanner is ready\n");
	  return ret;
	}
      else
	{
	  DBG (1, "wait_scanner: test unit ready failed (%s)\n",
	       sane_strstatus (ret));
	}
```

### 2. **Initialization Order**
The original driver (`coolscan.c`) shows:
1. Open device
2. Identify scanner (INQUIRY)
3. **Wait for scanner ready** (wait_scanner)
4. Initialize values:
   - Reserve unit (implicitly, via get_internal_info)
   - Mode sense (MUD)
   - Get internal info
   - Release unit

### 3. **USB-Specific Handling**
- `coolscan2.c` and `coolscan3.c` use USB-specific functions:
  - `sanei_usb_open()` - Opens USB device
  - `sanei_usb_write_bulk()` - Writes to USB bulk endpoint
  - `sanei_usb_read_bulk()` - Reads from USB bulk endpoint
- They handle phase checking differently than SCSI

## Recommendations

### 1. **Implement wait_scanner-like Function**
We should implement a function that:
- Sends TEST_UNIT_READY repeatedly
- Handles timeout errors (not just DEVICE_BUSY)
- Waits up to 20-30 seconds
- Uses 0.5 second delays between retries
- **Doesn't give up on timeouts - keeps retrying**

### 2. **Add Pre-Command Wait**
Before sending any command after initialization:
- Wait for scanner ready with retry logic
- Don't immediately fail on timeout
- Keep retrying with delays

### 3. **USB Interface Handling**
- The USB drivers don't show a specific wake-up sequence
- But they do call `cs2_page_inquiry()` / `cs3_page_inquiry()` immediately after opening
- This INQUIRY command might serve as a wake-up

### 4. **Initialization Sequence**
Suggested sequence:
1. Open USB device (done ✓)
2. Claim interface (done ✓)
3. **Send INQUIRY** (might wake up device)
4. **Wait for scanner ready** (TEST_UNIT_READY with retries)
5. Reserve unit
6. Mode sense
7. Get internal info
8. Release unit

## Conclusion

**The key missing piece is the `wait_scanner()` functionality:**
- Keep sending TEST_UNIT_READY
- Don't give up on timeouts
- Retry with delays (0.5 seconds)
- Wait up to 20-30 seconds total
- Handle the scanner being in a "becoming ready" state

This is likely why we're seeing timeouts - the scanner might be in a deep sleep or processing state, and we're not giving it enough time or retries to wake up.






