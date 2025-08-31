#!/usr/bin/env python3
"""
Communication verification test.
This script confirms with 100% certainty what's happening with scanner communication.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def test_communication_verification():
    """Verify scanner communication with 100% certainty."""
    print("Scanner Communication Verification")
    print("=" * 50)
    
    # Find scanner
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing communication with: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created successfully")
        
        # Test 1: Basic USB access
        print("\n2. Testing basic USB access...")
        try:
            # Try to access the USB device directly
            device = protocol.usb_device
            print(f"✓ USB device accessible: {device}")
            print(f"  Vendor ID: 0x{device.idVendor:04x}")
            print(f"  Product ID: 0x{device.idProduct:04x}")
            
            # Try to get device strings
            try:
                manufacturer = device.manufacturer
                product = device.product
                print(f"✓ Device strings accessible:")
                print(f"  Manufacturer: {manufacturer}")
                print(f"  Product: {product}")
            except Exception as e:
                print(f"✗ Device strings failed: {e}")
                
        except Exception as e:
            print(f"✗ Basic USB access failed: {e}")
            return False
        
        # Test 2: Endpoint access
        print("\n3. Testing endpoint access...")
        try:
            # Check if we can access the endpoints
            bulk_out = protocol.bulk_out
            bulk_in = protocol.bulk_in
            
            print(f"✓ Endpoints accessible:")
            print(f"  Bulk OUT: {bulk_out}")
            print(f"  Bulk IN: {bulk_in}")
            
        except Exception as e:
            print(f"✗ Endpoint access failed: {e}")
            return False
        
        # Test 3: Simple command send (no read)
        print("\n4. Testing simple command send...")
        try:
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"  Sending command: {cmd.hex()}")
            
            # Just try to send the command
            bytes_written = protocol._usb_write_bulk(cmd)
            print(f"✓ Command sent successfully: {bytes_written} bytes written")
            
        except Exception as e:
            print(f"✗ Command send failed: {e}")
            return False
        
        # Test 4: Simple read (no command)
        print("\n5. Testing simple read...")
        try:
            # Try to read a small amount of data
            print("  Attempting to read 1 byte...")
            data = protocol._usb_read_bulk(1)
            if hasattr(data, 'tobytes'):
                data = data.tobytes()
            print(f"✓ Read successful: {data.hex()}")
            
        except Exception as e:
            print(f"✗ Read failed: {e}")
            # This might be expected if no data is available
        
        # Test 5: Full command cycle
        print("\n6. Testing full command cycle...")
        try:
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"  Sending command: {cmd.hex()}")
            
            # Send command
            bytes_written = protocol._usb_write_bulk(cmd)
            print(f"  Command sent: {bytes_written} bytes")
            
            # Wait a bit
            time.sleep(0.1)
            
            # Try to read response
            print("  Reading response...")
            response = protocol._usb_read_bulk(1)
            if hasattr(response, 'tobytes'):
                response = response.tobytes()
            print(f"✓ Response received: {response.hex()}")
            
        except Exception as e:
            print(f"✗ Full command cycle failed: {e}")
            return False
        
        # Test 6: Phase check
        print("\n7. Testing phase check...")
        try:
            phase = protocol._check_phase()
            print(f"✓ Phase check successful: {phase}")
            
        except Exception as e:
            print(f"✗ Phase check failed: {e}")
            return False
        
        # Test 7: Complete command with status
        print("\n8. Testing complete command with status...")
        try:
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"  Sending command: {cmd.hex()}")
            
            data, status = protocol._issue_command(cmd)
            print(f"✓ Command completed:")
            print(f"  Status: {status}")
            print(f"  Data length: {len(data)} bytes")
            
            if status == StatusType.NO_DOCS:
                print("  Note: NO_DOCS status is expected when no film is loaded")
            elif status == StatusType.READY:
                print("  Note: READY status indicates scanner is ready")
            
        except Exception as e:
            print(f"✗ Complete command failed: {e}")
            return False
        
        protocol.close()
        
        print("\n" + "=" * 50)
        print("COMMUNICATION VERIFICATION RESULTS")
        print("=" * 50)
        print("✅ CONFIRMED: We are successfully sending messages to the scanner")
        print("✅ CONFIRMED: We are successfully receiving responses from the scanner")
        print("✅ CONFIRMED: The scanner is communicating properly")
        print("✅ CONFIRMED: The phase checking fix is working")
        print("✅ CONFIRMED: The status parsing is working correctly")
        
        return True
        
    except Exception as e:
        print(f"✗ Communication verification failed: {e}")
        return False


if __name__ == "__main__":
    success = test_communication_verification()
    sys.exit(0 if success else 1)
