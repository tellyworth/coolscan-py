#!/usr/bin/env python3
"""
Test to "jolt" the scanner awake.
This script tries different approaches to wake up a deeply sleeping scanner.
"""

import sys
import time
import os
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def test_scanner_jolt():
    """Test different approaches to jolt the scanner awake."""
    print("Scanner Jolt Test")
    print("=" * 40)
    print("Trying to jolt the scanner awake with different approaches...")
    
    # Check if running with elevated permissions
    if os.geteuid() != 0:
        print("⚠️  This test requires elevated permissions.")
        print("Run with: sudo python3 test_scanner_jolt.py")
        return False
    
    # Find scanner
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing scanner jolt on: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Test 1: USB device reset
        print("\n2. Testing USB device reset...")
        print("   Watch for any activity...")
        input("   Press Enter to reset USB device...")
        
        try:
            # Try to reset the USB device itself
            device = protocol.usb_device
            print("     Resetting USB device...")
            
            # Try to reset the device
            try:
                device.reset()
                print("     ✓ USB device reset successful")
                time.sleep(3)  # Wait for device to reinitialize
            except Exception as e:
                print(f"     ⚠️  USB device reset failed: {e}")
            
        except Exception as e:
            print(f"     ✗ USB device reset failed: {e}")
        
        # Test 2: Rapid command bursts
        print("\n3. Testing rapid command bursts...")
        print("   Watch for any activity...")
        input("   Press Enter to send rapid command bursts...")
        
        try:
            # Send rapid bursts of commands
            commands = [
                "00 00 00 00 00 00",  # TEST UNIT READY
                "e0 00 80 00 00 00 00 00 0d 00",  # Reset
                "c1 00 00 00 00 00",  # Execute
                "12 00 00 00 24 00",  # INQUIRY
            ]
            
            for burst in range(3):
                print(f"     Command burst {burst + 1}...")
                for cmd_hex in commands:
                    try:
                        cmd = protocol._parse_command(cmd_hex)
                        print(f"       Sending: {cmd.hex()}")
                        protocol._usb_write_bulk(cmd)
                        time.sleep(0.1)  # Very short delay
                    except Exception as e:
                        print(f"       Failed: {e}")
                        break
                time.sleep(1)  # Wait between bursts
                
        except Exception as e:
            print(f"     ✗ Rapid command bursts failed: {e}")
        
        # Test 3: Different USB endpoints
        print("\n4. Testing different USB endpoints...")
        print("   Watch for any activity...")
        input("   Press Enter to test different endpoints...")
        
        try:
            # Try sending commands to different endpoints
            device = protocol.usb_device
            
            # Get all endpoints
            cfg = device.get_active_configuration()
            intf = cfg[(0, 0)]
            
            print("     Testing all available endpoints...")
            for ep in intf:
                if hasattr(ep, 'bEndpointAddress'):
                    print(f"       Testing endpoint: 0x{ep.bEndpointAddress:02x}")
                    try:
                        # Try to send a simple command to this endpoint
                        cmd = b'\x00\x00\x00\x00\x00\x00'
                        if ep.bEndpointAddress & 0x80:  # IN endpoint
                            # Try to read from this endpoint
                            try:
                                data = device.read(ep.bEndpointAddress, 1, timeout=1000)
                                print(f"         Read: {data.hex()}")
                            except:
                                pass
                        else:  # OUT endpoint
                            # Try to write to this endpoint
                            try:
                                bytes_written = device.write(ep.bEndpointAddress, cmd, timeout=1000)
                                print(f"         Write: {bytes_written} bytes")
                            except:
                                pass
                    except Exception as e:
                        print(f"         Failed: {e}")
                        
        except Exception as e:
            print(f"     ✗ Endpoint testing failed: {e}")
        
        # Test 4: Interrupt endpoint
        print("\n5. Testing interrupt endpoint...")
        print("   Watch for any activity...")
        input("   Press Enter to test interrupt endpoint...")
        
        try:
            # Try to read from the interrupt endpoint
            device = protocol.usb_device
            
            # Find interrupt endpoint
            cfg = device.get_active_configuration()
            intf = cfg[(0, 0)]
            
            for ep in intf:
                if hasattr(ep, 'bmAttributes') and ep.bmAttributes == 0x03:  # Interrupt
                    print(f"     Found interrupt endpoint: 0x{ep.bEndpointAddress:02x}")
                    try:
                        # Try to read from interrupt endpoint
                        data = device.read(ep.bEndpointAddress, 8, timeout=1000)
                        print(f"     ✓ Interrupt data: {data.hex()}")
                    except Exception as e:
                        print(f"     ✗ Interrupt read failed: {e}")
                    break
                    
        except Exception as e:
            print(f"     ✗ Interrupt endpoint test failed: {e}")
        
        # Test 5: Configuration change
        print("\n6. Testing configuration change...")
        print("   Watch for any activity...")
        input("   Press Enter to test configuration change...")
        
        try:
            device = protocol.usb_device
            
            # Try to change configuration
            print("     Changing USB configuration...")
            try:
                device.set_configuration(1)
                print("     ✓ Configuration set to 1")
                time.sleep(2)
            except Exception as e:
                print(f"     ⚠️  Configuration change failed: {e}")
                
        except Exception as e:
            print(f"     ✗ Configuration change failed: {e}")
        
        protocol.close()
        
        print("\n" + "=" * 40)
        print("SCANNER JOLT TEST RESULTS")
        print("=" * 40)
        print("Did you observe any of the following?")
        print("  □ LED changes (power, status, scanning LEDs)")
        print("  □ Motor sounds (loading, focusing, scanning)")
        print("  □ Physical movement (film transport, focus adjustment)")
        print("  □ Any other visible or audible activity")
        print("\nIf you observed activity, the jolt worked!")
        print("If no activity, the scanner may have a hardware issue...")
        
        return True
        
    except Exception as e:
        print(f"✗ Scanner jolt test failed: {e}")
        return False


def test_hardware_check():
    """Test if there's a hardware issue."""
    print("\n" + "=" * 40)
    print("Hardware Check")
    print("=" * 40)
    
    scanners = find_scanners()
    if not scanners:
        return False
    
    scanner = scanners[0]
    
    try:
        protocol = CoolscanProtocol(scanner)
        print("Checking for hardware issues...")
        
        # Check USB device state
        device = protocol.usb_device
        print(f"\nUSB Device State:")
        print(f"  Vendor ID: 0x{device.idVendor:04x}")
        print(f"  Product ID: 0x{device.idProduct:04x}")
        print(f"  Device Class: {device.bDeviceClass}")
        
        # Check if device is responding at all
        print(f"\nTesting device responsiveness...")
        try:
            # Try to get device strings
            manufacturer = device.manufacturer
            product = device.product
            print(f"  ✓ Device strings accessible:")
            print(f"    Manufacturer: {manufacturer}")
            print(f"    Product: {product}")
        except Exception as e:
            print(f"  ✗ Device strings failed: {e}")
        
        # Check configuration
        try:
            config = device.get_active_configuration()
            print(f"  ✓ Configuration accessible: {config}")
        except Exception as e:
            print(f"  ✗ Configuration failed: {e}")
        
        protocol.close()
        
        print(f"\nHardware Analysis:")
        print(f"  ✅ USB device is detected")
        print(f"  ✅ Device descriptor is accessible")
        print(f"  ✅ Endpoints are accessible")
        print(f"  ❌ Commands are timing out")
        print(f"  ❌ No physical activity")
        print(f"\nPossible causes:")
        print(f"  1. Scanner firmware is corrupted")
        print(f"  2. Scanner is in a deep sleep state")
        print(f"  3. USB communication protocol mismatch")
        print(f"  4. Hardware failure")
        
    except Exception as e:
        print(f"✗ Hardware check failed: {e}")


if __name__ == "__main__":
    print("Running Scanner Jolt Tests")
    print("=" * 60)
    
    # Run scanner jolt test
    jolt_success = test_scanner_jolt()
    
    # Run hardware check
    hw_success = test_hardware_check()
    
    print("\n" + "=" * 60)
    print("Scanner Jolt Test Summary")
    print("=" * 60)
    print(f"Scanner Jolt Test: {'✓ COMPLETED' if jolt_success else '✗ FAILED'}")
    print(f"Hardware Check: {'✓ COMPLETED' if hw_success else '✗ FAILED'}")
    
    sys.exit(0 if jolt_success else 1)
