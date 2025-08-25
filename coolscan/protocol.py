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


class CoolscanProtocol:
    """Implements the Coolscan communication protocol."""
    
    def __init__(self, device):
        self.device = device
        self.interface = device.interface
        self.usb_device = None
        self.scsi_fd = None
        
        if self.interface.value == "usb":
            self._init_usb()
        else:
            self._init_scsi()
    
    def _init_usb(self):
        """Initialize USB connection."""
        if not USB_AVAILABLE:
            raise RuntimeError("USB support not available")
        
        vendor_id = self.device.vendor_id
        product_id = self.device.product_id
        
        self.usb_device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if self.usb_device is None:
            raise RuntimeError(f"USB device {vendor_id:04x}:{product_id:04x} not found")
        
        # Set configuration
        self.usb_device.set_configuration()
        
        # Set timeouts (in milliseconds)
        self.usb_device.default_timeout = 5000  # 5 seconds default
        
        # Find endpoints
        cfg = self.usb_device.get_active_configuration()
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
        
        if not self.bulk_out or not self.bulk_in:
            raise RuntimeError("Could not find USB bulk endpoints")
    
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
    
    def _usb_write_bulk(self, data: bytes) -> int:
        """Write data to USB bulk endpoint."""
        return self.usb_device.write(self.bulk_out.bEndpointAddress, data)
    
    def _usb_read_bulk(self, length: int) -> bytes:
        """Read data from USB bulk endpoint."""
        return self.usb_device.read(self.bulk_in.bEndpointAddress, length)
    
    def _check_phase_with_retry(self, max_retries: int = 3) -> PhaseType:
        """Check phase with retry logic."""
        for attempt in range(max_retries):
            try:
                phase = self._check_phase()
                if phase != PhaseType.NONE:
                    return phase
                time.sleep(0.1 * (attempt + 1))
            except Exception as e:
                print(f"Phase check attempt {attempt + 1} failed: {e}")
        
        return PhaseType.NONE

    def _parse_status(self, status_data: bytes) -> Tuple[StatusType, dict]:
        """Parse 8-byte status response."""
        if len(status_data) != 8:
            return StatusType.ERROR, {}
        
        sense_key = status_data[1] & 0x0f
        sense_asc = status_data[2]
        sense_ascq = status_data[3]
        
        # Parse status based on sense key
        if sense_key == 0x00:
            status = StatusType.READY
        elif sense_key == 0x02:
            if sense_asc == 0x04:
                status = StatusType.PROCESSING
            elif sense_asc == 0x3a:
                status = StatusType.NO_DOCS
            else:
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
        self._usb_write_bulk(phase_cmd)
        
        # Read phase response
        response = self._usb_read_bulk(1)
        # Convert array.array to bytes if needed
        if hasattr(response, 'tobytes'):
            response = response.tobytes()
        if len(response) == 1:
            return PhaseType(response[0])
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
        """Issue a USB command."""
        print(f"  Issuing USB command: {command.hex()}")
        
        try:
            # Send command
            self._usb_write_bulk(command)
            print(f"    Command sent successfully")
            
            # Check phase and handle data transfer
            try:
                phase = self._check_phase_with_retry()
                print(f"    Phase after command: {phase}")
                
                if phase == PhaseType.OUT and data_out:
                    print(f"    Sending data out: {len(data_out)} bytes")
                    self._usb_write_bulk(data_out)
                    phase = self._check_phase_with_retry()
                    print(f"    Phase after data out: {phase}")
                
                data_in = b''
                if phase == PhaseType.IN and data_in_length > 0:
                    print(f"    Reading data in: {data_in_length} bytes")
                    data_in = self._usb_read_bulk(data_in_length)
                    # Convert array.array to bytes if needed
                    if hasattr(data_in, 'tobytes'):
                        data_in = data_in.tobytes()
                    print(f"    Read {len(data_in)} bytes")
                    phase = self._check_phase_with_retry()
                    print(f"    Phase after data in: {phase}")
                
                # Read status (8 bytes)
                print(f"    Reading status...")
                status_data = self._usb_read_bulk(8)
                # Convert array.array to bytes if needed
                if hasattr(status_data, 'tobytes'):
                    status_data = status_data.tobytes()
                print(f"    Status data: {status_data.hex()}")
                
                status, parsed_status = self._parse_status(status_data)
                print(f"    Parsed status: {status}, details: {parsed_status}")
                
                return data_in, status
                
            except Exception as e:
                print(f"    Phase check failed: {e}")
                # If phase check fails, try to read status anyway
                try:
                    status_data = self._usb_read_bulk(8)
                    if hasattr(status_data, 'tobytes'):
                        status_data = status_data.tobytes()
                    print(f"    Status data (no phase): {status_data.hex()}")
                    
                    status, parsed_status = self._parse_status(status_data)
                    print(f"    Parsed status (no phase): {status}, details: {parsed_status}")
                    
                    if status == StatusType.READY:
                        return data_in, StatusType.READY
                    
                    return data_in, StatusType.ERROR
                except:
                    return data_in, StatusType.ERROR
            
        except Exception as e:
            print(f"    Error in USB command: {e}")
            return b'', StatusType.ERROR
    
    def _issue_scsi_command(self, command: bytes, data_out: bytes = b'',
                           data_in_length: int = 0) -> Tuple[bytes, StatusType]:
        """Issue a SCSI command."""
        # TODO: Implement SCSI command handling
        raise NotImplementedError("SCSI command handling not yet implemented")
    
    def inquiry(self, page: int = -1) -> bytes:
        """Send INQUIRY command to get device information."""
        if page >= 0:
            # Page-specific inquiry
            cmd = self._parse_command("12 01") + self._pack_byte(page) + self._parse_command("00 04 00")
            data, status = self._issue_command(cmd, data_in_length=4)
            
            if status == StatusType.READY and len(data) == 4:
                length = data[3] + 4
                cmd = self._parse_command("12 01") + self._pack_byte(page) + self._parse_command("00") + self._pack_byte(length) + self._parse_command("00")
                data, status = self._issue_command(cmd, data_in_length=length)
        else:
            # Standard inquiry
            cmd = self._parse_command("12 00 00 00") + self._pack_byte(36) + self._parse_command("00")
            data, status = self._issue_command(cmd, data_in_length=36)
        
        if status == StatusType.READY:
            return data
        else:
            raise RuntimeError(f"INQUIRY failed with status {status}")
    
    def scanner_ready(self, timeout: int = 30) -> bool:
        """Check if scanner is ready with retry logic."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                if self.test_unit_ready():
                    return True
                time.sleep(1)
            except Exception as e:
                print(f"Scanner ready check failed: {e}")
                time.sleep(1)
        
        return False

    def test_unit_ready(self) -> bool:
        """Test if the scanner is ready."""
        print("Testing unit ready...")
        
        # Try multiple times with delays (like the SANE backend)
        for attempt in range(3):
            try:
                if attempt > 0:
                    print(f"  Retry attempt {attempt + 1}...")
                    time.sleep(1)  # Wait 1 second between attempts
                
                cmd = self._parse_command("00 00 00 00 00 00")
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
        """Reserve the scanner unit."""
        cmd = self._parse_command("16 00 00 00 00 00")
        _, status = self._issue_command(cmd)
        return status == StatusType.READY
    
    def release_unit(self) -> bool:
        """Release the scanner unit."""
        cmd = self._parse_command("17 00 00 00 00 00")
        _, status = self._issue_command(cmd)
        return status == StatusType.READY
    
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
        # Send scan command
        if scan_type == ScanType.NORMAL:
            cmd = self._parse_command("1b 00 00 00 03 00 01 02 03")
        else:
            # Handle other scan types
            cmd = self._parse_command("1b 00 00 00 03 00 01 02 03")
        
        _, status = self._issue_command(cmd)
        return status == StatusType.READY
    
    def read_scan_data(self, length: int) -> bytes:
        """Read scan data from the scanner."""
        # Send READ command
        cmd = self._parse_command("28 00 00 00 00 00") + self._pack_long(length) + self._parse_command("00")
        data, status = self._issue_command(cmd, data_in_length=length)
        
        if status == StatusType.READY:
            return data
        else:
            raise RuntimeError(f"Read scan data failed with status {status}")
    
    def cancel_scan(self) -> bool:
        """Cancel the current scan operation."""
        cmd = self._parse_command("c0 00 00 00 00 00")
        _, status = self._issue_command(cmd)
        return status == StatusType.READY
    
    def close(self):
        """Close the connection to the scanner."""
        if self.usb_device:
            usb.util.dispose_resources(self.usb_device)
        # TODO: Close SCSI connection if needed

