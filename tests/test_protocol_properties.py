"""Replay-based property tests for USB dispatch path.

These tests exercise the full CoolscanProtocol with UsbCaptureReplay to verify
USB bulk transfer dispatch, retry logic, polling loops, and timeout behavior.
They are the only tests that construct byte-level USB events by hand.

Tests for CDB construction, status parsing, WDB structure, and batch control
logic have been migrated to test_protocol_behavior.py (contract pattern).

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from coolscan.protocol import CoolscanProtocol, DataType, StatusType
from coolscan.usb_replay import UsbCaptureReplay
from tests.fakes import MockDevice


# ---------------------------------------------------------------------------
# REISSUE retry handling (USB dispatch path)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_reissue_causes_resend():
    """After START_SCAN returns REISSUE (sense 0x09800600/01), code re-issues."""
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
# poll_until_ready USB dispatch
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_poll_until_ready_returns_on_ready():
    """poll_until_ready() returns after receiving READY status."""
    events = []
    for _ in range(3):
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


@pytest.mark.property_test
def test_poll_until_ready_timeout_returns_false():
    """poll_until_ready returns False when timeout expires with all BUSY."""
    events = []
    for _ in range(10):
        events.extend([
            ("out", bytes([0x00] * 6)),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", bytes([0x02, 0x02, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00])),
        ])

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.poll_until_ready(timeout=1, poll_interval=0.1)

    assert result is False
    assert replay.position == replay.total
    proto.close()


# ---------------------------------------------------------------------------
# scanner_ready USB dispatch
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_scanner_ready_succeeds_after_tur_retries():
    """scanner_ready() succeeds after N TUR retries (N >= 1)."""
    events = []
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


@pytest.mark.property_test
def test_scanner_ready_timeout_returns_false():
    """scanner_ready returns False after timeout with all BUSY TURs."""
    events = [
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", bytes([0x02, 0x06, 0x28, 0x00, 0x01, 0x00, 0x00, 0x00])),
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", bytes([0x02, 0x06, 0x28, 0x00, 0x01, 0x00, 0x00, 0x00])),
    ]

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    fake_time = 0.0
    def fake_time_fn():
        nonlocal fake_time
        fake_time += 0.5
        return fake_time

    with patch("coolscan.protocol.time.sleep"):
        with patch("coolscan.protocol.time.time", side_effect=fake_time_fn):
            result = proto.scanner_ready(timeout=1.0)

    assert result is False
    proto.close()


# ---------------------------------------------------------------------------
# focus_setup USB dispatch
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_focus_setup_includes_read_focus_info():
    """focus_setup calls read_focus_info between read_focus and set_focus_param."""
    events = []
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),
    ])
    events.extend([
        ("out", bytes([0xE1, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", b"\x00" * 9),
        ("in", b"\x00" * 8),
    ])
    events.extend([
        ("out", bytes([0x00] * 6)),
        ("out", b"\xd0"),
        ("in", b"\x01"),
        ("in", b"\x00" * 8),
    ])
    events.extend([
        ("out", bytes([0xE1, 0x00, 0x91, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", b"\x00" * 9),
        ("in", b"\x00" * 8),
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
        result = proto.focus_setup()

    assert result is not None
    assert replay.position == replay.total
    proto.close()


# ---------------------------------------------------------------------------
# post_prescan_autofocus USB dispatch
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_post_prescan_autofocus_sequence():
    """post_prescan_autofocus: read focus -> e0/a0 -> execute -> poll -> read focus."""
    events = []
    events.extend([
        ("out", bytes([0xE1, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", b"\x00" * 9),
        ("in", b"\x00" * 8),
    ])
    events.extend([
        ("out", bytes([0xE0, 0x00, 0xA0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", b"\x00" * 9),
        ("in", b"\x00" * 8),
    ])
    events.extend([
        ("out", bytes([0xC1, 0x00, 0x00, 0x00, 0x00, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("in", b"\x00" * 8),
    ])
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
    events.extend([
        ("out", bytes([0xE1, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", b"\x00" * 9),
        ("in", b"\x00" * 8),
    ])

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.post_prescan_autofocus()

    assert result is not None
    assert replay.position == replay.total
    proto.close()


# ---------------------------------------------------------------------------
# stop_scan REISSUE retry (USB dispatch)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_stop_scan_retries_on_reissue():
    """STOP_SCAN retries on REISSUE (sense 0x09800601) then succeeds."""
    stop_cmd = bytes([0x1B, 0x00, 0x00, 0x00, 0x04, 0x00])
    scan_data = bytes([0x09, 0x01, 0x02, 0x03])

    events = [
        ("out", stop_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", bytes([0x02, 0x09, 0x80, 0x06, 0x01, 0x00, 0x00, 0x00])),
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
        ("out", stop_cmd),
        ("out", b"\xd0"),
        ("in", b"\x02"),
        ("out", scan_data),
        ("in", b"\x00" * 8),
    ]

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        result = proto.stop_scan()

    assert result is True
    assert replay.position == replay.total
    proto.close()


# ---------------------------------------------------------------------------
# read_scan_data short read (USB dispatch)
# ---------------------------------------------------------------------------

@pytest.mark.property_test
def test_read_scan_data_short_read_returns_partial():
    """read_scan_data returns partial data on short read (exhausts replay)."""
    events = [
        ("out", bytes([0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40, 0x80])),
        ("out", b"\xd0"),
        ("in", b"\x03"),
        ("in", b"\xAA" * 32),
    ]

    replay = UsbCaptureReplay(events=events)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    data = proto.read_scan_data(64, DataType.IMAGE_DATA)

    assert len(data) == 32
    assert data == b"\xAA" * 32
    assert replay.position == replay.total
    proto.close()
