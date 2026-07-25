#!/usr/bin/env python3
"""
Fixture-independent tests for CoolscanScanner.

Uses a spec'd MagicMock of CoolscanProtocol to test the scanner layer in
isolation from USB hardware and capture replays.  No golden fixtures, no
pcapng captures.

Run with: python -m pytest tests/test_scanner.py -v
"""

import pytest
from unittest.mock import patch

import numpy as np

from coolscan.device import InterfaceType, ScannerDevice
from coolscan.protocol import ScanParameters, ScannerInfo
from coolscan.scanner import (
    LS40_CHANNEL_OFFSETS,
    _parse_scan_data,
    CoolscanScanner,
    auto_focus_scanner,
    get_scanner_info,
    prescan_scanner,
)
from tests.fakes import configure_mock, make_protocol_mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(**kwargs) -> ScannerDevice:
    """Create a minimal ScannerDevice for testing."""
    defaults = dict(
        name="test",
        interface=InterfaceType.USB,
        vendor="Nikon",
        model="LS-40 ED",
        revision="1.20",
        device_path="/dev/usb/scanner0",
        vendor_id=0x04B0,
        product_id=0x4000,
    )
    defaults.update(kwargs)
    return ScannerDevice(**defaults)


def _make_info(**kwargs) -> ScannerInfo:
    """Create a ScannerInfo for testing."""
    defaults = dict(
        ad_bits=14,
        output_bits=14,
        max_resolution=4000,
        x_max_pixels=2592,
        y_max_pixels=3888,
        auto_feeder=0,
        analog_gamma=1,
        device_errors=[0] * 8,
    )
    defaults.update(kwargs)
    return ScannerInfo(**defaults)


def _mock_with_info():
    """Create a mock that returns a ScannerInfo on get_internal_info."""
    mock = make_protocol_mock()
    mock.get_internal_info.return_value = _make_info()
    return mock


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerInit:
    """Test CoolscanScanner initialization."""

    def test_init_sets_device(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        assert scanner.device is device
        assert scanner.protocol is None
        assert scanner.is_connected is False
        assert scanner.scan_in_progress is False
        assert scanner.scanner_info is None


# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerConnect:
    """Test connection functionality using mocked protocol."""

    def test_connect_success(self):
        device = _make_device()
        mock = _mock_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            scanner = CoolscanScanner(device)
            result = scanner.connect()

        assert result is True
        assert scanner.is_connected is True
        assert scanner.protocol is mock
        # connect() no longer calls get_internal_info() to avoid extra
        # traffic after initialization; scanner_info stays None until set.
        assert scanner.scanner_info is None
        assert mock.initialize_scanner.call_count == 1
        assert mock.get_internal_info.call_count == 0

    def test_connect_init_fails(self):
        device = _make_device()
        mock = make_protocol_mock()
        mock.initialize_scanner.return_value = False

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            scanner = CoolscanScanner(device)
            result = scanner.connect()

        assert result is False
        assert scanner.is_connected is False

    def test_connect_exception(self):
        device = _make_device()

        with patch(
            "coolscan.scanner.CoolscanProtocol",
            side_effect=Exception("USB error"),
        ):
            scanner = CoolscanScanner(device)
            result = scanner.connect()

        assert result is False
        assert scanner.is_connected is False


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerDisconnect:
    """Test disconnection functionality."""

    def test_disconnect_releases_unit(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = _mock_with_info()
        scanner.protocol = mock
        scanner.is_connected = True
        scanner.scanner_info = _make_info()

        scanner.disconnect()

        assert mock.release_unit.call_count == 1
        assert mock.close.call_count == 1
        assert scanner.protocol is None
        assert scanner.is_connected is False
        assert scanner.scanner_info is None

    def test_disconnect_cancels_scan_in_progress(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        scanner.protocol = mock
        scanner.is_connected = True
        scanner.scan_in_progress = True

        scanner.disconnect()

        assert mock.cancel_scan.call_count == 1

    def test_disconnect_handles_release_error(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.release_unit.side_effect = Exception("Release failed")
        scanner.protocol = mock
        scanner.is_connected = True

        scanner.disconnect()  # Should not raise

        assert scanner.is_connected is False

    def test_disconnect_no_protocol(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        scanner.disconnect()  # Should not raise

        assert scanner.is_connected is False


# ---------------------------------------------------------------------------
# Device Info
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerGetDeviceInfo:
    """Test device info retrieval."""

    def test_get_device_info_not_connected(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.get_device_info()

    def test_get_device_info_uses_device_descriptor(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()

        scanner.is_connected = True
        scanner.protocol = mock
        scanner.scanner_info = _make_info()

        info = scanner.get_device_info()

        assert info["vendor"] == "Nikon"
        assert info["product"] == "LS-40 ED"
        assert info["revision"] == "1.20"
        assert info["ad_bits"] == 14
        assert info["max_resolution"] == 4000
        # get_device_info() no longer issues an INQUIRY; it uses cached
        # descriptor info from the ScannerDevice.
        assert mock.inquiry.call_count == 0

    def test_get_device_info_without_scanner_info(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()

        scanner.is_connected = True
        scanner.protocol = mock

        info = scanner.get_device_info()

        assert info["vendor"] == "Nikon"
        assert info["product"] == "LS-40 ED"
        assert "ad_bits" not in info


# ---------------------------------------------------------------------------
# Prescan
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerPrescan:
    """Test prescan functionality."""

    def test_prescan_not_connected(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.prescan()

    def test_prescan_already_in_progress(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.scan_in_progress = True

        with pytest.raises(RuntimeError, match="Scan already in progress"):
            scanner.prescan()

    def test_prescan_success(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        scanner.is_connected = True
        scanner.protocol = mock

        result = scanner.prescan()

        assert result is True
        assert mock.prescan.call_count == 1
        assert mock.reserve_unit.call_count == 0
        assert mock.release_unit.call_count == 0

    def test_prescan_failure(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.prescan.return_value = False
        scanner.is_connected = True
        scanner.protocol = mock

        result = scanner.prescan()

        assert result is False
        assert mock.prescan.call_count == 1

    def test_prescan_handles_error(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.prescan.side_effect = Exception("Prescan error")

        scanner.is_connected = True
        scanner.protocol = mock

        result = scanner.prescan()

        assert result is False


# ---------------------------------------------------------------------------
# Auto Focus
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerAutoFocus:
    """Test auto focus functionality."""

    def test_auto_focus_not_connected(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.auto_focus()

    def test_auto_focus_success(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.auto_focus.return_value = 42
        scanner.is_connected = True
        scanner.protocol = mock

        result = scanner.auto_focus()

        assert result == 42  # Scanner returns protocol's int result directly
        assert mock.auto_focus.call_count == 1

    def test_auto_focus_failure(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.auto_focus.return_value = None
        scanner.is_connected = True
        scanner.protocol = mock

        result = scanner.auto_focus()

        assert not result  # None is falsy


# ---------------------------------------------------------------------------
# Cancel Scan
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerCancelScan:
    """Test scan cancellation."""

    def test_cancel_no_scan_in_progress(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        scanner.scan_in_progress = False

        result = scanner.cancel_scan()

        assert result is True

    def test_cancel_success(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        scanner.protocol = mock
        scanner.scan_in_progress = True

        result = scanner.cancel_scan()

        assert result is True
        assert scanner.scan_in_progress is False
        assert mock.cancel_scan.call_count == 1

    def test_cancel_fails(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.cancel_scan.return_value = False
        scanner.protocol = mock
        scanner.scan_in_progress = True

        result = scanner.cancel_scan()

        assert result is False
        assert scanner.scan_in_progress is True  # Stays True on failure


# ---------------------------------------------------------------------------
# Wait For Ready
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerWaitForReady:
    """Test wait for ready functionality."""

    def test_wait_not_connected(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        result = scanner.wait_for_ready()

        assert result is False

    def test_wait_success(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        scanner.is_connected = True
        scanner.protocol = mock

        result = scanner.wait_for_ready(timeout=60)

        assert result is True
        assert mock.scanner_ready.call_count == 1
        mock.scanner_ready.assert_called_with(timeout=60)


# ---------------------------------------------------------------------------
# Scanner Status
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerGetStatus:
    """Test status retrieval."""

    def test_status_disconnected(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        status = scanner.get_scanner_status()

        assert status["status"] == "disconnected"

    def test_status_ready(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        scanner.is_connected = True
        scanner.protocol = mock
        scanner.scanner_info = _make_info()

        status = scanner.get_scanner_status()

        assert status["status"] == "ready"
        assert status["scan_in_progress"] is False
        assert status["scanner_info"] is not None

    def test_status_not_ready(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.test_unit_ready.return_value = False
        scanner.is_connected = True
        scanner.protocol = mock

        status = scanner.get_scanner_status()

        assert status["status"] == "not_ready"

    def test_status_error(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.test_unit_ready.side_effect = Exception("Test error")

        scanner.is_connected = True
        scanner.protocol = mock

        status = scanner.get_scanner_status()

        assert status["status"] == "error"
        assert "error" in status


# ---------------------------------------------------------------------------
# Context Manager
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerContextManager:
    """Test context manager functionality."""

    def test_context_manager_connects(self):
        device = _make_device()
        mock = _mock_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            with CoolscanScanner(device) as scanner:
                assert scanner.is_connected is True

    def test_context_manager_disconnects(self):
        device = _make_device()
        mock = _mock_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            with CoolscanScanner(device) as scanner:
                pass

        assert mock.release_unit.call_count >= 1
        assert mock.close.call_count >= 1

    def test_context_manager_connect_fails(self):
        device = _make_device()
        mock = make_protocol_mock()
        mock.initialize_scanner.return_value = False

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            with pytest.raises(RuntimeError, match="Failed to connect"):
                with CoolscanScanner(device):
                    pass


# ---------------------------------------------------------------------------
# Scan Preview / Full / Area
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCoolscanScannerScanPreview:
    """Test preview scan functionality."""

    def test_scan_preview_not_connected(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.scan_preview("/tmp/test.png")

    def test_scan_preview_creates_params(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.full_scan_frame.return_value = False
        scanner.is_connected = True
        scanner.protocol = mock

        scanner.scan_preview("/tmp/test.png", resolution=300)

        calls = mock.full_scan_frame.call_args_list
        assert len(calls) == 1
        params = calls[0][0][0]  # positional arg
        assert params.resolution == 300
        assert params.preview is True

    def test_scan_preview_scan_in_progress(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.scan_in_progress = True

        with pytest.raises(RuntimeError, match="Scan already in progress"):
            scanner.scan_preview("/tmp/test.png")


@pytest.mark.property_test
class TestCoolscanScannerScanFull:
    """Test full scan functionality."""

    def test_scan_full_not_connected(self):
        device = _make_device()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.scan_full("/tmp/test.png")

    def test_scan_full_creates_params(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.full_scan_frame.return_value = False
        scanner.is_connected = True
        scanner.protocol = mock

        scanner.scan_full(
            "/tmp/test.png", resolution=2700, negative=True, infrared=True
        )

        calls = mock.full_scan_frame.call_args_list
        assert len(calls) == 1
        params = calls[0][0][0]  # positional arg
        assert params.resolution == 2700
        assert params.negative is True
        assert params.infrared is True
        assert params.preview is False


@pytest.mark.property_test
class TestCoolscanScannerScanArea:
    """Test area scan functionality."""

    def test_scan_area_creates_params(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        mock = make_protocol_mock()
        mock.full_scan_frame.return_value = False
        scanner.is_connected = True
        scanner.protocol = mock

        scanner.scan_area("/tmp/test.png", 100, 200, 300, 400, resolution=1500)

        calls = mock.full_scan_frame.call_args_list
        assert len(calls) == 1
        params = calls[0][0][0]  # positional arg
        assert params.resolution == 1500
        assert params.x_min == 100
        assert params.y_min == 200
        assert params.x_max == 300
        assert params.y_max == 400


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_prescan_scanner(self):
        device = _make_device()
        mock = _mock_with_info()
        mock.prescan.return_value = True

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            result = prescan_scanner(device)

        assert result is True
        assert mock.prescan.call_count == 1

    def test_auto_focus_scanner(self):
        device = _make_device()
        mock = _mock_with_info()
        mock.auto_focus.return_value = 42

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            result = auto_focus_scanner(device)

        assert result == 42  # Returns protocol's int result
        assert mock.auto_focus.call_count == 1

    def test_get_scanner_info(self):
        device = _make_device()
        mock = _mock_with_info()

        inquiry_data = bytearray(36)
        inquiry_data[8:16] = b"Nikon   "
        mock.inquiry.return_value = inquiry_data

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            result = get_scanner_info(device)

        assert result is not None
        assert "vendor" in result


# ---------------------------------------------------------------------------
# _parse_scan_data
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestParseScanData:
    """Test _parse_scan_data with channel_offsets for trilinear-CCD alignment."""

    def _make_plane_data(self, width, height, num_channels, pattern=None):
        """Create synthetic plane-interleaved scan data."""
        if pattern is None:
            np.random.seed(42)
            pattern = np.random.randint(
                0, 256, (height, width, num_channels), dtype=np.uint8
            )
        data = bytearray()
        for y in range(height):
            for ch in range(num_channels):
                data.extend(pattern[y, :, ch].tobytes())
        return data, pattern

    def test_plane_no_offset(self):
        """Plane-interleaved with zero offsets produces correct output."""
        width, height = 64, 32
        data, expected = self._make_plane_data(width, height, 3)

        result, trailing = _parse_scan_data(data, width, height, 3, 8, "plane", (0, 0, 0))

        np.testing.assert_array_equal(result, expected)
        assert trailing == 0

    def test_plane_positive_offset_shifts_right(self):
        """Positive channel offset shifts the channel right (delays it)."""
        width, height = 64, 4
        pattern = np.zeros((height, width, 3), dtype=np.uint8)
        for ch in range(3):
            pattern[:, 10, ch] = 100 + ch * 50

        data, _ = self._make_plane_data(width, height, 3, pattern)

        result, _ = _parse_scan_data(data, width, height, 3, 8, "plane", (0, 5, 0))

        assert result[0, 10, 0] == 100  # R unchanged
        assert result[0, 15, 1] == 150  # G shifted right by 5
        assert result[0, 10, 2] == 200  # B unchanged
        assert result[0, 0, 1] == 0  # First 5 pixels of G are zero

    def test_plane_negative_offset_shifts_left(self):
        """Negative channel offset shifts the channel left (advances it)."""
        width, height = 64, 4
        pattern = np.zeros((height, width, 3), dtype=np.uint8)
        for ch in range(3):
            pattern[:, 10, ch] = 100 + ch * 50

        data, _ = self._make_plane_data(width, height, 3, pattern)

        result, _ = _parse_scan_data(data, width, height, 3, 8, "plane", (0, 0, -5))

        assert result[0, 10, 0] == 100  # R unchanged
        assert result[0, 10, 1] == 150  # G unchanged
        assert result[0, 5, 2] == 200  # B shifted left by 5
        assert result[0, 63, 2] == 0  # Last 5 pixels of B are zero

    def test_ls40_channel_offsets(self):
        """LS-40 ED decode-time workaround offsets: R=0, G=+10, B=+20."""
        width, height = 128, 8
        pattern = np.zeros((height, width, 3), dtype=np.uint8)
        for ch in range(3):
            pattern[:, 50:, ch] = 200

        data, _ = self._make_plane_data(width, height, 3, pattern)

        result, _ = _parse_scan_data(
            data, width, height, 3, 8, "plane", LS40_CHANNEL_OFFSETS
        )

        assert result[0, 49, 0] == 0
        assert result[0, 50, 0] == 200  # R edge at col 50
        assert result[0, 59, 1] == 0
        assert result[0, 60, 1] == 200  # G edge at col 60
        assert result[0, 69, 2] == 0
        assert result[0, 70, 2] == 200  # B edge at col 70

    def test_pixel_format_unchanged(self):
        """Pixel-interleaved format ignores channel_offsets."""
        width, height = 16, 8
        np.random.seed(99)
        raw = np.random.randint(0, 256, height * width * 3, dtype=np.uint8)
        data = bytearray(raw)

        result, _ = _parse_scan_data(
            data, width, height, 3, 8, "pixel", LS40_CHANNEL_OFFSETS
        )

        expected = raw[: height * width * 3].reshape((height, width, 3))
        np.testing.assert_array_equal(result, expected)

    def test_12bit_depth(self):
        """12-bit depth preserves full uint16 values without shifting."""
        width, height = 4, 2
        # Scanner sends 12-bit values in big-endian uint16.
        # Values are preserved as-is (no >>4 shift).
        # 0x0ABC stays as 2748, 0x0123 stays as 291
        data = bytearray()
        data.extend(b"\x0A\xBC")  # 0x0ABC -> 2748
        data.extend(b"\x01\x23")  # 0x0123 -> 291
        total_samples = height * width * 3
        data.extend(b"\x00\x00" * (total_samples - 2))

        result, _ = _parse_scan_data(data, width, height, 3, 12, "pixel", (0, 0, 0))

        assert result[0, 0, 0] == 0x0ABC
        assert result[0, 0, 1] == 0x0123
        assert result.dtype == np.uint16


# ---------------------------------------------------------------------------
# MagicMock protocol defaults verification
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestMagicMockProtocolDefaults:
    """Verify the mock protocol returns sensible defaults."""

    def test_default_bool_true(self):
        mock = make_protocol_mock()
        assert mock.initialize_scanner() is True
        assert mock.reserve_unit() is True

    def test_default_bytes_empty(self):
        mock = make_protocol_mock()
        assert mock.read_scan_data(100) == b""

    def test_records_calls(self):
        mock = make_protocol_mock()
        mock.prescan()
        mock.prescan()

        assert mock.prescan.call_count == 2
        assert len(mock.mock_calls) == 2

    def test_custom_response(self):
        mock = make_protocol_mock()
        mock.prescan.return_value = False
        assert mock.prescan() is False

    def test_call_args_preserved(self):
        mock = make_protocol_mock()
        mock.scanner_ready(timeout=45)

        assert mock.scanner_ready.call_count == 1
        mock.scanner_ready.assert_called_with(timeout=45)

    def test_reset_mock_clears(self):
        mock = make_protocol_mock()
        mock.prescan()
        mock.reset_mock()

        assert mock.prescan.call_count == 0
        assert len(mock.mock_calls) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
