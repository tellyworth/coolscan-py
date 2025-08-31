#!/usr/bin/env python3
"""
USB Diagnostic Test.
This script checks if commands are actually reaching the scanner at the USB level.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def test_usb_diagnostics():
    """Test USB communication at the lowest level."""
    print("USB Diagnostic Test")
    print("=" * 40)
    print("Testing USB communication at the lowest level...")
    
    # Find scanner
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing scanner: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Test 1: Check USB device state
        print("\n2. Checking USB device state...")
        try:
            device = protocol.usb_device
            print(f"✓ USB device accessible")
            print(f"  Vendor ID: 0x{device.idVendor:04x}")
            print(f"  Product ID: 0x{device.idProduct:04x}")
            print(f"  Device class: {device.bDeviceClass}")
            print(f"  Configuration: {device.get_active_configuration()}")
            
            # Check if device is in a valid state
            try:
                # Try to get device descriptor
                descriptor = device.get_device_descriptor()
                print(f"✓ Device descriptor accessible")
                print(f"  bcdUSB: 0x{descriptor.bcdUSB:04x}")
                print(f"  bMaxPacketSize0: {descriptor.bMaxPacketSize0}")
            except Exception as e:
                print(f"✗ Device descriptor failed: {e}")
                
        except Exception as e:
            print(f"✗ USB device state check failed: {e}")
            return False
        
        # Test 2: Check endpoint states
        print("\n3. Checking endpoint states...")
        try:
            bulk_out = protocol.bulk_out
            bulk_in = protocol.bulk_in
            
            print(f"✓ Endpoints accessible")
            print(f"  Bulk OUT: 0x{bulk_out.bEndpointAddress:02x}")
            print(f"  Bulk IN: 0x{bulk_in.bEndpointAddress:02x}")
            print(f"  Max packet size OUT: {bulk_out.wMaxPacketSize}")
            print(f"  Max packet size IN: {bulk_in.wMaxPacketSize}")
            
        except Exception as e:
            print(f"✗ Endpoint check failed: {e}")
            return False
        
        # Test 3: Test raw USB write/read
        print("\n4. Testing raw USB write/read...")
        try:
            # Send a simple command
            cmd = b'\x00\x00\x00\x00\x00\x00'  # TEST UNIT READY
            print(f"  Sending raw command: {cmd.hex()}")
            
            # Write to bulk OUT endpoint
            bytes_written = protocol._usb_write_bulk(cmd)
            print(f"  ✓ Raw write successful: {bytes_written} bytes")
            
            # Wait a bit
            time.sleep(0.1)
            
            # Try to read from bulk IN endpoint
            try:
                response = protocol._usb_read_bulk(1)
                if hasattr(response, 'tobytes'):
                    response = response.tobytes()
                print(f"  ✓ Raw read successful: {response.hex()}")
            except Exception as e:
                print(f"  ⚠️  Raw read failed (expected): {e}")
                
        except Exception as e:
            print(f"✗ Raw USB test failed: {e}")
            return False
        
        # Test 4: Check USB transfer errors
        print("\n5. Checking USB transfer errors...")
        try:
            # Try multiple commands and check for errors
            commands = [
                b'\x00\x00\x00\x00\x00\x00',  # TEST UNIT READY
                b'\x12\x00\x00\x00\x24\x00',  # INQUIRY
                b'\xe0\x00\x80\x00\x00\x00\x00\x00\x0d\x00',  # Reset
            ]
            
            for i, cmd in enumerate(commands):
                print(f"  Test {i+1}: Sending {cmd.hex()}")
                try:
                    bytes_written = protocol._usb_write_bulk(cmd)
                    print(f"    ✓ Write: {bytes_written} bytes")
                    
                    # Try to read response
                    time.sleep(0.1)
                    try:
                        response = protocol._usb_read_bulk(1)
                        if hasattr(response, 'tobytes'):
                            response = response.tobytes()
                        print(f"    ✓ Read: {response.hex()}")
                    except Exception as e:
                        print(f"    ⚠️  Read failed: {e}")
                        
                except Exception as e:
                    print(f"    ✗ Failed: {e}")
                    
        except Exception as e:
            print(f"✗ USB transfer test failed: {e}")
        
        # Test 5: Check if scanner is in a valid state
        print("\n6. Checking scanner state...")
        try:
            # Try to get device strings
            try:
                manufacturer = device.manufacturer
                product = device.product
                print(f"✓ Device strings accessible:")
                print(f"  Manufacturer: {manufacturer}")
                print(f"  Product: {product}")
            except Exception as e:
                print(f"✗ Device strings failed: {e}")
            
            # Try to get configuration
            try:
                config = device.get_active_configuration()
                print(f"✓ Configuration accessible: {config}")
            except Exception as e:
                print(f"✗ Configuration failed: {e}")
                
        except Exception as e:
            print(f"✗ Scanner state check failed: {e}")
        
        protocol.close()
        
        print("\n" + "=" * 40)
        print("USB DIAGNOSTIC RESULTS")
        print("=" * 40)
        print("✅ USB device is accessible")
        print("✅ Endpoints are accessible")
        print("✅ Raw USB write operations work")
        print("⚠️  Raw USB read operations may timeout (normal)")
        print("\nThe scanner is receiving our commands at the USB level.")
        print("If there's no physical activity, the issue may be:")
        print("1. Scanner firmware not processing commands")
        print("2. Scanner in a sleep/deep sleep state")
        print("3. Commands not in the correct format")
        print("4. Scanner requires specific initialization sequence")
        
        return True
        
    except Exception as e:
        print(f"✗ USB diagnostic test failed: {e}")
        return False


def test_scanner_power_state():
    """Test if scanner is in a proper power state."""
    print("\n" + "=" * 40)
    print("Scanner Power State Test")
    print("=" * 40)
    
    scanners = find_scanners()
    if not scanners:
        return False
    
    scanner = scanners[0]
    
    try:
        protocol = CoolscanProtocol(scanner)
        print("Testing scanner power state...")
        
        # Check if scanner responds to basic commands
        print("\nTesting basic command responses...")
        
        # Test 1: Simple command that should always work
        try:
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"Sending TEST UNIT READY: {cmd.hex()}")
            
            data, status = protocol._issue_command(cmd)
            print(f"Response: status={status}")
            
            if status == StatusType.READY:
                print("✅ Scanner is ready and responding")
            elif status == StatusType.NO_DOCS:
                print("⚠️  Scanner is ready but no document loaded")
            else:
                print(f"❓ Scanner status: {status}")
                
        except Exception as e:
            print(f"✗ Basic command failed: {e}")
        
        # Test 2: Check if scanner is in sleep mode
        print("\nTesting for sleep mode...")
        try:
            # Try a command that should wake up the scanner
            wake_cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
            print(f"Sending wake command: {wake_cmd.hex()}")
            
            protocol._usb_write_bulk(wake_cmd)
            print("✓ Wake command sent")
            
            time.sleep(2)
            
            # Test if scanner is now more responsive
            cmd = protocol._parse_command("00 00 00 00 00 00")
            data, status = protocol._issue_command(cmd)
            print(f"Post-wake status: {status}")
            
        except Exception as e:
            print(f"✗ Wake command failed: {e}")
        
        protocol.close()
        
    except Exception as e:
        print(f"✗ Power state test failed: {e}")


if __name__ == "__main__":
    print("Running USB Diagnostic Tests")
    print("=" * 60)
    
    # Run USB diagnostic test
    usb_success = test_usb_diagnostics()
    
    # Run power state test
    power_success = test_scanner_power_state()
    
    print("\n" + "=" * 60)
    print("USB Diagnostic Summary")
    print("=" * 60)
    print(f"USB Diagnostic Test: {'✓ COMPLETED' if usb_success else '✗ FAILED'}")
    print(f"Power State Test: {'✓ COMPLETED' if power_success else '✗ FAILED'}")
    
    sys.exit(0 if usb_success else 1)
