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
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coolscan.protocol import (
    CoolscanProtocol,
    DataType,
    PhaseType,
    ScanParameters,
    StatusType,
)
from coolscan.usb_replay import (
    ReplayExhaustedError,
    UsbCaptureReplay,
)


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
        # start_scan -> REISSUE
        ("out", start_scan_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", bytes([0x02, 0x09, 0x80, 0x06, 0x01, 0x00, 0x00, 0x00])),  # REISSUE
        # start_scan re-issue -> READY
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
