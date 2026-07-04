"""
Integration test — full scan flow using FakeCoolscanProtocol.

Tests the complete control flow: setup → scan → image read → release,
using the fixture-independent FakeCoolscanProtocol test double.  This
verifies call sequencing and data lengths without depending on USB replay
or fixture files.

The 64-byte allocation proves the protocol transitions correctly from
scanner_ready → reserve_unit → object_position → set_window → _upload_lut →
start_scan → poll_until_ready → read_scan_data → release_unit.
"""

import pytest

from coolscan.protocol import DataType, ScanParameters
from tests.fakes import FakeCoolscanProtocol


@pytest.mark.property_test
def test_full_scan_flow_with_synthetic_data():
    """
    Full control flow: scanner_ready → reserve → setup → start_scan →
    poll_until_ready → read_scan_data(64) → release_unit.

    Uses FakeCoolscanProtocol to verify call sequencing and return values.
    """
    proto = FakeCoolscanProtocol()

    # Configure responses for the full scan flow
    proto.set_response("scanner_ready", True)
    proto.set_response("reserve_unit", True)
    proto.set_response("object_position", True)
    proto.set_response("set_window", True)
    proto.set_response("_upload_lut", True)
    proto.set_response("start_scan", True)
    proto.set_response("poll_until_ready", True)
    proto.set_response("release_unit", True)

    # read_scan_data returns 64 bytes of synthetic image data
    synthetic_data = b"\x00" * 64
    proto.set_response("read_scan_data", synthetic_data)

    # Run the full scan sequence
    assert proto.scanner_ready(timeout=30) is True
    assert proto.reserve_unit() is True
    assert proto.object_position() is True
    assert proto.set_window(ScanParameters()) is True
    assert proto._upload_lut(channel=1, lut_data=b"\x00" * 8192) is True
    assert proto.start_scan() is True
    assert proto.poll_until_ready(timeout=30) is True

    # Read image data before release
    data = proto.read_scan_data(64, DataType.IMAGE_DATA)
    assert len(data) == 64
    assert data == synthetic_data

    # Release unit
    assert proto.release_unit() is True

    # Verify call sequence matches expected order
    expected = [
        "scanner_ready",
        "reserve_unit",
        "object_position",
        "set_window",
        "_upload_lut",
        "start_scan",
        "poll_until_ready",
        "read_scan_data",
        "release_unit",
    ]
    actual = [call[0] for call in proto.call_log]
    assert actual == expected, f"Call sequence mismatch:\n  expected: {expected}\n  actual:   {actual}"

    # Verify read_scan_data was called with correct length
    read_calls = proto.calls_to("read_scan_data")
    assert len(read_calls) == 1
    args, kwargs = read_calls[0]
    assert args[0] == 64, f"Expected length=64, got {args[0]}"
    assert args[1] == DataType.IMAGE_DATA


@pytest.mark.property_test
def test_scan_data_length_matches_request():
    """read_scan_data returns data matching the requested length."""
    proto = FakeCoolscanProtocol()
    expected_data = b"\xFF" * 128
    proto.set_response("read_scan_data", expected_data)

    data = proto.read_scan_data(128, DataType.IMAGE_DATA)
    assert len(data) == 128
    assert data == expected_data


@pytest.mark.property_test
def test_scan_flow_with_partial_data():
    """read_scan_data can return shorter data (end of scan signal)."""
    proto = FakeCoolscanProtocol()
    partial_data = b"\xAB" * 32
    proto.set_response("read_scan_data", partial_data)

    data = proto.read_scan_data(64, DataType.IMAGE_DATA)
    assert len(data) == 32
    assert data == partial_data
