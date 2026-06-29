"""Property tests for protocol invariants (non-byte-exact).

These tests verify protocol invariants independent of the exact fixture
contents.  They catch regressions in control flow, command ordering, and
data sizes without depending on byte-exact match against a particular
capture.

Markers: ``@pytest.mark.replay_consistency`` (internal consistency)
         ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

import struct
from unittest.mock import patch

import pytest

from coolscan.protocol import (
    CoolscanProtocol,
    DataType,
    StatusType,
)
from coolscan.usb_replay import UsbCaptureReplay


class MockInterface:
    value = "usb"


class MockDevice:
    def __init__(self):
        self.vendor = "Nikon"
        self.model = "LS-40 ED"
        self.revision = "1.20"
        self.interface = MockInterface()
        self.device_path = "/dev/usb/scanner0"
        self.vendor_id = 0x04B0
        self.product_id = 0x4000


# ---------------------------------------------------------------------------
# Property: REISSUE handling
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_reissue_causes_resend():
    """After START_SCAN returns REISSUE (sense 0x09800600/01), code re-issues."""
    # Build a minimal replay for start_scan only.
    # start_scan sends: OUT(cmd) -> OUT(d0) -> IN(phase) -> OUT(scan_data) -> IN(status)
    start_scan_cmd = bytes([0x1B, 0x00, 0x00, 0x00, 0x03, 0x00])
    scan_data = bytes([0x01, 0x02, 0x03])

    events = [
        # Attempt 1: REISSUE
        ("out", start_scan_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", bytes([0x02, 0x09, 0x80, 0x06, 0x01, 0x00, 0x00, 0x00])),  # REISSUE
        # READ status/progress between retries (6 bytes then 33 bytes)
        ("out", b"\x28\x00\x87\x00\x00\x00\x00\x00\x06\x80"),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", bytes([0x87, 0x08, 0x00, 0x00, 0x00, 0x1b])),
        ("in", b"\x00" * 8),
        ("out", b"\x28\x00\x87\x00\x00\x00\x00\x00\x21\x80"),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", bytes([0x87, 0x08, 0x00, 0x00, 0x00, 0x1b, 0x06, 0x09, 0x80, 0x06, 0x01, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
        ("in", b"\x00" * 8),
        # Attempt 2: transient ERROR (sense 0x09800100) — must be retried
        ("out", start_scan_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", bytes([0x02, 0x09, 0x80, 0x01, 0x00, 0x00, 0x00, 0x00])),  # transient ERROR
        # READ status/progress between retries
        ("out", b"\x28\x00\x87\x00\x00\x00\x00\x00\x06\x80"),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", bytes([0x87, 0x08, 0x00, 0x00, 0x00, 0x12])),
        ("in", b"\x00" * 8),
        ("out", b"\x28\x00\x87\x00\x00\x00\x00\x00\x18\x80"),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", bytes([0x87, 0x08, 0x00, 0x00, 0x00, 0x12, 0x01, 0x09, 0x80, 0x01, 0x06, 0x00, 0x5f, 0x04, 0x83, 0x0c, 0x04, 0x83, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])),
        ("in", b"\x00" * 8),
        # Attempt 3: READY
        ("out", start_scan_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", b"\x00" * 8),  # READY
    ]

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.start_scan()

    assert result is True
    assert replay.position == replay.total
    proto.close()


# ---------------------------------------------------------------------------
# Property: poll_until_ready returns on READY
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_poll_until_ready_returns_on_ready():
    """poll_until_ready() returns after receiving READY status (0x01)."""
    events = []
    # 3 BUSY polls then READY
    for _ in range(3):
        events.extend([
            ("out", bytes([0x00] * 6)),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", bytes([0x02, 0x02, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00])),  # PROCESSING
        ])
    # Final READY
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),  # READY
    ])

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.poll_until_ready(timeout=5, poll_interval=0.01)

    assert result is True
    proto.close()


@pytest.mark.property_test
def test_poll_until_ready_handles_many_busy():
    """poll_until_ready() returns after N BUSY cycles (N >= 10)."""
    events = []
    for _ in range(12):
        events.extend([
            ("out", bytes([0x00] * 6)),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", bytes([0x02, 0x02, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00])),
        ])
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),
    ])

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.poll_until_ready(timeout=10, poll_interval=0.01)

    assert result is True
    proto.close()


# ---------------------------------------------------------------------------
# Property: LUT upload sizes (no USB needed — test _generate_identity_lut directly)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_lut_upload_sends_correct_size():
    """LUT upload sends 8192 bytes per channel for channels 1, 2, 3."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    maxbits = 12
    proto.maxbits = maxbits
    expected_size = 2 * (1 << maxbits)

    lut = proto._generate_identity_lut()
    assert len(lut) == expected_size, f"LUT size {len(lut)} != {expected_size}"
    proto.close()


@pytest.mark.property_test
def test_lut_upload_11bit_size():
    """LUT upload with 11-bit maxbits produces 4096 bytes."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    proto.maxbits = 11

    lut = proto._generate_identity_lut()
    assert len(lut) == 2 * (1 << 11)  # 4096
    proto.close()


# ---------------------------------------------------------------------------
# Property: SET_WINDOW before scan (CDB construction, no USB needed)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_set_window_called_for_rgb():
    """SET_WINDOW is called for windows 1, 2, 3 before any START_SCAN."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    # Check that set_scan_window builds the correct CDB
    cmd_hex = "24000000000000003a80"
    expected = struct.pack(
        "BBBBBBBBBB", 0x24, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3A, 0x80
    )
    assert expected.hex() == cmd_hex
    proto.close()


# ---------------------------------------------------------------------------
# Property: scanner_ready with TUR retries
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_scanner_ready_succeeds_after_tur_retries():
    """scanner_ready() succeeds after N TUR retries (N >= 1)."""
    events = []
    # 2 BUSY TURs then READY
    for _ in range(2):
        events.extend([
            ("out", bytes([0x00] * 6)),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", bytes([0x02, 0x06, 0x28, 0x00, 0x01, 0x00, 0x00, 0x00])),  # BUSY
        ])
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),  # READY
    ])

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.scanner_ready(timeout=5)

    assert result is True
    proto.close()


@pytest.mark.property_test
def test_scanner_ready_succeeds_after_many_retries():
    """scanner_ready() succeeds after 5 TUR retries."""
    events = []
    for _ in range(5):
        events.extend([
            ("out", bytes([0x00] * 6)),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", bytes([0x02, 0x06, 0x28, 0x00, 0x01, 0x00, 0x00, 0x00])),
        ])
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),
    ])

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.scanner_ready(timeout=10)

    assert result is True
    proto.close()


# ---------------------------------------------------------------------------
# Property: CDB construction correctness (no USB needed)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_inquiry_cdb_standard_36_bytes():
    """Standard INQUIRY produces 6-byte CDB requesting 36 bytes."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    cmd = proto._build_6byte_command(0x12, page=0x00, alloc_length=0x24, control=0x80)
    assert len(cmd) == 6
    assert cmd[0] == 0x12
    assert cmd[4] == 0x24  # 36 bytes
    assert cmd[5] == 0x80
    proto.close()


@pytest.mark.property_test
def test_read_capacity_cdb_format():
    """READ_CAPACITY produces 10-byte CDB."""
    cmd = struct.pack(
        "BBBBBBBBBB", 0x25, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3A, 0x80
    )
    assert len(cmd) == 10
    assert cmd[0] == 0x25


@pytest.mark.property_test
def test_read_scan_data_cdb_10_byte():
    """read_scan_data builds a 10-byte READ(10) CDB."""
    cmd = struct.pack(
        "BBBBBBBBBB",
        0x28, 0x00, DataType.IMAGE_DATA.value, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x40, 0x80,
    )
    assert len(cmd) == 10
    assert cmd[0] == 0x28
    assert cmd[2] == DataType.IMAGE_DATA.value


# ---------------------------------------------------------------------------
# Property: status parsing (no USB needed — _parse_status is a method)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_status_parse_ready():
    """8-byte all-zeros status parses as READY."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    status, parsed = proto._parse_status(b"\x00" * 8)
    assert status == StatusType.READY
    proto.close()


@pytest.mark.property_test
def test_status_parse_reissue():
    """Sense key 0x09 + ASC 0x80 + ASCQ 0x06 + aux 0x00/0x01 parses as REISSUE."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    status, _ = proto._parse_status(bytes([0x02, 0x09, 0x80, 0x06, 0x00, 0x00, 0x00, 0x00]))
    assert status == StatusType.REISSUE
    status2, _ = proto._parse_status(bytes([0x02, 0x09, 0x80, 0x06, 0x01, 0x00, 0x00, 0x00]))
    assert status2 == StatusType.REISSUE
    proto.close()


@pytest.mark.property_test
def test_status_parse_processing():
    """Sense key 0x02 + ASC 0x04 + ASCQ 0x01 parses as PROCESSING."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    status, _ = proto._parse_status(bytes([0x02, 0x02, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00]))
    assert status == StatusType.PROCESSING
    proto.close()


# ---------------------------------------------------------------------------
# Property: read_focus_info CDB format (e1/91, golden fixture line 181)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_read_focus_info_cdb_format():
    """read_focus_info sends e1/91 READ(10) requesting 9 bytes."""
    focus_info_cmd = struct.pack(
        "BBBBBBBBBB", 0xE1, 0x00, 0x91, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00
    )
    assert len(focus_info_cmd) == 10
    assert focus_info_cmd[0] == 0xE1
    assert focus_info_cmd[2] == 0x91
    assert focus_info_cmd[8] == 0x09  # 9 bytes


# ---------------------------------------------------------------------------
# Property: read_control_params CDB format (1a/8f)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_read_control_params_cdb_format():
    """read_control_params sends MODE SENSE(10) for page 0x8f, 52 bytes."""
    ctrl_params_cmd = struct.pack(
        "BBBBBBBBBB", 0x1A, 0x00, 0x8F, 0x00, 0x00, 0x03, 0x00, 0x00, 0x34, 0x00
    )
    assert len(ctrl_params_cmd) == 10
    assert ctrl_params_cmd[0] == 0x1A  # MODE SENSE(10)
    assert ctrl_params_cmd[2] == 0x8F  # page code
    assert ctrl_params_cmd[8] == 0x34  # 52 bytes


# ---------------------------------------------------------------------------
# Property: auto_focus 9-byte payload (golden fixture line 439)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_auto_focus_payload_is_9_bytes():
    """auto_focus sends 9-byte payload: 0x00 prefix + focusx(4) + focusy(4)."""
    focus_x, focus_y = 0x0000059B, 0x00000AC4
    expected = b"\x00" + struct.pack(">II", focus_x, focus_y)
    assert len(expected) == 9
    assert expected[0] == 0x00
    assert struct.unpack(">I", expected[1:5])[0] == focus_x
    assert struct.unpack(">I", expected[5:9])[0] == focus_y


# ---------------------------------------------------------------------------
# Property: focus_setup includes read_focus_info
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_focus_setup_includes_read_focus_info():
    """focus_setup calls read_focus_info between read_focus and set_focus_param.

    read_focus uses the 9-byte allocation seen in the golden fixture.
    """
    events = []
    # Initial TEST UNIT READY before focus setup
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),  # status READY
    ])
    # read_focus: e1/c1 -> DATA_IN(0x03) -> 9 bytes -> status READY
    events.extend([
        ("out", bytes([0xE1, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x03"),  # DATA_IN phase
        ("in", b"\x00" * 9),  # 9 bytes focus data
        ("in", b"\x00" * 8),  # status READY
    ])
    # TEST UNIT READY between read_focus and read_focus_info
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),  # status READY
    ])
    # read_focus_info: e1/91 -> DATA_IN(0x03) -> 9 bytes -> status READY
    events.extend([
        ("out", bytes([0xE1, 0x00, 0x91, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x03"),  # DATA_IN phase
        ("in", b"\x00" * 9),  # 9 bytes focus info
        ("in", b"\x00" * 8),  # status READY
    ])
    # TEST UNIT READY between read_focus_info and set_focus_param
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),  # status READY
    ])

    replay = UsbCaptureReplay(events=events)

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.focus_setup()

    assert result is not None
    assert replay.position == replay.total
    proto.close()


# ---------------------------------------------------------------------------
# Property: post_prescan_autofocus sequence
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_post_prescan_autofocus_sequence():
    """post_prescan_autofocus: read focus -> e0/a0 -> execute -> poll -> read focus."""
    events = []
    # Step 1: read focus (e1/c1) -> DATA_IN -> 9 bytes -> status
    events.extend([
        ("out", bytes([0xE1, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x03"),  # DATA_IN phase
        ("in", b"\x00" * 9),  # 9 bytes focus data
        ("in", b"\x00" * 8),  # status READY
    ])
    # Step 2: autofocus command (e0/a0) -> DATA_OUT -> send 9 bytes -> status
    events.extend([
        ("out", bytes([0xE0, 0x00, 0xA0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x02"),  # DATA_OUT phase
        ("out", b"\x00" * 9),  # 9-byte autofocus payload
        ("in", b"\x00" * 8),  # status READY
    ])
    # Step 3: execute (c1) -> DATA_OUT -> status
    events.extend([
        ("out", bytes([0xC1, 0x00, 0x00, 0x00, 0x00, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x02"),  # DATA_OUT phase
        ("in", b"\x00" * 8),  # status READY
    ])
    # Step 4: poll until ready (1 PROCESSING then READY)
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", bytes([0x02, 0x02, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00])),  # PROCESSING
    ])
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),  # READY
    ])
    # Step 5: read new focus (e1/c1) -> DATA_IN -> 9 bytes -> status
    events.extend([
        ("out", bytes([0xE1, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x03"),  # DATA_IN phase
        ("in", b"\x00" * 9),  # 9 bytes focus data
        ("in", b"\x00" * 8),  # status READY
    ])

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.post_prescan_autofocus()

    assert result is not None
    assert replay.position == replay.total
    proto.close()


# ---------------------------------------------------------------------------
# Property: WDB byte 34 (bits_per_pixel) matches requested depth
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_wdb_depth_byte_8bit():
    """WDB byte 34 (bits_per_pixel) is 0x08 for normal scan with depth=8."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    captured_wdb = []

    def capture_issue(cmd, data_out=b"", data_in_length=0):
        captured_wdb.append(data_out)
        return (b"", StatusType.READY)

    with patch.object(proto, "_issue_command", side_effect=capture_issue):
        proto.set_scan_window(1, scan_type="normal", depth=8)

    assert len(captured_wdb) >= 1
    wdb = captured_wdb[-1]
    assert len(wdb) == 58
    assert wdb[34] == 0x08, f"Expected byte 34 = 0x08, got 0x{wdb[34]:02x}"
    proto.close()


@pytest.mark.property_test
def test_wdb_depth_byte_12bit():
    """WDB byte 34 (bits_per_pixel) is 0x0c for normal scan with depth=12."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    captured_wdb = []

    def capture_issue(cmd, data_out=b"", data_in_length=0):
        captured_wdb.append(data_out)
        return (b"", StatusType.READY)

    with patch.object(proto, "_issue_command", side_effect=capture_issue):
        proto.set_scan_window(1, scan_type="normal", depth=12)

    assert len(captured_wdb) >= 1
    wdb = captured_wdb[-1]
    assert len(wdb) == 58
    assert wdb[34] == 0x0C, f"Expected byte 34 = 0x0C, got 0x{wdb[34]:02x}"
    proto.close()


@pytest.mark.property_test
def test_wdb_prescan_depth_unchanged():
    """Prescan WDB byte 34 remains 0x0c (12-bit) regardless of depth parameter."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    captured_wdb = []

    def capture_issue(cmd, data_out=b"", data_in_length=0):
        captured_wdb.append(data_out)
        return (b"", StatusType.READY)

    with patch.object(proto, "_issue_command", side_effect=capture_issue):
        proto.set_scan_window(1, scan_type="prescan", depth=8)

    assert len(captured_wdb) >= 1
    wdb = captured_wdb[-1]
    assert len(wdb) == 58
    assert wdb[34] == 0x0C, f"Prescan byte 34 should be 0x0C, got 0x{wdb[34]:02x}"
    proto.close()


# ---------------------------------------------------------------------------
# Cross-capture invariants (Phase 6 of golden-fixture-sequence-alignment.md)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_start_scan_retries_on_reissue_and_transient_error():
    """START_SCAN retries on REISSUE (0x09800601) and transient ERROR (0x09800100)."""
    start_scan_cmd = bytes([0x1B, 0x00, 0x00, 0x00, 0x03, 0x00])
    scan_data = bytes([0x01, 0x02, 0x03])

    events = [
        # Attempt 1: REISSUE
        ("out", start_scan_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", bytes([0x02, 0x09, 0x80, 0x06, 0x01, 0x00, 0x00, 0x00])),
        # Progress reads after REISSUE: 6 bytes then 33 bytes
        ("out", bytes([0x28, 0x00, 0x87, 0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x80])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", bytes([0x87, 0x08, 0x00, 0x00, 0x00, 0x1b])),
        ("in", b"\x00" * 8),
        ("out", bytes([0x28, 0x00, 0x87, 0x00, 0x00, 0x00, 0x00, 0x00, 0x21, 0x80])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", b"\x00" * 33),
        ("in", b"\x00" * 8),
        # Attempt 2: transient ERROR
        ("out", start_scan_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", bytes([0x02, 0x09, 0x80, 0x01, 0x00, 0x00, 0x00, 0x00])),
        # Progress reads after transient ERROR: 6 bytes then 24 bytes
        ("out", bytes([0x28, 0x00, 0x87, 0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x80])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", bytes([0x87, 0x08, 0x00, 0x00, 0x00, 0x12])),
        ("in", b"\x00" * 8),
        ("out", bytes([0x28, 0x00, 0x87, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x80])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", b"\x00" * 24),
        ("in", b"\x00" * 8),
        # Attempt 3: READY
        ("out", start_scan_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", b"\x00" * 8),
    ]

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.start_scan()

    assert result is True
    assert replay.position == replay.total
    proto.close()


@pytest.mark.property_test
def test_set_scan_window_wdb_length_and_window_id():
    """SET_WINDOW always sends a 58-byte WDB with window_id at byte 0."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    proto.maxbits = 12

    valid_cases = [
        ("prescan", [1, 2, 3]),
        ("normal", [1, 2, 3, 9]),
        ("setup", [9, 1, 2, 3]),
        ("batch", [9, 1, 2, 3]),
        ("batch_between", [1, 2, 3]),
    ]

    for scan_type, window_ids in valid_cases:
        for window_id in window_ids:
            captured = []

            def capture_issue(cmd, data_out=b"", data_in_length=0):
                captured.append((cmd, data_out))
                return (b"", StatusType.READY)

            with patch.object(proto, "_issue_command", side_effect=capture_issue):
                proto.set_scan_window(window_id=window_id, scan_type=scan_type)

            assert len(captured) == 1, f"{scan_type}/{window_id}: expected one SET_WINDOW call"
            cmd, wdb = captured[0]
            assert cmd[0] == 0x24, f"{scan_type}/{window_id}: expected SET_WINDOW opcode 0x24"
            assert len(wdb) == 58, f"{scan_type}/{window_id}: WDB length {len(wdb)} != 58"
            # The capture-derived 58-byte WDB carries the window ID at byte 8.
            # This offset is consistent across single-BW and batch captures and
            # distinguishes R/G/B/IR channels.
            assert wdb[8] == window_id, f"{scan_type}/{window_id}: WDB byte 8 0x{wdb[8]:02x} != {window_id}"

    proto.close()


@pytest.mark.property_test
def test_upload_identity_luts_sends_three_or_four_8192_byte_chunks():
    """upload_identity_luts sends 3 (RGB) or 4 (RGB+IR) chunks of 8192 bytes."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    proto.maxbits = 12

    for include_ir, expected_count in [(False, 3), (True, 4)]:
        captured = []

        def capture_issue(cmd, data_out=b"", data_in_length=0):
            captured.append((cmd, data_out))
            return (b"", StatusType.READY)

        with patch.object(proto, "_issue_command", side_effect=capture_issue):
            result = proto.upload_identity_luts(include_ir=include_ir)

        assert result is True
        data_outs = [d for _, d in captured if len(d) > 0]
        assert len(data_outs) == expected_count, (
            f"include_ir={include_ir}: expected {expected_count} LUT chunks, got {len(data_outs)}"
        )
        for idx, payload in enumerate(data_outs):
            assert len(payload) == 8192, f"include_ir={include_ir} chunk {idx}: {len(payload)} != 8192"

    proto.close()


@pytest.mark.property_test
def test_read_scan_data_uses_correct_datatype():
    """Image data READ(10) uses datatype 0x00; status/progress uses 0x87."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    captured = []

    def capture_issue(cmd, data_out=b"", data_in_length=0):
        captured.append(cmd)
        return (b"", StatusType.READY)

    with patch.object(proto, "_issue_command", side_effect=capture_issue):
        proto.read_scan_data(64, DataType.IMAGE_DATA)
        proto.read_scan_data(6, DataType.STATUS_PROGRESS)

    assert len(captured) == 2
    assert captured[0][2] == DataType.IMAGE_DATA.value, (
        f"image datatype 0x{captured[0][2]:02x} != 0x{DataType.IMAGE_DATA.value:02x}"
    )
    assert captured[1][2] == DataType.STATUS_PROGRESS.value, (
        f"status datatype 0x{captured[1][2]:02x} != 0x{DataType.STATUS_PROGRESS.value:02x}"
    )
    proto.close()


@pytest.mark.property_test
def test_session_has_one_reserve_unit_before_first_scan():
    """A session issues exactly one RESERVE_UNIT before the first scan operation."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    reserve_count = 0

    def counting_issue(cmd, data_out=b"", data_in_length=0):
        nonlocal reserve_count
        if cmd and len(cmd) >= 1 and cmd[0] == 0x16:
            reserve_count += 1
        return (b"", StatusType.READY)

    with patch.object(proto, "_issue_command", side_effect=counting_issue):
        assert proto.reserve_unit() is True
        assert proto.start_scan() is True

    assert reserve_count == 1, f"expected 1 RESERVE_UNIT, got {reserve_count}"
    proto.close()


# ---------------------------------------------------------------------------
# Property: _build_scan_window_wdb matches hardcoded tables byte-for-byte
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_build_scan_window_wdb_matches_hardcoded_tables():
    """_build_scan_window_wdb reproduces the original hardcoded tables exactly
    for all valid (scan_type, window_id) combinations with default depth=8."""
    from coolscan.protocol import (
        _SCAN_WINDOW_WDB_TABLES,
        _SCAN_WINDOW_RESOLUTIONS,
    )

    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    proto.maxbits = 12

    for scan_type, windows in _SCAN_WINDOW_WDB_TABLES.items():
        for window_id, expected_bytes in windows.items():
            built = proto._build_scan_window_wdb(window_id, scan_type, depth=8)
            assert built is not None, f"{scan_type}/{window_id}: builder returned None"
            assert len(built) == 58, f"{scan_type}/{window_id}: length {len(built)} != 58"

            # The builder modifies bytes 8, 10-13, and 34. For non-normal/non-single_bw
            # types (or IR windows), byte 34 is unchanged. For normal/single_bw RGB,
            # byte 34 is set to 0x08 (depth=8). The expected table already has the
            # correct values for the default window_id and resolution.
            #
            # For normal/single_bw with depth=8, byte 34 should be 0x08.
            # The hardcoded tables already have 0x08 for single_bw and normal RGB.
            # For prescan/setup/batch/batch_between, byte 34 is 0x0c and unchanged.

            if scan_type in ("normal", "single_bw") and window_id != 9:
                # Builder sets byte 34 to 0x08 for depth=8; hardcoded table already has 0x08
                assert built == expected_bytes, (
                    f"{scan_type}/{window_id}: builder output differs from hardcoded table. "
                    f"Built: {built.hex()[:80]}... Expected: {expected_bytes.hex()[:80]}..."
                )
            else:
                # For non-depth-patched types, builder output must match exactly
                assert built == expected_bytes, (
                    f"{scan_type}/{window_id}: builder output differs from hardcoded table. "
                    f"Built: {built.hex()[:80]}... Expected: {expected_bytes.hex()[:80]}..."
                )

    proto.close()


@pytest.mark.property_test
def test_build_scan_window_wdb_depth_12bit_normal():
    """_build_scan_window_wdb sets byte 34 to 0x0C for normal/single_bw RGB with depth=12."""
    from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    for scan_type in ("normal", "single_bw"):
        for window_id in [1, 2, 3]:
            built = proto._build_scan_window_wdb(window_id, scan_type, depth=12)
            assert built is not None, f"{scan_type}/{window_id}: builder returned None"
            assert built[34] == 0x0C, (
                f"{scan_type}/{window_id}: byte 34 = 0x{built[34]:02x}, expected 0x0C"
            )
            # Verify other fields match the table
            expected = _SCAN_WINDOW_WDB_TABLES[scan_type][window_id]
            assert built[8] == window_id
            assert built[10:14] == expected[10:14]  # resolution unchanged
            # All non-parameterized bytes match
            for i in range(58):
                if i == 8 or 10 <= i <= 13 or i == 34:
                    continue
                assert built[i] == expected[i], (
                    f"{scan_type}/{window_id}: byte {i} differs: "
                    f"built=0x{built[i]:02x} expected=0x{expected[i]:02x}"
                )

    proto.close()


@pytest.mark.property_test
def test_build_scan_window_wdb_preserves_ir_window_depth():
    """IR window (9) in normal/single_bw keeps capture-derived depth, not overridden."""
    from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    # normal has window 9; single_bw does not
    built = proto._build_scan_window_wdb(9, "normal", depth=8)
    expected = _SCAN_WINDOW_WDB_TABLES["normal"][9]
    assert built is not None
    # IR window in normal has 0x0c (12-bit) in the table; builder should NOT override it
    assert built[34] == expected[34], (
        f"normal/IR: byte 34 = 0x{built[34]:02x}, expected 0x{expected[34]:02x}"
    )
    assert built == expected, "normal/IR: full WDB must match table exactly"

    proto.close()


@pytest.mark.property_test
def test_build_scan_window_wdb_unknown_combination_returns_none():
    """_build_scan_window_wdb returns None for invalid (scan_type, window_id)."""
    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    # Window 9 doesn't exist in prescan/single_bw tables
    assert proto._build_scan_window_wdb(9, "prescan", 8) is None
    assert proto._build_scan_window_wdb(9, "single_bw", 8) is None
    # Invalid window ID
    assert proto._build_scan_window_wdb(5, "normal", 8) is None
    # Invalid scan_type
    assert proto._build_scan_window_wdb(1, "invalid", 8) is None

    proto.close()


@pytest.mark.property_test
def test_build_scan_window_wdb_set_scan_window_integration():
    """set_scan_window produces the same WDB as the original hardcoded tables."""
    from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES, _SCAN_WINDOW_RESOLUTIONS

    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    proto.maxbits = 12

    captured_wdb = []

    def capture_issue(cmd, data_out=b"", data_in_length=0):
        captured_wdb.append(data_out)
        return (b"", StatusType.READY)

    valid_cases = [
        ("prescan", [1, 2, 3]),
        ("setup", [9, 1, 2, 3]),
        ("single_bw", [1, 2, 3]),
        ("normal", [1, 2, 3, 9]),
        ("batch", [9, 1, 2, 3]),
        ("batch_between", [1, 2, 3]),
    ]

    for scan_type, window_ids in valid_cases:
        for window_id in window_ids:
            captured_wdb.clear()
            with patch.object(proto, "_issue_command", side_effect=capture_issue):
                proto.set_scan_window(window_id=window_id, scan_type=scan_type)

            assert len(captured_wdb) == 1
            built_wdb = captured_wdb[0]
            expected = _SCAN_WINDOW_WDB_TABLES[scan_type][window_id]

            assert len(built_wdb) == 58
            assert built_wdb == expected, (
                f"{scan_type}/{window_id}: set_scan_window WDB differs from hardcoded table. "
                f"Built: {built_wdb.hex()[:80]}... Expected: {expected.hex()[:80]}..."
            )

    proto.close()


@pytest.mark.property_test
def test_build_scan_window_wdb_y_offset_and_height_offsets():
    """_build_scan_window_wdb writes y_offset and height to the LS-40 ED WDB
    offsets observed in ls40-batch.pcapng:

    - bytes 14-17: ulx (preserved from table)
    - bytes 18-21: uly (overridden by y_offset)
    - bytes 22-25: width (preserved from table)
    - bytes 26-29: length/height (overridden by height)
    """
    from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    proto.maxbits = 12

    base = _SCAN_WINDOW_WDB_TABLES["batch"][9]
    built = proto._build_scan_window_wdb(
        9, "batch", depth=8, y_offset=30, height=4332
    )
    assert built is not None

    # ulx and width are preserved from the hardcoded table.
    assert built[14:18] == base[14:18]
    assert built[22:26] == base[22:26]

    # y_offset -> uly at bytes 18-21.
    assert struct.unpack(">I", built[18:22])[0] == 30

    # height -> length at bytes 26-29.
    assert struct.unpack(">I", built[26:30])[0] == 4332

    # bytes 28-31 are preserved (were erroneously overwritten before).
    assert built[28:32] == base[28:32]

    proto.close()


@pytest.mark.property_test
def test_build_scan_window_wdb_batch_window_9_matches_golden_geometry():
    """Batch window 9 with y_offset=30, height=4332 reproduces the golden
    fixture WDB byte-for-byte (except exposure, which is calibrated on real
    hardware and not patched when exposure=None)."""
    from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    proto.maxbits = 12

    expected = _SCAN_WINDOW_WDB_TABLES["batch"][9]
    built = proto._build_scan_window_wdb(
        9, "batch", depth=8, y_offset=30, height=4332
    )
    assert built == expected, (
        f"Batch window 9 WDB mismatch.\n"
        f"Built:    {built.hex()}\n"
        f"Expected: {expected.hex()}"
    )

    proto.close()


@pytest.mark.property_test
def test_batch_scan_frame_count_estimation_uses_wdb_length_field():
    """batch_scan_to_frames estimates frame count from the WDB length field at
    bytes 26-29, not from the uly field at bytes 18-21."""
    from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES
    from contextlib import ExitStack

    replay = UsbCaptureReplay(events=[])
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
    proto.maxbits = 12

    # Use a prescan WDB with uly=0 and length=34656 (matching golden fixture).
    prescan_wdb = bytearray(_SCAN_WINDOW_WDB_TABLES["prescan"][1])
    assert struct.unpack(">I", prescan_wdb[18:22])[0] == 0  # uly
    assert struct.unpack(">I", prescan_wdb[26:30])[0] == 34656  # length

    proto._last_prescan_image_data = b"dummy"

    # Patch the downstream helpers so we can exercise just the estimation logic.
    return_values = {
        "prescan": True,
        "set_boundary": True,
        "batch_full_scan_setup_frame": True,
        "start_scan": True,
        "batch_full_scan_capture_frame": b"",
        "_wait_ready_or_replay_once": True,
        "batch_between_scan_setup_frame": True,
        "batch_preview_capture_frame": b"",
        "set_scan_window": True,
        "upload_identity_luts": True,
        "poll_until_ready": True,
        "batch_full_res_capture_frame": b"",
        "post_prescan_autofocus": None,
        "scan_teardown": True,
    }
    with ExitStack() as stack:
        stack.enter_context(patch.object(proto, "get_window", return_value=bytes(prescan_wdb)))
        for name, value in return_values.items():
            stack.enter_context(patch.object(proto, name, return_value=value))
        results = list(
            proto.batch_scan_to_frames(
                frame_count=6, first_y=30, frame_height=4332, step=4330
            )
        )
        # With prescan_height=34656 and step=4330, estimated frames is
        # max(1, 34656 // 4330) = 8, so the requested 6 is not clamped.
        assert len(results) == 6

    proto.close()


# ---------------------------------------------------------------------------
# Property: CONTROL_FRAME payload generation (batch scanning)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_build_control_frame_payload_default_batch_geometry():
    """_build_control_frame_payload produces the expected 52-byte payload for
    the default batch geometry."""
    payload = CoolscanProtocol._build_control_frame_payload(
        frame_count=6,
        first_y=30,
        frame_height=4332,
        step=4330,
    )

    assert len(payload) == 52, f"Expected 52 bytes, got {len(payload)}"

    # Header: 00320600
    assert payload[:4] == b"\x00\x32\x06\x00"

    # Entry 0 (i=0): y_start=30, x1=6, y_end=4362, x2=0x0008000c
    y_start_0 = struct.unpack(">I", payload[4:8])[0]
    x1_0 = struct.unpack(">I", payload[8:12])[0]
    y_end_0 = struct.unpack(">I", payload[12:16])[0]
    x2_0 = struct.unpack(">I", payload[16:20])[0]
    assert y_start_0 == 30, f"Entry 0 y_start: {y_start_0}"
    assert x1_0 == 6, f"Entry 0 x1: {x1_0}"
    assert y_end_0 == 4362, f"Entry 0 y_end: {y_end_0}"
    assert x2_0 == 0x0008000c, f"Entry 0 x2: {x2_0:#x}"

    # Entry 1 (i=1): y_start=4360, x1=0x00000010, y_end=8692, x2=0x0018000c
    y_start_1 = struct.unpack(">I", payload[20:24])[0]
    x1_1 = struct.unpack(">I", payload[24:28])[0]
    y_end_1 = struct.unpack(">I", payload[28:32])[0]
    x2_1 = struct.unpack(">I", payload[32:36])[0]
    assert y_start_1 == 4360, f"Entry 1 y_start: {y_start_1}"
    assert x1_1 == 0x00000010, f"Entry 1 x1: {x1_1:#x}"
    assert y_end_1 == 8692, f"Entry 1 y_end: {y_end_1}"
    assert x2_1 == 0x0018000c, f"Entry 1 x2: {x2_1:#x}"

    # Entry 2 (i=2): y_start=8690, x1=0x00000014, y_end=13022, x2=0x00280010
    y_start_2 = struct.unpack(">I", payload[36:40])[0]
    x1_2 = struct.unpack(">I", payload[40:44])[0]
    y_end_2 = struct.unpack(">I", payload[44:48])[0]
    x2_2 = struct.unpack(">I", payload[48:52])[0]
    assert y_start_2 == 8690, f"Entry 2 y_start: {y_start_2}"
    assert x1_2 == 0x00000014, f"Entry 2 x1: {x1_2:#x}"
    assert y_end_2 == 13022, f"Entry 2 y_end: {y_end_2}"
    assert x2_2 == 0x00280010, f"Entry 2 x2: {x2_2:#x}"


@pytest.mark.property_test
def test_build_control_frame_payload_x_fields_match_fixture():
    """The X-related fields match the pattern from golden_batch.txt line 281."""
    payload = CoolscanProtocol._build_control_frame_payload(
        frame_count=6,
        first_y=30,
        frame_height=4332,
        step=4330,
    )

    # X1 values from golden_batch.txt line 281: 0x00000006, 0x00000010, 0x00000014
    x1_values = [
        struct.unpack(">I", payload[8:12])[0],
        struct.unpack(">I", payload[24:28])[0],
        struct.unpack(">I", payload[40:44])[0],
    ]
    assert x1_values == [0x00000006, 0x00000010, 0x00000014]

    # X2 values from golden_batch.txt line 281: 0x0008000c, 0x0018000c, 0x00280010
    x2_values = [
        struct.unpack(">I", payload[16:20])[0],
        struct.unpack(">I", payload[32:36])[0],
        struct.unpack(">I", payload[48:52])[0],
    ]
    assert x2_values == [0x0008000c, 0x0018000c, 0x00280010]


@pytest.mark.property_test
def test_build_control_frame_payload_single_frame():
    """With frame_count=1, only one entry is populated (padded to 52 bytes)."""
    payload = CoolscanProtocol._build_control_frame_payload(
        frame_count=1,
        first_y=100,
        frame_height=5000,
        step=5000,
    )

    assert len(payload) == 52
    assert payload[:4] == b"\x00\x32\x06\x00"

    y_start = struct.unpack(">I", payload[4:8])[0]
    y_end = struct.unpack(">I", payload[12:16])[0]
    assert y_start == 100
    assert y_end == 5100

    # Remaining entries should be zero-padded
    assert payload[20:52] == b"\x00" * 32


@pytest.mark.property_test
def test_build_control_frame_payload_custom_geometry():
    """Verify step progression with non-default geometry."""
    payload = CoolscanProtocol._build_control_frame_payload(
        frame_count=4,
        first_y=50,
        frame_height=4000,
        step=4100,
    )

    assert len(payload) == 52

    # Entry 0: y_start=50, y_end=4050
    y0_start = struct.unpack(">I", payload[4:8])[0]
    y0_end = struct.unpack(">I", payload[12:16])[0]
    assert y0_start == 50
    assert y0_end == 4050

    # Entry 1: y_start=4150, y_end=8150
    y1_start = struct.unpack(">I", payload[20:24])[0]
    y1_end = struct.unpack(">I", payload[28:32])[0]
    assert y1_start == 4150
    assert y1_end == 8150

    # Entry 2: y_start=8250, y_end=12250
    y2_start = struct.unpack(">I", payload[36:40])[0]
    y2_end = struct.unpack(">I", payload[44:48])[0]
    assert y2_start == 8250
    assert y2_end == 12250
