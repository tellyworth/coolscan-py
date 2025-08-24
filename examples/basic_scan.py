#!/usr/bin/env python3
"""
Basic scanning example for Coolscan tool.

This example demonstrates how to:
1. Find and connect to a scanner
2. Wake up the scanner
3. Get scanner information
4. Perform basic operations
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol


def main():
    """Main function demonstrating basic scanner operations."""
    print("Coolscan Basic Scanning Example")
    print("=" * 40)
    
    # Step 1: Find scanners
    print("\n1. Finding scanners...")
    scanners = find_scanners()
    
    if not scanners:
        print("No scanners found!")
        print("Please check:")
        print("  - Scanner is powered on")
        print("  - USB cable is connected")
        print("  - USB permissions are granted")
        return
    
    print(f"Found {len(scanners)} scanner(s):")
    for i, scanner in enumerate(scanners):
        print(f"  {i+1}. {scanner}")
    
    # Step 2: Connect to first scanner
    scanner = scanners[0]
    print(f"\n2. Connecting to: {scanner}")
    
    try:
        protocol = CoolscanProtocol(scanner)
        print("✓ Connected successfully")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return
    
    # Step 3: Wake up scanner
    print("\n3. Waking up scanner...")
    try:
        if protocol.wake_up():
            print("✓ Scanner woke up successfully")
        else:
            print("✗ Failed to wake up scanner")
            return
    except Exception as e:
        print(f"✗ Wake-up failed: {e}")
        return
    
    # Step 4: Get scanner information
    print("\n4. Getting scanner information...")
    try:
        info = protocol.get_scanner_info()
        if info:
            print("✓ Scanner information:")
            print(f"  Vendor: {info.get('vendor', 'Unknown')}")
            print(f"  Product: {info.get('product', 'Unknown')}")
            print(f"  Revision: {info.get('revision', 'Unknown')}")
        else:
            print("✗ Failed to get scanner information")
    except Exception as e:
        print(f"✗ Get scanner info failed: {e}")
    
    # Step 5: Test basic operations
    print("\n5. Testing basic operations...")
    
    # Test scanner ready
    try:
        ready = protocol._scanner_ready()
        print(f"  Scanner ready: {ready}")
    except Exception as e:
        print(f"  Scanner ready check failed: {e}")
    
    # Test phase check
    try:
        phase = protocol._check_phase()
        print(f"  Current phase: {phase}")
    except Exception as e:
        print(f"  Phase check failed: {e}")
    
    # Step 6: Demonstrate scanner control (if available)
    print("\n6. Testing scanner control...")
    
    # Note: These operations require a loaded film/slide
    print("  Note: Load/eject operations require loaded film/slide")
    
    # Test load (will likely fail without film)
    try:
        print("  Testing load operation...")
        # load_success = protocol.load_medium()
        # print(f"  Load result: {load_success}")
        print("  Load operation not yet implemented")
    except Exception as e:
        print(f"  Load operation failed: {e}")
    
    # Test eject (will likely fail without film)
    try:
        print("  Testing eject operation...")
        # eject_success = protocol.eject_medium()
        # print(f"  Eject result: {eject_success}")
        print("  Eject operation not yet implemented")
    except Exception as e:
        print(f"  Eject operation failed: {e}")
    
    print("\n✓ Basic scanning example completed!")
    print("\nNext steps:")
    print("  - Implement load/eject operations")
    print("  - Add scanning functionality")
    print("  - Implement image processing")
    print("  - Add error recovery")


if __name__ == "__main__":
    main()


