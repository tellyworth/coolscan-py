#!/usr/bin/env python3
"""
Wake-up test for Coolscan scanner.
This script tries different approaches to wake up the scanner from sleep state.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from device import find_scanners
from protocol import CoolscanProtocol, StatusType


def test_wakeup_sequence():
    """Test different wake-up sequences."""
    print("Coolscan Wake-up Test")
    print("=" * 40)
    
    # Find scanners
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing wake-up on: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Try different wake-up approaches
        print("\n2. Trying wake-up sequences...")
        
        # Approach 1: Send a simple command without phase check
        print("\n   Approach 1: Direct command send...")
        try:
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"     Sending: {cmd.hex()}")
            protocol._usb_write_bulk(cmd)
            print("     ✓ Command sent")
            
            # Wait a bit
            time.sleep(0.1)
            
            # Try to read response
            try:
                response = protocol._usb_read_bulk(1)
                if hasattr(response, 'tobytes'):
                    response = response.tobytes()
                print(f"     ✓ Got response: {response.hex()}")
            except Exception as e:
                print(f"     ✗ No response: {e}")
                
        except Exception as e:
            print(f"     ✗ Failed: {e}")
        
        # Approach 2: Try with longer timeout
        print("\n   Approach 2: Longer timeout...")
        try:
            # Set longer timeout
            protocol.usb_device.default_timeout = 10000  # 10 seconds
            
            cmd = protocol._parse_command("00 00 00 00 00 00")
            print(f"     Sending: {cmd.hex()}")
            protocol._usb_write_bulk(cmd)
            print("     ✓ Command sent")
            
            time.sleep(0.5)  # Wait longer
            
            try:
                response = protocol._usb_read_bulk(1)
                if hasattr(response, 'tobytes'):
                    response = response.tobytes()
                print(f"     ✓ Got response: {response.hex()}")
            except Exception as e:
                print(f"     ✗ No response: {e}")
                
        except Exception as e:
            print(f"     ✗ Failed: {e}")
        
        # Approach 3: Try a different command
        print("\n   Approach 3: Different command...")
        try:
            # Try INQUIRY command
            cmd = protocol._parse_command("12 00 00 00 24 00")  # INQUIRY
            print(f"     Sending: {cmd.hex()}")
            protocol._usb_write_bulk(cmd)
            print("     ✓ Command sent")
            
            time.sleep(0.1)
            
            try:
                response = protocol._usb_read_bulk(1)
                if hasattr(response, 'tobytes'):
                    response = response.tobytes()
                print(f"     ✓ Got response: {response.hex()}")
            except Exception as e:
                print(f"     ✗ No response: {e}")
                
        except Exception as e:
            print(f"     ✗ Failed: {e}")
        
        print("\n✓ Wake-up test completed!")
        return True
        
    except Exception as e:
        print(f"✗ Wake-up test failed: {e}")
        return False


if __name__ == "__main__":
    success = test_wakeup_sequence()
    sys.exit(0 if success else 1)
