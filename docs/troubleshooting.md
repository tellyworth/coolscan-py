# Troubleshooting Guide

This guide helps you diagnose and resolve common issues with the Coolscan tool.

## Quick Diagnosis

### 1. Scanner Detection Issues
**Symptoms**: No scanners found, "No scanners found!" message

**Check these first**:
- [ ] Scanner is powered on
- [ ] USB cable is connected
- [ ] Scanner appears in System Information
- [ ] USB permissions are granted

**Diagnostic commands**:
```bash
# Check USB devices
system_profiler SPUSBDataType | grep -A 10 -B 5 "Nikon\|Coolscan"

# Check for USB permissions
ls -la /dev/usb*

# Run detection test
python3.11 test_detection.py
```

### 2. Communication Timeouts (RESOLVED)
**Symptoms**: "Operation timed out", "Connection failed", "Other error", "I/O error"

**Root Cause (SOLVED)**:
The scanner uses a **non-standard 6-byte command format** (not standard SCSI), and requires a specific **phase checking pattern** after every command. See `docs/usb-capture-findings.md` for details.

**Solution Implemented**:
1. **6-byte command format**: Commands are 6 bytes with allocation length in byte 4 and control byte in byte 5
2. **Phase checking pattern**: Send command → send 0xd0 phase check → read phase response → read data/status
3. **Proper endpoint discovery**: Use `get_configuration_descriptor()` to get real endpoint addresses
4. **Configuration handling**: Properly set configuration and claim interface

**If you still experience timeouts**:
1. **Wake up scanner**:
   ```python
   protocol = CoolscanProtocol(scanner)
   protocol.wait_scanner()  # Uses proper command format
   ```

2. **Reset USB connection**:
   - Unplug and replug USB cable
   - Try different USB port
   - Restart scanner

3. **Check for driver conflicts**:
   ```bash
   # Check for conflicting drivers
   kextstat | grep -i usb
   ```

### 3. Permission Errors
**Symptoms**: "Permission denied", "Access denied"

**Solutions**:
1. **Grant USB permissions** (macOS):
   - System Preferences > Security & Privacy > Privacy
   - Select "USB" from left panel
   - Add Terminal/IDE to allowed applications

2. **Run with sudo** (temporary fix):
   ```bash
   sudo python3.11 your_script.py
   ```

3. **Check device permissions**:
   ```bash
   ls -la /dev/usb*
   sudo chmod 666 /dev/usb*  # Temporary fix
   ```

## Detailed Troubleshooting

### Scanner Detection Problems

#### Problem: Scanner not detected by tool
**Diagnostic steps**:
1. **Check hardware connection**:
   ```bash
   # Verify scanner appears in system
   system_profiler SPUSBDataType | grep -A 15 "Nikon"
   ```

2. **Check USB enumeration**:
   ```bash
   # List USB devices
   ioreg -p IOUSB -l -w 0
   ```

3. **Test with different tools**:
   ```bash
   # Use system_profiler
   system_profiler SPUSBDataType

   # Use lsusb (if available)
   lsusb | grep Nikon
   ```

**Solutions**:
- Try different USB cable
- Test on different computer
- Check scanner power supply
- Reset scanner to factory defaults

#### Problem: Scanner detected but connection fails
**Diagnostic steps**:
1. **Check USB permissions**:
   ```bash
   # Check device permissions
   ls -la /dev/usb*

   # Check if user is in correct groups
   groups $USER
   ```

2. **Test basic USB communication**:
   ```python
   from coolscan.device import find_scanners
   scanners = find_scanners()
   print(f"Found {len(scanners)} scanners")
   ```

**Solutions**:
- Grant USB permissions to Terminal/IDE
- Run with elevated privileges
- Check for conflicting drivers

### Communication Problems

#### Problem: Wake-up sequence fails
**Symptoms**: Reset/execute commands timeout

**Diagnostic steps**:
1. **Test basic communication**:
   ```python
   # Test simple command
   protocol = CoolscanProtocol(scanner)
   protocol._usb_write_bulk(b'\x00\x00\x00\x00\x00\x00')
   ```

2. **Check scanner state**:
   - Is scanner powered on?
   - Is scanner in sleep mode?
   - Are there any error lights?

**Solutions**:
- Power cycle scanner
- Try different wake-up sequence
- Check USB cable quality
- Test on different USB port

#### Problem: Phase check timeouts
**Symptoms**: "Phase check failed", communication stalls

**Diagnostic steps**:
1. **Test phase check manually**:
   ```python
   # Send phase check command
   protocol._usb_write_bulk(b'\xd0')
   response = protocol._usb_read_bulk(1)
   print(f"Phase: {response.hex()}")
   ```

2. **Check USB timing**:
   - Add delays between commands
   - Increase timeout values
   - Check USB bus speed

**Solutions**:
- Add delays between commands
- Implement retry logic
- Check USB driver settings
- Use different USB controller

#### Problem: Status reading fails
**Symptoms**: Can't read status, communication errors

**Diagnostic steps**:
1. **Test status reading**:
   ```python
   # Try to read status
   try:
       status = protocol._usb_read_bulk(8)
       print(f"Status: {status.hex()}")
   except Exception as e:
       print(f"Status read failed: {e}")
   ```

2. **Check USB buffer sizes**:
   - Verify buffer allocation
   - Check for memory issues
   - Test with smaller buffers

**Solutions**:
- Implement proper error handling
- Add timeout handling
- Check USB driver configuration
- Test with different buffer sizes

### Scanner-Specific Issues

#### LS-40 ED Issues
**Common problems**:
- Infrared channel not working
- Focus problems
- Resolution limitations

**Solutions**:
- Check infrared sensor
- Calibrate focus
- Use supported resolutions

#### LS-50/LS-5000 Issues
**Common problems**:
- Block padding errors
- Multi-sampling issues
- Advanced features not working

**Solutions**:
- Implement proper block padding
- Check multi-sampling support
- Verify advanced features

#### Firewire Scanner Issues
**Common problems**:
- SCSI driver not loaded
- Firewire connection problems
- Device not recognized

**Solutions**:
- Load SCSI drivers
- Check Firewire cable
- Verify SBP2 support

## Debug Mode

Enable debug output for detailed diagnostics:

```bash
# Set debug environment variable
export COOLSCAN_DEBUG=1

# Run your script
python3.11 your_script.py
```

**Debug output includes**:
- USB communication details
- Command/response data
- Timing information
- Error details

## Common Error Messages

### "No scanners found!"
**Causes**:
- Scanner not connected
- Scanner not powered on
- USB permissions denied
- Driver not loaded

**Solutions**:
1. Check hardware connection
2. Grant USB permissions
3. Load required drivers
4. Test with system tools

### "Operation timed out"
**Causes**:
- Scanner in sleep mode
- USB connection issues
- Driver problems
- Hardware faults

**Solutions**:
1. Wake up scanner
2. Check USB cable
3. Try different USB port
4. Reset scanner

### "Permission denied"
**Causes**:
- USB permissions not granted
- User not in correct groups
- Device permissions incorrect

**Solutions**:
1. Grant USB permissions
2. Add user to correct groups
3. Fix device permissions
4. Run with elevated privileges

### "Connection failed"
**Causes**:
- Scanner not responding
- USB driver issues
- Hardware problems
- Protocol errors

**Solutions**:
1. Check scanner state
2. Update USB drivers
3. Test hardware
4. Verify protocol implementation

## Performance Issues

### Slow Communication
**Causes**:
- USB 1.1 instead of USB 2.0
- Driver overhead
- Protocol inefficiencies
- System load

**Solutions**:
1. Use USB 2.0 port
2. Optimize driver settings
3. Improve protocol efficiency
4. Reduce system load

### Memory Issues
**Causes**:
- Large buffer allocations
- Memory leaks
- Insufficient system memory

**Solutions**:
1. Use smaller buffers
2. Implement proper cleanup
3. Add memory management
4. Monitor memory usage

## Getting Help

### Before Asking for Help
1. **Collect diagnostic information**:
   ```bash
   # System information
   system_profiler SPUSBDataType
   system_profiler SPHardwareDataType

   # USB device list
   ioreg -p IOUSB -l -w 0

   # Tool output with debug
   export COOLSCAN_DEBUG=1
   python3.11 your_script.py
   ```

2. **Document the problem**:
   - What you're trying to do
   - What happens instead
   - Error messages
   - System configuration

3. **Test with minimal example**:
   ```python
   from coolscan.device import find_scanners
   scanners = find_scanners()
   print(f"Scanners: {scanners}")
   ```

### Where to Get Help
1. **Check documentation**: `docs/` directory
2. **Review protocol spec**: `docs/protocol.md`
3. **Check command reference**: `docs/commands.md`
4. **Open issue**: Project repository
5. **Community forums**: SANE project forums

## Prevention

### Best Practices
1. **Always check scanner state** before operations
2. **Implement proper error handling** in your code
3. **Use appropriate timeouts** for operations
4. **Test with different scanners** when possible
5. **Keep USB drivers updated**
6. **Use quality USB cables**
7. **Monitor system resources**

### Regular Maintenance
1. **Clean scanner optics** regularly
2. **Update firmware** when available
3. **Check USB connections** periodically
4. **Monitor system logs** for USB errors
5. **Test scanner functionality** regularly

## References

- [SANE Project](http://www.sane-project.org/)
- [USB Mass Storage Specification](https://www.usb.org/document-library/mass-storage-device-class-specification)
- [SCSI-3 Specification](https://www.t10.org/drafts.htm)
- [Nikon Technical Support](https://www.nikon.com/support/)
