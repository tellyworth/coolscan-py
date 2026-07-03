#!/usr/bin/env python3
"""
Fixture-independent tests for CoolscanScanner.

Uses FakeCoolscanProtocol to test the scanner layer in isolation from USB
hardware and capture replays.  No golden fixtures, no pcapng captures.

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
from tests.fakes import FakeCoolscanProtocol


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


def _fake_with_info() -> FakeCoolscanProtocol:
    """Create a fake that returns a ScannerInfo on get_internal_info."""
    fake = FakeCoolscanProtocol()
    fake.set_response("get_internal_info", _make_info())
    return fake


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
    """Test connection functionality using FakeCoolscanProtocol."""

    def test_connect_success(self):
        device = _make_device()
        fake = _fake_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=fake):
            scanner = CoolscanScanner(device)
            result = scanner.connect()

        assert result is True
        assert scanner.is_connected is True
        assert scanner.protocol is fake
        assert scanner.scanner_info is not None
        assert fake.call_count("initialize_scanner") == 1
        assert fake.call_count("get_internal_info") == 1

    def test_connect_init_fails(self):
        device = _make_device()
        fake = FakeCoolscanProtocol()
        fake.set_response("initialize_scanner", False)

        with patch("coolscan.scanner.CoolscanProtocol", return_value=fake):
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
        fake = _fake_with_info()
        scanner.protocol = fake
        scanner.is_connected = True
        scanner.scanner_info = _make_info()

        scanner.disconnect()

        assert fake.call_count("release_unit") == 1
        assert fake.call_count("close") == 1
        assert scanner.protocol is None
        assert scanner.is_connected is False
        assert scanner.scanner_info is None

    def test_disconnect_cancels_scan_in_progress(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()
        scanner.protocol = fake
        scanner.is_connected = True
        scanner.scan_in_progress = True

        scanner.disconnect()

        assert fake.call_count("cancel_scan") == 1

    def test_disconnect_handles_release_error(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()
        fake.set_response("release_unit", None)
        # Make release_unit raise
        orig_release = fake.release_unit

        def raise_release():
            raise Exception("Release failed")

        fake.release_unit = raise_release
        scanner.protocol = fake
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

    def test_get_device_info_with_inquiry(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()

        inquiry_data = bytearray(36)
        inquiry_data[8:16] = b"Nikon   "
        inquiry_data[16:32] = b"LS-40 ED        "
        inquiry_data[32:36] = b"1.20"
        fake.set_response("inquiry", inquiry_data)

        scanner.is_connected = True
        scanner.protocol = fake
        scanner.scanner_info = _make_info()

        info = scanner.get_device_info()

        assert info["vendor"] == "Nikon"
        assert info["product"] == "LS-40 ED"
        assert info["revision"] == "1.20"
        assert info["ad_bits"] == 14
        assert info["max_resolution"] == 4000
        assert fake.call_count("inquiry") == 1

    def test_get_device_info_short_inquiry(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()
        fake.set_response("inquiry", bytearray(10))

        scanner.is_connected = True
        scanner.protocol = fake

        info = scanner.get_device_info()

        assert info["vendor"] == "Nikon"
        assert info["product"] == "LS-40 ED"

    def test_get_device_info_inquiry_error(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()

        def raise_inquiry(*a, **k):
            raise Exception("Inquiry failed")

        fake.inquiry = raise_inquiry

        scanner.is_connected = True
        scanner.protocol = fake

        info = scanner.get_device_info()

        assert "error" in info
        assert info["vendor"] == "Nikon"


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
        fake = FakeCoolscanProtocol()
        scanner.is_connected = True
        scanner.protocol = fake

        result = scanner.prescan()

        assert result is True
        assert fake.call_count("prescan") == 1
        assert fake.call_count("reserve_unit") == 0
        assert fake.call_count("release_unit") == 0

    def test_prescan_failure(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()
        fake.set_response("prescan", False)
        scanner.is_connected = True
        scanner.protocol = fake

        result = scanner.prescan()

        assert result is False
        assert fake.call_count("prescan") == 1

    def test_prescan_handles_error(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()

        def raise_prescan(*a, **k):
            raise Exception("Prescan error")

        fake.prescan = raise_prescan

        scanner.is_connected = True
        scanner.protocol = fake

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
        fake = FakeCoolscanProtocol()
        fake.set_response("auto_focus", 42)
        scanner.is_connected = True
        scanner.protocol = fake

        result = scanner.auto_focus()

        assert result == 42  # Scanner returns protocol's int result directly
        assert fake.call_count("auto_focus") == 1

    def test_auto_focus_failure(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()
        fake.set_response("auto_focus", None)
        scanner.is_connected = True
        scanner.protocol = fake

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
        fake = FakeCoolscanProtocol()
        scanner.protocol = fake
        scanner.scan_in_progress = True

        result = scanner.cancel_scan()

        assert result is True
        assert scanner.scan_in_progress is False
        assert fake.call_count("cancel_scan") == 1

    def test_cancel_fails(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()
        fake.set_response("cancel_scan", False)
        scanner.protocol = fake
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
        fake = FakeCoolscanProtocol()
        scanner.is_connected = True
        scanner.protocol = fake

        result = scanner.wait_for_ready(timeout=60)

        assert result is True
        calls = fake.calls_to("scanner_ready")
        assert len(calls) == 1
        assert calls[0][0][0] == 60


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
        fake = FakeCoolscanProtocol()
        scanner.is_connected = True
        scanner.protocol = fake
        scanner.scanner_info = _make_info()

        status = scanner.get_scanner_status()

        assert status["status"] == "ready"
        assert status["scan_in_progress"] is False
        assert status["scanner_info"] is not None

    def test_status_not_ready(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()
        fake.set_response("test_unit_ready", False)
        scanner.is_connected = True
        scanner.protocol = fake

        status = scanner.get_scanner_status()

        assert status["status"] == "not_ready"

    def test_status_error(self):
        device = _make_device()
        scanner = CoolscanScanner(device)
        fake = FakeCoolscanProtocol()

        def raise_tur(*a, **k):
            raise Exception("Test error")

        fake.test_unit_ready = raise_tur

        scanner.is_connected = True
        scanner.protocol = fake

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
        fake = _fake_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=fake):
            with CoolscanScanner(device) as scanner:
                assert scanner.is_connected is True

    def test_context_manager_disconnects(self):
        device = _make_device()
        fake = _fake_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=fake):
            with CoolscanScanner(device) as scanner:
                pass

        assert fake.call_count("release_unit") >= 1
        assert fake.call_count("close") >= 1

    def test_context_manager_connect_fails(self):
        device = _make_device()
        fake = FakeCoolscanProtocol()
        fake.set_response("initialize_scanner", False)

        with patch("coolscan.scanner.CoolscanProtocol", return_value=fake):
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
        fake = FakeCoolscanProtocol()
        fake.set_response("full_scan_frame", False)
        scanner.is_connected = True
        scanner.protocol = fake

        scanner.scan_preview("/tmp/test.png", resolution=300)

        calls = fake.calls_to("full_scan_frame")
        assert len(calls) == 1
        params = calls[0][1]["params"]
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
        fake = FakeCoolscanProtocol()
        fake.set_response("full_scan_frame", False)
        scanner.is_connected = True
        scanner.protocol = fake

        scanner.scan_full(
            "/tmp/test.png", resolution=2700, negative=True, infrared=True
        )

        calls = fake.calls_to("full_scan_frame")
        assert len(calls) == 1
        params = calls[0][1]["params"]
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
        fake = FakeCoolscanProtocol()
        fake.set_response("full_scan_frame", False)
        scanner.is_connected = True
        scanner.protocol = fake

        scanner.scan_area("/tmp/test.png", 100, 200, 300, 400, resolution=1500)

        calls = fake.calls_to("full_scan_frame")
        assert len(calls) == 1
        params = calls[0][1]["params"]
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
        fake = _fake_with_info()
        fake.set_response("prescan", True)

        with patch("coolscan.scanner.CoolscanProtocol", return_value=fake):
            result = prescan_scanner(device)

        assert result is True
        assert fake.call_count("prescan") == 1

    def test_auto_focus_scanner(self):
        device = _make_device()
        fake = _fake_with_info()
        fake.set_response("auto_focus", 42)

        with patch("coolscan.scanner.CoolscanProtocol", return_value=fake):
            result = auto_focus_scanner(device)

        assert result == 42  # Returns protocol's int result
        assert fake.call_count("auto_focus") == 1

    def test_get_scanner_info(self):
        device = _make_device()
        fake = _fake_with_info()

        inquiry_data = bytearray(36)
        inquiry_data[8:16] = b"Nikon   "
        fake.set_response("inquiry", inquiry_data)

        with patch("coolscan.scanner.CoolscanProtocol", return_value=fake):
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
        """12-bit depth: >>4 then uint8 extracts middle 8 bits of 12-bit value."""
        width, height = 4, 2
        # Scanner sends 12-bit values in top 12 bits of big-endian uint16.
        # >>4 then uint8 extracts bits 11..4 (the "middle" byte).
        # 0x0ABC >> 4 = 0x0AB -> uint8 = 0xAB
        # 0x0123 >> 4 = 0x012 -> uint8 = 0x12
        data = bytearray()
        data.extend(b"\x0A\xBC")  # 0x0ABC -> 0xAB
        data.extend(b"\x01\x23")  # 0x0123 -> 0x12
        total_samples = height * width * 3
        data.extend(b"\x00\x00" * (total_samples - 2))

        result, _ = _parse_scan_data(data, width, height, 3, 12, "pixel", (0, 0, 0))

        assert result[0, 0, 0] == 0xAB
        assert result[0, 0, 1] == 0x12


# ---------------------------------------------------------------------------
# FakeCoolscanProtocol self-tests
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestFakeCoolscanProtocol:
    """Verify the fake itself works as expected."""

    def test_records_calls(self):
        fake = FakeCoolscanProtocol()
        fake.prescan()
        fake.prescan()

        assert fake.call_count("prescan") == 2
        assert len(fake.call_log) == 2

    def test_custom_response(self):
        fake = FakeCoolscanProtocol()
        fake.set_response("prescan", False)

        assert fake.prescan() is False

    def test_default_bool_true(self):
        fake = FakeCoolscanProtocol()
        assert fake.initialize_scanner() is True
        assert fake.reserve_unit() is True

    def test_default_bytes_empty(self):
        fake = FakeCoolscanProtocol()
        assert fake.read_scan_data(100) == b""

    def test_call_log_preserves_args(self):
        fake = FakeCoolscanProtocol()
        fake.scanner_ready(timeout=45)

        calls = fake.calls_to("scanner_ready")
        assert len(calls) == 1
        assert calls[0][0][0] == 45

    def test_clear_log(self):
        fake = FakeCoolscanProtocol()
        fake.prescan()
        fake.clear_log()

        assert fake.call_log == []
        assert fake.call_count("prescan") == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
