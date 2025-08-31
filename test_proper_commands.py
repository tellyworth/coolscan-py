#!/usr/bin/env python3
"""
Test proper command sequences from SANE backend.
This script uses the exact command sequences that should work.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def test_proper_commands():
    """Test proper command sequences from SANE backend."""
    print("Proper Command Sequences Test")
    print("=" * 40)
    print("Watch the scanner for any activity...")
    
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
        
        # Test 1: Proper wake-up sequence from SANE backend
        print("\n2. Testing proper wake-up sequence...")
        print("   Watch for any LED changes...")
        input("   Press Enter to send proper wake-up sequence...")
        
        try:
            # Step 1: Reset command (from SANE backend)
            reset_cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
            print(f"   Step 1: Sending reset command: {reset_cmd.hex()}")
            protocol._usb_write_bulk(reset_cmd)
            print("   ✓ Reset command sent")
            time.sleep(1)
            
            # Step 2: Execute command (from SANE backend)
            exec_cmd = protocol._parse_command("c1 00 00 00 00 00")
            print(f"   Step 2: Sending execute command: {exec_cmd.hex()}")
            protocol._usb_write_bulk(exec_cmd)
            print("   ✓ Execute command sent")
            time.sleep(2)
            
            # Step 3: Test unit ready
            print(f"   Step 3: Testing unit ready...")
            ready = protocol.test_unit_ready()
            print(f"   ✓ Unit ready: {ready}")
            
        except Exception as e:
            print(f"   ✗ Wake-up sequence failed: {e}")
        
        # Test 2: Proper inquiry sequence
        print("\n3. Testing proper inquiry sequence...")
        print("   Watch for any activity...")
        input("   Press Enter to send inquiry...")
        
        try:
            # Use the proper inquiry command
            inquiry_data = protocol.inquiry()
            print(f"   ✓ Inquiry successful: {len(inquiry_data)} bytes")
            if len(inquiry_data) >= 36:
                vendor = inquiry_data[8:16].decode('ascii', errors='ignore').strip()
                product = inquiry_data[16:32].decode('ascii', errors='ignore').strip()
                print(f"     Vendor: {vendor}")
                print(f"     Product: {product}")
                
        except Exception as e:
            print(f"   ✗ Inquiry failed: {e}")
        
        # Test 3: Reserve unit (should trigger activity)
        print("\n4. Testing reserve unit...")
        print("   Watch for any LED changes...")
        input("   Press Enter to reserve unit...")
        
        try:
            success = protocol.reserve_unit()
            print(f"   ✓ Reserve unit: {success}")
            
        except Exception as e:
            print(f"   ✗ Reserve unit failed: {e}")
        
        # Test 4: Simple scan command (without WDB)
        print("\n5. Testing simple scan command...")
        print("   Watch for scanning LED or motor activity...")
        input("   Press Enter to send simple scan command...")
        
        try:
            # Send a simple scan command without complex parameters
            scan_cmd = protocol._parse_command("1b 00 00 00 00 00")
            print(f"   Sending simple scan command: {scan_cmd.hex()}")
            
            data, status = protocol._issue_command(scan_cmd)
            print(f"   ✓ Scan command completed: status={status}")
            
        except Exception as e:
            print(f"   ✗ Scan command failed: {e}")
        
        # Test 5: Release unit
        print("\n6. Testing release unit...")
        print("   Watch for any LED changes...")
        input("   Press Enter to release unit...")
        
        try:
            success = protocol.release_unit()
            print(f"   ✓ Release unit: {success}")
            
        except Exception as e:
            print(f"   ✗ Release unit failed: {e}")
        
        protocol.close()
        
        print("\n" + "=" * 40)
        print("PROPER COMMANDS TEST RESULTS")
        print("=" * 40)
        print("Did you observe any of the following?")
        print("  □ LED changes (power, status, scanning LEDs)")
        print("  □ Motor sounds (loading, focusing, scanning)")
        print("  □ Physical movement (film transport, focus adjustment)")
        print("  □ Any other visible or audible activity")
        print("\nIf you observed activity, the scanner is responding to commands!")
        print("If no activity, we may need to investigate the command format...")
        
        return True
        
    except Exception as e:
        print(f"✗ Proper commands test failed: {e}")
        return False


def test_command_timing():
    """Test if timing is the issue."""
    print("\n" + "=" * 40)
    print("Command Timing Test")
    print("=" * 40)
    
    scanners = find_scanners()
    if not scanners:
        return False
    
    scanner = scanners[0]
    
    try:
        protocol = CoolscanProtocol(scanner)
        print("Testing command timing...")
        
        # Test with different delays
        for delay in [0.1, 0.5, 1.0, 2.0]:
            print(f"\nTesting with {delay}s delay...")
            
            try:
                cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
                protocol._usb_write_bulk(cmd)
                print(f"  Command sent, waiting {delay}s...")
                time.sleep(delay)
                
                # Try to read response
                response = protocol._usb_read_bulk(1)
                if hasattr(response, 'tobytes'):
                    response = response.tobytes()
                print(f"  Response: {response.hex()}")
                
            except Exception as e:
                print(f"  Failed: {e}")
        
        protocol.close()
        
    except Exception as e:
        print(f"✗ Timing test failed: {e}")


if __name__ == "__main__":
    print("Running Proper Commands Tests")
    print("=" * 60)
    
    # Run proper commands test
    commands_success = test_proper_commands()
    
    # Run timing test
    timing_success = test_command_timing()
    
    print("\n" + "=" * 60)
    print("Proper Commands Test Summary")
    print("=" * 60)
    print(f"Proper Commands Test: {'✓ COMPLETED' if commands_success else '✗ FAILED'}")
    print(f"Timing Test: {'✓ COMPLETED' if timing_success else '✗ FAILED'}")
    
    sys.exit(0 if commands_success else 1)
