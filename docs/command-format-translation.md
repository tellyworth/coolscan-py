# Command Format Translation Layer Discovery

## The Critical Question

**Why does SANE show standard SCSI command format, but the USB capture shows a different 6-byte format?**

This was the key detail causing our communication problems - we were using standard SCSI format, but the scanner expects a USB-specific format.

## The Answer: SANE's USB Translation Layer

### What We Discovered

1. **SANE Backend Code** shows standard SCSI 6-byte CDB format:
   ```c
   static unsigned char inquiryC[] = {INQUIRY, 0x00, 0x00, 0x00, 0x1f, 0x00};
   // Standard SCSI: [Cmd] [LUN/EVPD] [Page] [Reserved] [AllocLen] [Control]
   ```

2. **USB Capture** shows a different 6-byte format:
   ```
   12 00 00 00 24 80
   // USB-specific: [Cmd] [Page] [Param2] [Param3] [AllocLen] [Control=0x80]
   ```

3. **Key Difference**: The control byte is `0x80` in USB capture, `0x00` in standard SCSI.

### The Missing Translation Layer

**SANE's USB Infrastructure (`sanei_usb_*`) performs translation:**

When SANE uses `sanei_usb_open()` and `sanei_usb_write_bulk()`, there's a translation layer that:
- Takes standard SCSI CDB format from the backend
- Converts it to the USB-specific format the scanner expects
- Handles the control byte (0x80) and parameter layout

**We don't have this layer in PyUSB** - we send raw USB bulk transfers directly.

### Why This Matters

1. **SANE abstracts the USB protocol** - Backend code shows standard SCSI, but the USB layer translates it
2. **PyUSB requires the actual USB format** - We must send commands in the format the scanner expects
3. **This explains the mismatch** - SANE documentation shows SCSI format, but actual USB traffic shows different format

### Standard SCSI vs USB-Specific Format

#### Standard SCSI 6-byte CDB (What SANE shows):
```
Byte 0: Command code
Byte 1: LUN/EVPD/Page code (varies by command)
Byte 2: Reserved/Page code
Byte 3: Reserved
Byte 4: Allocation length
Byte 5: Control (usually 0x00)
```

**Example - INQUIRY:**
```
12 00 00 00 1f 00
│  │  │  │  │  └─ Control (0x00)
│  │  │  │  └──── Allocation length (0x1f = 31, but response is 36)
│  │  │  └─────── Reserved
│  │  └────────── Page code (0x00 = standard inquiry)
│  └───────────── EVPD (0x00 = no vital product data)
└──────────────── Command (0x12 = INQUIRY)
```

#### USB-Specific Format (What scanner actually expects):
```
Byte 0: Command code
Byte 1: Page/Subcommand code
Byte 2: Parameter 2
Byte 3: Parameter 3
Byte 4: Allocation length
Byte 5: Control byte (0x80 for most commands)
```

**Example - INQUIRY:**
```
12 00 00 00 24 80
│  │  │  │  │  └─ Control (0x80) ← KEY DIFFERENCE
│  │  │  │  └──── Allocation length (0x24 = 36 bytes)
│  │  │  └─────── Parameter 3 (0x00)
│  │  └────────── Parameter 2 (0x00)
│  └───────────── Page code (0x00 = standard inquiry)
└──────────────── Command (0x12 = INQUIRY)
```

### Is This USB Mass Storage Protocol?

**No.** Standard USB Mass Storage uses:
- **CBW (Command Block Wrapper)**: 31 bytes wrapping the SCSI command
- **CSW (Command Status Wrapper)**: 13 bytes for status

The scanner uses **raw bulk transfers** with a **vendor-specific command format**, not standard USB Mass Storage.

### What This Means for Our Implementation

1. **We must use the USB-specific format** - Not standard SCSI
2. **Control byte is 0x80** - Not 0x00 (except for simple commands like TEST_UNIT_READY)
3. **Parameter layout is different** - Page codes and parameters are in different positions
4. **No translation layer in PyUSB** - We must build commands in the correct format ourselves

### Why SANE Doesn't Show This

SANE's architecture:
```
Backend Code (coolscan.c)
    ↓ (uses standard SCSI CDB)
SANE USB Infrastructure (sanei_usb_*)
    ↓ (TRANSLATES to USB format)
USB Device
```

The translation happens in SANE's USB layer, which is:
- Part of the SANE library, not the backend
- Not visible in backend source code
- Handles protocol-specific details

### Conclusion

**Yes, we missed the translation layer!** SANE's `sanei_usb_*` functions perform the translation from standard SCSI CDB format to the USB-specific format the scanner expects. This is why:

1. SANE backend code shows standard SCSI format
2. USB captures show a different format
3. Our initial implementation (using standard SCSI) failed
4. Our current implementation (using USB-specific format from capture) works

**The USB capture was essential** because it showed us what the scanner actually expects, bypassing SANE's abstraction layer.
