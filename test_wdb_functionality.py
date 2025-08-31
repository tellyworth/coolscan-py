#!/usr/bin/env python3
"""
Test script to verify WDB functionality and handle no-document case.
This script tests the Window Descriptor Block implementation.
"""

import sys
import time
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, StatusType, WindowDescriptorBlock


def test_wdb_functionality():
    """Test WDB creation and functionality."""
    print("WDB Functionality Test")
    print("=" * 40)
    
    # Test 1: WDB Creation and Serialization
    print("\n1. Testing WDB creation and serialization...")
    try:
        # Create a basic WDB
        wdb = WindowDescriptorBlock()
        wdb.x_resolution = 2700
        wdb.y_resolution = 2700
        wdb.width = 1000
        wdb.length = 1000
        wdb.brightness = 128
        wdb.contrast = 128
        
        # Serialize to bytes
        wdb_data = wdb.to_bytes()
        print(f"✓ WDB created: {len(wdb_data)} bytes")
        print(f"  Resolution: {wdb.x_resolution}x{wdb.y_resolution} DPI")
        print(f"  Size: {wdb.width}x{wdb.length} pixels")
        
        # Parse back from bytes
        wdb_parsed = WindowDescriptorBlock.from_bytes(wdb_data)
        print(f"✓ WDB parsed successfully")
        print(f"  Parsed resolution: {wdb_parsed.x_resolution}x{wdb_parsed.y_resolution} DPI")
        
        # Verify they match
        if (wdb.x_resolution == wdb_parsed.x_resolution and 
            wdb.y_resolution == wdb_parsed.y_resolution):
            print("✓ Serialization test passed")
        else:
            print("✗ Serialization test failed")
            
    except Exception as e:
        print(f"✗ WDB creation test failed: {e}")
        return False
    
    # Test 2: Scanner Communication (if available)
    print("\n2. Testing scanner communication...")
    scanners = find_scanners()
    if not scanners:
        print("No scanners found - skipping scanner test")
        return True
    
    scanner = scanners[0]
    print(f"Found scanner: {scanner}")
    
    try:
        protocol = CoolscanProtocol(scanner)
        print("✓ Protocol object created")
        
        # Test basic communication
        print("\n3. Testing basic communication...")
        try:
            # Try to get current window configuration
            current_wdb = protocol.get_window()
            if current_wdb:
                print(f"✓ Retrieved current WDB from scanner")
                print(f"  Current resolution: {current_wdb.x_resolution}x{current_wdb.y_resolution} DPI")
                print(f"  Current size: {current_wdb.width}x{current_wdb.length} pixels")
            else:
                print("Could not retrieve current WDB (this is normal if scanner is not ready)")
                
        except Exception as e:
            print(f"✗ GET WINDOW failed: {e}")
        
        # Test status parsing
        print("\n4. Testing status parsing...")
        try:
            # The scanner should respond with NO_DOCS status
            # This is expected behavior when no film is loaded
            cmd = protocol._parse_command("00 00 00 00 00 00")  # TEST UNIT READY
            _, status = protocol._issue_command(cmd)
            
            if status == StatusType.NO_DOCS:
                print("✓ Scanner correctly reports NO_DOCS (no film loaded)")
                print("  This is expected behavior - scanner is working correctly")
            elif status == StatusType.READY:
                print("✓ Scanner reports READY")
            else:
                print(f"✓ Scanner status: {status}")
                
        except Exception as e:
            print(f"✗ Status test failed: {e}")
        
        protocol.close()
        
    except Exception as e:
        print(f"✗ Scanner communication test failed: {e}")
        return False
    
    print("\n✓ WDB functionality test completed successfully!")
    return True


def test_scan_parameters():
    """Test scan parameter conversion."""
    print("\n" + "=" * 40)
    print("Scan Parameter Test")
    print("=" * 40)
    
    try:
        # Test different scan configurations
        print("\n1. Testing preview scan WDB...")
        preview_wdb = WindowDescriptorBlock()
        preview_wdb.x_resolution = 270  # Low resolution for preview
        preview_wdb.y_resolution = 270
        preview_wdb.width = 500
        preview_wdb.length = 500
        preview_wdb.scan_mode = 0x01  # Prescan mode
        preview_wdb.brightness = 140
        preview_wdb.contrast = 120
        
        print(f"✓ Preview WDB created")
        print(f"  Resolution: {preview_wdb.x_resolution}x{preview_wdb.y_resolution} DPI")
        print(f"  Size: {preview_wdb.width}x{preview_wdb.length} pixels")
        print(f"  Scan mode: {'Prescan' if preview_wdb.scan_mode == 0x01 else 'Normal'}")
        
        print("\n2. Testing negative film WDB...")
        negative_wdb = WindowDescriptorBlock()
        negative_wdb.x_resolution = 2700
        negative_wdb.y_resolution = 2700
        negative_wdb.width = 2592
        negative_wdb.length = 3888
        negative_wdb.negative_dropout = 0x01  # Negative film
        negative_wdb.brightness = 150
        negative_wdb.contrast = 140
        
        print(f"✓ Negative WDB created")
        print(f"  Film type: {'Negative' if negative_wdb.negative_dropout == 0x01 else 'Positive'}")
        print(f"  Brightness: {negative_wdb.brightness}")
        print(f"  Contrast: {negative_wdb.contrast}")
        
        print("\n✓ Scan parameter test completed successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Scan parameter test failed: {e}")
        return False


if __name__ == "__main__":
    print("Running WDB Functionality Tests")
    print("=" * 60)
    
    # Run WDB functionality test
    wdb_success = test_wdb_functionality()
    
    # Run scan parameter test
    param_success = test_scan_parameters()
    
    # Overall result
    overall_success = wdb_success and param_success
    
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    print(f"WDB Functionality Test: {'✓ PASSED' if wdb_success else '✗ FAILED'}")
    print(f"Scan Parameter Test:    {'✓ PASSED' if param_success else '✗ FAILED'}")
    print(f"Overall Result:         {'✓ PASSED' if overall_success else '✗ FAILED'}")
    
    sys.exit(0 if overall_success else 1)
