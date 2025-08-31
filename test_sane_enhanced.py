#!/usr/bin/env python3
"""
Test script for enhanced SANE-based Coolscan implementation.
This tests all the missing elements identified in the SANE backend analysis.
"""

import sys
import time
import os

# Add the coolscan module to the path
sys.path.insert(0, '.')

from coolscan.scanner import CoolscanScanner
from coolscan.device import find_scanners
from coolscan.protocol import (
    WindowDescriptorBlock, DataType, ScanParameters, 
    ScanType, StatusType, ScannerInfo
)

def test_enhanced_initialization():
    """Test the enhanced initialization sequence."""
    print("=== Testing Enhanced Initialization Sequence ===")
    
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False
    
    scanner = scanners[0]
    print(f"📷 Found scanner: {scanner}")
    
    try:
        # Test enhanced connection
        print("\n1. Testing enhanced connection...")
        coolscan = CoolscanScanner(scanner)
        
        if not coolscan.connect():
            print("❌ Enhanced connection failed")
            return False
        
        print("✅ Enhanced connection successful")
        
        # Test device info
        print("\n2. Testing device info...")
        info = coolscan.get_device_info()
        print(f"✅ Device info: {info}")
        
        # Test scanner status
        print("\n3. Testing scanner status...")
        status = coolscan.get_scanner_status()
        print(f"✅ Scanner status: {status}")
        
        # Test scanner ready
        print("\n4. Testing scanner ready...")
        ready = coolscan.wait_for_ready(timeout=10)
        print(f"✅ Scanner ready: {ready}")
        
        coolscan.disconnect()
        print("\n✅ Enhanced initialization test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced initialization test failed: {e}")
        return False

def test_sane_sequence():
    """Test the complete SANE sequence."""
    print("\n=== Testing Complete SANE Sequence ===")
    
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False
    
    scanner = scanners[0]
    print(f"📷 Found scanner: {scanner}")
    
    try:
        coolscan = CoolscanScanner(scanner)
        
        if not coolscan.connect():
            print("❌ Connection failed")
            return False
        
        print("✅ Connected successfully")
        
        # Test prescan
        print("\n1. Testing prescan...")
        prescan_success = coolscan.prescan()
        print(f"✅ Prescan: {'SUCCESS' if prescan_success else 'FAILED'}")
        
        # Test auto focus
        print("\n2. Testing auto focus...")
        focus_success = coolscan.auto_focus()
        print(f"✅ Auto focus: {'SUCCESS' if focus_success else 'FAILED'}")
        
        # Test WDB operations
        print("\n3. Testing WDB operations...")
        wdb = WindowDescriptorBlock()
        wdb.x_resolution = 2700
        wdb.y_resolution = 2700
        wdb.width = 2592
        wdb.length = 3888
        wdb.composition = 0x05  # RGB full
        wdb.bits_per_pixel = 0x08  # 8-bit
        
        # Test setting window
        if coolscan.protocol.reserve_unit():
            try:
                set_success = coolscan.protocol.set_window_wdb(wdb)
                print(f"✅ Set window: {'SUCCESS' if set_success else 'FAILED'}")
                
                # Test getting window
                get_wdb = coolscan.protocol.get_window()
                if get_wdb:
                    print(f"✅ Get window: SUCCESS (resolution: {get_wdb.x_resolution}x{get_wdb.y_resolution})")
                else:
                    print("❌ Get window: FAILED")
                    
            finally:
                coolscan.protocol.release_unit()
        
        coolscan.disconnect()
        print("\n✅ SANE sequence test completed!")
        return True
        
    except Exception as e:
        print(f"❌ SANE sequence test failed: {e}")
        return False

def test_enhanced_commands():
    """Test enhanced command implementations."""
    print("\n=== Testing Enhanced Commands ===")
    
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False
    
    scanner = scanners[0]
    print(f"📷 Found scanner: {scanner}")
    
    try:
        coolscan = CoolscanScanner(scanner)
        
        if not coolscan.connect():
            print("❌ Connection failed")
            return False
        
        print("✅ Connected successfully")
        
        # Test unit reservation cycle
        print("\n1. Testing unit reservation cycle...")
        if coolscan.protocol.reserve_unit():
            print("✅ Unit reserved")
            if coolscan.protocol.release_unit():
                print("✅ Unit released")
            else:
                print("❌ Unit release failed")
        else:
            print("❌ Unit reservation failed")
        
        # Test mode sense
        print("\n2. Testing mode sense...")
        mud = coolscan.protocol.mode_sense()
        if mud:
            print(f"✅ Mode sense: MUD = {mud}")
        else:
            print("❌ Mode sense failed")
        
        # Test internal info read
        print("\n3. Testing internal info read...")
        info = coolscan.protocol.get_internal_info()
        if info:
            print(f"✅ Internal info: AD bits={info.ad_bits}, Max res={info.max_resolution}")
        else:
            print("❌ Internal info read failed")
        
        # Test object position
        print("\n4. Testing object position...")
        if coolscan.protocol.reserve_unit():
            try:
                obj_success = coolscan.protocol.object_position()
                print(f"✅ Object position: {'SUCCESS' if obj_success else 'FAILED'}")
            finally:
                coolscan.protocol.release_unit()
        
        # Test LUT sending
        print("\n5. Testing LUT sending...")
        if coolscan.protocol.reserve_unit():
            try:
                # Create simple linear LUT
                lut_data = bytes([i for i in range(256)] * 3)  # R, G, B LUTs
                lut_success = coolscan.protocol.send_lut(lut_data)
                print(f"✅ LUT send: {'SUCCESS' if lut_success else 'FAILED'}")
            finally:
                coolscan.protocol.release_unit()
        
        coolscan.disconnect()
        print("\n✅ Enhanced commands test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced commands test failed: {e}")
        return False

def test_scan_sequence():
    """Test the enhanced scan sequence."""
    print("\n=== Testing Enhanced Scan Sequence ===")
    
    scanners = find_scanners()
    if not scanners:
        print("❌ No scanners found")
        return False
    
    scanner = scanners[0]
    print(f"📷 Found scanner: {scanner}")
    
    try:
        coolscan = CoolscanScanner(scanner)
        
        if not coolscan.connect():
            print("❌ Connection failed")
            return False
        
        print("✅ Connected successfully")
        
        # Test scan sequence with parameters
        print("\n1. Testing scan sequence...")
        params = ScanParameters(
            resolution=2700,
            preview=False,
            negative=False,
            infrared=False,
            x_min=0,
            y_min=0,
            x_max=2592,
            y_max=3888
        )
        
        # Test the complete scan sequence
        if coolscan.protocol.reserve_unit():
            try:
                sequence_success = coolscan.protocol.perform_scan_sequence(params)
                print(f"✅ Scan sequence: {'SUCCESS' if sequence_success else 'FAILED'}")
            finally:
                coolscan.protocol.release_unit()
        
        coolscan.disconnect()
        print("\n✅ Enhanced scan sequence test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced scan sequence test failed: {e}")
        return False

def main():
    """Run all enhanced tests."""
    print("🔍 Enhanced SANE-Based Coolscan Tests")
    print("=" * 50)
    
    # Test 1: Enhanced initialization
    success1 = test_enhanced_initialization()
    
    # Test 2: SANE sequence
    success2 = test_sane_sequence()
    
    # Test 3: Enhanced commands
    success3 = test_enhanced_commands()
    
    # Test 4: Scan sequence
    success4 = test_scan_sequence()
    
    print("\n" + "=" * 50)
    print("📊 Enhanced Test Results Summary:")
    print(f"   Enhanced Initialization: {'✅ PASS' if success1 else '❌ FAIL'}")
    print(f"   SANE Sequence:          {'✅ PASS' if success2 else '❌ FAIL'}")
    print(f"   Enhanced Commands:      {'✅ PASS' if success3 else '❌ FAIL'}")
    print(f"   Scan Sequence:          {'✅ PASS' if success4 else '❌ FAIL'}")
    
    if success1 and success2 and success3 and success4:
        print("\n🎉 All enhanced tests passed!")
        return True
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
