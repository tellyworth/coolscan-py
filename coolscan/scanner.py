"""
High-level scanner operations for Nikon Coolscan scanners.

This module provides easy-to-use functions for common scanning operations.
"""

import time
from typing import Optional, Tuple, List
from PIL import Image
import numpy as np

from .device import ScannerDevice
from .protocol import (
    CoolscanProtocol,
    ScanParameters,
    ScanType,
    StatusType,
    WindowDescriptorBlock,
    DataType,
    ScannerInfo,
)


class CoolscanScanner:
    """High-level interface for Coolscan scanner operations."""

    def __init__(self, device: ScannerDevice):
        self.device = device
        self.protocol = None
        self.is_connected = False
        self.scan_in_progress = False
        self.scanner_info = None

    def connect(self) -> bool:
        """Connect to the scanner using enhanced SANE sequence."""
        try:
            print("Connecting to scanner...")
            self.protocol = CoolscanProtocol(self.device)

            # Initialize scanner with full SANE sequence
            if not self.protocol.initialize_scanner():
                raise RuntimeError("Scanner initialization failed")

            # Get scanner info
            self.scanner_info = self.protocol.get_internal_info()

            self.is_connected = True
            print("Scanner connected successfully")
            return True

        except Exception as e:
            print(f"Failed to connect to scanner: {e}")
            self.is_connected = False
            return False

    def disconnect(self):
        """Disconnect from the scanner."""
        if self.protocol:
            if self.scan_in_progress:
                self.cancel_scan()

            try:
                self.protocol.release_unit()
            except:
                pass

            try:
                self.protocol.close()
            except:
                pass

        self.protocol = None
        self.is_connected = False
        self.scan_in_progress = False
        self.scanner_info = None

    def get_device_info(self) -> dict:
        """Get detailed device information."""
        if not self.is_connected:
            raise RuntimeError("Scanner not connected")

        try:
            # Get standard inquiry data
            inquiry_data = self.protocol.inquiry()

            if len(inquiry_data) >= 36:
                vendor = inquiry_data[8:16].decode("ascii", errors="ignore").strip()
                product = inquiry_data[16:32].decode("ascii", errors="ignore").strip()
                revision = inquiry_data[32:36].decode("ascii", errors="ignore").strip()

                info = {
                    "vendor": vendor,
                    "product": product,
                    "revision": revision,
                    "interface": self.device.interface.value,
                    "device_path": self.device.device_path,
                }

                # Add scanner info if available
                if self.scanner_info:
                    info.update(
                        {
                            "ad_bits": self.scanner_info.ad_bits,
                            "output_bits": self.scanner_info.output_bits,
                            "max_resolution": self.scanner_info.max_resolution,
                            "x_max_pixels": self.scanner_info.x_max_pixels,
                            "y_max_pixels": self.scanner_info.y_max_pixels,
                            "auto_feeder": bool(self.scanner_info.auto_feeder),
                            "analog_gamma": bool(self.scanner_info.analog_gamma),
                            "device_errors": self.scanner_info.device_errors,
                        }
                    )

                return info
            else:
                return {
                    "vendor": self.device.vendor,
                    "product": self.device.model,
                    "revision": self.device.revision,
                    "interface": self.device.interface.value,
                    "device_path": self.device.device_path,
                }

        except Exception as e:
            print(f"Error getting device info: {e}")
            return {
                "vendor": self.device.vendor,
                "product": self.device.model,
                "revision": self.device.revision,
                "interface": self.device.interface.value,
                "device_path": self.device.device_path,
                "error": str(e),
            }

    def scan_preview(self, output_path: str, resolution: int = 270) -> bool:
        """Perform a preview scan."""
        params = ScanParameters(
            resolution=resolution,
            preview=True,
            x_min=0,
            y_min=0,
            x_max=1000,  # Small preview area
            y_max=1000,
        )

        return self._perform_scan(params, output_path, "preview")

    def scan_full(
        self,
        output_path: str,
        resolution: int = 2700,
        negative: bool = False,
        infrared: bool = False,
        depth: int = 8,
    ) -> bool:
        """Perform a full resolution scan."""
        params = ScanParameters(
            resolution=resolution,
            preview=False,
            negative=negative,
            infrared=infrared,
            depth=depth,
            x_min=0,
            y_min=0,
            x_max=0,  # Full area
            y_max=0,
        )

        return self._perform_scan(params, output_path, "full")

    def scan_area(
        self,
        output_path: str,
        x_min: int,
        y_min: int,
        x_max: int,
        y_max: int,
        resolution: int = 2700,
    ) -> bool:
        """Scan a specific area."""
        params = ScanParameters(
            resolution=resolution, preview=False, x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max
        )

        return self._perform_scan(params, output_path, "area")

    def prescan(self) -> bool:
        """Perform a prescan operation."""
        if not self.is_connected:
            raise RuntimeError("Scanner not connected")

        if self.scan_in_progress:
            raise RuntimeError("Scan already in progress")

        try:
            print("Starting prescan...")

            # Session-level reservation happens during connect(); do not
            # reserve/release per operation.
            success = self.protocol.prescan()

            if success:
                print("Prescan completed successfully")
            else:
                print("Prescan failed")

            return success

        except Exception as e:
            print(f"Prescan failed: {e}")
            return False

    def auto_focus(self) -> bool:
        """Perform auto focus operation."""
        if not self.is_connected:
            raise RuntimeError("Scanner not connected")

        try:
            print("Performing auto focus...")

            # Session-level reservation happens during connect(); do not
            # reserve/release per operation.
            success = self.protocol.auto_focus()

            if success:
                print("Auto focus completed successfully")
            else:
                print("Auto focus failed")

            return success

        except Exception as e:
            print(f"Auto focus failed: {e}")
            return False

    def _perform_scan(self, params: ScanParameters, output_path: str, scan_type: str) -> bool:
        """Perform a scan with the given parameters using enhanced SANE sequence."""
        if not self.is_connected:
            raise RuntimeError("Scanner not connected")

        if self.scan_in_progress:
            raise RuntimeError("Scan already in progress")

        try:
            print(f"Starting {scan_type} scan...")

            # Use the capture-informed full-scan frame sequence.
            if not self.protocol.full_scan_frame(params):
                raise RuntimeError("Scan sequence failed")

            self.scan_in_progress = True

            # Read scan data with proper datatype
            print("Reading scan data...")

            # Calculate expected data size
            width = (
                params.x_max
                if params.x_max > 0
                else (self.scanner_info.x_max_pixels if self.scanner_info else 2592)
            )
            height = (
                params.y_max
                if params.y_max > 0
                else (self.scanner_info.y_max_pixels if self.scanner_info else 3888)
            )

            if params.infrared:
                # 4-channel image (RGB + IR)
                num_channels = 4
                datatype = DataType.IMAGE_DATA  # For RGBI data
            else:
                # 3-channel RGB image
                num_channels = 3
                datatype = DataType.IMAGE_DATA

            bytes_per_channel = 2 if params.depth > 8 else 1
            bytes_per_pixel = num_channels * bytes_per_channel
            total_bytes = width * height * bytes_per_pixel

            # Read scan data in chunks
            chunk_size = 64 * 1024  # 64KB chunks
            scan_data = bytearray()

            for offset in range(0, total_bytes, chunk_size):
                chunk_length = min(chunk_size, total_bytes - offset)
                chunk_data = self.protocol.read_scan_data(chunk_length, datatype)
                scan_data.extend(chunk_data)

                # Progress indicator
                progress = (offset + chunk_length) / total_bytes * 100
                print(f"Scan progress: {progress:.1f}%")

            # Drain any residual image data left in the scanner buffer.
            # On real hardware the scanner may buffer more data than the
            # expected pixel count; unread data causes eject_medium() to fail
            # with ILLEGAL REQUEST / COMMAND SEQUENCE ERROR.  The golden
            # fixture shows a short-read at the end of the image stream;
            # we replicate that by reading 64 KB chunks until the scanner
            # returns fewer bytes than requested (short read = end of data).
            # Skip this for replay mode — the fixture already encodes the
            # short-read and we must not consume extra events.
            if self.protocol._usb_capture_replay is None:
                try:
                    drain_chunk = self.protocol.read_scan_data(65536, datatype)
                    while len(drain_chunk) == 65536:
                        drain_chunk = self.protocol.read_scan_data(65536, datatype)
                    if drain_chunk:
                        scan_data.extend(drain_chunk)
                        print(f"  Drained {len(drain_chunk)} trailing bytes")
                except Exception:
                    pass  # Non-fatal: scanner may have already stalled

            # Convert scan data to image
            if params.depth > 8:
                # 12-bit: 16-bit big-endian containers, shift >> 4 for top 8 bits
                image_data = np.frombuffer(scan_data, dtype=np.uint16)
                image_data = image_data.reshape((height, width, num_channels))
                image_data = (image_data >> 4).astype(np.uint8)
            else:
                # 8-bit: existing behavior
                image_data = np.array(scan_data, dtype=np.uint8)
                image_data = image_data.reshape((height, width, num_channels))

            if params.infrared:
                image = Image.fromarray(image_data, "RGBA")
            else:
                image = Image.fromarray(image_data, "RGB")

            # Save the image
            image.save(output_path)

            print(f"Scan completed and saved to {output_path}")
            self.scan_in_progress = False
            # Session-level reservation is released in disconnect(); do not
            # release per-operation to match the capture's one-reserve session.
            return True

        except Exception as e:
            print(f"Scan failed: {e}")
            if self.scan_in_progress:
                self.cancel_scan()
            return False

    def cancel_scan(self) -> bool:
        """Cancel the current scan operation."""
        if not self.scan_in_progress:
            return True

        try:
            if self.protocol.cancel_scan():
                self.scan_in_progress = False
                print("Scan cancelled")
                return True
            else:
                print("Failed to cancel scan")
                return False
        except Exception as e:
            print(f"Error cancelling scan: {e}")
            return False

    def wait_for_ready(self, timeout: int = 30) -> bool:
        """Wait for the scanner to be ready."""
        if not self.is_connected:
            return False

        return self.protocol.scanner_ready(timeout)

    def get_scanner_status(self) -> dict:
        """Get current scanner status."""
        if not self.is_connected:
            return {"status": "disconnected"}

        try:
            ready = self.protocol.test_unit_ready()
            return {
                "status": "ready" if ready else "not_ready",
                "scan_in_progress": self.scan_in_progress,
                "scanner_info": self.scanner_info.__dict__ if self.scanner_info else None,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def __enter__(self):
        """Context manager entry."""
        if not self.connect():
            raise RuntimeError("Failed to connect to scanner")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


def scan_preview(device: ScannerDevice, output_path: str, resolution: int = 270) -> bool:
    """Quick preview scan function."""
    with CoolscanScanner(device) as scanner:
        return scanner.scan_preview(output_path, resolution)


def scan_full(
    device: ScannerDevice,
    output_path: str,
    resolution: int = 2700,
    negative: bool = False,
    infrared: bool = False,
) -> bool:
    """Quick full scan function."""
    with CoolscanScanner(device) as scanner:
        return scanner.scan_full(output_path, resolution, negative, infrared)


def get_scanner_info(device: ScannerDevice) -> dict:
    """Get scanner information."""
    with CoolscanScanner(device) as scanner:
        return scanner.get_device_info()


def prescan_scanner(device: ScannerDevice) -> bool:
    """Perform prescan operation."""
    with CoolscanScanner(device) as scanner:
        return scanner.prescan()


def auto_focus_scanner(device: ScannerDevice) -> bool:
    """Perform auto focus operation."""
    with CoolscanScanner(device) as scanner:
        return scanner.auto_focus()
