# USB Capture Analysis Guide

## Overview
This document describes how to analyze USB traffic captures from Wireshark/USBPcap to understand the actual command sequences that work with the Nikon Coolscan scanner.

## Capturing USB Traffic

### On Windows (with USBPcap)
1. Install USBPcap: https://desowin.org/usbpcap/
2. Install Wireshark: https://www.wireshark.org/
3. Start USBPcap capture
4. Run your scanner software (e.g., Nikon Scan, VueScan, or SANE)
5. Stop capture and save as `.pcapng`

### Exporting from Wireshark
1. Open the `.pcapng` file in Wireshark
2. Filter for USB traffic: `usb`
3. Filter for your device: `usb.device_address == X` (find your device address)
4. Export packet bytes:
   - Right-click on a packet → Copy → Bytes → Hex Stream
   - Or: File → Export Packet Bytes → Select packets → Save

## Analyzing the Capture

### Using the Analysis Script
```bash
python analyze_usb_capture.py <capture_file>
```

### Manual Analysis
Look for these patterns:

1. **Command Sequences**: OUT packets (host → device)
   - Command codes (first byte)
   - Command parameters
   - Data payloads

2. **Response Sequences**: IN packets (device → host)
   - Status bytes (8 bytes)
   - Data responses
   - Phase information

3. **Timing**: Note delays between commands

## Key Things to Look For

### Initialization Sequence
- What commands are sent first?
- Are there any reset/wake-up commands?
- What is the exact byte sequence?

### Command Format
- Command code (first byte)
- Parameter bytes
- Data length encoding
- Endianness (big-endian vs little-endian)

### Phase Checking
- When is phase checked?
- What phase values are returned?
- How are phases used to determine next step?

### Status Responses
- Status byte values
- Sense keys
- ASC/ASCQ codes
- When does scanner report READY vs BUSY vs NO_DOCS?

## What We Need to Extract

1. **Exact command bytes** for:
   - Initialization/wake-up
   - TEST_UNIT_READY
   - INQUIRY
   - Phase check
   - Any vendor-specific commands

2. **Response patterns**:
   - Status byte sequences
   - Data formats
   - Error responses

3. **Timing**:
   - Delays between commands
   - Timeout values
   - Retry patterns

4. **Sequence order**:
   - What commands come first?
   - What's the initialization flow?
   - When are phase checks performed?
