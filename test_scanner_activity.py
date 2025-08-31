#!/usr/bin/env python3
"""
Test scanner physical activity.
This script sends commands that should trigger visible activity on the scanner.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType, WindowDescriptorBlock


def test_scanner_activity():
    """Test commands that should trigger visible scanner activity."""
    print("Scanner Physical Activity Test")
    print("=" * 40)
    print("Watch the scanner for any LED changes, motor sounds, or movement...")
    
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
        
        # Test 1: Wake-up sequence (should trigger activity)
        print("\n2. Testing wake-up sequence...")
        print("   Watch for any LED changes or sounds...")
        input("   Press Enter to send wake-up commands...")
        
        try:
            # Send reset command (should wake up scanner)
            reset_cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
            print(f"   Sending reset command: {reset_cmd.hex()}")
            protocol._usb_write_bulk(reset_cmd)
            print("   ✓ Reset command sent")
            time.sleep(2)  # Wait for scanner to respond
            
            # Send execute command
            exec_cmd = protocol._parse_command("c1 00 00 00 00 00")
            print(f"   Sending execute command: {exec_cmd.hex()}")
            protocol._usb_write_bulk(exec_cmd)
            print("   ✓ Execute command sent")
            time.sleep(2)  # Wait for scanner to respond
            
        except Exception as e:
            print(f"   ✗ Wake-up sequence failed: {e}")
        
        # Test 2: Load/Eject commands (should trigger motor activity)
        print("\n3. Testing load/eject commands...")
        print("   Watch for motor sounds or movement...")
        input("   Press Enter to send load command...")
        
        try:
            # Send load command (should trigger motor)
            load_cmd = protocol._parse_command("e0 00 d1 00 00 00 00 00 0d 00")
            print(f"   Sending load command: {load_cmd.hex()}")
            protocol._usb_write_bulk(load_cmd)
            print("   ✓ Load command sent")
            time.sleep(3)  # Wait for motor activity
            
        except Exception as e:
            print(f"   ✗ Load command failed: {e}")
        
        # Test 3: Auto-focus command (should trigger focus motor)
        print("\n4. Testing auto-focus command...")
        print("   Watch for focus motor sounds...")
        input("   Press Enter to send auto-focus command...")
        
        try:
            # Send auto-focus command
            focus_cmd = protocol._parse_command("c2 00 00 00 08 00")
            print(f"   Sending auto-focus command: {focus_cmd.hex()}")
            protocol._usb_write_bulk(focus_cmd)
            print("   ✓ Auto-focus command sent")
            time.sleep(3)  # Wait for focus motor activity
            
        except Exception as e:
            print(f"   ✗ Auto-focus command failed: {e}")
        
        # Test 4: Scan command (should trigger scanning activity)
        print("\n5. Testing scan command...")
        print("   Watch for scanning LED or motor activity...")
        input("   Press Enter to send scan command...")
        
        try:
            # Create a basic WDB for scanning
            wdb = WindowDescriptorBlock()
            wdb.x_resolution = 270  # Low resolution for quick test
            wdb.y_resolution = 270
            wdb.width = 100  # Small area
            wdb.length = 100
            wdb.scan_mode = 0x01  # Prescan mode
            
            # Set window parameters
            print("   Setting scan parameters...")
            success = protocol.set_window_wdb(wdb)
            if success:
                print("   ✓ Scan parameters set")
                
                # Send scan command
                scan_cmd = protocol._parse_command("1b 00 00 00 03 00 01 02 03")
                print(f"   Sending scan command: {scan_cmd.hex()}")
                protocol._usb_write_bulk(scan_cmd)
                print("   ✓ Scan command sent")
                time.sleep(5)  # Wait for scanning activity
            else:
                print("   ✗ Failed to set scan parameters")
                
        except Exception as e:
            print(f"   ✗ Scan command failed: {e}")
        
        # Test 5: Object position command (should trigger movement)
        print("\n6. Testing object position command...")
        print("   Watch for any movement or motor sounds...")
        input("   Press Enter to send object position command...")
        
        try:
            # Send object position command
            pos_cmd = protocol._parse_command("31 00 00 00 00 00 00 00 00 00")
            print(f"   Sending object position command: {pos_cmd.hex()}")
            protocol._usb_write_bulk(pos_cmd)
            print("   ✓ Object position command sent")
            time.sleep(2)  # Wait for movement
            
        except Exception as e:
            print(f"   ✗ Object position command failed: {e}")
        
        protocol.close()
        
        print("\n" + "=" * 40)
        print("ACTIVITY TEST RESULTS")
        print("=" * 40)
        print("Did you observe any of the following?")
        print("  □ LED changes (power, status, scanning LEDs)")
        print("  □ Motor sounds (loading, focusing, scanning)")
        print("  □ Physical movement (film transport, focus adjustment)")
        print("  □ Any other visible or audible activity")
        print("\nIf you observed activity, the scanner is responding to commands!")
        print("If no activity, we may need to investigate further...")
        
        return True
        
    except Exception as e:
        print(f"✗ Activity test failed: {e}")
        return False


def test_led_status():
    """Test if we can read LED status from the scanner."""
    print("\n" + "=" * 40)
    print("LED Status Test")
    print("=" * 40)
    
    scanners = find_scanners()
    if not scanners:
        return False
    
    scanner = scanners[0]
    
    try:
        protocol = CoolscanProtocol(scanner)
        print("Testing LED status reading...")
        
        # Try to read device internal info (might contain LED status)
        try:
            # Send READ command for device internal info
            read_cmd = protocol._parse_command("28 00 e0 00 00 00 00 00 00 00")
            print(f"Sending READ command for device info: {read_cmd.hex()}")
            
            data, status = protocol._issue_command(read_cmd, data_in_length=256)
            if status == StatusType.READY and len(data) > 0:
                print(f"✓ Device info read: {len(data)} bytes")
                print(f"  Data: {data[:32].hex()}...")
            else:
                print(f"✗ Device info read failed: status={status}")
                
        except Exception as e:
            print(f"✗ Device info read failed: {e}")
        
        protocol.close()
        
    except Exception as e:
        print(f"✗ LED status test failed: {e}")


if __name__ == "__main__":
    print("Running Scanner Activity Tests")
    print("=" * 60)
    
    # Run activity test
    activity_success = test_scanner_activity()
    
    # Run LED status test
    led_success = test_led_status()
    
    print("\n" + "=" * 60)
    print("Activity Test Summary")
    print("=" * 60)
    print(f"Activity Test: {'✓ COMPLETED' if activity_success else '✗ FAILED'}")
    print(f"LED Status Test: {'✓ COMPLETED' if led_success else '✗ FAILED'}")
    
    sys.exit(0 if activity_success else 1)
