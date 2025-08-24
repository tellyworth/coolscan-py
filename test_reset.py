#!/usr/bin/env python3
"""
Reset test for Coolscan scanner.
This script tries the reset command from the SANE backend to wake up the scanner.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from device import find_scanners
from protocol import CoolscanProtocol, StatusType


def test_reset_sequence():
    """Test the reset sequence from SANE backend."""
    print("Coolscan Reset Test")
    print("=" * 40)
    
    # Find scanners
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing reset on: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Try the reset command from SANE backend
        print("\n2. Trying reset command...")
        try:
            # This is the exact command from cs3_reset in coolscan3.c
            reset_cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
            print(f"  Sending reset command: {reset_cmd.hex()}")
            
            # Send the command
            protocol._usb_write_bulk(reset_cmd)
            print("  ✓ Reset command sent")
            
            # Wait a bit for the scanner to respond
            print("  Waiting for scanner response...")
            time.sleep(2)
            
            # Try to read any response
            try:
                response = protocol._usb_read_bulk(1)
                if hasattr(response, 'tobytes'):
                    response = response.tobytes()
                print(f"  ✓ Got response: {response.hex()}")
            except Exception as e:
                print(f"  ✗ No immediate response: {e}")
            
            # Now try a simple TEST UNIT READY command
            print("\n3. Testing communication after reset...")
            time.sleep(1)
            
            try:
                test_cmd = protocol._parse_command("00 00 00 00 00 00")
                print(f"  Sending TEST UNIT READY: {test_cmd.hex()}")
                protocol._usb_write_bulk(test_cmd)
                print("  ✓ Command sent")
                
                time.sleep(0.5)
                
                try:
                    response = protocol._usb_read_bulk(1)
                    if hasattr(response, 'tobytes'):
                        response = response.tobytes()
                    print(f"  ✓ Got response: {response.hex()}")
                    
                    # If we got a response, try the phase check
                    print("\n4. Testing phase check after reset...")
                    try:
                        phase = protocol._check_phase()
                        print(f"  ✓ Phase check successful: {phase}")
                        return True
                    except Exception as e:
                        print(f"  ✗ Phase check still failed: {e}")
                        
                except Exception as e:
                    print(f"  ✗ No response to TEST UNIT READY: {e}")
                    
            except Exception as e:
                print(f"  ✗ Failed to send TEST UNIT READY: {e}")
                
        except Exception as e:
            print(f"  ✗ Reset command failed: {e}")
        
        print("\n✓ Reset test completed!")
        return False
        
    except Exception as e:
        print(f"✗ Reset test failed: {e}")
        return False


if __name__ == "__main__":
    success = test_reset_sequence()
    sys.exit(0 if success else 1)
