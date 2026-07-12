"""Integration tests for CoolscanScanner full scan flows.

Exercises the scanner layer with FakeCoolscanProtocol to verify end-to-end
sequences: connect → prescan → scan → teardown, plus error injection and
state cleanup.

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from coolscan.device import InterfaceType, ScannerDevice
from coolscan.protocol import DataType, ScanParameters, ScannerInfo
from coolscan.scanner import CoolscanScanner, _parse_scan_data
from tests.fakes import configure_failure, configure_mock, make_protocol_mock


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
# Full scan flow
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestFullScanFlow:
    """End-to-end scan flow with mocked protocol."""

    def test_prescan_flow(self):
        """connect → prescan → verify protocol calls."""
        device = _make_device()
        mock = _mock_with_info()
        mock.prescan.return_value = True

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            scanner = CoolscanScanner(device)
            scanner.connect()
            result = scanner.prescan()

        assert result is True
        assert mock.prescan.call_count == 1
        scanner.disconnect()

    def test_prescan_failure(self):
        """prescan returns False when protocol fails."""
        device = _make_device()
        mock = _mock_with_info()
        mock.prescan.return_value = False

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            scanner = CoolscanScanner(device)
            scanner.connect()
            result = scanner.prescan()

        assert result is False
        scanner.disconnect()

    def test_full_scan_happy_path(self):
        """connect → scan_full → image saved successfully."""
        device = _make_device()
        mock = _mock_with_info()
        mock.full_scan_frame.return_value = True

        # Generate valid 3-channel plane-interleaved data for 4x4 image
        width, height, channels = 4, 4, 3
        total_bytes = width * height * channels  # 48 bytes
        scan_data = bytearray(range(total_bytes))
        mock.read_scan_data.return_value = bytes(scan_data)

        scanner_info = _make_info(x_max_pixels=width, y_max_pixels=height)
        mock.get_internal_info.return_value = scanner_info

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            scanner = CoolscanScanner(device)
            scanner.connect()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                output_path = f.name

            # Use low resolution so width/height come from scanner_info
            result = scanner.scan_full(output_path, resolution=270, format="plane",
                                       channel_offsets=(0, 0, 0))

        assert result is True
        assert scanner.scan_in_progress is False
        assert Path(output_path).exists()
        assert mock.full_scan_frame.call_count == 1
        assert mock.read_scan_data.call_count >= 1
        scanner.disconnect()

    def test_scan_failure_clears_in_progress(self):
        """scan_full fails when full_scan_frame returns False; state is clean."""
        device = _make_device()
        mock = _mock_with_info()
        mock.full_scan_frame.return_value = False  # Fails before scan_in_progress is set

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            scanner = CoolscanScanner(device)
            scanner.connect()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                output_path = f.name

            result = scanner.scan_full(output_path)

        assert result is False
        assert scanner.scan_in_progress is False
        scanner.disconnect()


# ---------------------------------------------------------------------------
# Error injection
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestErrorInjection:
    """Configure protocol to fail at specific points."""

    def test_prescan_after_failed_init(self):
        """prescan raises RuntimeError when scanner not connected."""
        device = _make_device()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.prescan()

    def test_scan_after_failed_init(self):
        """scan_full raises RuntimeError when scanner not connected."""
        device = _make_device()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.scan_full("/tmp/test.png")

    def test_double_scan_raises(self):
        """Second scan while first in progress raises RuntimeError."""
        device = _make_device()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.scan_in_progress = True

        with pytest.raises(RuntimeError, match="Scan already in progress"):
            scanner.scan_full("/tmp/test.png")

    def test_disconnect_cancels_in_progress_scan(self):
        """disconnect() calls cancel_scan() if scan_in_progress."""
        device = _make_device()
        mock = _mock_with_info()
        mock.cancel_scan.return_value = True

        scanner = CoolscanScanner(device)
        scanner.protocol = mock
        scanner.is_connected = True
        scanner.scan_in_progress = True

        scanner.disconnect()

        assert mock.cancel_scan.call_count == 1
        assert scanner.scan_in_progress is False
        assert scanner.is_connected is False


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestContextManager:
    """Context manager cleanup on success and exception."""

    def test_context_manager_success(self):
        """Context manager connects and disconnects cleanly."""
        device = _make_device()
        mock = _mock_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            with CoolscanScanner(device) as scanner:
                assert scanner.is_connected is True
                assert scanner.protocol is mock

        assert scanner.is_connected is False
        assert scanner.protocol is None
        assert mock.close.call_count == 1

    def test_context_manager_exception_cleanup(self):
        """Context manager disconnects even when body raises."""
        device = _make_device()
        mock = _mock_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            with pytest.raises(ValueError):
                with CoolscanScanner(device) as scanner:
                    assert scanner.is_connected is True
                    raise ValueError("test error")

        assert scanner.is_connected is False
        assert scanner.protocol is None
        assert mock.close.call_count == 1

    def test_context_manager_failed_connect(self):
        """Context manager raises when connect fails."""
        device = _make_device()
        mock = make_protocol_mock()
        mock.initialize_scanner.return_value = False

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            with pytest.raises(RuntimeError, match="Failed to connect"):
                with CoolscanScanner(device):
                    pass


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestStateManagement:
    """Scanner state transitions and cleanup."""

    def test_init_state(self):
        """Fresh scanner has correct initial state."""
        device = _make_device()
        scanner = CoolscanScanner(device)

        assert scanner.protocol is None
        assert scanner.is_connected is False
        assert scanner.scan_in_progress is False
        assert scanner.scanner_info is None

    def test_connect_sets_state(self):
        """connect() sets is_connected and scanner_info."""
        device = _make_device()
        mock = _mock_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            scanner = CoolscanScanner(device)
            scanner.connect()

        assert scanner.is_connected is True
        assert scanner.protocol is mock
        # connect() intentionally leaves scanner_info unset to avoid extra
        # command traffic after initialization.
        assert scanner.scanner_info is None

    def test_disconnect_resets_state(self):
        """disconnect() resets all state."""
        device = _make_device()
        mock = _mock_with_info()

        with patch("coolscan.scanner.CoolscanProtocol", return_value=mock):
            scanner = CoolscanScanner(device)
            scanner.connect()
            scanner.disconnect()

        assert scanner.protocol is None
        assert scanner.is_connected is False
        assert scanner.scan_in_progress is False
        assert scanner.scanner_info is None

    def test_disconnect_without_connect(self):
        """disconnect() is safe to call when not connected."""
        device = _make_device()
        scanner = CoolscanScanner(device)

        # Should not raise
        scanner.disconnect()

        assert scanner.is_connected is False
