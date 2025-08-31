#!/usr/bin/env python3
"""
Test exact wake-up sequence from SANE backend.
This script implements the proper wake-up sequence that should trigger scanner activity.
"""

import sys
import time
import os
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def test_sane_wakeup_sequence():
    """Test the exact wake-up sequence from SANE backend."""
    print("SANE Backend Wake-up Sequence Test")
    print("=" * 50)
    print("Watch the scanner for any LED changes, motor sounds, or movement...")
    
    # Check if running with elevated permissions
    if os.geteuid() != 0:
        print("⚠️  This test requires elevated permissions.")
        print("Run with: sudo python3 test_wakeup_sequence.py")
        return False
    
    # Find scanner
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing wake-up sequence on: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Test 1: Initial state check
        print("\n2. Checking initial scanner state...")
        try:
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"  Sending initial TEST UNIT READY: {cmd.hex()}")
            
            data, status = protocol._issue_command(cmd)
            print(f"  Initial status: {status}")
            
        except Exception as e:
            print(f"  Initial check failed: {e}")
        
        # Test 2: SANE Backend Wake-up Sequence
        print("\n3. Executing SANE Backend Wake-up Sequence...")
        print("   Watch for any LED changes or sounds...")
        input("   Press Enter to start wake-up sequence...")
        
        try:
            # Step 1: Reset command (from SANE backend coolscan2.c)
            print("   Step 1: Sending reset command...")
            reset_cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
            print(f"     Reset command: {reset_cmd.hex()}")
            
            # Send reset command
            bytes_written = protocol._usb_write_bulk(reset_cmd)
            print(f"     ✓ Reset command sent: {bytes_written} bytes")
            
            # Wait for scanner to process reset
            print("     Waiting 3 seconds for reset to complete...")
            time.sleep(3)
            
            # Step 2: Execute command (from SANE backend coolscan2.c)
            print("   Step 2: Sending execute command...")
            exec_cmd = protocol._parse_command("c1 00 00 00 00 00")
            print(f"     Execute command: {exec_cmd.hex()}")
            
            # Send execute command
            bytes_written = protocol._usb_write_bulk(exec_cmd)
            print(f"     ✓ Execute command sent: {bytes_written} bytes")
            
            # Wait for scanner to process execute
            print("     Waiting 3 seconds for execute to complete...")
            time.sleep(3)
            
            # Step 3: Test unit ready
            print("   Step 3: Testing unit ready...")
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"     TEST UNIT READY: {cmd.hex()}")
            
            data, status = protocol._issue_command(cmd)
            print(f"     ✓ Unit ready status: {status}")
            
            if status == StatusType.READY:
                print("     ✅ Scanner is now ready!")
            elif status == StatusType.NO_DOCS:
                print("     ⚠️  Scanner is ready but no document loaded")
            else:
                print(f"     📊 Scanner status: {status}")
            
        except Exception as e:
            print(f"   ✗ Wake-up sequence failed: {e}")
        
        # Test 3: Additional wake-up commands from SANE backend
        print("\n4. Testing additional wake-up commands...")
        print("   Watch for any additional activity...")
        input("   Press Enter to send additional commands...")
        
        try:
            # Try the COMMAND C1 sequence from SANE backend
            print("   Sending COMMAND C1 sequence...")
            c1_cmd = protocol._parse_command("c1 00 00 00 00 00 00 00 00 00")
            print(f"     COMMAND C1: {c1_cmd.hex()}")
            
            bytes_written = protocol._usb_write_bulk(c1_cmd)
            print(f"     ✓ COMMAND C1 sent: {bytes_written} bytes")
            time.sleep(2)
            
            # Try the COMMAND E1 sequence from SANE backend
            print("   Sending COMMAND E1 sequence...")
            e1_cmd = protocol._parse_command("e1 00 c1 00 00 00 00 00 0d 00")
            print(f"     COMMAND E1: {e1_cmd.hex()}")
            
            bytes_written = protocol._usb_write_bulk(e1_cmd)
            print(f"     ✓ COMMAND E1 sent: {bytes_written} bytes")
            time.sleep(2)
            
        except Exception as e:
            print(f"   ✗ Additional commands failed: {e}")
        
        # Test 4: Test scanner responsiveness after wake-up
        print("\n5. Testing scanner responsiveness...")
        try:
            # Try inquiry command
            print("   Testing INQUIRY command...")
            inquiry_data = protocol.inquiry()
            print(f"     ✓ INQUIRY successful: {len(inquiry_data)} bytes")
            
            if len(inquiry_data) >= 36:
                vendor = inquiry_data[8:16].decode('ascii', errors='ignore').strip()
                product = inquiry_data[16:32].decode('ascii', errors='ignore').strip()
                print(f"       Vendor: {vendor}")
                print(f"       Product: {product}")
                
        except Exception as e:
            print(f"   ✗ INQUIRY failed: {e}")
        
        protocol.close()
        
        print("\n" + "=" * 50)
        print("WAKE-UP SEQUENCE TEST RESULTS")
        print("=" * 50)
        print("Did you observe any of the following?")
        print("  □ LED changes (power, status, scanning LEDs)")
        print("  □ Motor sounds (loading, focusing, scanning)")
        print("  □ Physical movement (film transport, focus adjustment)")
        print("  □ Any other visible or audible activity")
        print("\nIf you observed activity, the wake-up sequence worked!")
        print("If no activity, the scanner may need a different approach...")
        
        return True
        
    except Exception as e:
        print(f"✗ Wake-up sequence test failed: {e}")
        return False


def test_alternative_wakeup():
    """Test alternative wake-up approaches."""
    print("\n" + "=" * 50)
    print("Alternative Wake-up Test")
    print("=" * 50)
    
    scanners = find_scanners()
    if not scanners:
        return False
    
    scanner = scanners[0]
    
    try:
        protocol = CoolscanProtocol(scanner)
        print("Testing alternative wake-up approaches...")
        
        # Test 1: Power cycle simulation
        print("\n1. Testing power cycle simulation...")
        print("   Watch for any activity...")
        input("   Press Enter to simulate power cycle...")
        
        try:
            # Send multiple reset commands to simulate power cycle
            for i in range(3):
                print(f"     Power cycle attempt {i+1}...")
                reset_cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
                protocol._usb_write_bulk(reset_cmd)
                time.sleep(1)
            
            # Wait longer for scanner to stabilize
            print("     Waiting 5 seconds for scanner to stabilize...")
            time.sleep(5)
            
            # Test if scanner is now responsive
            cmd = protocol._parse_command("00 00 00 00 00 00")
            data, status = protocol._issue_command(cmd)
            print(f"     Post-power cycle status: {status}")
            
        except Exception as e:
            print(f"     ✗ Power cycle failed: {e}")
        
        # Test 2: Force wake-up with repeated commands
        print("\n2. Testing force wake-up...")
        print("   Watch for any activity...")
        input("   Press Enter to force wake-up...")
        
        try:
            # Send repeated wake-up commands
            commands = [
                "e0 00 80 00 00 00 00 00 0d 00",  # Reset
                "c1 00 00 00 00 00",              # Execute
                "e1 00 c1 00 00 00 00 00 0d 00",  # COMMAND E1
            ]
            
            for i, cmd_hex in enumerate(commands):
                print(f"     Force wake-up command {i+1}...")
                cmd = protocol._parse_command(cmd_hex)
                protocol._usb_write_bulk(cmd)
                time.sleep(2)
            
            # Test responsiveness
            cmd = protocol._parse_command("00 00 00 00 00 00")
            data, status = protocol._issue_command(cmd)
            print(f"     Post-force wake-up status: {status}")
            
        except Exception as e:
            print(f"     ✗ Force wake-up failed: {e}")
        
        protocol.close()
        
    except Exception as e:
        print(f"✗ Alternative wake-up test failed: {e}")


if __name__ == "__main__":
    print("Running SANE Backend Wake-up Sequence Tests")
    print("=" * 70)
    
    # Run main wake-up sequence test
    wakeup_success = test_sane_wakeup_sequence()
    
    # Run alternative wake-up test
    alt_success = test_alternative_wakeup()
    
    print("\n" + "=" * 70)
    print("Wake-up Sequence Test Summary")
    print("=" * 70)
    print(f"Main Wake-up Test: {'✓ COMPLETED' if wakeup_success else '✗ FAILED'}")
    print(f"Alternative Test: {'✓ COMPLETED' if alt_success else '✗ FAILED'}")
    
    sys.exit(0 if wakeup_success else 1)
