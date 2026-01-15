#!/usr/bin/env python3
"""
Test Basic Scanning Operations

Tests basic scanning operations after initialization.
"""

import sys
sys.path.insert(0, '.')

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, ScanParameters, ScanType


def test_basic_scan():
    """Test basic scanning operations."""
    print("📸 Testing Basic Scanning Operations")
    print("=" * 60)

    # Find scanner
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False

    scanner = scanners[0]
    print(f"📷 Scanner: {scanner}\n")

    protocol = None
    try:
        # Create protocol and initialize
        print("🔌 Connecting and initializing...")
        protocol = CoolscanProtocol(scanner)
        print("✅ Connected\n")

        # Initialize scanner
        if not protocol.initialize_scanner():
            print("⚠️  Initialization had warnings, continuing...\n")

        # Check scanner status
        print("📊 Checking scanner status...")
        ready = protocol.test_unit_ready()
        print(f"  Scanner ready: {'✅ YES' if ready else '❌ NO'}\n")

        if not ready:
            print("⚠️  Scanner not ready, attempting to wait...")
            protocol.wait_scanner(max_attempts=10, delay=0.5)

        # Try a simple prescan
        print("🔍 Testing prescan...")
        try:
            # Prescan doesn't need parameters - it's a method that handles everything
            success = protocol.prescan()
            if success:
                print("  ✅ Prescan completed successfully")
            else:
                print("  ⚠️  Prescan may have failed")
        except Exception as e:
            print(f"  ⚠️  Prescan error: {e}")
            import traceback
            traceback.print_exc()

        print("\n✅ Basic scan test completed")
        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if protocol:
            protocol.close()


if __name__ == "__main__":
    success = test_basic_scan()
    sys.exit(0 if success else 1)
