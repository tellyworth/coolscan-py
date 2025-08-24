#!/usr/bin/env python3
"""
Simple connection test for Coolscan scanner.
This script just tries to establish basic communication without attempting scans.
"""

import sys
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from device import find_scanners
from protocol import CoolscanProtocol, StatusType


def test_basic_connection():
    """Test basic connection to scanner."""
    print("Coolscan Basic Connection Test")
    print("=" * 40)
    
    # Find scanners
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing connection to: {scanner}")
    
    try:
        # Try to create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Try a simple phase check
        print("\n2. Testing phase check...")
        try:
            phase = protocol._check_phase()
            print(f"✓ Phase check successful: {phase}")
        except Exception as e:
            print(f"✗ Phase check failed: {e}")
            return False
        
        # Try a simple command
        print("\n3. Testing simple command...")
        try:
            # Try a very simple command first
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"  Sending command: {cmd.hex()}")
            
            # Just try to send the command, don't read response yet
            protocol._usb_write_bulk(cmd)
            print("✓ Command sent successfully")
            
            # Try to read a small amount of data
            print("  Trying to read response...")
            response = protocol._usb_read_bulk(1)
            if hasattr(response, 'tobytes'):
                response = response.tobytes()
            print(f"✓ Read response: {response.hex()}")
            
        except Exception as e:
            print(f"✗ Command test failed: {e}")
            return False
        
        print("\n✓ Basic connection test successful!")
        return True
        
    except Exception as e:
        print(f"✗ Connection test failed: {e}")
        return False


if __name__ == "__main__":
    success = test_basic_connection()
    sys.exit(0 if success else 1)
