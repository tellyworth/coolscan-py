#!/usr/bin/env python3
"""
Simple Film Status Test

Tests if the scanner detects film after insertion.
"""

import sys
import time

sys.path.insert(0, '.')

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def test_film_status():
    """Test film status detection."""
    print("🎞️  Film Status Test")
    print("=" * 40)
    
    # Find scanner
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False
    
    scanner = scanners[0]
    print(f"📷 Scanner: {scanner}")
    
    protocol = None
    try:
        # Create protocol
        print("\n🔌 Connecting...")
        protocol = CoolscanProtocol(scanner)
        print("✅ Connected")
        
        # Reserve unit
        print("\n🔍 Reserving unit...")
        if protocol.reserve_unit():
            print("✅ Unit reserved")
        else:
            print("❌ Unit reservation failed")
            return False
        
        try:
            # Test unit ready multiple times to see status
            print("\n📊 Testing scanner status (5 attempts):")
            for i in range(5):
                try:
                    # Send TEST UNIT READY
                    cmd = protocol._parse_command("00 00 00 00 00 00")
                    data, status = protocol._issue_command(cmd)
                    
                    print(f"  Attempt {i+1}: ", end="")
                    if status == StatusType.READY:
                        print("✅ READY - Film may be loaded")
                    elif status == StatusType.NO_DOCS:
                        print("❌ NO_DOCS - No film detected")
                    elif status == StatusType.ERROR:
                        print("⚠️  ERROR - Check error details")
                    else:
                        print(f"❓ Status: {status}")
                    
                    # If we got status data, show it
                    if data and len(data) >= 8:
                        sense_key = data[1] & 0x0f
                        sense_asc = data[2]
                        sense_ascq = data[3]
                        print(f"    Sense: key=0x{sense_key:02x}, ASC=0x{sense_asc:02x}, ASCQ=0x{sense_ascq:02x}")
                    
                    time.sleep(0.5)
                    
                except Exception as e:
                    print(f"  Attempt {i+1}: ❌ Error: {e}")
                    time.sleep(0.5)
            
        finally:
            # Release unit
            print("\n🔍 Releasing unit...")
            protocol.release_unit()
            print("✅ Unit released")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if protocol:
            protocol.close()


if __name__ == "__main__":
    success = test_film_status()
    sys.exit(0 if success else 1)






