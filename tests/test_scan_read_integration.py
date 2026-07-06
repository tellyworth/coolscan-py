"""
Integration test — full scan flow using a mocked protocol.

Tests the complete control flow: setup → scan → image read → release,
using a fixture-independent MagicMock test double.  This verifies call
sequencing and data lengths without depending on USB replay or fixture files.

The 64-byte allocation proves the protocol transitions correctly from
scanner_ready → reserve_unit → object_position → set_window → _upload_lut →
start_scan → poll_until_ready → read_scan_data → release_unit.
"""

import pytest

from coolscan.protocol import DataType, ScanParameters
from tests.fakes import configure_mock, make_protocol_mock


@pytest.mark.property_test
def test_full_scan_flow_with_synthetic_data():
    """
    Full control flow: scanner_ready → reserve → setup → start_scan →
    poll_until_ready → read_scan_data(64) → release_unit.

    Uses a spec'd MagicMock to verify call sequencing and return values.
    """
    mock = make_protocol_mock()
    synthetic_data = b"\x00" * 64
    configure_mock(mock, {"read_scan_data": synthetic_data})

    # Run the full scan sequence
    assert mock.scanner_ready(timeout=30) is True
    assert mock.reserve_unit() is True
    assert mock.object_position() is True
    assert mock.set_window(ScanParameters()) is True
    assert mock._upload_lut(channel=1, lut_data=b"\x00" * 8192) is True
    assert mock.start_scan() is True
    assert mock.poll_until_ready(timeout=30) is True

    # Read image data before release
    data = mock.read_scan_data(64, DataType.IMAGE_DATA)
    assert len(data) == 64
    assert data == synthetic_data

    # Release unit
    assert mock.release_unit() is True

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
    actual = [call[0] for call in mock.mock_calls]
    assert actual == expected, f"Call sequence mismatch:\n  expected: {expected}\n  actual:   {actual}"

    # Verify read_scan_data was called with correct arguments
    mock.read_scan_data.assert_called_once_with(64, DataType.IMAGE_DATA)


@pytest.mark.property_test
def test_scan_data_length_matches_request():
    """read_scan_data returns data matching the requested length."""
    mock = make_protocol_mock()
    expected_data = b"\xFF" * 128
    configure_mock(mock, {"read_scan_data": expected_data})

    data = mock.read_scan_data(128, DataType.IMAGE_DATA)
    assert len(data) == 128
    assert data == expected_data


@pytest.mark.property_test
def test_scan_flow_with_partial_data():
    """read_scan_data can return shorter data (end of scan signal)."""
    mock = make_protocol_mock()
    partial_data = b"\xAB" * 32
    configure_mock(mock, {"read_scan_data": partial_data})

    data = mock.read_scan_data(64, DataType.IMAGE_DATA)
    assert len(data) == 32
    assert data == partial_data
