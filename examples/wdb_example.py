#!/usr/bin/env python3
"""
Example demonstrating Window Descriptor Block (WDB) functionality.

This example shows how to create and use WDB structures for scan configuration.
"""

import sys
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "coolscan"))

from device import find_scanners
from protocol import WindowDescriptorBlock, CoolscanProtocol


def demonstrate_wdb():
    """Demonstrate WDB creation and usage."""
    print("Window Descriptor Block (WDB) Example")
    print("=" * 40)
    
    # Create a basic WDB
    print("\n1. Creating basic WDB...")
    wdb = WindowDescriptorBlock()
    print(f"✓ Default WDB created")
    print(f"  Resolution: {wdb.x_resolution}x{wdb.y_resolution} DPI")
    print(f"  Size: {wdb.width}x{wdb.length} pixels")
    print(f"  Brightness: {wdb.brightness}")
    print(f"  Contrast: {wdb.contrast}")
    
    # Create a custom WDB for preview scan
    print("\n2. Creating custom WDB for preview...")
    preview_wdb = WindowDescriptorBlock()
    preview_wdb.x_resolution = 270  # Low resolution for preview
    preview_wdb.y_resolution = 270
    preview_wdb.width = 500  # Small area
    preview_wdb.length = 500
    preview_wdb.brightness = 140  # Slightly brighter
    preview_wdb.contrast = 120   # Slightly more contrast
    preview_wdb.scan_mode = 0x01  # Prescan mode
    
    print(f"✓ Preview WDB created")
    print(f"  Resolution: {preview_wdb.x_resolution}x{preview_wdb.y_resolution} DPI")
    print(f"  Size: {preview_wdb.width}x{preview_wdb.length} pixels")
    print(f"  Scan mode: {'Prescan' if preview_wdb.scan_mode == 0x01 else 'Normal'}")
    
    # Create a custom WDB for negative film
    print("\n3. Creating custom WDB for negative film...")
    negative_wdb = WindowDescriptorBlock()
    negative_wdb.x_resolution = 2700  # High resolution
    negative_wdb.y_resolution = 2700
    negative_wdb.width = 2592  # Full width
    negative_wdb.length = 3888  # Full length
    negative_wdb.negative_dropout = 0x01  # Negative film
    negative_wdb.brightness = 150  # Brighter for negatives
    negative_wdb.contrast = 140   # Higher contrast for negatives
    
    print(f"✓ Negative WDB created")
    print(f"  Resolution: {negative_wdb.x_resolution}x{negative_wdb.y_resolution} DPI")
    print(f"  Film type: {'Negative' if negative_wdb.negative_dropout == 0x01 else 'Positive'}")
    print(f"  Brightness: {negative_wdb.brightness}")
    print(f"  Contrast: {negative_wdb.contrast}")
    
    # Test WDB serialization
    print("\n4. Testing WDB serialization...")
    try:
        # Convert to bytes
        wdb_bytes = wdb.to_bytes()
        print(f"✓ WDB serialized: {len(wdb_bytes)} bytes")
        
        # Parse back from bytes
        wdb_parsed = WindowDescriptorBlock.from_bytes(wdb_bytes)
        print(f"✓ WDB parsed successfully")
        print(f"  Parsed resolution: {wdb_parsed.x_resolution}x{wdb_parsed.y_resolution} DPI")
        
        # Verify they match
        if (wdb.x_resolution == wdb_parsed.x_resolution and 
            wdb.y_resolution == wdb_parsed.y_resolution):
            print("✓ Serialization test passed")
        else:
            print("✗ Serialization test failed")
            
    except Exception as e:
        print(f"✗ Serialization test failed: {e}")
    
    # Test with actual scanner if available
    print("\n5. Testing WDB with scanner (if available)...")
    scanners = find_scanners()
    if scanners:
        scanner = scanners[0]
        print(f"Found scanner: {scanner}")
        
        try:
            protocol = CoolscanProtocol(scanner)
            
            # Try to get current window configuration
            current_wdb = protocol.get_window()
            if current_wdb:
                print(f"✓ Retrieved current WDB from scanner")
                print(f"  Current resolution: {current_wdb.x_resolution}x{current_wdb.y_resolution} DPI")
                print(f"  Current size: {current_wdb.width}x{current_wdb.length} pixels")
            else:
                print("Could not retrieve current WDB (this is normal if scanner is not ready)")
            
            protocol.close()
            
        except Exception as e:
            print(f"Scanner test failed: {e}")
    else:
        print("No scanner found - skipping scanner test")
    
    print("\n✓ WDB demonstration completed!")


if __name__ == "__main__":
    demonstrate_wdb()
