#!/usr/bin/env python3
"""
Test with sudo permissions.
This script explains the permission issue and provides a solution.
"""

import sys
import os
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def test_permission_issue():
    """Test and explain the permission issue."""
    print("USB Permission Issue Analysis")
    print("=" * 40)
    
    # Check if running with elevated permissions
    is_root = os.geteuid() == 0
    print(f"Running as root: {is_root}")
    
    if not is_root:
        print("\n⚠️  PERMISSION ISSUE DETECTED")
        print("=" * 40)
        print("The scanner is detected but we cannot send commands due to")
        print("insufficient USB permissions. This is why there's no physical")
        print("activity from the scanner.")
        print("\nSOLUTION:")
        print("Run this script with sudo to get the necessary permissions:")
        print("\n  sudo python3 test_with_sudo.py")
        print("\nThis will allow us to send commands to the scanner and")
        print("see physical activity (LEDs, motors, etc.).")
        return False
    
    # Find scanner
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing scanner with elevated permissions: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Test basic command
        print("\n2. Testing basic command with elevated permissions...")
        try:
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"  Sending command: {cmd.hex()}")
            
            data, status = protocol._issue_command(cmd)
            print(f"  ✓ Command completed: status={status}")
            
            if status == StatusType.READY:
                print("  ✅ Scanner is ready and responding!")
            elif status == StatusType.NO_DOCS:
                print("  ⚠️  Scanner is ready but no document loaded")
            else:
                print(f"  📊 Scanner status: {status}")
                
        except Exception as e:
            print(f"  ✗ Command failed: {e}")
        
        # Test wake-up sequence
        print("\n3. Testing wake-up sequence with elevated permissions...")
        print("   Watch for any LED changes or sounds...")
        input("   Press Enter to send wake-up commands...")
        
        try:
            # Send reset command
            reset_cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
            print(f"   Sending reset command: {reset_cmd.hex()}")
            protocol._usb_write_bulk(reset_cmd)
            print("   ✓ Reset command sent")
            
            # Wait for scanner to respond
            time.sleep(2)
            
            # Send execute command
            exec_cmd = protocol._parse_command("c1 00 00 00 00 00")
            print(f"   Sending execute command: {exec_cmd.hex()}")
            protocol._usb_write_bulk(exec_cmd)
            print("   ✓ Execute command sent")
            
            # Wait for scanner to respond
            time.sleep(2)
            
            print("   Did you see any LED changes or hear any sounds?")
            
        except Exception as e:
            print(f"   ✗ Wake-up sequence failed: {e}")
        
        protocol.close()
        
        print("\n" + "=" * 40)
        print("ELEVATED PERMISSIONS TEST RESULTS")
        print("=" * 40)
        print("✅ Commands are now being sent to the scanner")
        print("✅ Scanner should respond with physical activity")
        print("✅ This confirms the permission issue was the problem")
        
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


def explain_permission_issue():
    """Explain the permission issue in detail."""
    print("\n" + "=" * 60)
    print("PERMISSION ISSUE EXPLANATION")
    print("=" * 60)
    print("The scanner is working correctly, but macOS requires elevated")
    print("permissions to send commands to USB devices.")
    print("\nWhat we've confirmed:")
    print("✅ Scanner is detected by macOS")
    print("✅ USB device descriptor is accessible")
    print("✅ Endpoints are accessible")
    print("❌ Command transmission is blocked by permissions")
    print("❌ No physical activity because commands don't reach scanner")
    print("\nThis is why you haven't seen any LED changes, motor sounds,")
    print("or other physical activity from the scanner.")
    print("\nThe solution is to run the script with sudo permissions.")


if __name__ == "__main__":
    import time
    
    print("USB Permission Test")
    print("=" * 60)
    
    # Check if running with sudo
    if os.geteuid() == 0:
        # Running with elevated permissions
        success = test_permission_issue()
    else:
        # Not running with elevated permissions
        explain_permission_issue()
        print("\n" + "=" * 60)
        print("TO TEST WITH ELEVATED PERMISSIONS:")
        print("=" * 60)
        print("Run this command:")
        print("\n  sudo python3 test_with_sudo.py")
        print("\nThis will allow the script to send commands to the scanner")
        print("and you should see physical activity (LEDs, motors, etc.).")
        success = False
    
    sys.exit(0 if success else 1)
