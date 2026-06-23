# Scan Teardown, Focus, and Exposure Fixes

## Overview

Based on analysis of `test_hardware_scan_capture.txt` vs `golden_single_bw.txt` (derived from `ls40-single-bw.pcapng`) and SANE backend source (`backends-1.4.0/backend/coolscan3.c`), the following issues were identified:

1. **Scanner not released/reset** - Test capture ends abruptly after last image read; golden fixture has full teardown
2. **Exposure not set correctly** - Hardcoded WDB values; prescan exposure calibration not used; missing GET_WINDOW after SET_WINDOW
3. **Focus not set** - Missing focus read/set/execute sequence before prescan; autofocus uses wrong command (0xc2 vs 0xe0/a0)

---

## Frame Boundary Documentation

### What the frame boundary commands do

The LS-40 ED uses two different boundary commands depending on scan phase:

| Phase | Command | Data type | Purpose |
|-------|---------|-----------|---------|
| Prescan | `2a 00 92 00 00 03 00 00 04 00` | 0x92 (BORDER_POSITION) | Sets minimal frame boundary for low-res prescan |
| Full scan | `2a 00 8f 00 00 03 00 00 34 00` | 0x8f (CONTROL_FRAME) | Sets detailed frame positions for full-res scan |

**Important:** SANE's `cs3_set_boundary()` uses data type 0x88 (IMAGE_POSITIONS), but the LS-40 ED rejects 0x88 with ILLEGAL REQUEST (ASC=0x26). The golden fixture shows the correct types for this device.

### How frame boundaries are determined

Frame boundaries are NOT detected by analyzing prescan image data. They are computed from:
- Scanner physical dimensions (from INQUIRY pages 0xc1, 0xd1)
- Requested scan area (resolution, x/y offset, width/length)
- Frame offset formula: `frame_offset = resy_max * 1.5 + 1` (SANE coolscan3.c:2494)

The prescan image data is used for:
- **Exposure calibration** - Scanner computes optimal exposure times from prescan data
- **Focus quality** - Auto-focus may use prescan region to determine sharpness
- NOT for frame boundary detection

### Boundary payload structure

The 0x92 (BORDER_POSITION) payload is 4 bytes: `04 00 00 00` (frame count = 1, or boundary marker).

The 0x8f (CONTROL_FRAME) payload is 52 bytes containing per-frame Y-axis positions. The current hardcoded values work for standard 35mm film. For different film formats, these would need adjustment.

---

## Code Changes

### File: `coolscan/protocol.py`

#### Change 1: Replace `auto_focus()` and add new methods

**Location:** After `cancel_scan()` method (line ~2224), replace existing `auto_focus()` with:

```python
def _execute_command(self) -> bool:
    """Send EXECUTE command (0xc1).

    Golden fixture: c1 00 00 00 00 00 (6-byte CDB).
    SANE coolscan3.c:2539 cs3_execute().
    Called after e0 commands to commit parameter changes.
    """
    if self.verbose:
        print("  Sending EXECUTE (0xc1)...")
    cmd = bytes([0xC1, 0x00, 0x00, 0x00, 0x00, 0x00])
    _, status = self._issue_command(cmd)
    ok = status == StatusType.READY
    if self.verbose:
        print(f"    EXECUTE: {'OK' if ok else 'FAILED'}")
    return ok

def read_focus(self) -> Optional[int]:
    """Read current focus position from scanner.

    Golden fixture line 172: e1 00 c1 00 00 00 00 00 0d 00
    SANE coolscan3.c:2669 cs3_read_focus().
    Returns 13 bytes; focus value is 32-bit BE at bytes 1-4.

    Returns:
        Focus position value, or None on failure.
    """
    if self.verbose:
        print("  Reading focus position...")
    cmd = bytes([0xE1, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0D, 0x00])
    data, status = self._issue_command(cmd, data_in_length=13)
    if status != StatusType.READY or len(data) < 5:
        if self.verbose:
            print(f"    Focus read failed (status={status}, len={len(data)})")
        return None
    focus = struct.unpack(">I", b"\x00" + data[1:4])[0]
    if self.verbose:
        print(f"    Focus position: {focus} (0x{focus:04X})")
    return focus

def set_focus_param(self, focus_value: int = 0) -> bool:
    """Set focus parameter on scanner.

    Golden fixture line 190: e0 00 b4 00 00 00 00 00 09 00
    SANE coolscan3.c:2655 uses e0/c1 for set_focus, but golden
    fixture (LS-40 ED) uses e0/b4 for parameter setting.
    focus_value: 32-bit BE focus position (0 = default/auto).

    Returns:
        True if command accepted.
    """
    if self.verbose:
        print(f"  Setting focus param to {focus_value} (0x{focus_value:04X})...")
    cmd = bytes([0xE0, 0x00, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
    data_out = struct.pack(">I", focus_value) + bytes(4)
    _, status = self._issue_command(cmd, data_out=data_out)
    ok = status == StatusType.READY
    if self.verbose:
        print(f"    Set focus param: {'OK' if ok else 'FAILED'}")
    return ok

def focus_setup(self) -> Optional[int]:
    """Perform focus setup sequence before prescan.

    Golden fixture lines 172-195:
      1. e1/c1  - read current focus position
      2. e0/b4  - set focus parameter
      3. c1     - execute/commit

    Returns:
        Read focus position value, or None on failure.
    """
    if self.verbose:
        print("Performing focus setup...")

    focus = self.read_focus()
    if focus is None:
        if self.verbose:
            print("  Could not read focus, using default")
        focus = 0

    if not self.set_focus_param(focus):
        if self.verbose:
            print("  Could not set focus param, continuing")

    if not self._execute_command():
        if self.verbose:
            print("  Execute failed, continuing")

    if self.verbose:
        print(f"  Focus setup complete (position={focus})")
    return focus

def auto_focus(self, focus_x: int = 0, focus_y: int = 0) -> Optional[int]:
    """Perform auto-focus operation.

    Golden fixture / batch capture uses e0/a0 (not 0xc2).
    SANE coolscan3.c:2702 cs3_autofocus():
      1. e1/c1  - read current focus
      2. e0/a0  - autofocus at (focus_x, focus_y)
      3. c1     - execute
      4. e1/c1  - read new focus position

    Args:
        focus_x: X coordinate for autofocus target (0 = center).
        focus_y: Y coordinate for autofocus target (0 = center).

    Returns:
        New focus position after autofocus, or None on failure.
    """
    if self.verbose:
        print("Performing auto-focus...")

    # Step 1: Read current focus
    old_focus = self.read_focus()
    if old_focus is not None and self.verbose:
        print(f"    Old focus: {old_focus} (0x{old_focus:04X})")

    # Step 2: Send autofocus command with target coordinates
    if self.verbose:
        print(f"  Sending AUTOFOCUS (0xe0/a0) at ({focus_x}, {focus_y})...")
    cmd = bytes([0xE0, 0x00, 0xA0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
    data_out = struct.pack(">II", focus_x, focus_y)
    _, status = self._issue_command(cmd, data_out=data_out)
    if status != StatusType.READY:
        if self.verbose:
            print(f"    Autofocus command failed (status={status})")
        return None

    # Step 3: Execute
    if not self._execute_command():
        if self.verbose:
            print("    Execute after autofocus failed")
        return None

    # Step 4: Read new focus position
    new_focus = self.read_focus()
    if new_focus is not None and self.verbose:
        print(f"    New focus: {new_focus} (0x{new_focus:04X})")
    return new_focus

def eject_medium(self) -> bool:
    """Eject medium (post-scan cleanup).

    Golden fixture line 1425: e0 00 d0 00 00 00 00 00 0d 00
    SANE coolscan3.c:2599 cs3_eject().
    Followed by c1 execute command.

    Returns:
        True if eject succeeded.
    """
    if self.verbose:
        print("  Ejecting medium (0xe0/d0)...")
    cmd = bytes([0xE0, 0x00, 0xD0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0D, 0x00])
    _, status = self._issue_command(cmd)
    if status != StatusType.READY:
        if self.verbose:
            print(f"    Eject command failed (status={status})")
        return False

    return self._execute_command()

def reset_params(self) -> bool:
    """Reset scanner parameters (post-eject cleanup).

    Golden fixture line 1446: e0 00 b4 00 00 00 00 00 09 00
    SANE coolscan3.c:2616 uses e0/80 for reset, but golden
    fixture (LS-40 ED) uses e0/b4. Followed by c1 execute.

    Returns:
        True if reset succeeded.
    """
    if self.verbose:
        print("  Resetting params (0xe0/b4)...")
    cmd = bytes([0xE0, 0x00, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
    _, status = self._issue_command(cmd)
    if status != StatusType.READY:
        if self.verbose:
            print(f"    Reset command failed (status={status})")
        return False

    return self._execute_command()

def scan_teardown(self) -> bool:
    """Perform post-scan teardown matching golden fixture.

    Golden fixture lines 1413-1478 sequence:
      1. TUR polling until scanner ready (3 polls, ~2s apart)
      2. e0/d0 eject medium + c1 execute
      3. TUR polling (3 polls)
      4. e0/b4 reset params + c1 execute
      5. TUR polling
      6. SET_WINDOW for channels 1/2/3/9 (flush scanner state)

    This ensures the scanner is properly released and ready for
    the next session or safe disconnection.

    Returns:
        True if teardown completed successfully.
    """
    if self.verbose:
        print("Performing scan teardown...")

    # 1. TUR polling until ready
    if self.verbose:
        print("  Post-scan TUR polling...")
    for i in range(3):
        self.test_unit_ready()
        if i < 2:
            time.sleep(2.0)

    # 2. Eject medium
    if not self.eject_medium():
        if self.verbose:
            print("  Eject failed, continuing teardown...")

    # 3. TUR polling after eject
    for i in range(3):
        self.test_unit_ready()
        if i < 2:
            time.sleep(1.0)

    # 4. Reset params
    if not self.reset_params():
        if self.verbose:
            print("  Reset failed, continuing teardown...")

    # 5. Final TUR
    self.test_unit_ready()

    # 6. SET_WINDOW for all 4 channels to flush state
    for win_id in [1, 2, 3, 9]:
        self.set_scan_window(win_id, scan_type="normal")

    if self.verbose:
        print("  Scan teardown complete")
    return True
```

#### Change 2: Update `perform_scan_sequence()` to read back exposure

**Location:** In `perform_scan_sequence()` method, after the SET_WINDOW loop (around line 2680), add exposure read-back:

```python
# After step 8 (SET_WINDOW loop), before step 9 (TUR):

# 8b. Read back exposure values computed by scanner (SANE: cs3_get_exposure)
# The scanner recalculates exposure internally; we need to read what it decided.
exposure_values = self.get_exposure_values(colors=[1, 2, 3])
if exposure_values:
    if self.verbose:
        for ch, val in exposure_values.items():
            print(f"    {ch} exposure: {val} (10ns units) = {val/100000:.2f} ms")
else:
    if self.verbose:
        print("    Could not read exposure values")
```

#### Change 3: Update `prescan()` to include focus setup

**Location:** In `prescan()` method, after Step 0b (reserve_unit) and before Step 1 (SET_WINDOW):

```python
# Step 0c: Focus setup before prescan (golden fixture lines 172-195)
if not self._check_scanner_alive():
    print("  Scanner unresponsive before focus setup")
    return False
focus = self.focus_setup()
if focus is not None:
    print(f"  Focus position: {focus} (0x{focus:04X})")
```

#### Change 4: Update `set_boundary()` docstring with boundary documentation

**Location:** In `set_boundary()` method docstring, add:

```python
"""Send CONTROL_FRAME before full scan (golden fixture line 427).

Frame boundaries are determined from scanner physical dimensions
(INQUIRY pages 0xc1/0xd1) and requested scan area, NOT from
prescan image data analysis. The prescan provides exposure
calibration and focus data, but frame positions are computed
from the scan parameters.

The SANE coolscan3 backend sends SEND with datatype 0x88
(IMAGE_POSITIONS) for set_boundary, but the LS-40 ED rejects
0x88 with ILLEGAL REQUEST (ASC=0x26). The golden fixture shows
the LS-40 ED uses SEND 0x8f (CONTROL_FRAME) with a 52-byte
payload instead.

Args:
    params: Scan parameters (unused; payload is fixed from golden fixture).

Returns:
    True if scanner accepted the command.
"""
```

### File: `test_hardware_full_scan.py`

#### Change 5: Call teardown after scan data read

**Location:** After the scan data read loop (around line 91), before saving image:

```python
# After the scan data read loop, before "=== SAVING IMAGE ===":

# Teardown scanner (golden fixture lines 1413-1478)
print("\n=== SCAN TEARDOWN ===")
protocol.scan_teardown()
print("Teardown complete")
```

#### Change 6: Remove duplicate release_unit from finally block

The `finally` block already calls `release_unit()`, but `scan_teardown()` handles cleanup more thoroughly. The `finally` block's `release_unit()` is still useful as a safety net, so keep it.

---

## Verification

After applying changes:
1. Run `make check-all` to verify lint + tests pass
2. Run `python test_hardware_full_scan.py` with scanner connected
3. Compare new `test_hardware_scan_capture.txt` against golden fixture:
   - Focus commands (e1/c1, e0/b4, c1) should appear before prescan
   - Exposure read-back (25/GET_WINDOW) should appear after full scan SET_WINDOW
   - Teardown sequence (TUR, e0/d0, c1, TUR, e0/b4, c1, SET_WINDOW×4) should appear at end
   - Focus values should be printed in verbose output
