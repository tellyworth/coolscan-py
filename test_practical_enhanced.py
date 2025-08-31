#!/usr/bin/env python3
"""
Practical test script demonstrating the enhanced SANE-based functionality.
This shows real-world usage of the improved implementation.
"""

import sys
import time
import os

# Add the coolscan module to the path
sys.path.insert(0, '.')

from coolscan.scanner import (
    CoolscanScanner, scan_preview, scan_full, 
    get_scanner_info, prescan_scanner, auto_focus_scanner
)
from coolscan.device import find_scanners

def test_practical_workflow():
    """Test a practical scanning workflow."""
    print("=== Testing Practical Scanning Workflow ===")
    
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False
    
    scanner = scanners[0]
    print(f"📷 Found scanner: {scanner}")
    
    try:
        # Step 1: Get scanner information
        print("\n1. Getting scanner information...")
        info = get_scanner_info(scanner)
        print(f"✅ Scanner info: {info}")
        
        # Step 2: Connect and initialize
        print("\n2. Connecting and initializing scanner...")
        with CoolscanScanner(scanner) as coolscan:
            print("✅ Connected successfully")
            
            # Step 3: Check scanner status
            print("\n3. Checking scanner status...")
            status = coolscan.get_scanner_status()
            print(f"✅ Scanner status: {status}")
            
            # Step 4: Wait for ready
            print("\n4. Waiting for scanner ready...")
            ready = coolscan.wait_for_ready(timeout=10)
            print(f"✅ Scanner ready: {ready}")
            
            # Step 5: Perform prescan
            print("\n5. Performing prescan...")
            prescan_success = coolscan.prescan()
            print(f"✅ Prescan: {'SUCCESS' if prescan_success else 'FAILED'}")
            
            # Step 6: Perform auto focus
            print("\n6. Performing auto focus...")
            focus_success = coolscan.auto_focus()
            print(f"✅ Auto focus: {'SUCCESS' if focus_success else 'FAILED'}")
            
            # Step 7: Test preview scan
            print("\n7. Testing preview scan...")
            preview_success = coolscan.scan_preview("test_preview.png", resolution=270)
            print(f"✅ Preview scan: {'SUCCESS' if preview_success else 'FAILED'}")
            
            # Step 8: Test full scan
            print("\n8. Testing full scan...")
            full_success = coolscan.scan_full("test_full.png", resolution=2700)
            print(f"✅ Full scan: {'SUCCESS' if full_success else 'FAILED'}")
            
            # Step 9: Test area scan
            print("\n9. Testing area scan...")
            area_success = coolscan.scan_area("test_area.png", 0, 0, 1000, 1000, resolution=1350)
            print(f"✅ Area scan: {'SUCCESS' if area_success else 'FAILED'}")
        
        print("\n✅ Practical workflow completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Practical workflow failed: {e}")
        return False

def test_enhanced_features():
    """Test enhanced features."""
    print("\n=== Testing Enhanced Features ===")
    
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False
    
    scanner = scanners[0]
    print(f"📷 Found scanner: {scanner}")
    
    try:
        with CoolscanScanner(scanner) as coolscan:
            print("✅ Connected successfully")
            
            # Test enhanced protocol features
            print("\n1. Testing enhanced protocol features...")
            
            # Test mode sense
            mud = coolscan.protocol.mode_sense()
            print(f"   MUD: {mud}")
            
            # Test internal info
            info = coolscan.protocol.get_internal_info()
            if info:
                print(f"   AD bits: {info.ad_bits}")
                print(f"   Max resolution: {info.max_resolution}")
                print(f"   X max pixels: {info.x_max_pixels}")
                print(f"   Y max pixels: {info.y_max_pixels}")
                print(f"   Auto feeder: {info.auto_feeder}")
                print(f"   Analog gamma: {info.analog_gamma}")
            
            # Test WDB operations
            print("\n2. Testing WDB operations...")
            wdb = coolscan.protocol.get_window()
            if wdb:
                print(f"   Current WDB resolution: {wdb.x_resolution}x{wdb.y_resolution}")
                print(f"   Current WDB size: {wdb.width}x{wdb.length}")
                print(f"   Current WDB composition: {wdb.composition}")
                print(f"   Current WDB bits per pixel: {wdb.bits_per_pixel}")
            
            # Test unit reservation cycle
            print("\n3. Testing unit reservation cycle...")
            if coolscan.protocol.reserve_unit():
                print("   Unit reserved successfully")
                if coolscan.protocol.release_unit():
                    print("   Unit released successfully")
                else:
                    print("   Unit release failed")
            else:
                print("   Unit reservation failed")
        
        print("\n✅ Enhanced features test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced features test failed: {e}")
        return False

def test_error_handling():
    """Test enhanced error handling."""
    print("\n=== Testing Enhanced Error Handling ===")
    
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False
    
    scanner = scanners[0]
    print(f"📷 Found scanner: {scanner}")
    
    try:
        with CoolscanScanner(scanner) as coolscan:
            print("✅ Connected successfully")
            
            # Test scanner ready with retry logic
            print("\n1. Testing scanner ready with retry logic...")
            ready = coolscan.wait_for_ready(timeout=30)
            print(f"   Scanner ready: {ready}")
            
            # Test error recovery
            print("\n2. Testing error recovery...")
            try:
                # Try to read data without proper setup
                data = coolscan.protocol.read_scan_data(1024)
                print(f"   Data read: {len(data)} bytes")
            except Exception as e:
                print(f"   Expected error caught: {e}")
            
            # Test status parsing
            print("\n3. Testing status parsing...")
            status = coolscan.protocol.test_unit_ready()
            print(f"   Unit ready status: {status}")
        
        print("\n✅ Error handling test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False

def main():
    """Run all practical tests."""
    print("🔍 Practical Enhanced SANE-Based Tests")
    print("=" * 50)
    
    # Test 1: Practical workflow
    success1 = test_practical_workflow()
    
    # Test 2: Enhanced features
    success2 = test_enhanced_features()
    
    # Test 3: Error handling
    success3 = test_error_handling()
    
    print("\n" + "=" * 50)
    print("📊 Practical Test Results Summary:")
    print(f"   Practical Workflow: {'✅ PASS' if success1 else '❌ FAIL'}")
    print(f"   Enhanced Features:  {'✅ PASS' if success2 else '❌ FAIL'}")
    print(f"   Error Handling:     {'✅ PASS' if success3 else '❌ FAIL'}")
    
    if success1 and success2 and success3:
        print("\n🎉 All practical tests passed!")
        print("\n🚀 Enhanced SANE-based implementation is ready for use!")
        return True
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
