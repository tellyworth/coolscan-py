"""
Device detection for Nikon Coolscan scanners.

This module handles finding and identifying both USB and SCSI/Firewire
Coolscan scanners on the system.
"""

import os
import glob
import subprocess
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

try:
    import usb.core
    import usb.util

    USB_AVAILABLE = True
except ImportError:
    USB_AVAILABLE = False


class InterfaceType(Enum):
    """Scanner interface types."""

    USB = "usb"
    SCSI = "scsi"  # Includes Firewire via SBP2


@dataclass
class ScannerDevice:
    """Represents a detected Coolscan scanner."""

    name: str
    interface: InterfaceType
    vendor: str
    model: str
    revision: str
    device_path: str
    vendor_id: Optional[int] = None
    product_id: Optional[int] = None

    def __str__(self):
        return f"{self.model} ({self.interface.value}:{self.device_path})"


# Known Coolscan USB device IDs
COOLSCAN_USB_DEVICES = {
    (0x04B0, 0x4000): "LS-40 ED",
    (0x04B0, 0x4001): "LS-50 ED",
    (0x04B0, 0x4002): "LS-5000 ED",
}

# Known Coolscan SCSI/Firewire device patterns
COOLSCAN_SCSI_PATTERNS = [
    "LS-4000 ED",
    "LS-8000 ED",
    "COOLSCANIII",
    "LS-30",
    "LS-2000",
]


def find_usb_scanners() -> List[ScannerDevice]:
    """Find USB Coolscan scanners."""
    if not USB_AVAILABLE:
        print("USB support not available (pyusb not installed)")
        return []

    scanners = []
    print(f"Searching for USB Coolscan devices...")

    for (vendor_id, product_id), model_name in COOLSCAN_USB_DEVICES.items():
        print(f"  Checking for {model_name} (0x{vendor_id:04x}:0x{product_id:04x})...")
        try:
            device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
            if device is not None:
                print(f"    Found device!")
                # Get device strings
                try:
                    vendor = usb.util.get_string(device, device.iManufacturer)
                except:
                    vendor = "Nikon"

                try:
                    product = usb.util.get_string(device, device.iProduct)
                except:
                    product = model_name

                try:
                    revision = usb.util.get_string(device, device.iSerialNumber)
                except:
                    revision = "Unknown"

                scanner = ScannerDevice(
                    name=f"usb:{vendor_id:04x}:{product_id:04x}",
                    interface=InterfaceType.USB,
                    vendor=vendor,
                    model=product,
                    revision=revision,
                    device_path=f"{vendor_id:04x}:{product_id:04x}",
                    vendor_id=vendor_id,
                    product_id=product_id,
                )
                scanners.append(scanner)
            else:
                print(f"    Not found")

        except Exception as e:
            print(f"    Error accessing USB device {vendor_id:04x}:{product_id:04x}: {e}")

    return scanners


def find_scsi_scanners() -> List[ScannerDevice]:
    """Find SCSI/Firewire Coolscan scanners."""
    scanners = []
    print(f"Searching for SCSI/Firewire Coolscan devices...")

    # Common SCSI device paths on macOS
    scsi_paths = ["/dev/sg*", "/dev/scsi*", "/dev/disk*"]

    print(f"  Checking device paths: {scsi_paths}")

    for pattern in scsi_paths:
        devices = glob.glob(pattern)
        print(f"  Found {len(devices)} devices matching {pattern}")

        for device_path in devices:
            if os.access(device_path, os.R_OK | os.W_OK):
                try:
                    # Try to get device information using system commands
                    scanner = _probe_scsi_device(device_path)
                    if scanner:
                        scanners.append(scanner)
                except Exception as e:
                    # Silently continue if we can't access this device
                    pass

    return scanners


def _probe_scsi_device(device_path: str) -> Optional[ScannerDevice]:
    """Probe a SCSI device to see if it's a Coolscan scanner."""
    try:
        # Use system_profiler on macOS to get device info
        result = subprocess.run(
            ["system_profiler", "SPFireWireDataType", "SPUSBDataType"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            output = result.stdout

            # Look for Nikon devices
            if "Nikon" in output:
                # Parse the output to find device details
                # This is a simplified approach - in practice you'd want more robust parsing
                for pattern in COOLSCAN_SCSI_PATTERNS:
                    if pattern in output:
                        return ScannerDevice(
                            name=f"scsi:{device_path}",
                            interface=InterfaceType.SCSI,
                            vendor="Nikon",
                            model=pattern,
                            revision="Unknown",
                            device_path=device_path,
                        )

        # Alternative: try to read device directly
        # This would require implementing SCSI INQUIRY command
        # For now, we'll skip this approach

    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        pass

    return None


def find_scanners() -> List[ScannerDevice]:
    """Find all available Coolscan scanners (USB and SCSI/Firewire)."""
    scanners = []

    # Find USB scanners
    usb_scanners = find_usb_scanners()
    scanners.extend(usb_scanners)

    # Find SCSI/Firewire scanners
    scsi_scanners = find_scsi_scanners()
    scanners.extend(scsi_scanners)

    return scanners


def list_scanners():
    """List all detected scanners."""
    scanners = find_scanners()

    if not scanners:
        print("No Coolscan scanners found.")
        return

    print(f"Found {len(scanners)} Coolscan scanner(s):")
    print()

    for i, scanner in enumerate(scanners, 1):
        print(f"{i}. {scanner}")
        print(f"   Interface: {scanner.interface.value}")
        print(f"   Device: {scanner.device_path}")
        print(f"   Vendor: {scanner.vendor}")
        print(f"   Model: {scanner.model}")
        print(f"   Revision: {scanner.revision}")
        if scanner.vendor_id and scanner.product_id:
            print(f"   USB ID: {scanner.vendor_id:04x}:{scanner.product_id:04x}")
        print()


if __name__ == "__main__":
    list_scanners()
