# Coolscan Tool

A Python tool for communicating with Nikon Coolscan film scanners via USB and SCSI/Firewire interfaces, based on the SANE backend implementation.

## Overview

This tool provides a Python interface to Nikon Coolscan film scanners, supporting both USB and SCSI/Firewire connections. It's designed to be a foundation for scanner control, image acquisition, and device management. The implementation is based on the working SANE backend code, ensuring compatibility and reliability.

## Supported Scanners

### USB Models
- **LS-40 ED** (0x04b0:0x4000) - ✅ Detected and tested
- **LS-50 ED** (0x04b0:0x4001) - 🔄 Supported but not tested
- **LS-5000 ED** (0x04b0:0x4002) - 🔄 Supported but not tested

### SCSI/Firewire Models
- **LS-30** (Coolscan III)
- **LS-2000**
- **LS-4000 ED**
- **LS-8000 ED**

## Current Status

### ✅ Working Features
- Scanner detection (USB and SCSI)
- **USB communication working** - Bidirectional communication established! 🎉
- **6-byte command format** - Correct protocol format from USB capture analysis
- **Phase checking pattern** - Proper command/phase/status sequence
- **Status parsing** - READY, NO_DOCS, ERROR status codes working
- **Endpoint discovery** - Automatic endpoint detection from configuration descriptor
- **macOS compatibility** - Works without sudo, handles libusb quirks
- Device descriptor reading
- Enhanced SANE-based initialization sequence
- Complete command protocol implementation
- Window Descriptor Block (WDB) support
- Enhanced status parsing and error handling
- Unit reservation cycle
- Mode sense for MUD (Measurement Unit Divisor)
- Internal info read with datatype 0xe0
- Object position commands
- LUT sending with datatype 0xc0
- Proper timing (8-second prescan delay)
- Comprehensive sense key parsing
- Enhanced scan sequences

### 🔄 In Progress
- Full initialization sequence implementation
- INQUIRY command with page codes
- Full image acquisition
- Advanced scanner control features

### 📋 Planned Features
- SCSI/Firewire protocol implementation
- Batch processing capabilities
- Advanced image processing

## Recent Breakthrough

**Communication Barrier Solved!** See `docs/communication-breakthrough.md` for details.

The scanner now responds correctly to commands. Key fixes:
- 6-byte command format (not standard SCSI)
- Mandatory phase checking after every command
- Proper endpoint discovery from configuration descriptor
- macOS libusb quirk handling

## Recent Major Improvements (SANE Backend Analysis)

### Enhanced Initialization Sequence
The scanner now uses the complete SANE backend initialization sequence:

```python
# New SANE-based initialization
scanner = CoolscanScanner(device)
scanner.connect()  # Includes full SANE sequence

# Manual initialization steps
protocol.initialize_scanner()  # Complete SANE sequence
```

### Unit Reservation Cycle
Proper unit reservation and release cycle as used by SANE:

```python
# Reserve unit before operations
protocol.reserve_unit()

# Perform operations
protocol.set_window_wdb(wdb)
protocol.start_scan()

# Release unit after operations
protocol.release_unit()
```

### Enhanced Command Protocol
Complete implementation of all SANE backend commands:

```python
# Mode sense for MUD
mud = protocol.mode_sense()

# Internal info read
info = protocol.get_internal_info()

# Object position
protocol.object_position()

# LUT sending
protocol.send_lut(lut_data)

# Enhanced scan sequence
protocol.perform_scan_sequence(params)
```

### Proper Timing Implementation
SANE backend timing for reliable operation:

```python
# 8-second prescan delay
protocol.prescan()  # Includes 8-second sleep

# Enhanced retry logic
protocol.scanner_ready(timeout=30)  # Up to 40 retries with 0.5s delays
```

### Comprehensive Error Handling
SANE backend error handling with sense key parsing:

```python
# Enhanced status parsing
status, details = protocol._parse_status(status_data)
# Handles all sense keys: 0x00-0x0b with ASC/ASCQ codes
```

### Enhanced Data Types
Complete data type implementation from SANE backend:

```python
from coolscan.protocol import DataType

# Proper datatype codes
protocol.read_scan_data(length, DataType.IMAGE_DATA)
protocol.read_scan_data(length, DataType.DEVICE_INTERNAL_INFO)
```

### Enhanced WDB Support
Complete WDB implementation with model-specific handling:

```python
from coolscan.protocol import WindowDescriptorBlock

# Create scan configuration
wdb = WindowDescriptorBlock()
wdb.x_resolution = 2700  # DPI
wdb.y_resolution = 2700
wdb.width = 2592        # pixels
wdb.length = 3888       # pixels
wdb.composition = 0x05  # RGB full
wdb.bits_per_pixel = 0x08  # 8-bit
wdb.transfer_mode = 0x02  # Line sequence
wdb.gamma_selection = 0x03  # Monitor gamma

# Set scan parameters
protocol.set_window_wdb(wdb)
```

## Installation

### Prerequisites
- Python 3.8+
- macOS (tested on macOS 14.6.0)
- USB access permissions

### Setup
```bash
# Clone the repository
git clone <repository-url>
cd coolscan_tool

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic Scanner Operations

```python
from coolscan.scanner import CoolscanScanner
from coolscan.device import find_scanners

# Find scanners
scanners = find_scanners()
if scanners:
    scanner = scanners[0]

    # Connect with enhanced SANE sequence
    with CoolscanScanner(scanner) as coolscan:
        # Get device info
        info = coolscan.get_device_info()
        print(f"Scanner: {info}")

        # Perform prescan
        coolscan.prescan()

        # Perform auto focus
        coolscan.auto_focus()

        # Scan preview
        coolscan.scan_preview("preview.png", resolution=270)

        # Scan full resolution
        coolscan.scan_full("full_scan.png", resolution=2700)
```

### Advanced Protocol Operations

```python
from coolscan.protocol import (
    CoolscanProtocol, WindowDescriptorBlock,
    ScanParameters, DataType
)

# Direct protocol access
protocol = CoolscanProtocol(device)

# Initialize scanner
protocol.initialize_scanner()

# Get scanner capabilities
info = protocol.get_internal_info()
print(f"Max resolution: {info.max_resolution}")
print(f"X max pixels: {info.x_max_pixels}")
print(f"Y max pixels: {info.y_max_pixels}")

# Perform complete scan sequence
params = ScanParameters(
    resolution=2700,
    preview=False,
    negative=False,
    infrared=False
)

protocol.perform_scan_sequence(params)
```

### Enhanced Error Handling

```python
# Comprehensive error handling
try:
    with CoolscanScanner(scanner) as coolscan:
        # Operations with automatic error recovery
        coolscan.prescan()
        coolscan.scan_full("test.png")
except Exception as e:
    print(f"Scanner error: {e}")
    # Enhanced error details available
```

## Testing

### Run Enhanced Tests
```bash
# Test enhanced SANE-based implementation
python test_sane_enhanced.py

# Test practical workflow
python test_practical_enhanced.py

# Compare old vs new implementation
python test_sane_comparison.py
```

### Test Specific Features
```bash
# Test USB communication
python test_communication_verification.py

# Test with film loaded
python test_with_film.py

# Test scanner activity
python test_scanner_activity.py
```

## Troubleshooting

### USB Permission Issues
On macOS, you may need elevated permissions for USB access:

```bash
# Run with sudo for USB access
sudo python test_sane_enhanced.py
```

### Scanner Not Responding
The enhanced implementation includes comprehensive error handling:

1. Check scanner power and connections
2. Verify USB permissions
3. Try the enhanced initialization sequence
4. Check for firmware issues

### Communication Timeouts
The enhanced implementation includes retry logic and proper timing:

- Up to 40 retry attempts with 0.5-second delays
- 8-second prescan timing
- Comprehensive phase checking

## Development

### Architecture
- `coolscan/device.py` - Scanner detection and device management
- `coolscan/protocol.py` - Enhanced SANE-based communication protocol
- `coolscan/scanner.py` - High-level scanner operations
- `examples/` - Usage examples and demonstrations

### Key Improvements
1. **SANE Backend Analysis** - Based on working SANE implementation
2. **Complete Command Protocol** - All missing commands implemented
3. **Enhanced Error Handling** - Comprehensive sense key parsing
4. **Proper Timing** - SANE backend timing for reliability
5. **Unit Reservation** - Proper resource management
6. **Data Type Support** - Complete datatype implementation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Based on the SANE backend implementation for Coolscan scanners
- Inspired by the working SANE driver code
- Thanks to the SANE project for the reference implementation
