"""
Communication protocol for Nikon Coolscan scanners.

This module implements the low-level communication protocol used by
Coolscan scanners, based on the SANE backend implementation.
"""

import struct
import time
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum
from dataclasses import dataclass

try:
    import usb.core
    import usb.util
    import usb  # Import usb module itself for usb.backend access

    USB_AVAILABLE = True
except ImportError:
    USB_AVAILABLE = False

from coolscan.usb_replay import ReplayError


class PhaseType(Enum):
    """USB communication phases."""

    NONE = 0x00
    STATUS = 0x01
    OUT = 0x02
    IN = 0x03
    BUSY = 0x04


class ScanType(Enum):
    """Scan operation types."""

    NORMAL = 0
    AE = 1  # Auto-exposure
    AE_WB = 2  # Auto-exposure with white balance


class StatusType(Enum):
    """Scanner status types."""

    READY = 0
    BUSY = 1
    NO_DOCS = 2
    PROCESSING = 4
    ERROR = 8
    REISSUE = 16


# Data type codes from SANE backend
class DataType(Enum):
    """Data type codes for READ/SEND commands."""

    IMAGE_DATA = 0x00  # Image/pixel data (prescan and full scan)
    LUT = 0x01
    STATUS_PROGRESS = 0x87  # Internal status/progress information
    EXPOSURE_CALIBRATION = 0x8E  # Exposure/calibration tables
    CONTROL_FRAME = 0x8F  # Control/frame position data (WRITE)
    IMAGE_POSITIONS = 0x88
    SHADING_DATA = 0xA0
    USER_REG_GAMMA = 0xC0
    DEVICE_INTERNAL_INFO = 0xE0


@dataclass
class WindowDescriptorBlock:
    """Window Descriptor Block for scan configuration."""

    window_id: int = 0x00
    auto_flag: int = 0x00
    x_resolution: int = 2700  # DPI
    y_resolution: int = 2700  # DPI
    ulx: int = 0  # Upper left X
    uly: int = 0  # Upper left Y
    width: int = 2592  # Width in pixels
    length: int = 3888  # Length in pixels
    brightness: int = 128
    contrast: int = 128
    composition: int = 0x05  # RGB full
    bits_per_pixel: int = 0x08  # 8-bit
    negative_dropout: int = 0x00  # Positive, no dropout
    scan_mode: int = 0x00  # Normal scan
    transfer_mode: int = 0x02  # Line sequence
    gamma_selection: int = 0x03  # Monitor gamma
    brightness_r: int = 128
    brightness_g: int = 128
    brightness_b: int = 128
    contrast_r: int = 128
    contrast_g: int = 128
    contrast_b: int = 128
    exposure_r: int = 120
    exposure_g: int = 120
    exposure_b: int = 100
    shift_r: int = 128
    shift_g: int = 128
    shift_b: int = 128
    offset_r: int = 0
    offset_g: int = 0
    offset_b: int = 0

    def to_bytes(self) -> bytes:
        """Convert WDB to bytes."""
        data = bytearray(117)  # Standard WDB size

        # Basic fields
        data[0x00] = self.window_id
        data[0x01] = self.auto_flag

        # Resolution (big-endian)
        data[0x02:0x04] = struct.pack(">H", self.x_resolution)
        data[0x04:0x06] = struct.pack(">H", self.y_resolution)

        # Position and size (big-endian)
        data[0x06:0x0A] = struct.pack(">L", self.ulx)
        data[0x0A:0x0E] = struct.pack(">L", self.uly)
        data[0x0E:0x12] = struct.pack(">L", self.width)
        data[0x12:0x16] = struct.pack(">L", self.length)

        # Image parameters
        data[0x16] = self.brightness
        data[0x18] = self.contrast
        data[0x19] = self.composition
        data[0x1A] = self.bits_per_pixel

        # Pixel counts (big-endian)
        data[0x28:0x2C] = struct.pack(">L", self.width)
        data[0x2C:0x30] = struct.pack(">L", self.length)

        # Scan parameters
        data[0x30] = self.negative_dropout
        data[0x31] = self.scan_mode
        data[0x32] = self.transfer_mode
        data[0x33] = self.gamma_selection

        # Color adjustments
        data[0x37] = self.brightness_r
        data[0x38] = self.brightness_g
        data[0x39] = self.brightness_b
        data[0x3A] = self.contrast_r
        data[0x3B] = self.contrast_g
        data[0x3C] = self.contrast_b

        # Exposure settings
        data[0x49] = self.exposure_r
        data[0x4A] = self.exposure_g
        data[0x4B] = self.exposure_b

        # Color shifts
        data[0x52] = self.shift_r
        data[0x53] = self.shift_g
        data[0x54] = self.shift_b

        # Color offsets
        data[0x55] = self.offset_r
        data[0x56] = self.offset_g
        data[0x57] = self.offset_b

        return bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "WindowDescriptorBlock":
        """Create WDB from bytes."""
        if len(data) < 117:
            raise ValueError("WDB data too short")

        wdb = cls()

        # Parse basic fields
        wdb.window_id = data[0x00]
        wdb.auto_flag = data[0x01]

        # Resolution
        wdb.x_resolution = struct.unpack(">H", data[0x02:0x04])[0]
        wdb.y_resolution = struct.unpack(">H", data[0x04:0x06])[0]

        # Position and size
        wdb.ulx = struct.unpack(">L", data[0x06:0x0A])[0]
        wdb.uly = struct.unpack(">L", data[0x0A:0x0E])[0]
        wdb.width = struct.unpack(">L", data[0x0E:0x12])[0]
        wdb.length = struct.unpack(">L", data[0x12:0x16])[0]

        # Image parameters
        wdb.brightness = data[0x16]
        wdb.contrast = data[0x18]
        wdb.composition = data[0x19]
        wdb.bits_per_pixel = data[0x1A]

        # Scan parameters
        wdb.negative_dropout = data[0x30]
        wdb.scan_mode = data[0x31]
        wdb.transfer_mode = data[0x32]
        wdb.gamma_selection = data[0x33]

        # Color adjustments
        wdb.brightness_r = data[0x37]
        wdb.brightness_g = data[0x38]
        wdb.brightness_b = data[0x39]
        wdb.contrast_r = data[0x3A]
        wdb.contrast_g = data[0x3B]
        wdb.contrast_b = data[0x3C]

        # Exposure settings
        wdb.exposure_r = data[0x49]
        wdb.exposure_g = data[0x4A]
        wdb.exposure_b = data[0x4B]

        # Color shifts
        wdb.shift_r = data[0x52]
        wdb.shift_g = data[0x53]
        wdb.shift_b = data[0x54]

        # Color offsets
        wdb.offset_r = data[0x55]
        wdb.offset_g = data[0x56]
        wdb.offset_b = data[0x57]

        return wdb


@dataclass
class ScanParameters:
    """Scan parameters for the scanner."""

    resolution: int = 2700
    preview: bool = False
    negative: bool = False
    infrared: bool = False
    depth: int = 8
    x_min: int = 0
    y_min: int = 0
    x_max: int = 0
    y_max: int = 0
    exposure: float = 1.0
    exposure_r: float = 1200.0
    exposure_g: float = 1200.0
    exposure_b: float = 1000.0


@dataclass
class ScannerInfo:
    """Scanner information from internal info read."""

    ad_bits: int = 8
    output_bits: int = 8
    max_resolution: int = 2700
    x_max: int = 1151
    y_max: int = 1727
    x_max_pixels: int = 2591
    y_max_pixels: int = 3887
    current_y: int = 0
    current_focus: int = 0
    current_scan_pitch: int = 1
    auto_feeder: int = 0
    analog_gamma: int = 0
    device_errors: List[int] = None

    def __post_init__(self):
        if self.device_errors is None:
            self.device_errors = [0] * 8


class CoolscanProtocol:
    """Implements the Coolscan communication protocol."""

    def __init__(self, device, verbose: bool = False, *, usb_capture_replay=None):
        self.device = device
        self.interface = device.interface
        self.usb_device = None
        self.scsi_fd = None
        self.scanner_info = None
        self.mud = 2700  # Measurement Unit Divisor
        self.verbose = verbose  # Control verbose output
        self._last_status_raw = None  # Store last raw status for detailed logging
        self._last_status_parsed = None  # Store last parsed status
        self._usb_capture_log = None  # File handle for USB capture logging
        self._usb_capture_start_time = None  # Start time for relative timestamps
        self._usb_capture_replay = usb_capture_replay

        if usb_capture_replay is not None and self.interface.value != "usb":
            raise ValueError("usb_capture_replay is only valid for USB interface devices")

        if self.interface.value == "usb":
            self._init_usb()
        else:
            self._init_scsi()

    def _replay_reraise_if_needed(self, exc: BaseException) -> None:
        """When driving I/O from a capture replay, do not swallow replay mismatch errors."""
        if self._usb_capture_replay is not None and isinstance(exc, ReplayError):
            raise exc

    def _init_usb_from_replay(self):
        """Bind bulk endpoints to capture replay traffic (no libusb)."""
        from coolscan.usb_replay import ReplayUsbDevice

        class _Ep:
            __slots__ = ("bEndpointAddress", "wMaxPacketSize")

            def __init__(self, addr: int) -> None:
                self.bEndpointAddress = addr
                self.wMaxPacketSize = 64

        self.bulk_out = _Ep(0x01)
        self.bulk_in = _Ep(0x82)
        self.usb_device = ReplayUsbDevice(self._usb_capture_replay)

    def _init_usb(self):
        """Initialize USB connection with proper interface claiming and endpoint setup."""
        if self._usb_capture_replay is not None:
            self._init_usb_from_replay()
            return
        if not USB_AVAILABLE:
            raise RuntimeError("USB support not available")

        vendor_id = self.device.vendor_id
        product_id = self.device.product_id

        # Try default backend first (libusb1 usually works better than libusb0 on macOS)
        self.usb_device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if self.usb_device is None:
            # Fallback to libusb0 if default didn't work
            try:
                # Import at module level to avoid variable shadowing issues
                from usb import backend

                libusb0_backend = backend.libusb0.get_backend()
                self.usb_device = usb.core.find(
                    idVendor=vendor_id, idProduct=product_id, backend=libusb0_backend
                )
                if self.usb_device is not None:
                    print(f"  Using libusb0 backend (fallback)")
            except (ImportError, AttributeError):
                pass

        if self.usb_device is None:
            raise RuntimeError(f"USB device {vendor_id:04x}:{product_id:04x} not found")

        # Get endpoints from configuration descriptor (doesn't require device to be configured)
        cfg = None
        cfg_desc = None
        try:
            # Try to get configuration descriptor using usb.util.find_descriptor
            # This doesn't require the device to be in an active configuration
            cfg_desc = usb.util.find_descriptor(self.usb_device, bConfigurationValue=1)
            if cfg_desc:
                print(f"  Got configuration descriptor 1")

            # Try to get active configuration (might fail, that's OK)
            try:
                cfg = self.usb_device.get_active_configuration()
                print(f"  Device already configured (config {cfg.bConfigurationValue})")
            except usb.core.USBError:
                # Not configured, try to set it
                try:
                    self.usb_device.set_configuration(1)
                    print(f"  Configuration set to 1")
                    try:
                        cfg = self.usb_device.get_active_configuration()
                    except usb.core.USBError:
                        pass
                except usb.core.USBError as e:
                    err_msg = str(e).lower()
                    if "result too large" not in err_msg and e.errno != 16:
                        print(f"  ⚠️  Configuration set failed: {e}")
        except Exception as e:
            print(f"  ⚠️  Could not get configuration descriptor: {e}")

        # Set timeouts (in milliseconds)
        # Use longer timeout to allow scanner time to respond, especially after film insertion
        self.usb_device.default_timeout = 30000  # 30 seconds default

        # Find endpoints - try from configuration descriptor or active config
        if cfg_desc:
            try:
                # Get interface 0 from configuration descriptor
                intf = cfg_desc.interfaces()[0]

                # Find bulk endpoints
                self.bulk_out = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT,
                )

                self.bulk_in = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_IN,
                )

                if self.bulk_out and self.bulk_in:
                    print(
                        f"  Found endpoints via descriptor: OUT=0x{self.bulk_out.bEndpointAddress:02x}, IN=0x{self.bulk_in.bEndpointAddress:02x}"
                    )
                else:
                    raise RuntimeError("Endpoints not found in descriptor")
            except Exception as e:
                print(f"  ⚠️  Could not get endpoints from descriptor: {e}")
                cfg_desc = None  # Force fallback
        elif cfg:
            try:
                intf = cfg[(0, 0)]

                # Find bulk endpoints
                self.bulk_out = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT,
                )

                self.bulk_in = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_IN,
                )

                if self.bulk_out and self.bulk_in:
                    print(
                        f"  Found endpoints via active config: OUT=0x{self.bulk_out.bEndpointAddress:02x}, IN=0x{self.bulk_in.bEndpointAddress:02x}"
                    )
                else:
                    raise RuntimeError("Endpoints not found in configuration")
            except Exception as e:
                print(f"  ⚠️  Could not get endpoints from configuration: {e}")
                print(f"  Using hardcoded endpoint addresses (from USB capture analysis)")

        # Fallback: Use hardcoded endpoint addresses from USB capture analysis
        # OUT endpoint: 0x01 (endpoint 1, OUT direction)
        # IN endpoint: 0x82 (endpoint 2, IN direction = 0x02 | 0x80)
        if not cfg:
            print(f"  Using hardcoded endpoints: OUT=0x01, IN=0x82")

            # Create mock endpoint objects with the known addresses
            class MockEndpoint:
                def __init__(self, address):
                    self.bEndpointAddress = address
                    self.wMaxPacketSize = 64  # Typical bulk endpoint size

            self.bulk_out = MockEndpoint(0x01)
            self.bulk_in = MockEndpoint(0x82)

        # Try to detach kernel driver if active (mostly for Linux, not macOS)
        # On macOS, kernel driver operations often fail with "No such file or directory"
        # This is normal and expected - macOS doesn't use kernel drivers the same way
        try:
            if hasattr(self.usb_device, "is_kernel_driver_active"):
                try:
                    if self.usb_device.is_kernel_driver_active(0):
                        try:
                            self.usb_device.detach_kernel_driver(0)
                            print(f"  Detached kernel driver")
                        except (usb.core.USBError, NotImplementedError) as e:
                            # Not supported on macOS, that's OK
                            pass
                except usb.core.USBError as e:
                    # On macOS, this often fails with "No such file or directory"
                    # This is expected and not an error
                    err_msg = str(e).lower()
                    if "no such file" not in err_msg and "not supported" not in err_msg:
                        # Only log if it's an unexpected error
                        print(f"  ⚠️  Kernel driver check failed: {e}")
        except (AttributeError, NotImplementedError):
            # Kernel driver handling not available (normal on macOS)
            pass

        # Claim the interface explicitly
        # On macOS, this often fails due to various quirks, but we can continue with hardcoded endpoints
        try:
            usb.util.claim_interface(self.usb_device, 0)
            print(f"  Interface claimed successfully")
        except usb.core.USBError as e:
            # Interface might already be claimed, or various macOS quirks
            # Since we're using hardcoded endpoints, we can continue anyway
            err_msg = str(e).lower()
            if (
                e.errno == 16
                or "result too large" in err_msg
                or "resource busy" in err_msg
                or "other error" in err_msg
            ):
                # These errors often mean the interface is already claimed or can't be claimed, which is OK
                print(f"  Interface claim failed (will continue with hardcoded endpoints): {e}")
            else:
                # Log but don't fail - we'll try to continue anyway
                print(f"  ⚠️  Interface claim failed: {e} (will try to continue)")

        # Clear any halted endpoints (don't reset device - it causes disconnection)
        # Note: device.reset() causes the device to disconnect, so we skip it
        try:
            self.usb_device.clear_halt(self.bulk_out.bEndpointAddress)
            self.usb_device.clear_halt(self.bulk_in.bEndpointAddress)
            print(f"  Endpoints cleared")
        except (usb.core.USBError, AttributeError) as e:
            # Endpoint clearing might fail, that's OK
            print(f"  Endpoint clearing failed (may be normal): {e}")

    def _init_scsi(self):
        """Initialize SCSI connection."""
        # For now, we'll implement basic SCSI support
        # This would require direct device file access
        raise NotImplementedError("SCSI support not yet implemented")

    def _pack_byte(self, byte: int) -> bytes:
        """Pack a single byte."""
        return struct.pack("B", byte)

    def _pack_word(self, word: int) -> bytes:
        """Pack a 16-bit word (big-endian)."""
        return struct.pack(">H", word)

    def _pack_long(self, value: int) -> bytes:
        """Pack a 32-bit long (big-endian)."""
        return struct.pack(">L", value)

    def _parse_command(self, command_str: str) -> bytes:
        """Parse a hex command string into bytes."""
        # Remove spaces and convert hex string to bytes
        hex_str = command_str.replace(" ", "")
        return bytes.fromhex(hex_str)

    def _build_6byte_command(
        self,
        cmd_code: int,
        page: int = 0,
        param2: int = 0,
        param3: int = 0,
        alloc_length: int = 0,
        control: int = 0x80,
    ) -> bytes:
        """
        Build a 6-byte command in the format used by the scanner.

        Format:
        Byte 0: Command code
        Byte 1: Page/Subcommand code
        Byte 2: Parameter 2
        Byte 3: Parameter 3
        Byte 4: Allocation length (how many bytes to read)
        Byte 5: Control byte (0x80 for most commands, 0x00 for simple ones)
        """
        return struct.pack("BBBBBB", cmd_code, page, param2, param3, alloc_length, control)

    def enable_usb_capture(self, log_file):
        """
        Enable USB traffic capture logging.

        Args:
            log_file: File handle or path to file for logging USB traffic
        """
        if isinstance(log_file, str):
            self._usb_capture_log = open(log_file, "w")
        else:
            self._usb_capture_log = log_file
        self._usb_capture_start_time = time.time()

    def disable_usb_capture(self):
        """Disable USB traffic capture logging."""
        if self._usb_capture_log:
            if hasattr(self._usb_capture_log, "close"):
                self._usb_capture_log.close()
            self._usb_capture_log = None
        self._usb_capture_start_time = None

    def _usb_write_bulk(self, data: bytes) -> int:
        """Write data to USB bulk endpoint."""
        try:
            # Convert to bytes for consistent handling
            if hasattr(data, "tobytes"):
                data_bytes = data.tobytes()
            elif hasattr(data, "__iter__") and not isinstance(data, (bytes, str)):
                data_bytes = bytes(data)
            else:
                data_bytes = data

            # Verbose hex dump for debugging
            if self.verbose:
                hex_preview = data_bytes.hex()[:120]
                suffix = "..." if len(data_bytes) > 60 else ""
                print(f"  USB OUT: [{len(data_bytes)}B] {hex_preview}{suffix}")

            # Perform the actual USB write first
            result = self.usb_device.write(
                self.bulk_out.bEndpointAddress, data, timeout=self.usb_device.default_timeout
            )

            # Log after successful write (don't let logging interfere with USB operations)
            if self._usb_capture_log and self._usb_capture_start_time is not None:
                try:
                    timestamp = time.time() - self._usb_capture_start_time
                    endpoint = f"0x{self.bulk_out.bEndpointAddress:02x}"
                    # Convert to bytes if it's an array.array
                    if hasattr(data, "tobytes"):
                        data_bytes = data.tobytes()
                    elif hasattr(data, "__iter__") and not isinstance(data, (bytes, str)):
                        data_bytes = bytes(data)
                    else:
                        data_bytes = data
                    length = len(data_bytes)
                    # Truncate hex data for very long writes (like LUTs)
                    hex_data = data_bytes.hex()[:200] if length > 100 else data_bytes.hex()
                    self._usb_capture_log.write(
                        f"{timestamp:.9f}\t{endpoint}\t{length}\t{hex_data}\n"
                    )
                    self._usb_capture_log.flush()
                except Exception as log_error:
                    # Don't let logging errors break USB communication
                    pass

            return result
        except Exception as e:
            self._replay_reraise_if_needed(e)
            # Log failed writes for debugging
            if self._usb_capture_log and self._usb_capture_start_time is not None:
                try:
                    timestamp = time.time() - self._usb_capture_start_time
                    endpoint = f"0x{self.bulk_out.bEndpointAddress:02x}"
                    data_bytes = data if isinstance(data, bytes) else bytes(data)
                    length = len(data_bytes)
                    hex_data = data_bytes.hex()[:200] if length > 100 else data_bytes.hex()
                    self._usb_capture_log.write(
                        f"{timestamp:.9f}\t{endpoint}\t{length}\t{hex_data}\t#ERROR:{e}\n"
                    )
                    self._usb_capture_log.flush()
                except Exception:
                    pass
            print(f"    ❌ Write error: {e}")
            raise

    def _usb_read_bulk(self, length: int) -> bytes:
        """Read data from USB bulk endpoint."""
        try:
            # Perform the actual USB read first
            data = self.usb_device.read(
                self.bulk_in.bEndpointAddress, length, timeout=self.usb_device.default_timeout
            )

            # Convert to bytes if it's an array.array (pyusb sometimes returns array.array)
            if hasattr(data, "tobytes"):
                data_bytes = data.tobytes()
            elif hasattr(data, "__iter__") and not isinstance(data, (bytes, str)):
                data_bytes = bytes(data)
            else:
                data_bytes = data

            # Verbose hex dump for debugging
            if self.verbose:
                hex_preview = data_bytes.hex()[:120]
                suffix = "..." if len(data_bytes) > 60 else ""
                print(f"  USB IN:  [{len(data_bytes)}B] {hex_preview}{suffix}")

            # Log after successful read (don't let logging interfere with USB operations)
            if self._usb_capture_log and self._usb_capture_start_time is not None:
                try:
                    timestamp = time.time() - self._usb_capture_start_time
                    endpoint = f"0x{self.bulk_in.bEndpointAddress:02x}"
                    actual_length = len(data_bytes)
                    # Truncate hex data for very long reads
                    hex_data = data_bytes.hex()[:200] if actual_length > 100 else data_bytes.hex()
                    self._usb_capture_log.write(
                        f"{timestamp:.9f}\t{endpoint}\t{actual_length}\t{hex_data}\n"
                    )
                    self._usb_capture_log.flush()
                except Exception as log_error:
                    # Don't let logging errors break USB communication
                    pass

            return data_bytes
        except Exception as e:
            self._replay_reraise_if_needed(e)
            # Log failed reads for debugging
            if self._usb_capture_log and self._usb_capture_start_time is not None:
                try:
                    timestamp = time.time() - self._usb_capture_start_time
                    endpoint = f"0x{self.bulk_in.bEndpointAddress:02x}"
                    self._usb_capture_log.write(
                        f"{timestamp:.9f}\t{endpoint}\t0\t#READ_ERROR:{e}\n"
                    )
                    self._usb_capture_log.flush()
                except Exception:
                    pass
            print(f"    ❌ Read error: {e}")
            raise

    def wait_scanner(self, max_attempts: int = 10, delay: float = 0.5) -> bool:
        """
        Wait for scanner to be ready - based on SANE backend wait_scanner().
        """
        # Use shorter timeout for wait_scanner to fail faster
        original_timeout = self.usb_device.default_timeout
        self.usb_device.default_timeout = 2000  # 2 seconds instead of 30

        try:
            for attempt in range(max_attempts):
                try:
                    cmd = self._build_6byte_command(0x00, control=0x00)
                    self._usb_write_bulk(cmd)
                    self._usb_write_bulk(self._pack_byte(0xD0))

                    try:
                        phase_response = self._usb_read_bulk(1)
                        if hasattr(phase_response, "tobytes"):
                            phase_response = phase_response.tobytes()
                    except Exception as e:
                        self._replay_reraise_if_needed(e)
                        time.sleep(delay)
                        continue

                    status_data = self._usb_read_bulk(8)
                    if hasattr(status_data, "tobytes"):
                        status_data = status_data.tobytes()

                    if status_data and len(status_data) >= 8:
                        status, _ = self._parse_status(status_data)
                        if status == StatusType.READY or status == StatusType.NO_DOCS:
                            return True

                    time.sleep(delay)
                except Exception as e:
                    self._replay_reraise_if_needed(e)
                    time.sleep(delay)
                    continue

            print(f"  ⚠️  Scanner not ready after {max_attempts} attempts")
            return False
        finally:
            # Restore original timeout
            self.usb_device.default_timeout = original_timeout

    def _check_phase_with_retry(self, max_retries: int = 3) -> PhaseType:
        """Check phase with retry logic."""
        for attempt in range(max_retries):
            try:
                phase = self._check_phase()
                if phase != PhaseType.NONE:
                    return phase
                # Longer delay between retries to allow scanner time to respond
                time.sleep(0.5 * (attempt + 1))
            except Exception as e:
                self._replay_reraise_if_needed(e)
                print(f"Phase check attempt {attempt + 1} failed: {e}")
                # Longer delay on error too
                time.sleep(1.0 * (attempt + 1))

        return PhaseType.NONE

    def _parse_status(self, status_data: bytes) -> Tuple[StatusType, dict]:
        """Parse 8-byte status response with comprehensive sense key handling."""
        if len(status_data) != 8:
            return StatusType.ERROR, {}

        sense_key = status_data[1] & 0x0F
        sense_asc = status_data[2]
        sense_ascq = status_data[3]

        # Comprehensive sense key parsing like SANE backend
        if sense_key == 0x00:
            status = StatusType.READY
        elif sense_key == 0x01:
            # Recovered error
            if sense_asc == 0x37 and sense_ascq == 0x00:
                status = StatusType.READY  # Rounded parameter
            else:
                status = StatusType.ERROR
        elif sense_key == 0x02:
            # Not ready
            if sense_asc == 0x04 and sense_ascq == 0x01:
                status = StatusType.PROCESSING  # Becoming ready
            elif sense_asc == 0x3A and sense_ascq == 0x00:
                status = StatusType.NO_DOCS  # No document
            else:
                status = StatusType.ERROR
        elif sense_key == 0x03:
            # Medium error
            status = StatusType.ERROR
        elif sense_key == 0x04:
            # Hardware error
            status = StatusType.ERROR
        elif sense_key == 0x05:
            # Illegal request
            status = StatusType.ERROR
        elif sense_key == 0x06:
            # Unit attention
            status = StatusType.ERROR
        elif sense_key == 0x0B:
            # Aborted command
            status = StatusType.ERROR
        else:
            status = StatusType.ERROR

        return status, {"sense_key": sense_key, "sense_asc": sense_asc, "sense_ascq": sense_ascq}

    def _check_phase(self) -> PhaseType:
        """Check the current USB phase."""
        # Send phase check command (0xd0)
        phase_cmd = self._pack_byte(0xD0)
        try:
            self._usb_write_bulk(phase_cmd)
            print(f"      Phase check command (0xd0) sent")

            # Read phase response
            response = self._usb_read_bulk(1)
            # Convert array.array to bytes if needed
            if hasattr(response, "tobytes"):
                response = response.tobytes()
            elif hasattr(response, "__iter__"):
                response = bytes(response)

            if response and len(response) >= 1:
                phase = PhaseType(response[0])
                print(f"      Phase response: {phase}")
                return phase
            else:
                print(f"      ⚠️  No phase response received")
                return PhaseType.NONE
        except Exception as e:
            self._replay_reraise_if_needed(e)
            print(f"      ⚠️  Phase check error: {e}")
        return PhaseType.NONE

    def _issue_command(
        self, command: bytes, data_out: bytes = b"", data_in_length: int = 0
    ) -> Tuple[bytes, StatusType]:
        """Issue a command to the scanner."""
        if self.interface.value == "usb":
            return self._issue_usb_command(command, data_out, data_in_length)
        else:
            return self._issue_scsi_command(command, data_out, data_in_length)

    def _issue_usb_command(
        self, command: bytes, data_out: bytes = b"", data_in_length: int = 0
    ) -> Tuple[bytes, StatusType]:
        """
        Issue a USB command following the protocol pattern from USB capture.
        """
        try:
            # Initialize data_in early (may be set during Overflow handling)
            data_in = b""
            remaining_data_length = data_in_length  # Track how much data we still need to read

            # Send command + phase check
            self._usb_write_bulk(command)
            self._usb_write_bulk(self._pack_byte(0xD0))

            # Read phase response
            try:
                phase_response = self._usb_read_bulk(1)
                if hasattr(phase_response, "tobytes"):
                    phase_response = phase_response.tobytes()
                phase_byte = phase_response[0] if len(phase_response) > 0 else 0
            except Exception as e:
                self._replay_reraise_if_needed(e)
                # Handle Overflow - for READ commands, this might mean data is already available
                if "Overflow" in str(e) or "84" in str(e):
                    # Overflow means we tried to read 1 byte but more is available
                    # For READ commands, try to read a small buffer and extract phase byte
                    if data_in_length > 0:
                        # Try to read a small chunk to get the phase byte
                        # The first byte should be the phase (0x03 for DATA_IN)
                        try:
                            # Read a small buffer (up to 64 bytes) to get phase + start of data
                            chunk = self._usb_read_bulk(min(64, data_in_length + 1))
                            if hasattr(chunk, "tobytes"):
                                chunk = chunk.tobytes()
                            if len(chunk) > 0:
                                phase_byte = chunk[0]
                                # If we got data, we'll need to prepend it to the full data read
                                # Store it for later use
                                if len(chunk) > 1:
                                    # We got phase + some data, store the data part
                                    data_in = chunk[1:]
                                    # Adjust remaining_data_length to account for what we already read
                                    remaining_data_length -= len(data_in)
                                else:
                                    data_in = b""
                                print(
                                    f"    ⚠️  Overflow on phase read - extracted phase=0x{phase_byte:02x}, got {len(chunk)-1} bytes of data"
                                )
                            else:
                                phase_byte = 0x03  # Default to DATA_IN
                                data_in = b""
                        except Exception as e2:
                            self._replay_reraise_if_needed(e2)
                            print(f"    ⚠️  Failed to read chunk after Overflow: {e2}")
                            phase_byte = 0x03  # Assume DATA_IN phase
                            data_in = b""
                    else:
                        # No data expected - might be status
                        try:
                            status_data = self._usb_read_bulk(8)
                            if hasattr(status_data, "tobytes"):
                                status_data = status_data.tobytes()
                            if len(status_data) >= 8:
                                status, parsed = self._parse_status(status_data)
                                print(f"    ⚠️  Got status directly (Overflow on phase): {status}")
                                return b"", status
                        except Exception as e_ov:
                            self._replay_reraise_if_needed(e_ov)
                            pass
                        phase_byte = 0x03  # Default to DATA_IN
                        data_in = b""
                else:
                    print(f"    ⚠️  Phase read failed: {e}")
                    phase_byte = 0x03  # Assume DATA_IN phase
                    data_in = b""

            # Handle Busy phase (0x04)
            if phase_byte == 0x04:
                print(f"    Scanner busy, retrying...")
                for retry in range(5):
                    time.sleep(0.5)
                    try:
                        # Re-send the original command, then check phase again
                        self._usb_write_bulk(command)
                        self._usb_write_bulk(self._pack_byte(0xD0))
                        phase_response = self._usb_read_bulk(1)
                        if hasattr(phase_response, "tobytes"):
                            phase_response = phase_response.tobytes()
                        phase_byte = phase_response[0] if len(phase_response) > 0 else 0
                        if phase_byte != 0x04:
                            break
                    except Exception as e_busy:
                        self._replay_reraise_if_needed(e_busy)
                        pass
                if phase_byte == 0x04:
                    print(f"    ⚠️  Scanner still busy")
                    return b"", StatusType.BUSY

            # data_in already initialized at start of function

            # Send data if phase is Data OUT (0x02)
            if phase_byte == 0x02 and len(data_out) > 0:
                try:
                    self._usb_write_bulk(data_out)
                    time.sleep(0.01)
                    # After sending DATA_OUT, go straight to reading status (like SANE)
                    # No phase check needed - status is next in the protocol sequence
                except Exception as e:
                    self._replay_reraise_if_needed(e)
                    print(f"    ⚠️  Data out failed: {e}")
                    return b"", StatusType.ERROR

            # Read data if phase is Data IN (0x03)
            if phase_byte == 0x03 and remaining_data_length > 0:
                try:
                    # If we already got some data from Overflow handling, prepend it
                    existing_data = data_in

                    if remaining_data_length > 0:
                        new_data = self._usb_read_bulk(remaining_data_length)
                        if hasattr(new_data, "tobytes"):
                            new_data = new_data.tobytes()
                        data_in = existing_data + new_data
                    else:
                        data_in = existing_data
                except Exception as e:
                    self._replay_reraise_if_needed(e)
                    print(f"    ⚠️  Data read failed: {e}")
                    # Keep existing data if we have it
                    if len(data_in) == 0:
                        data_in = b""

            # Read status (8 bytes) - always read status after command
            try:
                status_data = self._usb_read_bulk(8)
                if hasattr(status_data, "tobytes"):
                    status_data = status_data.tobytes()
                status, parsed = self._parse_status(status_data)

                # Store raw status for detailed logging (especially for START_SCAN)
                # This allows us to check ASCQ values
                if len(status_data) == 8:
                    self._last_status_raw = status_data
                    self._last_status_parsed = parsed
                else:
                    self._last_status_raw = None
                    self._last_status_parsed = None

                # Only print if error
                if status != StatusType.READY:
                    print(f"    Status: {status}, sense: {parsed}")
                    if len(status_data) == 8:
                        print(f"    Raw status: {status_data.hex()}")

                return data_in, status
            except Exception as e:
                self._replay_reraise_if_needed(e)
                print(f"    ⚠️  Status read failed: {e}")
                try:
                    self._usb_write_bulk(self._build_6byte_command(0x00, control=0x00))
                    self._usb_write_bulk(self._pack_byte(0xD0))
                except Exception as e_tur:
                    self._replay_reraise_if_needed(e_tur)
                    pass
                return data_in, StatusType.ERROR

        except Exception as e:
            self._replay_reraise_if_needed(e)
            print(f"    ❌ USB command error: {e}")
            return b"", StatusType.ERROR

    def _issue_scsi_command(
        self, command: bytes, data_out: bytes = b"", data_in_length: int = 0
    ) -> Tuple[bytes, StatusType]:
        """Issue a SCSI command."""
        # TODO: Implement SCSI command handling
        raise NotImplementedError("SCSI command handling not yet implemented")

    def inquiry(self, page: int = -1) -> bytes:
        """
        Send INQUIRY command to get device information.

        Uses the correct 6-byte command format from USB capture.
        """
        # Use shorter timeout for INQUIRY to fail faster
        original_timeout = self.usb_device.default_timeout
        self.usb_device.default_timeout = 2000  # 2 seconds instead of 30

        try:
            if page >= 0:
                # Page-specific inquiry - two-step process
                # First: Get length (4 bytes)
                cmd = self._build_6byte_command(
                    0x12, page=0x01, param2=page, alloc_length=4, control=0x80
                )
                data, status = self._issue_command(cmd, data_in_length=4)

                if status == StatusType.READY and len(data) >= 4:
                    # Extract actual length from response
                    # Response format: 06 [page] [length_high] [length_low]
                    if len(data) >= 4:
                        length = data[3] + 4  # Length is in byte 3, add 4 for header
                    else:
                        length = 4

                    # Second: Get full data
                    cmd = self._build_6byte_command(
                        0x12, page=0x01, param2=page, alloc_length=length, control=0x80
                    )
                    data, status = self._issue_command(cmd, data_in_length=length)
            else:
                # Standard inquiry (36 bytes) - format: 12 00 00 00 24 80
                cmd = self._build_6byte_command(0x12, page=0x00, alloc_length=0x24, control=0x80)
                data, status = self._issue_command(cmd, data_in_length=36)

            if status == StatusType.READY:
                return data
            else:
                raise RuntimeError(f"INQUIRY failed with status {status}")
        finally:
            # Restore original timeout
            self.usb_device.default_timeout = original_timeout

    def scanner_ready(self, timeout: int = 30) -> bool:
        """
        Check if scanner is ready with retry logic.

        This is a simpler wrapper - for proper wake-up sequence, use wait_scanner().
        """
        max_attempts = int(timeout / 0.5)  # Number of attempts based on timeout
        return self.wait_scanner(max_attempts=max_attempts, delay=0.5)

    def test_unit_ready(self) -> bool:
        """
        Test if the scanner is ready.

        Uses the correct 6-byte command format: 00 00 00 00 00 00
        """
        print("Testing unit ready...")

        # Use shorter timeout for TEST_UNIT_READY to fail faster
        original_timeout = self.usb_device.default_timeout
        self.usb_device.default_timeout = 2000  # 2 seconds instead of 30

        try:
            # Try multiple times with shorter delays for faster failure detection
            for attempt in range(3):
                try:
                    if attempt > 0:
                        print(f"  Retry attempt {attempt + 1}...")
                        time.sleep(0.2)  # Shorter delay between attempts (200ms instead of 1s)

                    # Format: 00 00 00 00 00 00 (all zeros)
                    cmd = self._build_6byte_command(0x00, control=0x00)
                    print(f"  Sending TEST UNIT READY command: {cmd.hex()}")
                    _, status = self._issue_command(cmd)
                    print(f"  Status: {status}")

                    if status == StatusType.READY:
                        return True

                except Exception as e:
                    print(f"  Error in test_unit_ready (attempt {attempt + 1}): {e}")
                    continue

            return False
        finally:
            # Restore original timeout
            self.usb_device.default_timeout = original_timeout

    def reserve_unit(self) -> bool:
        """Reserve the scanner unit (like SANE coolscan_grab_scanner)."""
        print("Reserving unit...")
        # Format: 16 00 00 00 00 00 (from USB capture)
        cmd = self._build_6byte_command(0x16, control=0x00)
        _, status = self._issue_command(cmd)
        success = status == StatusType.READY
        print(f"Unit reservation: {'SUCCESS' if success else 'FAILED'}")
        return success

    def release_unit(self) -> bool:
        """Release the scanner unit."""
        print("Releasing unit...")
        # Format: 17 00 00 00 00 00 (from USB capture)
        cmd = self._build_6byte_command(0x17, control=0x00)
        _, status = self._issue_command(cmd)
        success = status == StatusType.READY
        print(f"Unit release: {'SUCCESS' if success else 'FAILED'}")
        return success

    def reset_scanner(self) -> bool:
        """
        Reset/cleanup scanner to restore it to a responsive state.

        This should be called after errors to avoid needing to power cycle.
        Uses very short timeouts and limited retries to avoid hanging.

        Returns True if scanner appears responsive, False otherwise.
        """
        print("🔄 Attempting to reset scanner state (aggressive cleanup)...")

        if not self.usb_device:
            print("  ⚠️  No USB device, nothing to reset")
            return False

        try:
            import usb.util

            # Save original timeout
            original_timeout = self.usb_device.default_timeout

            # Use short timeout for all recovery operations
            self.usb_device.default_timeout = 500  # 500ms

            try:
                # Step 1: Clear any stalled endpoints
                print("  Clearing endpoints...")
                try:
                    if hasattr(self, "bulk_out") and self.bulk_out:
                        self.usb_device.clear_halt(self.bulk_out.bEndpointAddress)
                    if hasattr(self, "bulk_in") and self.bulk_in:
                        self.usb_device.clear_halt(self.bulk_in.bEndpointAddress)
                except Exception as e:
                    print(f"    (endpoint clear: {e})")

                # Step 2: Drain any pending data aggressively
                print("  Draining pending data...")
                if hasattr(self, "bulk_in") and self.bulk_in:
                    for _ in range(10):  # More drain attempts
                        try:
                            self.usb_device.read(self.bulk_in.bEndpointAddress, 4096, timeout=50)
                        except:
                            break

                # Step 3: Send STOP_SCAN command (0x1b with action 0x04)
                print("  Sending STOP_SCAN...")
                try:
                    if hasattr(self, "bulk_out") and self.bulk_out:
                        stop_cmd = bytes([0x1B, 0x00, 0x00, 0x00, 0x04, 0x00])
                        self.usb_device.write(self.bulk_out.bEndpointAddress, stop_cmd, timeout=200)
                        time.sleep(0.1)
                        # Try to read any response
                        try:
                            self.usb_device.read(self.bulk_in.bEndpointAddress, 64, timeout=100)
                        except:
                            pass
                except Exception as e:
                    print(f"    (stop scan: {e})")

                # Step 4: Send RELEASE_UNIT
                print("  Sending RELEASE_UNIT...")
                try:
                    if hasattr(self, "bulk_out") and self.bulk_out:
                        release_cmd = bytes([0x17, 0x00, 0x00, 0x00, 0x00, 0x00])
                        self.usb_device.write(
                            self.bulk_out.bEndpointAddress, release_cmd, timeout=200
                        )
                        time.sleep(0.1)
                        # Try to read any response
                        try:
                            self.usb_device.read(self.bulk_in.bEndpointAddress, 64, timeout=100)
                        except:
                            pass
                except Exception as e:
                    print(f"    (release unit: {e})")

                # Step 5: Final drain
                time.sleep(0.2)
                if hasattr(self, "bulk_in") and self.bulk_in:
                    for _ in range(5):
                        try:
                            self.usb_device.read(self.bulk_in.bEndpointAddress, 4096, timeout=50)
                        except:
                            break

                # Step 6: Try a TEST_UNIT_READY to check responsiveness
                print("  Testing responsiveness...")
                try:
                    if hasattr(self, "bulk_out") and self.bulk_out:
                        tur_cmd = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                        self.usb_device.write(self.bulk_out.bEndpointAddress, tur_cmd, timeout=500)
                        self.usb_device.write(
                            self.bulk_out.bEndpointAddress, bytes([0xD0]), timeout=500
                        )
                        time.sleep(0.05)
                        phase = self.usb_device.read(self.bulk_in.bEndpointAddress, 1, timeout=500)
                        if phase and phase[0] == 0x01:  # Status phase
                            status = self.usb_device.read(
                                self.bulk_in.bEndpointAddress, 8, timeout=500
                            )
                            if status and status[0] == 0x00:
                                print("  ✅ Scanner is responsive")
                                return True
                except Exception as e:
                    print(f"    (test ready: {e})")

                print("  ⚠️  Reset completed but scanner responsiveness unknown")
                return False

            finally:
                # Always restore original timeout
                self.usb_device.default_timeout = original_timeout

        except Exception as e:
            print(f"  ⚠️  Reset error: {e}")
            return False

    def mode_sense(self) -> Optional[int]:
        """Get mode sense data to determine MUD (Measurement Unit Divisor)."""
        print("Getting mode sense...")
        cmd = self._parse_command("1a 18 03 00 00 00")
        data, status = self._issue_command(cmd, data_in_length=64)

        if status == StatusType.READY and len(data) >= 8:
            # Extract MUD like SANE backend
            mud = struct.unpack(">H", data[6:8])[0]
            print(f"MUD (Measurement Unit Divisor): {mud}")
            self.mud = mud
            return mud
        else:
            print("Mode sense failed")
            return None

    def get_internal_info(self) -> Optional[ScannerInfo]:
        """Get internal scanner information (like SANE get_internal_info)."""
        print("Getting internal info...")
        # READ with datatype 0xe0 for internal info (256 bytes)
        cmd = bytearray(
            [
                0x28,  # READ
                0x00,  # LUN
                0xE0,  # Data type (internal info)
                0x00,  # Reserved
                0x00,
                0x00,  # Data type qualifier
                0x00,
                0x00,
                0x01,  # Transfer length (256 bytes, big-endian)
                0x00,  # Control byte
            ]
        )

        data, status = self._issue_command(bytes(cmd), data_in_length=256)

        if status == StatusType.READY and len(data) >= 32:
            info = ScannerInfo()

            # Parse internal info like SANE backend
            info.ad_bits = data[0x00]
            info.output_bits = data[0x01]
            info.max_resolution = struct.unpack(">H", data[0x02:0x04])[0]
            info.x_max = struct.unpack(">H", data[0x04:0x06])[0]
            info.y_max = struct.unpack(">H", data[0x06:0x08])[0]
            info.x_max_pixels = struct.unpack(">H", data[0x08:0x0A])[0]
            info.y_max_pixels = struct.unpack(">H", data[0x0A:0x0C])[0]
            info.current_y = struct.unpack(">H", data[0x10:0x12])[0]
            info.current_focus = struct.unpack(">H", data[0x12:0x14])[0]
            info.current_scan_pitch = data[0x14]
            info.auto_feeder = data[0x1E]
            info.analog_gamma = data[0x1F]

            # Device errors
            for i in range(8):
                info.device_errors[i] = data[0x40 + i]

            print(f"Scanner info: {info}")
            self.scanner_info = info
            return info
        else:
            print("Internal info read failed")
            return None

    def object_position(self, auto_feed: int = 0x00) -> bool:
        """Send OBJECT_POSITION command (like SANE coolscan_object_feed)."""
        print("Sending object position command...")
        cmd = bytearray(
            [
                0x31,  # OBJECT_POSITION
                0x00,  # Auto feeder function
                0x00,
                0x00,
                0x00,  # Count
                0x00,
                0x00,
                0x00,
                0x00,  # Reserved
                0x00,  # Control byte
            ]
        )

        _, status = self._issue_command(bytes(cmd))
        success = status == StatusType.READY
        print(f"Object position: {'SUCCESS' if success else 'FAILED'}")
        return success

    def send_lut(self, lut_data: bytes) -> bool:
        """Send LUT data (like SANE send_LUT)."""
        print("Sending LUT data...")
        # SEND with datatype 0xc0 for LUT
        cmd = bytearray(
            [
                0x2A,  # SEND
                0x00,  # LUN
                0xC0,  # Data type (user reg gamma/LUT)
                0x00,
                0x00,  # Data type qualifier
                0x00,
                0x00,
                0x00,  # Transfer length (will be set)
                0x00,  # Control byte
            ]
        )

        # Set transfer length
        cmd[6:9] = struct.pack(">L", len(lut_data))[1:4]  # 3 bytes

        _, status = self._issue_command(bytes(cmd), lut_data)
        success = status == StatusType.READY
        print(f"LUT send: {'SUCCESS' if success else 'FAILED'}")
        return success

    def _generate_identity_lut(self) -> bytes:
        """
        Generate an identity LUT (8192 bytes).

        The LUT maps each input value (0-4095) to itself.
        Format: 4096 × 16-bit big-endian values = 8192 bytes
        """
        lut = bytearray(8192)
        for i in range(4096):
            lut[i * 2] = (i >> 8) & 0xFF  # High byte
            lut[i * 2 + 1] = i & 0xFF  # Low byte
        return bytes(lut)

    def _upload_lut(self, channel: int, lut_data: bytes) -> bool:
        """Upload LUT data for a specific channel (1=R, 2=G, 3=B)."""
        if len(lut_data) != 8192:
            print(f"  ⚠️  LUT data must be 8192 bytes, got {len(lut_data)}")
            return False

        cmd = struct.pack(
            "BBBBBBBBBB", 0x2A, 0x00, 0x03, 0x00, channel, 0x01, 0x00, 0x20, 0x00, 0x00
        )

        _, status = self._issue_command(cmd, data_out=lut_data)
        if status != StatusType.READY:
            channel_names = {1: "R", 2: "G", 3: "B"}
            print(f"  ⚠️  LUT {channel_names.get(channel, channel)} upload failed")
            return False
        return True

    def upload_identity_luts(self, include_ir: bool = False) -> bool:
        """Upload identity LUTs for R, G, B channels (required before scan).

        Args:
            include_ir: If True, also upload LUT for IR channel (window 9).
                       Batch capture shows IR LUT uploaded before full scan.
        """
        lut_data = self._generate_identity_lut()

        channels = [9, 1, 2, 3] if include_ir else [1, 2, 3]

        for channel in channels:
            if not self._upload_lut(channel, lut_data):
                return False

        if self.verbose:
            ch_names = {1: "R", 2: "G", 3: "B", 9: "IR"}
            ch_list = ", ".join(ch_names.get(c, str(c)) for c in channels)
            print(f"  ✅ LUTs uploaded ({ch_list})")
        return True

    def set_window_wdb(self, wdb: WindowDescriptorBlock) -> bool:
        """Set the scan window parameters using MODE_SELECT."""
        mode_select_cmd = self._build_6byte_command(
            0x15, page=0x10, alloc_length=0x14, control=0x00
        )
        mode_params = bytes(
            [
                0x00,
                0x00,
                0x00,
                0x08,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x01,
                0x03,
                0x06,
                0x00,
                0x00,
                0x0B,
                0x54,
                0x00,
                0x00,
            ]
        )

        _, status = self._issue_command(mode_select_cmd, data_out=mode_params)
        if status != StatusType.READY:
            print(f"  ⚠️  MODE_SELECT failed")
            return False
        print("  ✅ MODE_SELECT OK")
        return True

    def set_scan_window(self, window_id: int = 1, scan_type: str = "prescan") -> bool:
        """
        Send SET_WINDOW (0x24) command with 58-byte window descriptor.

        This is REQUIRED before LUT uploads and START_SCAN.
        From USB capture: 24000000000000003a80 + 58 bytes WDB

        Args:
            window_id: Window ID (1=R, 2=G, 3=B, 9=IR)
            scan_type: 'prescan' for low-res AE scan, 'normal' for full scan
        """
        # SET_WINDOW command: 24 00 00 00 00 00 00 00 3a 80
        cmd = struct.pack("BBBBBBBBBB", 0x24, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3A, 0x80)

        # WDB data from USB capture - prescan uses low resolution (96 DPI)
        # Structure: header(8) + window_id(1) + res_xy(4) + offset_xy(8) + size(8) +
        #            brightness/threshold/contrast/composition(4) + depth(1) + zeros(13) +
        #            multiread(1) + averaging(1) + scan_kind(1) + scan_mode(1) +
        #            color_interleave(1) + ae(1) + exposure(4)
        # Key differences:
        #   - prescan: res=0x0060 (96 DPI), scan_kind=0x02
        #   - normal: res=0x0b54 (2900 DPI), scan_kind=0x01

        if scan_type == "prescan":
            # Exact bytes from USB capture for prescan (low-res AE scan)
            # Resolution: 0x0060 = 96 DPI, scan_kind: 0x02
            wdb_data = {
                1: bytes.fromhex(
                    "0000000000000032010000600060000000000000000000000b3600008760000000050c000000000000000000000000000081020202ff0000a381"
                ),
                2: bytes.fromhex(
                    "0000000000000032020000600060000000000000000000000b3600008760000000050c000000000000000000000000000081020202ff00008452"
                ),
                3: bytes.fromhex(
                    "0000000000000032030000600060000000000000000000000b3600008760000000050c000000000000000000000000000081020202ff00004e29"
                ),
            }
        else:
            # Full resolution scan (2900 DPI), scan_kind: 0x01
            wdb_data = {
                1: bytes.fromhex(
                    "000000000000003201000b540b54000000000000000000000b36000010ec0000000208000000000000000000000000000081010202ff00009ce6"
                ),
                2: bytes.fromhex(
                    "000000000000003202000b540b54000000000000000000000b36000010ec0000000208000000000000000000000000000081010202ff0000f912"
                ),
                3: bytes.fromhex(
                    "000000000000003203000b540b54000000000000000000000b36000010ec0000000208000000000000000000000000000081010202ff0000d77a"
                ),
                9: bytes.fromhex(
                    "000000000000003209000b540b54000000000000000000000b36000010ec0000000208000000000000000000000000000081010202ff0002056c"
                ),
            }

        wdb = wdb_data.get(window_id)
        if wdb is None:
            print(f"  ⚠️  Unknown window ID {window_id} for scan_type={scan_type}")
            return False

        print(f"    Sending SET_WINDOW {window_id}...")
        _, status = self._issue_command(cmd, data_out=wdb)
        if status != StatusType.READY:
            print(f"  ⚠️  SET_WINDOW {window_id} failed")
            return False
        return True

    def set_window(self, params: ScanParameters, scan_type: ScanType = ScanType.NORMAL) -> bool:
        """Set the scan window parameters (legacy method)."""
        # Convert ScanParameters to WDB
        wdb = WindowDescriptorBlock()
        wdb.x_resolution = params.resolution
        wdb.y_resolution = params.resolution
        wdb.width = params.x_max if params.x_max > 0 else 2592
        wdb.length = params.y_max if params.y_max > 0 else 3888
        wdb.ulx = params.x_min
        wdb.uly = params.y_min

        # Set negative/positive mode
        if params.negative:
            wdb.negative_dropout = 0x01  # Negative
        else:
            wdb.negative_dropout = 0x00  # Positive

        # Set scan mode
        if params.preview:
            wdb.scan_mode = 0x01  # Prescan
        else:
            wdb.scan_mode = 0x00  # Normal scan

        return self.set_window_wdb(wdb)

    def start_scan(self, scan_type: ScanType = ScanType.NORMAL) -> bool:
        """Start a scan operation."""
        cmd = self._build_6byte_command(0x1B, alloc_length=0x03, control=0x00)
        scan_data = bytes([0x01, 0x02, 0x03])  # R, G, B channels

        # Issue command and capture the raw status response
        # We need to get the actual 8-byte status to check ASCQ
        data, status = self._issue_command(cmd, data_out=scan_data)

        # Check the actual sense codes from the status response
        # USB capture shows START_SCAN returns: 0209800601000000
        # sense_key=9 (0x09), ASC=128 (0x80), ASCQ=6 (0x06)
        # This is expected and scanner continues to work
        # However, our status parser might classify this as ERROR or READY
        # We need to check the actual sense codes regardless of status type

        # Always log the sense codes for START_SCAN to diagnose issues
        if self._last_status_parsed:
            sense_key = self._last_status_parsed.get("sense_key", 0)
            sense_asc = self._last_status_parsed.get("sense_asc", 0)
            sense_ascq = self._last_status_parsed.get("sense_ascq", 0)
            if self._last_status_raw:
                print(
                    f"  START_SCAN status: {status}, sense: key=0x{sense_key:02x}, ASC=0x{sense_asc:02x}, ASCQ=0x{sense_ascq:02x}"
                )
                print(f"  Raw status: {self._last_status_raw.hex()}")

            # USB capture shows ASCQ=6 is expected (scan starts)
            if sense_key == 0x09 and sense_asc == 0x80:
                if sense_ascq == 0x06:
                    print(f"  ✅ ASCQ=6 (expected) - scan should start")
                elif sense_ascq == 0x01:
                    print(f"  ⚠️  ASCQ=1 (unexpected) - scan may not start")
                else:
                    print(f"  ⚠️  ASCQ=0x{sense_ascq:02x} (unexpected)")
        else:
            if self._last_status_raw:
                print(f"  ⚠️  No status parsed, raw: {self._last_status_raw.hex()}")

        if status == StatusType.ERROR:
            # Log the actual sense codes for debugging
            if self._last_status_parsed:
                sense_key = self._last_status_parsed.get("sense_key", 0)
                sense_asc = self._last_status_parsed.get("sense_asc", 0)
                sense_ascq = self._last_status_parsed.get("sense_ascq", 0)
                print(f"  ⚠️  START_SCAN returned error status")
                print(
                    f"     Sense: key=0x{sense_key:02x}, ASC=0x{sense_asc:02x}, ASCQ=0x{sense_ascq:02x}"
                )
                if self._last_status_raw:
                    print(f"     Raw status: {self._last_status_raw.hex()}")

                # USB capture shows ASCQ=6 is expected (scan starts)
                # ASCQ=1 indicates scan command was rejected - this is a real error
                if sense_key == 0x09 and sense_asc == 0x80:
                    if sense_ascq == 0x06:
                        print(f"     ✅ ASCQ=6 (expected) - scan should start")
                        # Continue - this is expected
                        return True
                    elif sense_ascq == 0x01:
                        print(f"     ❌ ASCQ=1 (error) - scan command rejected")
                        print(f"     Scanner did not start the scan. Possible causes:")
                        print(f"       - Scanner not in correct state (needs reset?)")
                        print(f"       - Missing prerequisite commands")
                        print(f"       - WDB configuration issue")
                        print(f"       - Scanner hardware issue or no film inserted")
                        # Fail immediately - this is a real error
                        return False
                    else:
                        print(f"     ⚠️  ASCQ=0x{sense_ascq:02x} (unexpected)")
                        # Unknown ASCQ - be conservative and fail
                        return False
            else:
                print(f"  ⚠️  START_SCAN returned error status (no sense details)")

            # Unknown error - fail to be safe
            return False
        elif status != StatusType.READY:
            print(f"  ⚠️  START_SCAN failed with status: {status}")
            return False

        # If we get here, status is READY
        # But USB capture shows START_SCAN should return ERROR with sense_key=9, ASC=128, ASCQ=6
        # Log this for debugging
        if self._last_status_parsed:
            sense_key = self._last_status_parsed.get("sense_key", 0)
            sense_asc = self._last_status_parsed.get("sense_asc", 0)
            sense_ascq = self._last_status_parsed.get("sense_ascq", 0)
            if sense_key != 0x00:  # If sense_key is not 0, it's unusual for READY status
                print(
                    f"  ⚠️  START_SCAN returned READY but sense_key=0x{sense_key:02x}, ASC=0x{sense_asc:02x}, ASCQ=0x{sense_ascq:02x}"
                )
                if self._last_status_raw:
                    print(f"     Raw status: {self._last_status_raw.hex()}")

        print("  ✅ Scan started")
        return True

    def read_scan_data(self, length: int, datatype: DataType = DataType.IMAGE_DATA) -> bytes:
        """
        Read scan data from the scanner with proper datatype.

        Format from USB capture: 28 00 [datatype] 00 00 00 [len_hi] [len_mid] [len_lo] 80 (10 bytes)
        This is READ(10) command (0x28) with datatype in byte 2 and 3-byte length.

        Examples from USB capture:
        - Image data: 28000000000001fec080 (130752 bytes, datatype 0x00)
        - Status: 28008700000000000680 (6 bytes, datatype 0x87)
        - Exposure: 28008e00000000000680 (6 bytes header, datatype 0x8e)
        - Exposure table: 28008e000000000d8880 (3464 bytes, datatype 0x8e)
        """
        if self.verbose:
            print(f"Reading scan data (datatype: {datatype.name}, length: {length})...")

        # Use appropriate timeout for read operations
        # Full scan chunks can take time; use 30s for large reads, 10s for small
        original_timeout = self.usb_device.default_timeout
        self.usb_device.default_timeout = 30000 if length > 65536 else 10000

        try:
            # Format: 28 00 [datatype] 00 00 00 [len_hi] [len_mid] [len_lo] 80
            # From capture: 28000000000001fec080 = 28 00 00 00 00 00 01 fe c0 80
            # Byte 0: 0x28 (READ command)
            # Byte 2: Datatype (0x00=image, 0x87=status, 0x8e=exposure)
            # Bytes 6-8: Length (3 bytes, big-endian)
            # Byte 9: 0x80 (control byte)
            cmd = struct.pack(
                "BBBBBBBBBB",
                0x28,  # READ(10) command (0x28, not 0x24!)
                0x00,  # Reserved
                datatype.value,  # Datatype in byte 2
                0x00,  # Reserved
                0x00,  # Reserved
                0x00,  # Reserved
                (length >> 16) & 0xFF,  # Length high byte
                (length >> 8) & 0xFF,  # Length mid byte
                length & 0xFF,  # Length low byte
                0x80,  # Control byte
            )

            data, status = self._issue_command(cmd, data_in_length=length)

            if status == StatusType.READY:
                if self.verbose:
                    print(f"Read {len(data)} bytes successfully")
                return data
            else:
                raise RuntimeError(f"Read scan data failed with status {status}")
        finally:
            # Restore original timeout
            self.usb_device.default_timeout = original_timeout

    def poll_until_ready(self, timeout: int = 30, poll_interval: float = 0.1) -> bool:
        """
        Poll scanner with TEST_UNIT_READY until it's ready (not busy/processing).

        From USB capture: After START_SCAN, scanner returns status 0x0202040100000000
        (PROCESSING) while scanning, then 0x0000000000000000 (READY) when complete.

        Args:
            timeout: Maximum time to wait in seconds
            poll_interval: Time between polls in seconds (default 0.1s = 100ms)

        Returns:
            True if scanner becomes ready, False if timeout
        """
        max_attempts = int(timeout / poll_interval)
        start_time = time.time()

        for attempt in range(max_attempts):
            try:
                cmd = self._build_6byte_command(0x00, control=0x00)
                _, status = self._issue_command(cmd)

                if status == StatusType.READY:
                    elapsed = time.time() - start_time
                    print(f"  ✅ Scanner ready after {elapsed:.1f}s ({attempt + 1} polls)")
                    return True
                elif status == StatusType.PROCESSING:
                    # Scanner is actively scanning - continue polling
                    if attempt % 20 == 0:  # Print every 2 seconds (20 * 0.1s)
                        elapsed = time.time() - start_time
                        print(f"  Scanning... ({elapsed:.1f}s, attempt {attempt + 1})")
                    # Continue polling - don't return yet
                elif status == StatusType.ERROR:
                    # Some errors might indicate still processing
                    if attempt % 20 == 0:
                        elapsed = time.time() - start_time
                        print(
                            f"  Polling... ({elapsed:.1f}s, attempt {attempt + 1}, status: {status.name})"
                        )
                    # Continue polling - don't return yet
                else:
                    # Unknown status - continue polling
                    if attempt % 20 == 0:
                        elapsed = time.time() - start_time
                        print(
                            f"  Polling... ({elapsed:.1f}s, attempt {attempt + 1}, status: {status.name})"
                        )

                time.sleep(poll_interval)
            except Exception as e:
                self._replay_reraise_if_needed(e)
                elapsed = time.time() - start_time
                if attempt % 20 == 0:  # Print errors periodically too
                    print(f"  Poll error ({elapsed:.1f}s, attempt {attempt + 1}): {e}")
                time.sleep(poll_interval)
                continue

        # Timeout - scanner never became ready
        elapsed = time.time() - start_time
        print(f"  ⚠️  Scanner not ready after {elapsed:.1f}s ({max_attempts} polls)")
        print(f"  ⚠️  Last status was PROCESSING - scanner may still be scanning")
        return False

    def read_prescan_image_data(self) -> bytes:
        """
        Read prescan image data blocks.

        From USB capture: Two 130752-byte blocks + one 11520-byte residual block.
        Total: 2 * 130752 + 11520 = 273024 bytes

        Returns:
            Concatenated image data bytes
        """
        if self.verbose:
            print("  Reading prescan image data...")

        all_data = bytearray()

        # Block 1: 130752 bytes (0x01fec0)
        try:
            data1 = self.read_scan_data(130752, DataType.IMAGE_DATA)
            all_data.extend(data1)
            if self.verbose:
                print(f"    Read block 1: {len(data1)} bytes")
        except Exception as e:
            print(f"    ⚠️  Failed to read block 1: {e}")
            return bytes(all_data)

        # Block 2: 130752 bytes (0x01fec0)
        try:
            data2 = self.read_scan_data(130752, DataType.IMAGE_DATA)
            all_data.extend(data2)
            if self.verbose:
                print(f"    Read block 2: {len(data2)} bytes")
        except Exception as e:
            print(f"    ⚠️  Failed to read block 2: {e}")
            return bytes(all_data)

        # Residual block: 11520 bytes (0x2d00)
        try:
            data3 = self.read_scan_data(11520, DataType.IMAGE_DATA)
            all_data.extend(data3)
            if self.verbose:
                print(f"    Read residual block: {len(data3)} bytes")
        except Exception as e:
            print(f"    ⚠️  Failed to read residual block: {e}")
            return bytes(all_data)

        if self.verbose:
            print(f"  ✅ Total image data: {len(all_data)} bytes")
        return bytes(all_data)

    def read_exposure_data(self) -> Optional[dict]:
        """
        Read exposure/calibration data (datatype 0x8e).

        From USB capture:
        1. Read 6-byte header: 28008e00000000000680
        2. Read 3464-byte table: 28008e000000000d8880

        Returns:
            Dict with 'header' and 'table' keys, or None if failed
        """
        if self.verbose:
            print("  Reading exposure/calibration data...")

        try:
            # Read header (6 bytes)
            header = self.read_scan_data(6, DataType.EXPOSURE_CALIBRATION)
            if self.verbose:
                print(f"    Read exposure header: {len(header)} bytes")

            # Read table (3464 bytes = 0x0d88)
            table = self.read_scan_data(0x0D88, DataType.EXPOSURE_CALIBRATION)
            if self.verbose:
                print(f"    Read exposure table: {len(table)} bytes")

            return {"header": header, "table": table}
        except Exception as e:
            self._replay_reraise_if_needed(e)
            print(f"    ⚠️  Failed to read exposure data: {e}")
            return None

    def get_window(self, window_id: int) -> Optional[bytes]:
        """
        Read back a Window Descriptor Block (WDB) using GET_WINDOW command.

        From USB capture: 25010000000100003a80 (window 1)
        Format: 25 01 00 00 00 [window_id] 00 00 3a 80 (10 bytes)
        Returns 58-byte WDB.

        Args:
            window_id: Window ID (0x01=R, 0x02=G, 0x03=B, 0x09=IR)

        Returns:
            58-byte WDB data, or None if failed
        """
        if self.verbose:
            print(f"  Reading WDB for window {window_id}...")

        # GET_WINDOW command: 25 01 00 00 00 [window_id] 00 00 3a 80
        cmd = struct.pack(
            "BBBBBBBBBB",
            0x25,  # GET_WINDOW command
            0x01,  # Subcommand/page
            0x00,  # Reserved
            0x00,  # Reserved
            0x00,  # Reserved
            window_id,  # Window ID (0x01=R, 0x02=G, 0x03=B, 0x09=IR)
            0x00,  # Reserved
            0x00,  # Reserved
            0x3A,  # Allocation length (58 bytes)
            0x80,  # Control byte
        )

        try:
            data, status = self._issue_command(cmd, data_in_length=58)
            if status == StatusType.READY and len(data) == 58:
                if self.verbose:
                    print(f"    Read WDB for window {window_id}: {len(data)} bytes")
                return data
            else:
                print(f"    ⚠️  Failed to read WDB: status={status}, len={len(data) if data else 0}")
                return None
        except Exception as e:
            self._replay_reraise_if_needed(e)
            print(f"    ⚠️  Error reading WDB: {e}")
            return None

    def extract_exposure_from_wdb(self, wdb: bytes) -> Optional[int]:
        """
        Extract exposure value from WDB bytes 54-57.

        From SANE backend (coolscan3.c):
        exposure = 65536 * (256 * wdb[54] + wdb[55]) + 256 * wdb[56] + wdb[57]

        Value is in 10ns units.

        Args:
            wdb: 58-byte Window Descriptor Block

        Returns:
            Exposure value in 10ns units, or None if invalid
        """
        if len(wdb) < 58:
            return None

        # Extract 4-byte exposure value (big-endian) from bytes 54-57
        exposure = 65536 * (256 * wdb[54] + wdb[55]) + 256 * wdb[56] + wdb[57]

        return exposure

    def get_exposure_values(self, colors: list = [1, 2, 3]) -> Optional[dict]:
        """
        Get exposure values for specified color channels by reading WDBs.

        This is equivalent to SANE's cs3_get_exposure() function.
        Reads WDBs for each color channel and extracts exposure from bytes 54-57.

        Args:
            colors: List of window IDs (default [1, 2, 3] for R, G, B)

        Returns:
            Dict with keys 'R', 'G', 'B' (and optionally 'IR') mapping to exposure
            values in 10ns units, or None if failed
        """
        if self.verbose:
            print("  Getting exposure values from WDBs...")

        exposure_values = {}
        color_names = {1: "R", 2: "G", 3: "B", 9: "IR"}

        for window_id in colors:
            wdb = self.get_window(window_id)
            if wdb is None:
                print(f"    ⚠️  Failed to read WDB for window {window_id}")
                continue

            exposure = self.extract_exposure_from_wdb(wdb)
            if exposure is not None:
                color_name = color_names.get(window_id, f"Window{window_id}")
                exposure_values[color_name] = exposure
                if self.verbose:
                    # Convert to milliseconds for readability
                    exposure_ms = exposure / 100000.0  # 10ns units -> ms
                    print(f"    {color_name}: {exposure} (10ns) = {exposure_ms:.2f} ms")
            else:
                print(f"    ⚠️  Failed to extract exposure from WDB for window {window_id}")

        if len(exposure_values) == 0:
            print("    ⚠️  No exposure values extracted")
            return None

        return exposure_values

    def stop_scan(self) -> bool:
        """Stop the current scan operation.

        USB capture shows: 1b 00 00 00 04 00 (sf=0x04 = stop)
        Followed by 4-byte data payload: 09 01 02 03 (IR + RGB channels)
        Then status read (0x87).
        """
        cmd = self._build_6byte_command(0x1B, alloc_length=0x04, control=0x00)
        scan_data = bytes([0x09, 0x01, 0x02, 0x03])  # IR, R, G, B channels

        if self.verbose:
            print("Stopping scan...")

        data, status = self._issue_command(cmd, data_out=scan_data)

        if status == StatusType.ERROR:
            if self._last_status_parsed:
                sense_key = self._last_status_parsed.get("sense_key", 0)
                sense_asc = self._last_status_parsed.get("sense_asc", 0)
                sense_ascq = self._last_status_parsed.get("sense_ascq", 0)
                print(
                    f"  STOP_SCAN status: {status}, sense: key=0x{sense_key:02x}, "
                    f"ASC=0x{sense_asc:02x}, ASCQ=0x{sense_ascq:02x}"
                )
            return False
        elif status != StatusType.READY:
            print(f"  ⚠️  STOP_SCAN returned status: {status}")
            return False

        if self.verbose:
            print("  ✅ Scan stopped")
        return True

    def cancel_scan(self) -> bool:
        """Cancel the current scan operation."""
        cmd = self._parse_command("c0 00 00 00 00 00")
        _, status = self._issue_command(cmd)
        return status == StatusType.READY

    def auto_focus(self) -> bool:
        """Perform auto focus operation."""
        print("Performing auto focus...")
        cmd = bytearray(
            [
                0xC2,  # AUTO_FOCUS
                0x00,
                0x00,
                0x00,  # Reserved
                0x00,  # Transfer length
                0x00,  # Control byte
            ]
        )

        _, status = self._issue_command(bytes(cmd))
        success = status == StatusType.READY
        print(f"Auto focus: {'SUCCESS' if success else 'FAILED'}")
        return success

    def prescan(self) -> bool:
        """Perform prescan operation."""
        print("Starting prescan...")

        # Step 0: Ensure scanner is ready before starting
        # If scanner is in a bad state, try to reset it
        if not self.test_unit_ready():
            print("  ⚠️  Scanner not ready, attempting reset...")
            self.reset_scanner()
            # Wait a bit for scanner to recover
            time.sleep(0.5)
            if not self.wait_scanner(max_attempts=5, delay=0.2):
                print("  ❌ Scanner not responsive after reset")
                return False

        # Step 0b: Reserve unit (required before scan operations)
        # USB capture shows RESERVE_UNIT (0x16) before prescan sequence
        if not self.reserve_unit():
            print("  ⚠️  Failed to reserve unit - scanner may be in use")
            return False

        # Step 1: SET_WINDOW with 58-byte window descriptors
        # Note: MODE_SELECT happens earlier in the session (during initialization),
        # not right before prescan. USB capture shows MODE_SELECT at line 239 (~36s),
        # while prescan SET_WINDOW commands are at lines 695-715 (~87s).
        # For prescan: only windows 1, 2, 3 (RGB) - no infrared (window 9)
        # USB capture shows exactly 3 SET_WINDOW commands for prescan
        for win_id in [1, 2, 3]:
            if not self.set_scan_window(win_id, scan_type="prescan"):
                return False
        print("  ✅ Windows set")

        # Step 2b: TEST_UNIT_READY between SET_WINDOW and LUTs (from capture)
        if not self.test_unit_ready():
            print("  ⚠️  Scanner not ready before LUT upload")
            return False

        # Step 3: Upload identity LUTs for R, G, B
        if not self.upload_identity_luts():
            return False

        # Step 4: Start scan
        # Note: USB capture shows direct transition from LUT uploads to START_SCAN
        # (no TEST_UNIT_READY after LUTs). The extra TEST_UNIT_READY might cause
        # scanner to reject START_SCAN with ASCQ=1 instead of accepting with ASCQ=6.
        if not self.start_scan():
            # Release unit on failure
            self.release_unit()
            return False

        # Step 4b: Read initial status/progress blocks after START_SCAN
        # USB capture shows immediate READ of status/progress (datatype 0x87) after START_SCAN
        # This appears to be required to get the scanner into the scanning state
        # USB capture sequence: START_SCAN -> read 6-byte status block -> read 33-byte status block
        # Note: These reads may fail with ABORTED COMMAND - that's OK, scanner will continue
        try:
            # Read first status/progress block (6 bytes, datatype 0x87)
            # Command: 28008700000000000680
            status_block1 = self.read_scan_data(6, DataType.STATUS_PROGRESS)
            if len(status_block1) > 0:
                if self.verbose:
                    print(f"  Status/progress block 1: {len(status_block1)} bytes")
        except Exception as e:
            self._replay_reraise_if_needed(e)
            # ABORTED COMMAND (sense_key=11) is common here - scanner may not be ready yet
            # This is non-fatal - continue to polling
            if self.verbose:
                print(f"  (Status/progress block 1 skipped: {e})")

        try:
            # Read second status/progress block (33 bytes, datatype 0x87)
            # Command: 28008700000000002180
            status_block2 = self.read_scan_data(33, DataType.STATUS_PROGRESS)
            if len(status_block2) > 0:
                if self.verbose:
                    print(f"  Status/progress block 2: {len(status_block2)} bytes")
        except Exception as e:
            self._replay_reraise_if_needed(e)
            # ABORTED COMMAND is common here too - non-fatal
            if self.verbose:
                print(f"  (Status/progress block 2 skipped: {e})")

        # Step 5: Poll until scanner is ready (replaces fixed 8s sleep)
        # From USB capture: Scanner returns PROCESSING status while scanning,
        # then READY when complete (~13 seconds for prescan)
        print("  Waiting for prescan to complete...")
        ready = self.poll_until_ready(timeout=30, poll_interval=0.1)
        if not ready:
            print("  ⚠️  Scanner not ready after prescan - aborting data read")
            return False
        print("  ✅ Scanner confirmed ready, proceeding to read data...")

        # Small delay after READY to allow scanner to prepare data buffers
        # USB capture shows ~1ms delay between READY status and first READ command
        time.sleep(0.05)  # 50ms delay to let scanner settle

        # Clear any pending data in USB buffers before reading
        # This prevents Overflow errors from leftover data from polling
        # USB capture shows GET_WINDOW commands before image data read, which might clear buffer
        # But we'll also explicitly drain any pending data
        try:
            # Clear halt on IN endpoint to reset any error state
            self.usb_device.clear_halt(self.bulk_in.bEndpointAddress)
            time.sleep(0.01)  # Brief delay after clear_halt

            # Try to drain any pending data (non-blocking, short timeout)
            # This handles leftover data from TEST_UNIT_READY polling
            # Use pyusb's read with short timeout to fail fast if no data
            drained = 0
            original_timeout = self.usb_device.default_timeout
            self.usb_device.default_timeout = 100  # 100ms timeout for draining
            try:
                for attempt in range(10):  # More attempts
                    try:
                        chunk = self.usb_device.read(self.bulk_in.bEndpointAddress, 4096)
                        if hasattr(chunk, "tobytes"):
                            chunk = chunk.tobytes()
                        if len(chunk) > 0:
                            drained += len(chunk)
                            if self.verbose:
                                print(
                                    f"  Drained {len(chunk)} bytes from buffer (attempt {attempt+1})"
                                )
                        else:
                            break  # No more data
                    except (usb.core.USBTimeoutError, usb.core.USBError) as e:
                        # Timeout or other USB error - no more data
                        if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                            break  # No more data
                        # Other USB errors might indicate no data
                        break
                    except Exception:
                        break  # No more data or other error
            finally:
                self.usb_device.default_timeout = original_timeout
            if drained > 0:
                print(f"  Drained {drained} bytes from USB buffer before data read")
            elif self.verbose:
                print("  No data to drain from buffer")
        except Exception as e:
            if self.verbose:
                print(f"  (Buffer clear: {e})")

        # Step 6: Read prescan image data
        # From USB capture: Two 130752-byte blocks + one 11520-byte residual
        image_data = self.read_prescan_image_data()
        if len(image_data) == 0:
            print("  ⚠️  No image data read")
            # Don't fail - exposure data might still be useful

        # Step 7: Read exposure/calibration data
        # From USB capture: 6-byte header + 3464-byte table (datatype 0x8e)
        exposure_data = self.read_exposure_data()
        if exposure_data is None:
            print("  ⚠️  Failed to read exposure data")
            # Don't fail - image data was already read

        # Step 8: Get exposure values from WDBs (optional but recommended)
        # This reads back the WDBs and extracts exposure from bytes 54-57
        # Equivalent to SANE's cs3_get_exposure() function
        exposure_values = self.get_exposure_values(colors=[1, 2, 3])  # R, G, B
        if exposure_values:
            if self.verbose:
                print("  ✅ Exposure values extracted from WDBs")
        else:
            print("  ⚠️  Could not extract exposure values from WDBs")

        print("✅ Prescan completed")
        return True

    def read_capacity(self) -> Optional[dict]:
        """
        Read capacity information (READ_CAPACITY command).

        Format from USB capture: 25 00 00 00 00 00 00 00 3a 80 (10 bytes)
        """
        print("Reading capacity...")
        try:
            # READ_CAPACITY is 10 bytes: 25 00 00 00 00 00 00 00 3a 80
            # Byte 0: 0x25 = READ_CAPACITY
            # Bytes 1-8: Parameters
            # Byte 9: 0x80 = Control byte
            cmd = struct.pack(
                "BBBBBBBBBB", 0x25, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3A, 0x80
            )
            data, status = self._issue_command(cmd, data_in_length=58)  # 58 bytes response

            if status == StatusType.READY and len(data) >= 58:
                # Parse capacity data
                # Response format from capture: 01 00 00 00 00 00 00 32 00 00 0b 54 0b 54 00 00...
                return {
                    "status": data[0],
                    "capacity": struct.unpack(">Q", data[1:9])[0] if len(data) >= 9 else 0,
                    "block_size": struct.unpack(">I", data[9:13])[0] if len(data) >= 13 else 0,
                    "raw_data": data.hex(),
                }
            else:
                print(
                    f"  ⚠️  READ_CAPACITY failed: status={status}, data_len={len(data) if data else 0}"
                )
                return None
        except Exception as e:
            print(f"  ❌ READ_CAPACITY error: {e}")
            import traceback

            traceback.print_exc()
            return None

    def initialize_scanner(self) -> bool:
        """
        Initialize scanner with full sequence from USB capture analysis.

        Sequence:
        1. INQUIRY (standard) - 36 bytes
        2. TEST_UNIT_READY (multiple times)
        3. INQUIRY pages (0x01, 0xd1, 0xc1, 0xe1, 0xf0, 0xf8)
        4. RESERVE_UNIT
        5. READ_CAPACITY
        """
        print("Initializing scanner with USB capture sequence...")

        try:
            # 1. Standard INQUIRY (36 bytes)
            print("\n1. Standard INQUIRY...")
            try:
                inquiry_data = self.inquiry(page=-1)
                if inquiry_data and len(inquiry_data) >= 36:
                    # Extract device identification
                    vendor = inquiry_data[8:16].decode("ascii", errors="ignore").strip()
                    product = inquiry_data[16:32].decode("ascii", errors="ignore").strip()
                    revision = inquiry_data[32:36].decode("ascii", errors="ignore").strip()
                    print(f"  ✅ Device: {vendor} {product} {revision}")
                else:
                    print(f"  ❌ Standard INQUIRY returned insufficient data")
                    return False
            except Exception as e:
                self._replay_reraise_if_needed(e)
                print(f"  ❌ Standard INQUIRY failed: {e}")
                print("  Aborting initialization - scanner is not responding")
                return False

            # 2. Wait for scanner ready (multiple TEST_UNIT_READY)
            print("\n2. Waiting for scanner ready...")
            if not self.wait_scanner(max_attempts=10, delay=0.5):
                print("  ⚠️  Scanner not ready, continuing anyway...")

            # 3. INQUIRY pages (two-step: get length, then full data)
            pages = [
                (0x01, "Page 0x01 (capabilities)"),
                (0xD1, "Page 0xd1 (MUD info)"),
                (0xC1, "Page 0xc1 (configuration)"),
                (0xE1, "Page 0xe1"),
                (0xF0, "Page 0xf0"),
                (0xF8, "Page 0xf8"),
            ]

            print("\n3. Reading INQUIRY pages...")
            for page, description in pages:
                try:
                    print(f"  {description}...")
                    data = self.inquiry(page=page)
                    if data:
                        print(f"    ✅ Got {len(data)} bytes")
                        # Store MUD if this is page 0xd1
                        if page == 0xD1 and len(data) >= 28:
                            # Extract MUD from page 0xd1 data
                            # Format from capture: 06 d1 00 18 07 42 02 46...
                            # MUD might be in the data
                            pass
                except Exception as e:
                    self._replay_reraise_if_needed(e)
                    print(f"    ⚠️  Page 0x{page:02x} failed: {e}")

            # 4. RESERVE_UNIT
            print("\n4. Reserving unit...")
            if not self.reserve_unit():
                print("  ⚠️  Failed to reserve unit, continuing anyway...")

            # 5. READ_CAPACITY
            print("\n5. Reading capacity...")
            capacity = self.read_capacity()
            if capacity:
                print(f"  ✅ Capacity info retrieved")
            else:
                print(f"  ⚠️  READ_CAPACITY failed, continuing anyway...")

            # 6. MODE_SELECT - required before SET_WINDOW operations
            # USB capture shows MODE_SELECT at line 239 (~36s) during initialization
            print("\n6. Sending MODE_SELECT...")
            mode_select_cmd = self._build_6byte_command(0x15, page=0x10, alloc_length=0x14, control=0x00)
            mode_params = bytes([
                0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00,
                0x00, 0x00, 0x00, 0x01, 0x03, 0x06, 0x00, 0x00,
                0x0B, 0x54, 0x00, 0x00
            ])
            _, status = self._issue_command(mode_select_cmd, data_out=mode_params)
            if status != StatusType.READY:
                print("  ⚠️  MODE_SELECT failed")
                return False
            print("  ✅ MODE_SELECT OK")
            # Small delay after MODE_SELECT (USB capture shows ~150ms)
            time.sleep(0.15)

            print("\n✅ Scanner initialization completed")
            return True

        except Exception as e:
            self._replay_reraise_if_needed(e)
            print(f"❌ Scanner initialization failed: {e}")
            import traceback

            traceback.print_exc()
            return False

    def perform_scan_sequence(self, params: ScanParameters) -> bool:
        """Perform complete scan sequence like SANE backend."""
        print("Performing complete scan sequence...")

        try:
            # 1. Wait for scanner ready
            if not self.scanner_ready(timeout=30):
                print("Scanner not ready")
                return False

            # 2. Reserve unit
            if not self.reserve_unit():
                print("Failed to reserve unit")
                return False

            # 3. Object feed
            if not self.object_position():
                print("Failed object position")
                return False

            # 4. Set window parameters
            if not self.set_window(params):
                print("Failed to set window")
                return False

            # 5. Send proper 8192-byte identity LUTs per channel (like prescan)
            if not self.upload_identity_luts():
                print("Failed to upload LUTs")
                return False

            # 6. Start scan
            if not self.start_scan():
                print("Failed to start scan")
                return False

            # 7. Poll until scanner is ready (no TEST_UNIT_READY after start_scan!)
            # USB capture shows direct PROCESSING->READY polling, not TUR.
            # Sending TUR after START_SCAN causes scanner to reject with ASCQ=1.
            if not self.poll_until_ready(timeout=120, poll_interval=0.5):
                print("Scanner did not become ready after scan start")
                return False

            print("Scan sequence completed successfully")
            return True

        except Exception as e:
            print(f"Scan sequence failed: {e}")
            return False

    def batch_scan_setup(self) -> bool:
        """Perform full scan setup with IR channel support.

        USB capture shows: SET_WINDOW ×4 (RGB + IR window 9),
        LUT uploads (IR + RGB), then STOP_SCAN.
        """
        if self.verbose:
            print("Performing batch scan setup (with IR channel)...")

        # SET_WINDOW for RGB + IR (window 9)
        for win_id in [1, 2, 3, 9]:
            if not self.set_scan_window(win_id, scan_type="normal"):
                return False
        if self.verbose:
            print("  ✅ Windows set (RGB + IR)")

        # TEST_UNIT_READY between SET_WINDOW and LUTs
        if not self.test_unit_ready():
            if self.verbose:
                print("  ⚠️  TUR after SET_WINDOW failed")

        # Upload LUTs for IR + RGB
        if not self.upload_identity_luts(include_ir=True):
            return False

        # STOP_SCAN to finalize setup
        if not self.stop_scan():
            if self.verbose:
                print("  ⚠️  STOP_SCAN after setup failed")

        if self.verbose:
            print("  ✅ Batch scan setup complete")
        return True

    def batch_scan_teardown(self) -> bool:
        """Perform teardown after full scan.

        USB capture shows: SET_WINDOW ×4, LUT uploads, STOP_SCAN.
        """
        if self.verbose:
            print("Performing batch scan teardown...")

        # SET_WINDOW for RGB + IR
        for win_id in [1, 2, 3, 9]:
            if not self.set_scan_window(win_id, scan_type="normal"):
                return False

        # TEST_UNIT_READY
        if not self.test_unit_ready():
            if self.verbose:
                print("  ⚠️  TUR after teardown SET_WINDOW failed")

        # Upload LUTs for IR + RGB
        if not self.upload_identity_luts(include_ir=True):
            return False

        # STOP_SCAN
        if not self.stop_scan():
            if self.verbose:
                print("  ⚠️  STOP_SCAN after teardown failed")

        if self.verbose:
            print("  ✅ Teardown complete")
        return True

    def batch_between_scan_setup(self) -> bool:
        """Setup between scans in a batch.

        USB capture shows: polling until READY, READ_CAPACITY for RGB windows,
        SET_WINDOW for RGB only, TUR, LUT uploads for RGB, then START_SCAN.
        """
        if self.verbose:
            print("Performing between-scan setup...")

        # Poll until ready
        if not self.poll_until_ready(timeout=60, poll_interval=0.5):
            print("  ❌ Scanner did not become ready")
            return False

        # READ_CAPACITY for RGB windows
        for win_id in [1, 2, 3]:
            self.read_capacity(window_id=win_id)

        # SET_WINDOW for RGB only
        for win_id in [1, 2, 3]:
            if not self.set_scan_window(win_id, scan_type="normal"):
                return False

        # TUR
        if not self.test_unit_ready():
            if self.verbose:
                print("  ⚠️  TUR failed")

        # Upload LUTs for RGB only
        if not self.upload_identity_luts(include_ir=False):
            return False

        if self.verbose:
            print("  ✅ Between-scan setup complete")
        return True

    def close(self):
        """Close the connection to the scanner."""
        # Disable USB capture if active
        self.disable_usb_capture()

        if self._usb_capture_replay is not None:
            self.usb_device = None
            return

        if self.usb_device:
            try:
                # Release interface before disposing
                try:
                    usb.util.release_interface(self.usb_device, 0)
                except (usb.core.USBError, AttributeError):
                    # Interface might not be claimed, that's OK
                    pass

                # Reattach kernel driver if it was detached (mostly for Linux)
                try:
                    if hasattr(self.usb_device, "attach_kernel_driver"):
                        self.usb_device.attach_kernel_driver(0)
                except (usb.core.USBError, NotImplementedError, AttributeError):
                    # Not supported on macOS, that's OK
                    pass

            except Exception:
                # Ignore errors during cleanup
                pass
            finally:
                usb.util.dispose_resources(self.usb_device)
        # TODO: Close SCSI connection if needed
