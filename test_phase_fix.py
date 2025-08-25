#!/usr/bin/env python3
"""
Test script to verify the phase checking fix.
This script tests the improved phase checking with retry logic.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from device import find_scanners
from protocol import CoolscanProtocol, StatusType, PhaseType, WindowDescriptorBlock


def test_phase_checking():
    """Test the improved phase checking functionality."""
    print("Coolscan Phase Checking Test")
    print("=" * 40)
    
    # Find scanners
    scanners = find_scanners()
    if not scanners:
        print("No scanners found!")
        return False
    
    scanner = scanners[0]
    print(f"Testing phase checking on: {scanner}")
    
    try:
        # Create protocol object
        print("\n1. Creating protocol object...")
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Test basic phase check
        print("\n2. Testing basic phase check...")
        try:
            phase = protocol._check_phase()
            print(f"✓ Basic phase check: {phase}")
        except Exception as e:
            print(f"✗ Basic phase check failed: {e}")
            return False
        
        # Test phase check with retry
        print("\n3. Testing phase check with retry...")
        try:
            phase = protocol._check_phase_with_retry()
            print(f"✓ Phase check with retry: {phase}")
        except Exception as e:
            print(f"✗ Phase check with retry failed: {e}")
            return False
        
        # Test scanner ready function
        print("\n4. Testing scanner ready function...")
        try:
            ready = protocol.scanner_ready(timeout=10)
            print(f"✓ Scanner ready: {ready}")
        except Exception as e:
            print(f"✗ Scanner ready check failed: {e}")
            return False
        
        # Test WDB creation
        print("\n5. Testing WDB creation...")
        try:
            wdb = WindowDescriptorBlock()
            wdb_data = wdb.to_bytes()
            print(f"✓ WDB created: {len(wdb_data)} bytes")
            print(f"  Resolution: {wdb.x_resolution}x{wdb.y_resolution} DPI")
            print(f"  Size: {wdb.width}x{wdb.length} pixels")
        except Exception as e:
            print(f"✗ WDB creation failed: {e}")
            return False
        
        # Test simple command with improved phase handling
        print("\n6. Testing command with improved phase handling...")
        try:
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            print(f"  Sending command: {cmd.hex()}")
            
            data, status = protocol._issue_command(cmd)
            print(f"✓ Command completed: status={status}")
            
        except Exception as e:
            print(f"✗ Command test failed: {e}")
            return False
        
        print("\n✓ All phase checking tests passed!")
        return True
        
    except Exception as e:
        print(f"✗ Phase checking test failed: {e}")
        return False


if __name__ == "__main__":
    success = test_phase_checking()
    sys.exit(0 if success else 1)
