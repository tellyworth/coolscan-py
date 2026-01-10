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
    IMAGE_DATA = 0x00
    LUT = 0x01
    IMAGE_POSITIONS = 0x88
    SHADING_DATA = 0xa0
    USER_REG_GAMMA = 0xc0
    DEVICE_INTERNAL_INFO = 0xe0


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
        data[0x02:0x04] = struct.pack('>H', self.x_resolution)
        data[0x04:0x06] = struct.pack('>H', self.y_resolution)

        # Position and size (big-endian)
        data[0x06:0x0a] = struct.pack('>L', self.ulx)
        data[0x0a:0x0e] = struct.pack('>L', self.uly)
        data[0x0e:0x12] = struct.pack('>L', self.width)
        data[0x12:0x16] = struct.pack('>L', self.length)

        # Image parameters
        data[0x16] = self.brightness
        data[0x18] = self.contrast
        data[0x19] = self.composition
        data[0x1a] = self.bits_per_pixel

        # Pixel counts (big-endian)
        data[0x28:0x2c] = struct.pack('>L', self.width)
        data[0x2c:0x30] = struct.pack('>L', self.length)

        # Scan parameters
        data[0x30] = self.negative_dropout
        data[0x31] = self.scan_mode
        data[0x32] = self.transfer_mode
        data[0x33] = self.gamma_selection

        # Color adjustments
        data[0x37] = self.brightness_r
        data[0x38] = self.brightness_g
        data[0x39] = self.brightness_b
        data[0x3a] = self.contrast_r
        data[0x3b] = self.contrast_g
        data[0x3c] = self.contrast_b

        # Exposure settings
        data[0x49] = self.exposure_r
        data[0x4a] = self.exposure_g
        data[0x4b] = self.exposure_b

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
    def from_bytes(cls, data: bytes) -> 'WindowDescriptorBlock':
        """Create WDB from bytes."""
        if len(data) < 117:
            raise ValueError("WDB data too short")

        wdb = cls()

        # Parse basic fields
        wdb.window_id = data[0x00]
        wdb.auto_flag = data[0x01]

        # Resolution
        wdb.x_resolution = struct.unpack('>H', data[0x02:0x04])[0]
        wdb.y_resolution = struct.unpack('>H', data[0x04:0x06])[0]

        # Position and size
        wdb.ulx = struct.unpack('>L', data[0x06:0x0a])[0]
        wdb.uly = struct.unpack('>L', data[0x0a:0x0e])[0]
        wdb.width = struct.unpack('>L', data[0x0e:0x12])[0]
        wdb.length = struct.unpack('>L', data[0x12:0x16])[0]

        # Image parameters
        wdb.brightness = data[0x16]
        wdb.contrast = data[0x18]
        wdb.composition = data[0x19]
        wdb.bits_per_pixel = data[0x1a]

        # Scan parameters
        wdb.negative_dropout = data[0x30]
        wdb.scan_mode = data[0x31]
        wdb.transfer_mode = data[0x32]
        wdb.gamma_selection = data[0x33]

        # Color adjustments
        wdb.brightness_r = data[0x37]
        wdb.brightness_g = data[0x38]
        wdb.brightness_b = data[0x39]
        wdb.contrast_r = data[0x3a]
        wdb.contrast_g = data[0x3b]
        wdb.contrast_b = data[0x3c]

        # Exposure settings
        wdb.exposure_r = data[0x49]
        wdb.exposure_g = data[0x4a]
        wdb.exposure_b = data[0x4b]

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

    def __init__(self, device):
        self.device = device
        self.interface = device.interface
        self.usb_device = None
        self.scsi_fd = None
        self.scanner_info = None
        self.mud = 2700  # Measurement Unit Divisor

        if self.interface.value == "usb":
            self._init_usb()
        else:
            self._init_scsi()

    def _init_usb(self):
        """Initialize USB connection with proper interface claiming and endpoint setup."""
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
                self.usb_device = usb.core.find(idVendor=vendor_id, idProduct=product_id, backend=libusb0_backend)
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
            cfg_desc = usb.util.find_descriptor(
                self.usb_device,
                bConfigurationValue=1
            )
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
                    if 'result too large' not in err_msg and e.errno != 16:
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
                    custom_match=lambda e:
                        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
                )

                self.bulk_in = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e:
                        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                )

                if self.bulk_out and self.bulk_in:
                    print(f"  Found endpoints via descriptor: OUT=0x{self.bulk_out.bEndpointAddress:02x}, IN=0x{self.bulk_in.bEndpointAddress:02x}")
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
                    custom_match=lambda e:
                        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
                )

                self.bulk_in = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e:
                        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                )

                if self.bulk_out and self.bulk_in:
                    print(f"  Found endpoints via active config: OUT=0x{self.bulk_out.bEndpointAddress:02x}, IN=0x{self.bulk_in.bEndpointAddress:02x}")
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
            if hasattr(self.usb_device, 'is_kernel_driver_active'):
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
                    if 'no such file' not in err_msg and 'not supported' not in err_msg:
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
            if e.errno == 16 or 'result too large' in err_msg or 'resource busy' in err_msg or 'other error' in err_msg:
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
        return struct.pack('B', byte)

    def _pack_word(self, word: int) -> bytes:
        """Pack a 16-bit word (big-endian)."""
        return struct.pack('>H', word)

    def _pack_long(self, value: int) -> bytes:
        """Pack a 32-bit long (big-endian)."""
        return struct.pack('>L', value)

    def _parse_command(self, command_str: str) -> bytes:
        """Parse a hex command string into bytes."""
        # Remove spaces and convert hex string to bytes
        hex_str = command_str.replace(' ', '')
        return bytes.fromhex(hex_str)

    def _build_6byte_command(self, cmd_code: int, page: int = 0,
                            param2: int = 0, param3: int = 0,
                            alloc_length: int = 0, control: int = 0x80) -> bytes:
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
        return struct.pack('BBBBBB', cmd_code, page, param2, param3, alloc_length, control)

    def _usb_write_bulk(self, data: bytes) -> int:
        """Write data to USB bulk endpoint."""
        try:
            result = self.usb_device.write(self.bulk_out.bEndpointAddress, data)
            # Display data sent
            data_hex = data.hex()
            print(f"    📤 Sent {len(data)} bytes: {data_hex}")
            if len(data) > 0:
                print(f"       First byte: 0x{data[0]:02x}, Last byte: 0x{data[-1]:02x}")
            return result
        except Exception as e:
            print(f"    ❌ Write error: {e}")
            raise

    def _usb_read_bulk(self, length: int) -> bytes:
        """Read data from USB bulk endpoint."""
        try:
            data = self.usb_device.read(self.bulk_in.bEndpointAddress, length)
            # Display any data received
            if data:
                data_bytes = data.tobytes() if hasattr(data, 'tobytes') else bytes(data)
                print(f"    📥 Received {len(data_bytes)} bytes: {data_bytes.hex()}")
                if len(data_bytes) > 0:
                    print(f"       First byte: 0x{data_bytes[0]:02x}, Last byte: 0x{data_bytes[-1]:02x}")
            return data
        except Exception as e:
            print(f"    ❌ Read error: {e}")
            raise

    def wait_scanner(self, max_attempts: int = 40, delay: float = 0.5) -> bool:
        """
        Wait for scanner to be ready - based on SANE backend wait_scanner().

        This function keeps sending TEST_UNIT_READY repeatedly until the scanner
        responds, handling timeouts and busy states. This is the wake-up sequence
        that's critical for initializing communication.
        """
        print(f"  ⏳ Waiting for scanner to be ready (max {max_attempts} attempts, {delay}s delay)...")

        for attempt in range(max_attempts):
            try:
                print(f"    Attempt {attempt + 1}/{max_attempts}: Sending TEST_UNIT_READY...")
                # Use correct 6-byte format
                cmd = self._build_6byte_command(0x00, control=0x00)

                # Use the proper command sequence: send command, phase check, read phase, read status
                try:
                    # Send command
                    self._usb_write_bulk(cmd)
                    print(f"      ✅ Command sent successfully")

                    # Send phase check
                    phase_check = self._pack_byte(0xd0)
                    self._usb_write_bulk(phase_check)

                    # Read phase response
                    try:
                        phase_response = self._usb_read_bulk(1)
                        if hasattr(phase_response, 'tobytes'):
                            phase_response = phase_response.tobytes()
                        phase_byte = phase_response[0] if len(phase_response) > 0 else 0
                        print(f"      Phase: 0x{phase_byte:02x}")
                    except Exception as e:
                        print(f"      ⚠️  Phase read failed: {e} (continuing anyway)")
                        phase_byte = 0x01  # Assume status phase

                    # Read status (8 bytes)
                    print(f"      Reading status (8 bytes)...")
                    status_data = self._usb_read_bulk(8)
                    if hasattr(status_data, 'tobytes'):
                        status_data = status_data.tobytes()

                    if status_data and len(status_data) >= 8:
                        print(f"      ✅ Received status data!")
                        print(f"      Status bytes: {status_data.hex()}")

                        # Parse status
                        status, parsed = self._parse_status(status_data)
                        print(f"      Parsed status: {status}, sense: {parsed}")

                        if status == StatusType.READY:
                            print(f"  ✅ Scanner is READY after {attempt + 1} attempts!")
                            return True
                        elif status == StatusType.NO_DOCS:
                            print(f"  ✅ Scanner responded (NO_DOCS) after {attempt + 1} attempts!")
                            return True
                        elif status == StatusType.PROCESSING:
                            print(f"  ⏳ Scanner is PROCESSING, continuing wait...")
                            time.sleep(delay)
                            continue
                        else:
                            print(f"  ⚠️  Scanner status: {status}, continuing wait...")
                            time.sleep(delay)
                            continue
                    else:
                        print(f"      ⚠️  Incomplete status data: {len(status_data) if status_data else 0} bytes")
                        time.sleep(delay)
                        continue

                except Exception as e:
                    print(f"      ⚠️  Command sequence failed: {e} (will retry)")
                    time.sleep(delay)
                    continue

            except Exception as e:
                print(f"    ⚠️  Attempt {attempt + 1} error: {e} (will retry)")
                time.sleep(delay)
                continue

        print(f"  ❌ Scanner did not become ready after {max_attempts} attempts")
        return False

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
                print(f"Phase check attempt {attempt + 1} failed: {e}")
                # Longer delay on error too
                time.sleep(1.0 * (attempt + 1))

        return PhaseType.NONE

    def _parse_status(self, status_data: bytes) -> Tuple[StatusType, dict]:
        """Parse 8-byte status response with comprehensive sense key handling."""
        if len(status_data) != 8:
            return StatusType.ERROR, {}

        sense_key = status_data[1] & 0x0f
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
            elif sense_asc == 0x3a and sense_ascq == 0x00:
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
        elif sense_key == 0x0b:
            # Aborted command
            status = StatusType.ERROR
        else:
            status = StatusType.ERROR

        return status, {
            'sense_key': sense_key,
            'sense_asc': sense_asc,
            'sense_ascq': sense_ascq
        }

    def _check_phase(self) -> PhaseType:
        """Check the current USB phase."""
        # Send phase check command (0xd0)
        phase_cmd = self._pack_byte(0xd0)
        try:
            self._usb_write_bulk(phase_cmd)
            print(f"      Phase check command (0xd0) sent")

            # Read phase response
            response = self._usb_read_bulk(1)
            # Convert array.array to bytes if needed
            if hasattr(response, 'tobytes'):
                response = response.tobytes()
            elif hasattr(response, '__iter__'):
                response = bytes(response)

            if response and len(response) >= 1:
                phase = PhaseType(response[0])
                print(f"      Phase response: {phase}")
                return phase
            else:
                print(f"      ⚠️  No phase response received")
                return PhaseType.NONE
        except Exception as e:
            print(f"      ⚠️  Phase check error: {e}")
            return PhaseType.NONE

    def _issue_command(self, command: bytes, data_out: bytes = b'',
                      data_in_length: int = 0) -> Tuple[bytes, StatusType]:
        """Issue a command to the scanner."""
        if self.interface.value == "usb":
            return self._issue_usb_command(command, data_out, data_in_length)
        else:
            return self._issue_scsi_command(command, data_out, data_in_length)

    def _issue_usb_command(self, command: bytes, data_out: bytes = b'',
                          data_in_length: int = 0) -> Tuple[bytes, StatusType]:
        """
        Issue a USB command following the correct protocol pattern from USB capture.

        Pattern:
        1. Send command (6 bytes)
        2. Send phase check (0xd0)
        3. Read phase response (1 byte: 0x01 = status, 0x03 = data in)
        4. If phase is 0x03 and data_in_length > 0: Read data
        5. Read status (8 bytes)
        """
        print(f"  Issuing USB command: {command.hex()}")

        try:
            # Step 1: Send command
            self._usb_write_bulk(command)
            print(f"    Command sent successfully")

            # Step 2: Send phase check (0xd0)
            phase_check = self._pack_byte(0xd0)
            self._usb_write_bulk(phase_check)
            print(f"    Phase check sent (0xd0)")

            # Step 3: Read phase response (1 byte)
            try:
                phase_response = self._usb_read_bulk(1)
                if hasattr(phase_response, 'tobytes'):
                    phase_response = phase_response.tobytes()
                phase_byte = phase_response[0] if len(phase_response) > 0 else 0
                print(f"    Phase response: 0x{phase_byte:02x} ({'Status' if phase_byte == 0x01 else 'Data IN' if phase_byte == 0x03 else 'Unknown'})")
            except Exception as e:
                print(f"    ⚠️  Phase response read failed: {e}, continuing anyway")
                phase_byte = 0x03  # Assume data phase if we can't read phase

            # Step 4: Read data if phase indicates data in
            data_in = b''
            if phase_byte == 0x03 and data_in_length > 0:
                print(f"    Reading data in: {data_in_length} bytes")
                try:
                    data_in = self._usb_read_bulk(data_in_length)
                    # Convert array.array to bytes if needed
                    if hasattr(data_in, 'tobytes'):
                        data_in = data_in.tobytes()
                    print(f"    Read {len(data_in)} bytes")
                except Exception as e:
                    print(f"    ⚠️  Data read failed: {e}")
                    data_in = b''

            # Step 5: Read status (8 bytes)
            print(f"    Reading status...")
            try:
                status_data = self._usb_read_bulk(8)
                # Convert array.array to bytes if needed
                if hasattr(status_data, 'tobytes'):
                    status_data = status_data.tobytes()
                print(f"    Status data: {status_data.hex()}")

                status, parsed_status = self._parse_status(status_data)
                print(f"    Parsed status: {status}, details: {parsed_status}")

                return data_in, status
            except Exception as e:
                print(f"    ⚠️  Status read failed: {e}")
                return data_in, StatusType.ERROR

        except Exception as e:
            print(f"    Error in USB command: {e}")
            import traceback
            traceback.print_exc()
            return b'', StatusType.ERROR

    def _issue_scsi_command(self, command: bytes, data_out: bytes = b'',
                           data_in_length: int = 0) -> Tuple[bytes, StatusType]:
        """Issue a SCSI command."""
        # TODO: Implement SCSI command handling
        raise NotImplementedError("SCSI command handling not yet implemented")

    def inquiry(self, page: int = -1) -> bytes:
        """
        Send INQUIRY command to get device information.

        Uses the correct 6-byte command format from USB capture.
        """
        if page >= 0:
            # Page-specific inquiry - two-step process
            # First: Get length (4 bytes)
            cmd = self._build_6byte_command(0x12, page=0x01, param2=page, alloc_length=4, control=0x80)
            data, status = self._issue_command(cmd, data_in_length=4)

            if status == StatusType.READY and len(data) >= 4:
                # Extract actual length from response
                # Response format: 06 [page] [length_high] [length_low]
                if len(data) >= 4:
                    length = data[3] + 4  # Length is in byte 3, add 4 for header
                else:
                    length = 4

                # Second: Get full data
                cmd = self._build_6byte_command(0x12, page=0x01, param2=page, alloc_length=length, control=0x80)
                data, status = self._issue_command(cmd, data_in_length=length)
        else:
            # Standard inquiry (36 bytes) - format: 12 00 00 00 24 80
            cmd = self._build_6byte_command(0x12, page=0x00, alloc_length=0x24, control=0x80)
            data, status = self._issue_command(cmd, data_in_length=36)

        if status == StatusType.READY:
            return data
        else:
            raise RuntimeError(f"INQUIRY failed with status {status}")

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

        # Try multiple times with delays (like the SANE backend)
        for attempt in range(3):
            try:
                if attempt > 0:
                    print(f"  Retry attempt {attempt + 1}...")
                    time.sleep(1)  # Wait 1 second between attempts

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

    def mode_sense(self) -> Optional[int]:
        """Get mode sense data to determine MUD (Measurement Unit Divisor)."""
        print("Getting mode sense...")
        cmd = self._parse_command("1a 18 03 00 00 00")
        data, status = self._issue_command(cmd, data_in_length=64)

        if status == StatusType.READY and len(data) >= 8:
            # Extract MUD like SANE backend
            mud = struct.unpack('>H', data[6:8])[0]
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
        cmd = bytearray([
            0x28,  # READ
            0x00,  # LUN
            0xe0,  # Data type (internal info)
            0x00,  # Reserved
            0x00, 0x00,  # Data type qualifier
            0x00, 0x00, 0x01,  # Transfer length (256 bytes, big-endian)
            0x00   # Control byte
        ])

        data, status = self._issue_command(bytes(cmd), data_in_length=256)

        if status == StatusType.READY and len(data) >= 32:
            info = ScannerInfo()

            # Parse internal info like SANE backend
            info.ad_bits = data[0x00]
            info.output_bits = data[0x01]
            info.max_resolution = struct.unpack('>H', data[0x02:0x04])[0]
            info.x_max = struct.unpack('>H', data[0x04:0x06])[0]
            info.y_max = struct.unpack('>H', data[0x06:0x08])[0]
            info.x_max_pixels = struct.unpack('>H', data[0x08:0x0a])[0]
            info.y_max_pixels = struct.unpack('>H', data[0x0a:0x0c])[0]
            info.current_y = struct.unpack('>H', data[0x10:0x12])[0]
            info.current_focus = struct.unpack('>H', data[0x12:0x14])[0]
            info.current_scan_pitch = data[0x14]
            info.auto_feeder = data[0x1e]
            info.analog_gamma = data[0x1f]

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
        cmd = bytearray([
            0x31,  # OBJECT_POSITION
            0x00,  # Auto feeder function
            0x00, 0x00, 0x00,  # Count
            0x00, 0x00, 0x00, 0x00,  # Reserved
            0x00   # Control byte
        ])

        _, status = self._issue_command(bytes(cmd))
        success = status == StatusType.READY
        print(f"Object position: {'SUCCESS' if success else 'FAILED'}")
        return success

    def send_lut(self, lut_data: bytes) -> bool:
        """Send LUT data (like SANE send_LUT)."""
        print("Sending LUT data...")
        # SEND with datatype 0xc0 for LUT
        cmd = bytearray([
            0x2a,  # SEND
            0x00,  # LUN
            0xc0,  # Data type (user reg gamma/LUT)
            0x00, 0x00,  # Data type qualifier
            0x00, 0x00, 0x00,  # Transfer length (will be set)
            0x00   # Control byte
        ])

        # Set transfer length
        cmd[6:9] = struct.pack('>L', len(lut_data))[1:4]  # 3 bytes

        _, status = self._issue_command(bytes(cmd), lut_data)
        success = status == StatusType.READY
        print(f"LUT send: {'SUCCESS' if success else 'FAILED'}")
        return success

    def set_window_wdb(self, wdb: WindowDescriptorBlock) -> bool:
        """Set the scan window parameters using WDB."""
        # Convert WDB to bytes
        wdb_data = wdb.to_bytes()

        # Create SET WINDOW command
        cmd = bytearray([
            0x24,  # SET WINDOW
            0x00,  # LUN
            0x00, 0x00, 0x00, 0x00,  # Reserved
            len(wdb_data), 0x00, 0x00,  # Transfer length (big-endian)
            0x00   # Control byte
        ])

        print(f"Setting window with WDB: {wdb_data.hex()}")
        _, status = self._issue_command(bytes(cmd), wdb_data)
        return status == StatusType.READY

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

    def get_window(self, window_id: int = 0) -> Optional[WindowDescriptorBlock]:
        """Get the current window configuration."""
        # Create GET WINDOW command
        cmd = bytearray([
            0x25,  # GET WINDOW
            0x01,  # LUN, misc
            0x00, 0x00, 0x00,  # Reserved
            window_id,  # Window identifier
            0x75, 0x00, 0x00,  # Transfer length (117 bytes, big-endian)
            0x00   # Control byte
        ])

        data, status = self._issue_command(bytes(cmd), data_in_length=117)
        if status == StatusType.READY and len(data) == 117:
            return WindowDescriptorBlock.from_bytes(data)
        return None

    def start_scan(self, scan_type: ScanType = ScanType.NORMAL) -> bool:
        """Start a scan operation."""
        print("Starting scan...")
        # Send scan command (like SANE coolscan_start_scan)
        cmd = self._parse_command("1b 00 00 00 00 00")
        _, status = self._issue_command(cmd)
        success = status == StatusType.READY
        print(f"Scan start: {'SUCCESS' if success else 'FAILED'}")
        return success

    def read_scan_data(self, length: int, datatype: DataType = DataType.IMAGE_DATA) -> bytes:
        """Read scan data from the scanner with proper datatype."""
        print(f"Reading scan data (datatype: {datatype.name})...")
        # Send READ command with proper datatype
        cmd = bytearray([
            0x28,  # READ
            0x00,  # LUN
            datatype.value,  # Data type
            0x00,  # Reserved
            0x00, 0x00,  # Data type qualifier
            0x00, 0x00, 0x00,  # Transfer length (will be set)
            0x00   # Control byte
        ])

        # Set transfer length (3 bytes, big-endian)
        cmd[6:9] = struct.pack('>L', length)[1:4]

        data, status = self._issue_command(bytes(cmd), data_in_length=length)

        if status == StatusType.READY:
            print(f"Read {len(data)} bytes successfully")
            return data
        else:
            raise RuntimeError(f"Read scan data failed with status {status}")

    def cancel_scan(self) -> bool:
        """Cancel the current scan operation."""
        cmd = self._parse_command("c0 00 00 00 00 00")
        _, status = self._issue_command(cmd)
        return status == StatusType.READY

    def auto_focus(self) -> bool:
        """Perform auto focus operation."""
        print("Performing auto focus...")
        cmd = bytearray([
            0xc2,  # AUTO_FOCUS
            0x00, 0x00, 0x00,  # Reserved
            0x00,  # Transfer length
            0x00   # Control byte
        ])

        _, status = self._issue_command(bytes(cmd))
        success = status == StatusType.READY
        print(f"Auto focus: {'SUCCESS' if success else 'FAILED'}")
        return success

    def prescan(self) -> bool:
        """Perform prescan operation with proper timing."""
        print("Starting prescan...")

        # Set window for prescan
        wdb = WindowDescriptorBlock()
        wdb.scan_mode = 0x01  # Prescan mode
        if not self.set_window_wdb(wdb):
            print("Failed to set prescan window")
            return False

        # Start prescan
        if not self.start_scan():
            print("Failed to start prescan")
            return False

        # Wait 8 seconds like SANE backend
        print("Waiting 8 seconds for prescan...")
        time.sleep(8)

        # Wait for scanner ready
        if not self.scanner_ready(timeout=30):
            print("Scanner not ready after prescan")
            return False

        print("Prescan completed successfully")
        return True

    def initialize_scanner(self) -> bool:
        """Initialize scanner with full SANE sequence."""
        print("Initializing scanner with SANE sequence...")

        try:
            # 1. Wait for scanner ready
            if not self.scanner_ready(timeout=30):
                print("Scanner not ready during initialization")
                return False

            # 2. Reserve unit
            if not self.reserve_unit():
                print("Failed to reserve unit")
                return False

            # 3. Get mode sense for MUD
            if not self.mode_sense():
                print("Failed to get mode sense")
                return False

            # 4. Get internal info
            if not self.get_internal_info():
                print("Failed to get internal info")
                return False

            # 5. Release unit
            if not self.release_unit():
                print("Failed to release unit")
                return False

            print("Scanner initialization completed successfully")
            return True

        except Exception as e:
            print(f"Scanner initialization failed: {e}")
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

            # 5. Send LUT (simple linear LUT)
            lut_data = bytes([i for i in range(256)] * 3)  # R, G, B LUTs
            if not self.send_lut(lut_data):
                print("Failed to send LUT")
                return False

            # 6. Start scan
            if not self.start_scan():
                print("Failed to start scan")
                return False

            # 7. Wait for scanner
            if not self.scanner_ready(timeout=30):
                print("Scanner not ready after scan start")
                return False

            print("Scan sequence completed successfully")
            return True

        except Exception as e:
            print(f"Scan sequence failed: {e}")
            return False
        finally:
            # Always release unit
            self.release_unit()

    def close(self):
        """Close the connection to the scanner."""
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
                    if hasattr(self.usb_device, 'attach_kernel_driver'):
                        self.usb_device.attach_kernel_driver(0)
                except (usb.core.USBError, NotImplementedError, AttributeError):
                    # Not supported on macOS, that's OK
                    pass

                usb.util.dispose_resources(self.usb_device)
            except Exception:
                # Ignore errors during cleanup
                pass
        # TODO: Close SCSI connection if needed
