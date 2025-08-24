# Coolscan Tool

A Python tool for communicating with Nikon Coolscan film scanners via USB and SCSI/Firewire interfaces.

## Overview

This tool provides a Python interface to Nikon Coolscan film scanners, supporting both USB and SCSI/Firewire connections. It's designed to be a foundation for scanner control, image acquisition, and device management.

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
- USB connection establishment
- Device descriptor reading
- Basic wake-up sequence (reset + execute)
- Command parsing and sending

### 🔄 In Progress
- Full USB protocol implementation
- Status handling and error recovery
- Image acquisition
- Scanner control features

### 📋 Planned Features
- SCSI/Firewire protocol implementation
- Image scanning and data transfer
- Scanner settings management
- Batch processing capabilities

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

# Install dependencies
pip install -r requirements.txt

# Run tests
python3.11 test_detection.py
```

## Quick Start

### Basic Scanner Detection
```python
from coolscan.device import find_scanners

# Find all available scanners
scanners = find_scanners()
for scanner in scanners:
    print(f"Found: {scanner}")
```

### Basic Communication
```python
from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol

# Find and connect to scanner
scanners = find_scanners()
if scanners:
    scanner = scanners[0]
    protocol = CoolscanProtocol(scanner)
    
    # Wake up scanner
    protocol.wake_up()
    
    # Get scanner info
    info = protocol.get_scanner_info()
    print(f"Scanner: {info}")
```

## Project Structure

```
coolscan_tool/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
├── coolscan/                 # Main package
│   ├── __init__.py
│   ├── device.py            # Scanner detection
│   ├── protocol.py          # Communication protocol
│   └── types.py             # Type definitions
├── docs/                    # Documentation
│   ├── protocol.md          # Protocol specification
│   ├── commands.md          # Command reference
│   └── troubleshooting.md   # Troubleshooting guide
├── tests/                   # Test files
│   ├── test_detection.py    # Scanner detection tests
│   ├── test_protocol.py     # Protocol tests
│   └── test_coolscan2.py    # Coolscan2-style tests
└── examples/                # Example scripts
    ├── basic_scan.py        # Basic scanning example
    └── scanner_info.py      # Scanner information example
```

## Usage Examples

### Example 1: Scanner Information
```python
#!/usr/bin/env python3
from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol

def main():
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return
    
    scanner = scanners[0]
    print(f"Connecting to: {scanner}")
    
    protocol = CoolscanProtocol(scanner)
    info = protocol.get_scanner_info()
    print(f"Scanner info: {info}")

if __name__ == "__main__":
    main()
```

### Example 2: Basic Wake-up Test
```python
#!/usr/bin/env python3
from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol

def main():
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return
    
    scanner = scanners[0]
    protocol = CoolscanProtocol(scanner)
    
    # Test wake-up sequence
    if protocol.wake_up():
        print("Scanner woke up successfully!")
    else:
        print("Failed to wake up scanner")

if __name__ == "__main__":
    main()
```

## Development

### Running Tests
```bash
# Run all tests
python3.11 -m pytest tests/

# Run specific test
python3.11 test_detection.py
python3.11 test_coolscan2.py
```

### Adding New Scanner Support
1. Add scanner ID to `device.py`
2. Implement scanner-specific commands in `protocol.py`
3. Add tests in `tests/`
4. Update documentation

## Troubleshooting

### Common Issues

**Scanner not detected:**
- Check USB permissions
- Ensure scanner is powered on
- Try different USB ports

**Communication timeouts:**
- Check scanner power state
- Try the wake-up sequence
- Verify USB cable connection

**Permission errors:**
- On macOS, grant USB access to Terminal/IDE
- Check system preferences > Security & Privacy

### Debug Mode
Enable debug output by setting the environment variable:
```bash
export COOLSCAN_DEBUG=1
python3.11 your_script.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Based on SANE backend code (`coolscan2.c`, `coolscan3.c`)
- Inspired by the SANE project's scanner support
- Thanks to the open source scanner community

## Support

For issues and questions:
1. Check the troubleshooting guide in `docs/troubleshooting.md`
2. Review the protocol documentation in `docs/protocol.md`
3. Open an issue on the project repository

## Roadmap

### Short Term (Next 2-4 weeks)
- [ ] Complete USB protocol implementation
- [ ] Add SCSI/Firewire support
- [ ] Implement basic scanning functionality
- [ ] Add error recovery mechanisms

### Medium Term (1-3 months)
- [ ] Full scanner control interface
- [ ] Image processing capabilities
- [ ] Batch scanning support
- [ ] GUI interface

### Long Term (3-6 months)
- [ ] Advanced image processing
- [ ] Multi-scanner support
- [ ] Integration with image editing software
- [ ] Performance optimizations


