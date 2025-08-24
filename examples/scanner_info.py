#!/usr/bin/env python3
"""
Scanner Information Example

This example demonstrates how to get detailed information about a Coolscan scanner.
"""

import sys
from pathlib import Path

# Add the coolscan directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "coolscan"))

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol


def print_scanner_details(scanner):
    """Print detailed information about a scanner."""
    print(f"\nScanner Details:")
    print(f"  Name: {scanner.name}")
    print(f"  Interface: {scanner.interface}")
    print(f"  Model: {scanner.model}")
    
    if hasattr(scanner, 'vendor_id'):
        print(f"  Vendor ID: 0x{scanner.vendor_id:04x}")
    if hasattr(scanner, 'product_id'):
        print(f"  Product ID: 0x{scanner.product_id:04x}")
    if hasattr(scanner, 'serial_number'):
        print(f"  Serial Number: {scanner.serial_number}")


def print_system_info():
    """Print system information relevant to scanner operation."""
    import platform
    import subprocess
    
    print(f"\nSystem Information:")
    print(f"  OS: {platform.system()} {platform.release()}")
    print(f"  Architecture: {platform.machine()}")
    print(f"  Python: {platform.python_version()}")
    
    # Check for USB devices
    try:
        result = subprocess.run(['system_profiler', 'SPUSBDataType'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            nikon_lines = [line for line in lines if 'Nikon' in line or 'Coolscan' in line]
            if nikon_lines:
                print(f"  USB Devices:")
                for line in nikon_lines:
                    print(f"    {line.strip()}")
    except Exception as e:
        print(f"  Could not get USB device info: {e}")


def main():
    """Main function for scanner information example."""
    print("Coolscan Scanner Information Example")
    print("=" * 50)
    
    # Print system information
    print_system_info()
    
    # Find scanners
    print(f"\nSearching for Coolscan scanners...")
    scanners = find_scanners()
    
    if not scanners:
        print("No scanners found!")
        print("\nTroubleshooting:")
        print("  1. Check if scanner is powered on")
        print("  2. Verify USB cable connection")
        print("  3. Check USB permissions in System Preferences")
        print("  4. Try different USB port")
        print("  5. Restart scanner")
        return
    
    print(f"Found {len(scanners)} scanner(s):")
    
    # Print details for each scanner
    for i, scanner in enumerate(scanners):
        print(f"\n--- Scanner {i+1} ---")
        print_scanner_details(scanner)
        
        # Try to get additional information via protocol
        try:
            print(f"\nAttempting to connect to scanner {i+1}...")
            protocol = CoolscanProtocol(scanner)
            
            # Wake up scanner
            print("  Waking up scanner...")
            if protocol.wake_up():
                print("  ✓ Scanner woke up successfully")
                
                # Get scanner information
                print("  Getting scanner information...")
                info = protocol.get_scanner_info()
                if info:
                    print("  ✓ Scanner Information:")
                    print(f"    Vendor: {info.get('vendor', 'Unknown')}")
                    print(f"    Product: {info.get('product', 'Unknown')}")
                    print(f"    Revision: {info.get('revision', 'Unknown')}")
                    
                    # Try to get capabilities
                    print("  Getting scanner capabilities...")
                    try:
                        capabilities = protocol.get_scanner_capabilities()
                        if capabilities:
                            print("  ✓ Scanner Capabilities:")
                            for key, value in capabilities.items():
                                print(f"    {key}: {value}")
                        else:
                            print("  ⚠ Could not get capabilities")
                    except Exception as e:
                        print(f"  ⚠ Capabilities check failed: {e}")
                else:
                    print("  ✗ Failed to get scanner information")
            else:
                print("  ✗ Failed to wake up scanner")
                
        except Exception as e:
            print(f"  ✗ Connection failed: {e}")
    
    print(f"\n" + "=" * 50)
    print("Scanner information example completed!")
    
    if scanners:
        print(f"\nNext steps:")
        print(f"  - Try the basic_scan.py example")
        print(f"  - Check the troubleshooting guide")
        print(f"  - Review the protocol documentation")


if __name__ == "__main__":
    main()
