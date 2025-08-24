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
                phase = self._check_phase()
                print(f"    Phase after command: {phase}")
                
                if phase == PhaseType.OUT and data_out:
                    print(f"    Sending data out: {len(data_out)} bytes")
                    self._usb_write_bulk(data_out)
                    phase = self._check_phase()
                    print(f"    Phase after data out: {phase}")
                
                data_in = b''
                if phase == PhaseType.IN and data_in_length > 0:
                    print(f"    Reading data in: {data_in_length} bytes")
                    data_in = self._usb_read_bulk(data_in_length)
                    # Convert array.array to bytes if needed
                    if hasattr(data_in, 'tobytes'):
                        data_in = data_in.tobytes()
                    print(f"    Read {len(data_in)} bytes")
                    phase = self._check_phase()
                    print(f"    Phase after data in: {phase}")
                
                # Read status (8 bytes)
                print(f"    Reading status...")
                status_data = self._usb_read_bulk(8)
                # Convert array.array to bytes if needed
                if hasattr(status_data, 'tobytes'):
                    status_data = status_data.tobytes()
                print(f"    Status data: {status_data.hex()}")
                
                if len(status_data) == 8:
                    sense_key = status_data[1] & 0x0f
                    sense_asc = status_data[2]
                    sense_ascq = status_data[3]
                    
                    print(f"    Sense key: 0x{sense_key:02x}, ASC: 0x{sense_asc:02x}, ASCQ: 0x{sense_ascq:02x}")
                    
                    # Parse status
                    if sense_key == 0x00:
                        status = StatusType.READY
                    elif sense_key == 0x02:
                        if sense_asc == 0x04:
                            status = StatusType.PROCESSING
                        elif sense_asc == 0x3a:
                            status = StatusType.NO_DOCS
                        else:
                            status = StatusType.ERROR
                    elif sense_key == 0x09:
                        status = StatusType.REISSUE
                    else:
                        status = StatusType.ERROR
                else:
                    status = StatusType.ERROR
                
                return data_in, status
                
            except Exception as e:
                print(f"    Phase check failed: {e}")
                # If phase check fails, try to read status anyway
                try:
                    status_data = self._usb_read_bulk(8)
                    if hasattr(status_data, 'tobytes'):
                        status_data = status_data.tobytes()
                    print(f"    Status data (no phase): {status_data.hex()}")
                    
                    if len(status_data) == 8:
                        sense_key = status_data[1] & 0x0f
                        if sense_key == 0x00:
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
    
    def set_window(self, params: ScanParameters, scan_type: ScanType = ScanType.NORMAL) -> bool:
        """Set the scan window parameters."""
        # This is a simplified implementation
        # The full implementation would need to handle all the parameters
        # and send the appropriate SET WINDOW commands for each color channel
        
        # For now, just return success
        return True
    
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

