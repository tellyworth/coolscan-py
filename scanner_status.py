#!/usr/bin/env python3
"""
Scanner Status Script

A comprehensive status script that provides useful information about the scanner,
including diagnostic information when the scanner is not responding to commands.
"""

import sys
import time
import os

# Add the coolscan module to the path
sys.path.insert(0, '.')

from coolscan.scanner import CoolscanScanner
from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def check_usb_permissions():
    """Check USB permissions and provide diagnostic info."""
    print("🔧 USB Permissions Check:")
    
    # Check if we can access USB devices
    try:
        import usb.core
        devices = list(usb.core.find(find_all=True))
        print(f"  ✅ USB access available - found {len(devices)} devices")
        
        # Look for our scanner specifically
        scanner_device = usb.core.find(idVendor=0x04b0, idProduct=0x4000)
        if scanner_device:
            print("  ✅ Scanner device found in USB device list")
            
            # Try to access device descriptor
            try:
                descriptor = scanner_device.get_device_descriptor()
                print("  ✅ Can access device descriptor")
            except Exception as e:
                print(f"  ❌ Cannot access device descriptor: {e}")
                print("  💡 Try running with sudo for elevated permissions")
        else:
            print("  ❌ Scanner device not found in USB device list")
            
    except ImportError:
        print("  ❌ USB library not available")
    except Exception as e:
        print(f"  ❌ USB access error: {e}")


def check_system_info():
    """Check system information."""
    print("�� System Information:")
    print(f"  OS: {os.uname().sysname} {os.uname().release}")
    print(f"  Architecture: {os.uname().machine}")
    print(f"  Python: {sys.version}")
    
    # Check for common USB device files
    usb_devices = ['/dev/usb', '/dev/bus/usb']
    for device in usb_devices:
        if os.path.exists(device):
            print(f"  ✅ USB device path exists: {device}")
        else:
            print(f"  ❌ USB device path missing: {device}")


def comprehensive_status_check():
    """Perform comprehensive status check."""
    print("🔍 Comprehensive Scanner Status Check")
    print("=" * 50)
    
    # System and permission checks
    check_system_info()
    check_usb_permissions()
    
    # Find scanners
    print(f"\n🔍 Scanner Detection:")
    scanners = find_scanners()
    if not scanners:
        print("  ❌ No scanners found")
        print("\n💡 Troubleshooting suggestions:")
        print("  1. Check if scanner is powered on")
        print("  2. Check USB cable connection")
        print("  3. Try running with sudo: sudo python scanner_status.py")
        print("  4. Check if scanner appears in system USB device list")
        return False
    
    scanner = scanners[0]
    print(f"  ✅ Found scanner: {scanner}")
    
    # Basic device info
    print(f"\n📋 Scanner Information:")
    print(f"  Vendor: {scanner.vendor}")
    print(f"  Model: {scanner.model}")
    print(f"  Revision: {scanner.revision}")
    print(f"  Interface: {scanner.interface.value}")
    print(f"  Device Path: {scanner.device_path}")
    print(f"  Vendor ID: 0x{scanner.vendor_id:04x}")
    print(f"  Product ID: 0x{scanner.product_id:04x}")
    
    # Communication status
    print(f"\n🔌 Communication Status:")
    
    # Try to create protocol object
    try:
        protocol = CoolscanProtocol(scanner)
        print("  ✅ Protocol object created successfully")
        
        # Test basic communication with timeout handling
        communication_tests = [
            ("Inquiry", lambda: protocol.inquiry()),
            ("Test Unit Ready", lambda: protocol.test_unit_ready()),
            ("Scanner Ready", lambda: protocol.scanner_ready(timeout=5)),
            ("Get Window", lambda: protocol.get_window()),
            ("Mode Sense", lambda: protocol.mode_sense()),
        ]
        
        for test_name, test_func in communication_tests:
            print(f"  🔍 Testing {test_name}...")
            try:
                result = test_func()
                if result:
                    print(f"    ✅ {test_name} successful")
                    if test_name == "Get Window" and result:
                        wdb = result
                        print(f"      Resolution: {wdb.x_resolution}x{wdb.y_resolution}")
                        print(f"      Window: {wdb.width}x{wdb.length}")
                        print(f"      Negative: {'Yes' if wdb.negative_dropout else 'No'}")
                    elif test_name == "Mode Sense" and result:
                        print(f"      MUD: {result}")
                else:
                    print(f"    ❌ {test_name} failed")
            except Exception as e:
                print(f"    ❌ {test_name} error: {e}")
        
        # Try to get detailed status
        print(f"  🔍 Getting detailed status...")
        try:
            # Try to reserve unit for detailed checks
            if protocol.reserve_unit():
                print("    ✅ Unit reserved for detailed checks")
                try:
                    # Try to get internal info
                    try:
                        info = protocol.get_internal_info()
                        if info:
                            print("    ✅ Internal info retrieved")
                            print(f"      Auto Feeder: {'Yes' if info.auto_feeder else 'No'}")
                            print(f"      Analog Gamma: {'Yes' if info.analog_gamma else 'No'}")
                            print(f"      Max Resolution: {info.max_resolution}")
                            print(f"      X Max Pixels: {info.x_max_pixels}")
                            print(f"      Y Max Pixels: {info.y_max_pixels}")
                            print(f"      Current Y: {info.current_y}")
                            print(f"      Current Focus: {info.current_focus}")
                            
                            # Check for device errors
                            if any(error != 0 for error in info.device_errors):
                                print("      ⚠️  Device errors detected:")
                                for i, error in enumerate(info.device_errors):
                                    if error != 0:
                                        print(f"        Error {i}: 0x{error:02x}")
                            else:
                                print("      ✅ No device errors")
                        else:
                            print("    ❌ Internal info not available")
                    except Exception as e:
                        print(f"    ❌ Internal info error: {e}")
                    
                    # Try to check film status
                    print("    🔍 Checking film status...")
                    try:
                        ready = protocol.test_unit_ready()
                        if ready:
                            print("      ✅ Scanner ready - film may be loaded")
                        else:
                            print("      ❌ Scanner not ready - no film or error")
                    except Exception as e:
                        print(f"      ❌ Film status check error: {e}")
                        
                finally:
                    protocol.release_unit()
                    print("    ✅ Unit released")
            else:
                print("    ❌ Could not reserve unit for detailed checks")
        except Exception as e:
            print(f"    ❌ Detailed status error: {e}")
        
        protocol.close()
        print("  ✅ Protocol connection closed")
        
    except Exception as e:
        print(f"  ❌ Protocol creation failed: {e}")
        print("\n💡 Troubleshooting suggestions:")
        print("  1. Check if scanner is powered on and connected")
        print("  2. Try running with sudo: sudo python scanner_status.py")
        print("  3. Check USB cable and connection")
        print("  4. Try unplugging and reconnecting the scanner")
        print("  5. Check if scanner appears in system USB device list")
    
    # Summary
    print(f"\n📊 Status Summary:")
    print(f"  Scanner Detected: ✅ YES")
    print(f"  Scanner Model: {scanner.model}")
    print(f"  Communication: {'✅ Working' if 'protocol' in locals() else '❌ Failed'}")
    
    if 'protocol' in locals():
        print(f"  Film Status: {'✅ Ready' if 'ready' in locals() and ready else '❓ Unknown'}")
        print(f"  Auto Feeder: {'✅ Available' if 'info' in locals() and info and info.auto_feeder else '❌ Not Available'}")
    
    print(f"\n✅ Status check completed!")
    return True


def main():
    """Main function."""
    success = comprehensive_status_check()
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
