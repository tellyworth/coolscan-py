"""
High-level scanner operations for Nikon Coolscan scanners.

This module provides easy-to-use functions for common scanning operations.
"""

import os
import time
from typing import List, Optional, Tuple, Literal
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

# Temporary workaround for LS-40 ED channel misalignment observed in
# hardware_scan_output.raw.  The trilinear CCD outputs G ~10 px to the
# left of R and B ~20 px to the left of R.  Decode-time shifts of
# (R=0, G=+10, B=+20) applied during plane-to-pixel conversion produce
# a sharp, aligned image.
#
# TODO: remove once the scanner is configured to output aligned planes.
LS40_CHANNEL_OFFSETS: Tuple[int, ...] = (0, 10, 20)

ImageFormat = Literal["plane", "pixel"]


def _parse_scan_data(
    scan_data: bytearray,
    width: int,
    height: int,
    num_channels: int,
    depth: int,
    format: str,
    channel_offsets: Tuple[int, ...] = (0, 0, 0),
) -> Tuple[np.ndarray, int]:
    """Parse raw scan bytes into an RGB image array.

    The ``channel_offsets`` parameter lets the caller specify a per-channel
    horizontal shift (in output pixels) applied during the plane-to-pixel
    conversion.  A positive offset shifts the channel right; a negative
    offset shifts it left.  Edge pixels that fall outside the sensor readout
    range are filled with zeros.  This is useful for compensating physical
    misalignment of trilinear-CCD sensors at decode time.

    Args:
        scan_data: Raw image bytes from the scanner.
        width: Image width in pixels.
        height: Image height in pixels.
        num_channels: Number of colour channels (3 or 4).
        depth: Bits per sample (8 or 12).
        format: "plane" for plane-interleaved per line,
                "pixel" for pixel-interleaved (RGBRGB…).
        channel_offsets: Per-channel horizontal shift in pixels.  Defaults to
            ``(0, 0, 0)`` (no shift).  Non-zero offsets are a temporary
            workaround for hardware misalignment; see LS40_CHANNEL_OFFSETS.

    Returns:
        (image_array, trailing_bytes) where image_array is (height, width, channels)
        and trailing_bytes is the number of unused bytes at the end.
    """
    if depth > 8:
        samples = np.frombuffer(scan_data, dtype=">u2")  # big-endian uint16
        samples = (samples >> 4).astype(np.uint8)  # top 8 bits of 12-bit value
    else:
        samples = np.frombuffer(scan_data, dtype=np.uint8)

    if format == "pixel":
        # Pixel-interleaved: [R,G,B][R,G,B]… per line
        expected = height * width * num_channels
        trailing = len(samples) - expected
        if trailing < 0:
            # Not enough data — pad with zeros
            samples = np.pad(samples, (0, -trailing), constant_values=0)
            trailing = 0
        arr = samples[:expected].reshape((height, width, num_channels))
    else:
        # Plane-interleaved per line: [R…][G…][B…] per line
        # The LS-40 ED outputs data in this format.  Each line contains
        # width bytes for R, then width bytes for G, then width bytes for B.
        expected = height * width * num_channels
        trailing = len(samples) - expected
        if trailing < 0:
            samples = np.pad(samples, (0, -trailing), constant_values=0)
            trailing = 0

        arr = np.zeros((height, width, num_channels), dtype=np.uint8)
        offset = 0
        for y in range(height):
            for ch in range(num_channels):
                ch_offset = channel_offsets[ch] if ch < len(channel_offsets) else 0
                end = offset + width
                if end > len(samples):
                    break
                ch_data = samples[offset:end]
                if ch_offset > 0:
                    # Shift right: source[i] → output[i + offset]
                    dst_start = ch_offset
                    dst_end = min(ch_offset + width, width)
                    src_start = 0
                    src_end = dst_end - dst_start
                    arr[y, dst_start:dst_end, ch] = ch_data[src_start:src_end]
                elif ch_offset < 0:
                    # Shift left: source[i - |offset|] → output[i]
                    src_start = -ch_offset
                    dst_start = 0
                    src_end = min(src_start + width, width)
                    dst_end = src_end - src_start
                    arr[y, dst_start:dst_end, ch] = ch_data[src_start:src_end]
                else:
                    arr[y, :, ch] = ch_data
                offset = end
            if offset >= len(samples):
                break

    return arr, trailing


class CoolscanScanner:
    """High-level interface for Coolscan scanner operations."""

    def __init__(self, device: ScannerDevice, usb_log_file: Optional[str] = None):
        self.device = device
        self.usb_log_file = usb_log_file
        self.protocol = None
        self.is_connected = False
        self.scan_in_progress = False
        self.scanner_info = None

    def connect(self, usb_log_file: Optional[str] = None) -> bool:
        """Connect to the scanner using enhanced SANE sequence."""
        try:
            print("Connecting to scanner...")
            self.protocol = CoolscanProtocol(self.device)

            # Enable USB capture before any USB traffic
            if usb_log_file:
                self.protocol.enable_usb_capture(usb_log_file)

            # Initialize scanner with full SANE sequence
            if not self.protocol.initialize_scanner():
                raise RuntimeError("Scanner initialization failed")

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

        # Use device descriptor info (already available) instead of sending
        # another INQUIRY that disrupts scanner state.
        info = {
            "vendor": self.device.vendor,
            "product": self.device.model,
            "revision": self.device.revision,
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

    def scan_preview(
        self,
        output_path: str,
        resolution: int = 270,
        format: ImageFormat = "plane",
        channel_offsets: Tuple[int, ...] = None,
    ) -> bool:
        """Perform a preview scan.

        Args:
            output_path: File path for the saved image.
            resolution: Scan resolution in DPI.
            format: Image data format.  Defaults to "plane".
            channel_offsets: Per-channel horizontal shift in pixels applied
                during decode.  Defaults to LS40_CHANNEL_OFFSETS.  Pass
                ``(0, 0, 0)`` to disable the alignment workaround.
        """
        params = ScanParameters(
            resolution=resolution,
            preview=True,
            x_min=0,
            y_min=0,
            x_max=1000,  # Small preview area
            y_max=1000,
        )

        return self._perform_scan(
            params, output_path, "preview", format=format, channel_offsets=channel_offsets
        )

    def scan_full(
        self,
        output_path: str,
        resolution: int = 2700,
        negative: bool = False,
        infrared: bool = False,
        depth: int = 8,
        format: ImageFormat = "plane",
        channel_offsets: Tuple[int, ...] = None,
    ) -> bool:
        """Perform a full resolution scan.

        Args:
            output_path: File path for the saved image.
            resolution: Scan resolution in DPI.
            negative: Whether scanning film negative.
            infrared: Whether to include IR channel.
            depth: Bit depth (8 or 12).
            format: Image data format.  The LS-40 ED always uses "plane"
                (plane-interleaved per line).  Defaults to "plane".
            channel_offsets: Per-channel horizontal shift in pixels applied
                during decode.  Defaults to LS40_CHANNEL_OFFSETS ``(0, 10, 20)``
                as a temporary workaround for LS-40 ED trilinear-CCD misalignment.
                Pass ``(0, 0, 0)`` to disable the workaround.
        """
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

        return self._perform_scan(
            params, output_path, "full", format=format, channel_offsets=channel_offsets
        )

    def scan_area(
        self,
        output_path: str,
        x_min: int,
        y_min: int,
        x_max: int,
        y_max: int,
        resolution: int = 2700,
        format: ImageFormat = "plane",
        channel_offsets: Tuple[int, ...] = None,
    ) -> bool:
        """Scan a specific area.

        Args:
            output_path: File path for the saved image.
            x_min, y_min, x_max, y_max: Scan area coordinates.
            resolution: Scan resolution in DPI.
            format: Image data format.  Defaults to "plane".
            channel_offsets: Per-channel horizontal shift in pixels applied
                during decode.  Defaults to LS40_CHANNEL_OFFSETS.  Pass
                ``(0, 0, 0)`` to disable the alignment workaround.
        """
        params = ScanParameters(
            resolution=resolution, preview=False, x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max
        )

        return self._perform_scan(
            params, output_path, "area", format=format, channel_offsets=channel_offsets
        )

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

    def _perform_scan(
        self,
        params: ScanParameters,
        output_path: str,
        scan_type: str,
        format: ImageFormat = "plane",
        channel_offsets: Tuple[int, ...] = None,
    ) -> bool:
        """Perform a scan with the given parameters using enhanced SANE sequence.

        The LS-40 ED outputs plane-interleaved data (RRR…GGG…BBB… per line).
        The trilinear CCD sensors are physically separated, causing a small
        horizontal offset between channels.  A temporary decode-time shift
        (LS40_CHANNEL_OFFSETS) is applied during plane-to-pixel conversion to
        compensate.  Pass ``channel_offsets=(0, 0, 0)`` to disable.

        Args:
            params: Scan parameters.
            output_path: File path for the saved image.
            scan_type: One of "preview", "full", "area".
            format: Image data format.  The LS-40 ED always uses "plane"
                (plane-interleaved per line).  Defaults to "plane".
            channel_offsets: Per-channel horizontal shift in pixels applied
                during decode.  Defaults to LS40_CHANNEL_OFFSETS ``(0, 10, 20)``
                as a temporary workaround for LS-40 ED trilinear-CCD misalignment.
                Pass ``(0, 0, 0)`` to disable the workaround.
        """
        if channel_offsets is None:
            channel_offsets = LS40_CHANNEL_OFFSETS

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

            # Calculate expected image dimensions.
            # The LS-40 ED returns a 2880 x 3888 pixel frame for full-resolution
            # scans (resolution >= 2700).  scanner_info.x_max_pixels is the
            # scanner's reported addressable range, not the native sensor width,
            # so using it causes image truncation / reshape failures.
            if params.x_max > 0:
                width = params.x_max
            elif params.resolution >= 2700:
                width = 2880
            else:
                width = self.scanner_info.x_max_pixels if self.scanner_info else 2592

            if params.y_max > 0:
                height = params.y_max
            elif params.resolution >= 2700:
                height = 3888
            else:
                height = self.scanner_info.y_max_pixels if self.scanner_info else 3888

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

            # Read scan data in chunks.  Use a line-group-sized request
            # (0x3f480 = 259200 bytes) matching the golden fixture, and read
            # exactly the expected frame size.  Do not drain trailing overscan;
            # on real hardware that causes the scanner to hang after the final
            # short read.
            chunk_size = 0x3F480  # 259200 bytes, matches golden fixture reads
            scan_data = bytearray()

            bytes_read = 0
            while bytes_read < total_bytes:
                remaining = total_bytes - bytes_read
                request_length = min(chunk_size, remaining)
                chunk_data = self.protocol.read_scan_data(request_length, datatype)
                scan_data.extend(chunk_data)
                bytes_read += len(chunk_data)

                # Progress indicator
                progress = bytes_read / total_bytes * 100
                print(f"Scan progress: {progress:.1f}%")

            # --- Image format handling ---
            # The LS-40 ED outputs plane-interleaved data.  Apply channel
            # offsets during plane-to-pixel decode.
            img_arr, trailing = _parse_scan_data(
                scan_data, width, height, num_channels, params.depth,
                format, channel_offsets,
            )
            print(
                f"  Format: {format}, dimensions: {width}x{height}, "
                f"bytes={len(scan_data)}, trailing={trailing}, "
                f"offsets={channel_offsets}"
            )

            # Build PIL image from array
            if params.infrared:
                image = Image.fromarray(img_arr, "RGBA")
            else:
                image = Image.fromarray(img_arr, "RGB")

            # Save the image
            image.save(output_path)
            print(f"Scan saved to {output_path}")

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

    def selective_batch_scan(
        self,
        frame_positions: List[int],
        scan_frames: Optional[List[int]] = None,
        output_dir: str = "scans",
        resolution: int = 2900,
        depth: int = 8,
    ) -> bool:
        """Selective batch scan: preview all, scan selected frames.

        This method runs the workflow observed in ``ls40-batch-session.pcapng``:
        autofocus + preview for every frame, then main scan only for
        frames listed in ``scan_frames``.

        Args:
            frame_positions: Carriage Y positions for each frame
                (~4300 units apart, from autofocus tracking).
            scan_frames: Indices into ``frame_positions`` for main scanning.
                If None, all frames are scanned.
            output_dir: Directory for saved scan images.
            resolution: Scan resolution in DPI.
            depth: Bit depth (8 or 12).

        Returns:
            True if the scan completed successfully.
        """
        if not self.is_connected:
            raise RuntimeError("Scanner not connected")

        os.makedirs(output_dir, exist_ok=True)

        return self.protocol.selective_batch_scan(
            frame_positions=frame_positions,
            scan_frames=scan_frames,
        )

    def __enter__(self):
        """Context manager entry."""
        if not self.connect(self.usb_log_file):
            raise RuntimeError("Failed to connect to scanner")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


def scan_preview(
    device: ScannerDevice,
    output_path: str,
    resolution: int = 270,
    format: ImageFormat = "plane",
    channel_offsets: Tuple[int, ...] = None,
) -> bool:
    """Quick preview scan function."""
    with CoolscanScanner(device) as scanner:
        return scanner.scan_preview(output_path, resolution, format, channel_offsets)


def scan_full(
    device: ScannerDevice,
    output_path: str,
    resolution: int = 2700,
    negative: bool = False,
    infrared: bool = False,
    depth: int = 8,
    format: ImageFormat = "plane",
    channel_offsets: Tuple[int, ...] = None,
) -> bool:
    """Quick full scan function."""
    with CoolscanScanner(device) as scanner:
        return scanner.scan_full(
            output_path, resolution, negative, infrared, depth, format, channel_offsets
        )


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
