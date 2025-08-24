# Implementation Guide

This guide provides step-by-step instructions for implementing the remaining features of the Coolscan tool.

## Current Implementation Status

### ✅ Completed
- Scanner detection (USB and SCSI)
- Basic USB communication
- Command parsing and sending
- Wake-up sequence (reset + execute)
- Device descriptor reading

### 🔄 In Progress
- Full USB protocol implementation
- Status handling and error recovery
- Phase checking and data transfer

### 📋 Next Steps
- SCSI/Firewire protocol
- Image acquisition
- Scanner control features
- Error recovery mechanisms

## Implementation Roadmap

### Phase 1: Complete USB Protocol (1-2 weeks)

#### 1.1 Fix Phase Checking
**Current Issue**: Phase check timeouts after wake-up sequence

**Implementation Steps**:
1. **Analyze coolscan2.c phase handling**:
   ```c
   static cs2_phase_t cs2_phase_check(cs2_t * s)
   {
     static SANE_Byte phase_send_buf[1] = { 0xd0 }, phase_recv_buf[1];
     SANE_Status status = 0;
     size_t n = 1;
   
     status = sanei_usb_write_bulk(s->fd, phase_send_buf, &n);
     status |= sanei_usb_read_bulk(s->fd, phase_recv_buf, &n);
   
     if (status)
       return -1;
     else
       return phase_recv_buf[0];
   }
   ```

2. **Implement proper phase handling**:
   ```python
   def _check_phase(self) -> PhaseType:
       """Check current communication phase."""
       try:
           # Send phase check command
           self._usb_write_bulk(b'\xd0')
           
           # Read phase response
           response = self._usb_read_bulk(1)
           if hasattr(response, 'tobytes'):
               response = response.tobytes()
           
           phase_byte = response[0] if response else 0
           return PhaseType(phase_byte)
           
       except Exception as e:
           print(f"Phase check failed: {e}")
           return PhaseType.NONE
   ```

3. **Add retry logic**:
   ```python
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
   ```

#### 1.2 Implement Status Handling
**Current Issue**: Status reading fails after phase check

**Implementation Steps**:
1. **Add status parsing**:
   ```python
   def _parse_status(self, status_data: bytes) -> Tuple[StatusType, dict]:
       """Parse 8-byte status response."""
       if len(status_data) != 8:
           return StatusType.ERROR, {}
       
       sense_key = status_data[1] & 0x0f
       sense_asc = status_data[2]
       sense_ascq = status_data[3]
       sense_info = status_data[4]
       
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
       elif sense_key == 0x09:
           status = StatusType.REISSUE
       else:
           status = StatusType.ERROR
       
       return status, {
           'sense_key': sense_key,
           'sense_asc': sense_asc,
           'sense_ascq': sense_ascq,
           'sense_info': sense_info
       }
   ```

2. **Add status waiting**:
   ```python
   def _wait_for_status(self, expected_status: StatusType, 
                       timeout: float = 30.0) -> bool:
       """Wait for scanner to reach expected status."""
       start_time = time.time()
       
       while time.time() - start_time < timeout:
           try:
               status = self._get_status()
               if status == expected_status:
                   return True
               time.sleep(0.1)
           except Exception as e:
               print(f"Status check failed: {e}")
               time.sleep(0.5)
       
       return False
   ```

#### 1.3 Implement Scanner Ready Function
**Implementation Steps**:
1. **Add scanner ready check**:
   ```python
   def _scanner_ready(self, flags: int = 0) -> bool:
       """Check if scanner is ready for commands."""
       try:
           # Send TEST UNIT READY
           cmd = self._parse_command("00 00 00 00 00 00")
           self._usb_write_bulk(cmd)
           
           # Read status
           status_data = self._usb_read_bulk(8)
           if hasattr(status_data, 'tobytes'):
               status_data = status_data.tobytes()
           
           status, sense_data = self._parse_status(status_data)
           
           # Check if status matches expected flags
           if flags == 0:
               return status == StatusType.READY
           else:
               return (status.value & flags) == 0
               
       except Exception as e:
           print(f"Scanner ready check failed: {e}")
           return False
   ```

2. **Add retry logic**:
   ```python
   def _scanner_ready_with_retry(self, flags: int = 0, 
                                max_retries: int = 3) -> bool:
       """Check scanner ready with retry logic."""
       for attempt in range(max_retries):
           if self._scanner_ready(flags):
               return True
           
           if attempt < max_retries - 1:
               time.sleep(0.5 * (attempt + 1))
       
       return False
   ```

### Phase 2: Implement Scanner Operations (2-3 weeks)

#### 2.1 Add Scanner Information
**Implementation Steps**:
1. **Implement INQUIRY command**:
   ```python
   def get_scanner_info(self) -> dict:
       """Get scanner information via INQUIRY command."""
       try:
           # Send INQUIRY command
           cmd = self._parse_command("12 00 00 00 24 00")
           self._usb_write_bulk(cmd)
           
           # Read response
           response = self._usb_read_bulk(36)
           if hasattr(response, 'tobytes'):
               response = response.tobytes()
           
           # Parse response
           vendor = response[8:16].decode('ascii', errors='ignore').strip()
           product = response[16:32].decode('ascii', errors='ignore').strip()
           revision = response[32:36].decode('ascii', errors='ignore').strip()
           
           return {
               'vendor': vendor,
               'product': product,
               'revision': revision,
               'raw_response': response.hex()
           }
           
       except Exception as e:
           print(f"Failed to get scanner info: {e}")
           return {}
   ```

2. **Add scanner capabilities**:
   ```python
   def get_scanner_capabilities(self) -> dict:
       """Get scanner capabilities."""
       try:
           # Get page 0xc1 (capabilities)
           cmd = self._parse_command("12 01 c1 00 04 00")
           self._usb_write_bulk(cmd)
           
           response = self._usb_read_bulk(4)
           if hasattr(response, 'tobytes'):
               response = response.tobytes()
           
           # Get full capabilities page
           length = response[3] + 4
           cmd = self._parse_command(f"12 01 c1 00 {length:02x} 00")
           self._usb_write_bulk(cmd)
           
           response = self._usb_read_bulk(length)
           if hasattr(response, 'tobytes'):
               response = response.tobytes()
           
           # Parse capabilities
           return self._parse_capabilities(response)
           
       except Exception as e:
           print(f"Failed to get capabilities: {e}")
           return {}
   ```

#### 2.2 Add Scanner Control
**Implementation Steps**:
1. **Implement load/eject**:
   ```python
   def load_medium(self) -> bool:
       """Load next slide/film."""
       try:
           # Send load command
           cmd = self._parse_command("e0 00 d1 00 00 00 00 00 0d 00")
           self._usb_write_bulk(cmd)
           
           # Send load data
           load_data = b'\x00' * 13  # Default load parameters
           self._usb_write_bulk(load_data)
           
           # Execute command
           return self._execute_command()
           
       except Exception as e:
           print(f"Load medium failed: {e}")
           return False
   
   def eject_medium(self) -> bool:
       """Eject loaded medium."""
       try:
           # Send eject command
           cmd = self._parse_command("e0 00 d0 00 00 00 00 00 0d 00")
           self._usb_write_bulk(cmd)
           
           # Send eject data
           eject_data = b'\x00' * 13  # Default eject parameters
           self._usb_write_bulk(eject_data)
           
           # Execute command
           return self._execute_command()
           
       except Exception as e:
           print(f"Eject medium failed: {e}")
           return False
   ```

2. **Implement focus control**:
   ```python
   def set_focus(self, focus_value: int) -> bool:
       """Set manual focus position."""
       try:
           # Send focus command
           cmd = self._parse_command("e0 00 c1 00 00 00 00 00 0d 00")
           self._usb_write_bulk(cmd)
           
           # Send focus value (4 bytes, big-endian)
           focus_data = focus_value.to_bytes(4, 'big')
           self._usb_write_bulk(focus_data)
           
           # Execute command
           return self._execute_command()
           
       except Exception as e:
           print(f"Set focus failed: {e}")
           return False
   
   def auto_focus(self, x: int, y: int) -> bool:
       """Perform auto focus at specified coordinates."""
       try:
           # Send auto focus command
           cmd = self._parse_command("e0 00 a0 00 00 00 00 00 0d 00")
           self._usb_write_bulk(cmd)
           
           # Send coordinates (8 bytes, big-endian)
           coord_data = x.to_bytes(4, 'big') + y.to_bytes(4, 'big')
           self._usb_write_bulk(coord_data)
           
           # Execute command
           return self._execute_command()
           
       except Exception as e:
           print(f"Auto focus failed: {e}")
           return False
   ```

### Phase 3: Implement Scanning (3-4 weeks)

#### 3.1 Basic Scanning
**Implementation Steps**:
1. **Implement scan setup**:
   ```python
   def setup_scan(self, resolution: int, x_offset: int, y_offset: int,
                  width: int, height: int) -> bool:
       """Setup scan parameters."""
       try:
           # Set device unit
           self._set_device_unit(resolution)
           
           # Set boundary
           self._set_boundary(x_offset, y_offset, width, height)
           
           # Download LUTs
           self._download_luts()
           
           # Set color sequence
           self._set_color_sequence()
           
           return True
           
       except Exception as e:
           print(f"Scan setup failed: {e}")
           return False
   ```

2. **Implement scan execution**:
   ```python
   def perform_scan(self, scan_type: ScanType = ScanType.NORMAL) -> bool:
       """Perform scan operation."""
       try:
           # Prepare scan parameters
           params = self._prepare_scan_params(scan_type)
           
           # Send scan command
           cmd = self._parse_command("24 00 00 00 00 00 00 00 3a 00")
           self._usb_write_bulk(cmd)
           
           # Send scan parameters
           self._usb_write_bulk(params)
           
           # Wait for scan completion
           return self._wait_for_scan_completion()
           
       except Exception as e:
           print(f"Scan failed: {e}")
           return False
   ```

#### 3.2 Data Transfer
**Implementation Steps**:
1. **Implement data reading**:
   ```python
   def read_scan_data(self, length: int) -> bytes:
       """Read scanned image data."""
       try:
           # Send read command
           cmd = self._parse_command(f"28 00 00 00 {length:06x} 00 00 00 00 00")
           self._usb_write_bulk(cmd)
           
           # Read data
           data = self._usb_read_bulk(length)
           if hasattr(data, 'tobytes'):
               data = data.tobytes()
           
           return data
           
       except Exception as e:
           print(f"Read scan data failed: {e}")
           return b''
   ```

2. **Implement image processing**:
   ```python
   def process_scan_data(self, data: bytes, width: int, height: int,
                        channels: int, bit_depth: int) -> bytes:
       """Process raw scan data into image format."""
       try:
           # Convert raw data to image format
           # This depends on the specific scanner and data format
           
           # For now, return raw data
           return data
           
       except Exception as e:
           print(f"Process scan data failed: {e}")
           return b''
   ```

### Phase 4: SCSI/Firewire Support (2-3 weeks)

#### 4.1 SCSI Interface
**Implementation Steps**:
1. **Add SCSI device detection**:
   ```python
   def find_scsi_scanners(self) -> List[Scanner]:
       """Find SCSI/Firewire scanners."""
       scanners = []
       
       # Check for SCSI devices
       scsi_paths = [
           '/dev/sg*',
           '/dev/scsi*',
           '/dev/disk*'
       ]
       
       for pattern in scsi_paths:
           devices = glob.glob(pattern)
           for device in devices:
               if self._is_coolscan_scsi(device):
                   scanners.append(Scanner(
                       name=device,
                       interface='scsi',
                       model=self._get_scsi_model(device)
                   ))
       
       return scanners
   ```

2. **Implement SCSI communication**:
   ```python
   class SCSICoolscanProtocol:
       """SCSI protocol implementation for Coolscan scanners."""
       
       def __init__(self, device_path: str):
           self.device_path = device_path
           self.fd = None
       
       def open(self) -> bool:
           """Open SCSI device."""
           try:
               self.fd = os.open(self.device_path, os.O_RDWR)
               return True
           except Exception as e:
               print(f"Failed to open SCSI device: {e}")
               return False
       
       def close(self):
           """Close SCSI device."""
           if self.fd:
               os.close(self.fd)
               self.fd = None
       
       def send_command(self, command: bytes, data_out: bytes = b'',
                       data_in_length: int = 0) -> Tuple[bytes, int]:
           """Send SCSI command."""
           # Implement SCSI command sending
           # This requires SCSI interface implementation
           pass
   ```

## Testing Strategy

### Unit Tests
1. **Command parsing tests**:
   ```python
   def test_command_parsing():
       """Test command parsing functionality."""
       protocol = CoolscanProtocol(None)
       
       # Test basic command
       cmd = protocol._parse_command("00 00 00 00 00 00")
       assert cmd == b'\x00\x00\x00\x00\x00\x00'
       
       # Test complex command
       cmd = protocol._parse_command("e0 00 80 00 00 00 00 00 0d 00")
       assert cmd == b'\xe0\x00\x80\x00\x00\x00\x00\x00\x0d\x00'
   ```

2. **Status parsing tests**:
   ```python
   def test_status_parsing():
       """Test status parsing functionality."""
       protocol = CoolscanProtocol(None)
       
       # Test ready status
       status_data = b'\x00\x00\x00\x00\x00\x00\x00\x00'
       status, sense = protocol._parse_status(status_data)
       assert status == StatusType.READY
       
       # Test error status
       status_data = b'\x00\x02\x04\x00\x00\x00\x00\x00'
       status, sense = protocol._parse_status(status_data)
       assert status == StatusType.PROCESSING
   ```

### Integration Tests
1. **Scanner detection tests**:
   ```python
   def test_scanner_detection():
       """Test scanner detection."""
       scanners = find_scanners()
       assert len(scanners) > 0
       
       scanner = scanners[0]
       assert scanner.interface in ['usb', 'scsi']
       assert scanner.model is not None
   ```

2. **Communication tests**:
   ```python
   def test_basic_communication():
       """Test basic scanner communication."""
       scanners = find_scanners()
       if not scanners:
           pytest.skip("No scanner available")
       
       scanner = scanners[0]
       protocol = CoolscanProtocol(scanner)
       
       # Test wake-up
       assert protocol.wake_up()
       
       # Test scanner info
       info = protocol.get_scanner_info()
       assert 'vendor' in info
       assert 'product' in info
   ```

### Manual Tests
1. **Hardware tests**:
   - Test with different scanner models
   - Test with different USB cables
   - Test with different USB ports
   - Test with different operating systems

2. **Stress tests**:
   - Continuous scanning
   - Error recovery
   - Memory usage
   - Performance benchmarks

## Error Handling

### Implementation Strategy
1. **Graceful degradation**:
   ```python
   def safe_operation(self, operation: Callable, *args, **kwargs):
       """Execute operation with error handling."""
       try:
           return operation(*args, **kwargs)
       except Exception as e:
           print(f"Operation failed: {e}")
           return None
   ```

2. **Retry logic**:
   ```python
   def retry_operation(self, operation: Callable, max_retries: int = 3,
                      delay: float = 1.0, *args, **kwargs):
       """Execute operation with retry logic."""
       for attempt in range(max_retries):
           try:
               return operation(*args, **kwargs)
           except Exception as e:
               if attempt == max_retries - 1:
                   raise e
               print(f"Attempt {attempt + 1} failed: {e}")
               time.sleep(delay * (attempt + 1))
   ```

3. **Recovery procedures**:
   ```python
   def recover_from_error(self, error: Exception) -> bool:
       """Attempt to recover from error."""
       try:
           # Reset scanner
           self.wake_up()
           
           # Wait for ready state
           if self._wait_for_status(StatusType.READY):
               return True
           
           return False
       except Exception as e:
           print(f"Recovery failed: {e}")
           return False
   ```

## Performance Optimization

### Implementation Strategy
1. **Buffer management**:
   ```python
   class BufferManager:
       """Manage USB buffers efficiently."""
       
       def __init__(self, initial_size: int = 1024):
           self.buffer = bytearray(initial_size)
           self.size = initial_size
       
       def ensure_capacity(self, required_size: int):
           """Ensure buffer has required capacity."""
           if required_size > self.size:
               new_size = max(required_size, self.size * 2)
               self.buffer = bytearray(new_size)
               self.size = new_size
   ```

2. **Command batching**:
   ```python
   def batch_commands(self, commands: List[bytes]) -> bool:
       """Execute multiple commands in batch."""
       try:
           for cmd in commands:
               self._usb_write_bulk(cmd)
               time.sleep(0.01)  # Small delay between commands
           
           return True
       except Exception as e:
           print(f"Batch commands failed: {e}")
           return False
   ```

3. **Async operations**:
   ```python
   async def async_scan(self, parameters: dict) -> bytes:
       """Perform scan asynchronously."""
       # Implement async scanning
       # This requires async USB library
       pass
   ```

## Documentation

### Implementation Notes
- Document all public APIs
- Include usage examples
- Document error conditions
- Provide troubleshooting tips

### Code Comments
- Comment complex algorithms
- Document protocol details
- Explain error handling
- Note hardware-specific details

## Next Steps

### Immediate (Next Week)
1. Fix phase checking implementation
2. Implement proper status handling
3. Add scanner ready function
4. Create comprehensive tests

### Short Term (2-4 weeks)
1. Complete USB protocol implementation
2. Add scanner control features
3. Implement basic scanning
4. Add error recovery

### Medium Term (1-3 months)
1. Add SCSI/Firewire support
2. Implement image processing
3. Add advanced features
4. Performance optimization

### Long Term (3-6 months)
1. GUI interface
2. Batch processing
3. Advanced image processing
4. Multi-scanner support

## Resources

### Reference Materials
- [SANE Project Documentation](http://www.sane-project.org/docs.html)
- [USB Mass Storage Specification](https://www.usb.org/document-library/mass-storage-device-class-specification)
- [SCSI-3 Specification](https://www.t10.org/drafts.htm)
- [Nikon Technical Support](https://www.nikon.com/support/)

### Code References
- `coolscan2.c`: USB protocol implementation
- `coolscan3.c`: SCSI protocol implementation
- SANE backend code: Additional protocol details

### Tools
- USB debugging tools
- SCSI debugging tools
- Protocol analyzers
- Performance profilers
