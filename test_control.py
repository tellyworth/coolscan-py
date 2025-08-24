#!/usr/bin/env python3
"""
USB Control Transfer test for Coolscan scanner.
This script tries USB control transfers to wake up the scanner.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from device import find_scanners
from protocol import CoolscanProtocol, StatusType


def test_control_transfers():
    """Test USB control transfers to wake up scanner."""
    print("Coolscan USB Control Transfer Test")
    print("=" * 40)
    
    # Find scanners
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing control transfers on: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Try different USB control transfers
        print("\n2. Trying USB control transfers...")
        
        # Try to get device descriptor
        print("\n   Getting device descriptor...")
        try:
            # Get device descriptor
            descriptor = protocol.usb_device.get_active_configuration()
            print(f"     ✓ Got configuration: {descriptor}")
            
            # Try to get string descriptors
            try:
                manufacturer = protocol.usb_device.iManufacturer
                print(f"     Manufacturer index: {manufacturer}")
                if manufacturer:
                    mfg_string = protocol.usb_device.manufacturer
                    print(f"     Manufacturer: {mfg_string}")
            except Exception as e:
                print(f"     ✗ Could not get manufacturer: {e}")
            
            try:
                product = protocol.usb_device.iProduct
                print(f"     Product index: {product}")
                if product:
                    prod_string = protocol.usb_device.product
                    print(f"     Product: {prod_string}")
            except Exception as e:
                print(f"     ✗ Could not get product: {e}")
                
        except Exception as e:
            print(f"     ✗ Failed to get device info: {e}")
        
        # Try to set USB configuration
        print("\n   Setting USB configuration...")
        try:
            # Try to set configuration to 1
            protocol.usb_device.set_configuration(1)
            print("     ✓ Configuration set to 1")
        except Exception as e:
            print(f"     ✗ Failed to set configuration: {e}")
        
        # Try to claim the interface
        print("\n   Claiming interface...")
        try:
            # Try to claim interface 0
            usb.util.claim_interface(protocol.usb_device, 0)
            print("     ✓ Interface claimed")
        except Exception as e:
            print(f"     ✗ Failed to claim interface: {e}")
        
        # Try to clear any pending transfers
        print("\n   Clearing endpoints...")
        try:
            # Try to clear the bulk in endpoint
            protocol.usb_device.clear_halt(protocol.bulk_in.bEndpointAddress)
            print("     ✓ Bulk IN endpoint cleared")
        except Exception as e:
            print(f"     ✗ Failed to clear bulk IN: {e}")
        
        try:
            # Try to clear the bulk out endpoint
            protocol.usb_device.clear_halt(protocol.bulk_out.bEndpointAddress)
            print("     ✓ Bulk OUT endpoint cleared")
        except Exception as e:
            print(f"     ✗ Failed to clear bulk OUT: {e}")
        
        # Now try a simple command
        print("\n3. Testing communication after setup...")
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
                return True
            except Exception as e:
                print(f"  ✗ No response: {e}")
                
        except Exception as e:
            print(f"  ✗ Failed to send command: {e}")
        
        print("\n✓ Control transfer test completed!")
        return False
        
    except Exception as e:
        print(f"✗ Control transfer test failed: {e}")
        return False


if __name__ == "__main__":
    success = test_control_transfers()
    sys.exit(0 if success else 1)
