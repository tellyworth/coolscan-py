#!/usr/bin/env python3
"""
Test wait_scanner Function

Tests the new wait_scanner() function based on SANE backend wait_scanner().
This should properly wake up the scanner and show all data received.
"""

import sys
import time

sys.path.insert(0, '.')

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType


def test_wait_scanner():
    """Test the wait_scanner function."""
    print("🔍 Testing wait_scanner() Function")
    print("=" * 60)

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

        # Try wait_scanner with shorter timeout first
        print("\n⏳ Testing wait_scanner() with 40 attempts (20 seconds max)...")
        success = protocol.wait_scanner(max_attempts=40, delay=0.5)

        if success:
            print("\n✅ wait_scanner() succeeded!")

            # Try a simple command to confirm communication
            print("\n📤 Testing TEST_UNIT_READY to confirm communication...")
            try:
                cmd = protocol._parse_command("00 00 00 00 00 00")
                data, status = protocol._issue_command(cmd)

                if data and len(data) >= 8:
                    print(f"\n✅ Got response! Status: {status}")
                    print(f"Status bytes: {data.hex()}")

                    # Check film status
                    sense_key = data[1] & 0x0f
                    sense_asc = data[2]
                    sense_ascq = data[3]
                    print(f"Sense key: 0x{sense_key:02x}, ASC: 0x{sense_asc:02x}, ASCQ: 0x{sense_ascq:02x}")

                    if status == StatusType.READY:
                        print("\n🎉 Scanner is READY - film may be loaded!")
                    elif status == StatusType.NO_DOCS:
                        print("\n📭 Scanner reports NO_DOCS - no film detected")
                    else:
                        print(f"\nStatus: {status}")
                else:
                    print(f"\n⚠️  No data received, status: {status}")
            except Exception as e:
                print(f"\n❌ Command test failed: {e}")
                import traceback
                traceback.print_exc()

        else:
            print("\n❌ wait_scanner() failed")

        return success

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if protocol:
            protocol.close()


if __name__ == "__main__":
    success = test_wait_scanner()
    sys.exit(0 if success else 1)






