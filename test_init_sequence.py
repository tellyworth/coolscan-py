#!/usr/bin/env python3
"""
Test Full Initialization Sequence

Tests the complete initialization sequence from USB capture analysis.
"""

import sys
sys.path.insert(0, '.')

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol


def test_init_sequence():
    """Test the full initialization sequence."""
    print("🔧 Testing Full Initialization Sequence")
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
        # Create protocol (this does USB initialization)
        print("🔌 Connecting...")
        protocol = CoolscanProtocol(scanner)
        print("✅ Connected\n")

        # Run full initialization sequence
        print("🚀 Running initialization sequence...")
        success = protocol.initialize_scanner()

        if success:
            print("\n✅ Initialization sequence completed successfully!")
            return True
        else:
            print("\n❌ Initialization sequence failed")
            return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if protocol:
            protocol.close()


if __name__ == "__main__":
    success = test_init_sequence()
    sys.exit(0 if success else 1)
