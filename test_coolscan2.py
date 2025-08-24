#!/usr/bin/env python3
"""
Coolscan2-style wake-up test for Coolscan scanner.
This script implements the exact sequence from coolscan2.c
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from device import find_scanners
from protocol import CoolscanProtocol, StatusType


def test_coolscan2_sequence():
    """Test the exact sequence from coolscan2.c."""
    print("Coolscan2-Style Wake-up Test")
    print("=" * 40)
    
    # Find scanners
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing coolscan2 sequence on: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Step 1: Send reset command (e0 00 80 00 00 00 00 00 0d 00)
        print("\n2. Sending reset command...")
        try:
            reset_cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
            print(f"  Sending: {reset_cmd.hex()}")
            protocol._usb_write_bulk(reset_cmd)
            print("  ✓ Reset command sent")
            
            # Wait a bit
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ✗ Reset command failed: {e}")
            return False
        
        # Step 2: Send execute command (c1 00 00 00 00 00)
        print("\n3. Sending execute command...")
        try:
            execute_cmd = protocol._parse_command("c1 00 00 00 00 00")
            print(f"  Sending: {execute_cmd.hex()}")
            protocol._usb_write_bulk(execute_cmd)
            print("  ✓ Execute command sent")
            
            # Wait for execution
            time.sleep(1)
            
        except Exception as e:
            print(f"  ✗ Execute command failed: {e}")
            return False
        
        # Step 3: Test communication
        print("\n4. Testing communication...")
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
                print("\n5. Testing phase check...")
                try:
                    phase = protocol._check_phase()
                    print(f"  ✓ Phase check successful: {phase}")
                    
                    # Try a full inquiry
                    print("\n6. Testing full inquiry...")
                    try:
                        inquiry_cmd = protocol._parse_command("12 00 00 00 24 00")
                        print(f"  Sending INQUIRY: {inquiry_cmd.hex()}")
                        protocol._usb_write_bulk(inquiry_cmd)
                        print("  ✓ INQUIRY sent")
                        
                        time.sleep(0.5)
                        
                        try:
                            inquiry_response = protocol._usb_read_bulk(36)
                            if hasattr(inquiry_response, 'tobytes'):
                                inquiry_response = inquiry_response.tobytes()
                            print(f"  ✓ Got INQUIRY response: {inquiry_response.hex()}")
                            
                            # Parse vendor and product strings
                            vendor = inquiry_response[8:16].decode('ascii', errors='ignore').strip()
                            product = inquiry_response[16:32].decode('ascii', errors='ignore').strip()
                            print(f"  ✓ Vendor: '{vendor}'")
                            print(f"  ✓ Product: '{product}'")
                            
                            return True
                            
                        except Exception as e:
                            print(f"  ✗ No INQUIRY response: {e}")
                            
                    except Exception as e:
                        print(f"  ✗ INQUIRY failed: {e}")
                        
                except Exception as e:
                    print(f"  ✗ Phase check failed: {e}")
                    
            except Exception as e:
                print(f"  ✗ No response to TEST UNIT READY: {e}")
                
        except Exception as e:
            print(f"  ✗ TEST UNIT READY failed: {e}")
        
        print("\n✓ Coolscan2 sequence test completed!")
        return False
        
    except Exception as e:
        print(f"✗ Coolscan2 sequence test failed: {e}")
        return False


if __name__ == "__main__":
    success = test_coolscan2_sequence()
    sys.exit(0 if success else 1)
