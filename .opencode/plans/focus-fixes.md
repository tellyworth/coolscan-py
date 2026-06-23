# Focus Fixes: e1/91, Post-Prescan Autofocus

## Overview

Analysis of `golden_single_bw.txt` revealed two focus issues:
1. **Missing `e1/91` READ** in pre-prescan focus setup (golden fixture line 181)
2. **Missing post-prescan autofocus** — golden fixture runs `e0/a0` autofocus after prescan data reads, before full scan (lines 436–461)

The prescan image data is used by the scanner to determine optimal focus. Without post-prescan autofocus, the full scan uses whatever focus position was set before prescan.

## Golden Fixture Focus Sequence

### Pre-prescan (lines 172–195)
```
e1/c1 READ focus      → 0x000000f3 (243)
TUR
e1/91 READ (unknown)  → 000000000100000000
TUR
e0/b4 WRITE focus param → 0000000e1000000001 (9 bytes)
c1 EXECUTE
TUR
```

### Post-prescan (lines 436–461)
```
e0/a0 AUTOFOCUS       → 000000059b00000ac4 (9 bytes: focusx=1435, focusy=2756)
c1 EXECUTE
TUR polling (PROCESSING → READY, ~14s)
e1/c1 READ new focus  → 0x000000fb (251)
```

## Code Changes

### File: `coolscan/protocol.py`

#### Change 1: Add `read_focus_info()` for e1/91

**Location:** After `read_focus()` method (~line 2270)

```python
def read_focus_info(self) -> Optional[bytes]:
    """Read focus info via e1/91 (golden fixture line 181).

    Purpose unknown — SANE backend doesn't document this datatype.
    Golden fixture shows 9-byte response: 000000000100000000.
    Called between read_focus and set_focus_param in focus setup.

    Returns:
        9 bytes of focus info, or None on failure.
    """
    if self.verbose:
        print("  Reading focus info (e1/91)...")
    cmd = bytes([0xE1, 0x00, 0x91, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
    data, status = self._issue_command(cmd, data_in_length=9)
    if status != StatusType.READY or len(data) < 9:
        if self.verbose:
            print(f"    Focus info read failed (status={status}, len={len(data)})")
        return None
    if self.verbose:
        print(f"    Focus info: {data.hex()}")
    return data
```

#### Change 2: Add `e1/91` to `focus_setup()`

**Location:** In `focus_setup()` method, after `read_focus()` and before `set_focus_param()`

```python
    def focus_setup(self) -> Optional[int]:
        # ... existing docstring ...
        focus = self.read_focus()
        if focus is None:
            if self.verbose:
                print("  Could not read focus, using default")
            focus = 0

        # Read focus info (golden fixture line 181)
        self.read_focus_info()

        if not self.set_focus_param(focus):
            # ... rest unchanged ...
```

#### Change 3: Fix `auto_focus()` data payload to 9 bytes

**Location:** In `auto_focus()` method (~line 2357)

The golden fixture line 439 shows 9-byte payload: `00` + focusx(4) + focusy(4).
SANE `cs3_autofocus()` (coolscan3.c:2702) sends `00` prefix + two `pack_long` calls.

```python
        # BEFORE:
        data_out = struct.pack(">II", focus_x, focus_y)

        # AFTER:
        data_out = b"\x00" + struct.pack(">II", focus_x, focus_y)
```

#### Change 4: Add `post_prescan_autofocus()` method

**Location:** After `auto_focus()` method

This is a convenience wrapper that matches the golden fixture's post-prescan sequence:
autofocus → execute → TUR poll → read new focus.

```python
def post_prescan_autofocus(self, focus_x: int = 0, focus_y: int = 0) -> Optional[int]:
    """Perform autofocus after prescan (golden fixture lines 436-461).

    The prescan provides image data the scanner uses to determine
    optimal focus. This method runs autofocus, waits for completion,
    and reads the new focus position.

    Args:
        focus_x: X coordinate for autofocus target (0 = center).
        focus_y: Y coordinate for autofocus target (0 = center).

    Returns:
        New focus position after autofocus, or None on failure.
    """
    if self.verbose:
        print("Performing post-prescan autofocus...")

    # Step 1: Read current focus
    old_focus = self.read_focus()
    if old_focus is not None and self.verbose:
        print(f"    Pre-autofocus focus: {old_focus} (0x{old_focus:04X})")

    # Step 2: Send autofocus command
    if self.verbose:
        print(f"  Sending AUTOFOCUS (0xe0/a0) at ({focus_x}, {focus_y})...")
    cmd = bytes([0xE0, 0x00, 0xA0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
    data_out = b"\x00" + struct.pack(">II", focus_x, focus_y)
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

    # Step 4: Poll until scanner ready (autofocus takes ~14s)
    if self.verbose:
        print("  Waiting for autofocus to complete...")
    if not self.poll_until_ready(timeout=60, poll_interval=1.0):
        if self.verbose:
            print("    Autofocus poll timed out")
        return None

    # Step 5: Read new focus position
    new_focus = self.read_focus()
    if new_focus is not None and self.verbose:
        print(f"    Post-autofocus focus: {new_focus} (0x{new_focus:04X})")
    return new_focus
```

### File: `test_hardware_full_scan.py`

#### Change 5: Call autofocus between prescan and full scan

**Location:** After prescan completes, before `perform_scan_sequence()`

```python
        # 5. Prescan (auto-exposure)
        print("\n=== PRESCAN ===")
        protocol.reserve_unit()
        prescan_ok = protocol.prescan()
        protocol.release_unit()
        print(f"Prescan: {'OK' if prescan_ok else 'FAILED'}")
        if not prescan_ok:
            return False

        # 5b. Post-prescan autofocus (golden fixture lines 436-461)
        print("\n=== AUTOFOCUS ===")
        new_focus = protocol.post_prescan_autofocus()
        if new_focus is not None:
            print(f"Autofocus complete, focus position: {new_focus} (0x{new_focus:04X})")
        else:
            print("Autofocus failed, continuing with current focus")

        # 6. Full scan setup
        print("\n=== FULL SCAN SETUP ===")
        # ...
```

## Verification

After applying changes:
1. Run `make check-all` to verify lint + tests pass
2. Run `python test_hardware_full_scan.py` with scanner connected
3. Compare new `test_hardware_scan_capture.txt` against golden fixture:
   - `e1/91` command should appear in pre-prescan focus setup
   - `e0/a0` autofocus should appear after prescan, before full scan
   - TUR polling (PROCESSING→READY) should appear during autofocus (~14s)
   - Post-autofocus focus value should be printed in verbose output
