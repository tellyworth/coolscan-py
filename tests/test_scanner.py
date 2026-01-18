#!/usr/bin/env python3
"""
Unit Tests for CoolscanScanner class

These tests verify the high-level scanner operations work correctly
by mocking the protocol layer.

Run with: python -m pytest tests/test_scanner.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import sys
sys.path.insert(0, '.')

from coolscan.scanner import (
    CoolscanScanner,
    scan_preview,
    scan_full,
    get_scanner_info,
    prescan_scanner,
    auto_focus_scanner
)
from coolscan.protocol import ScanParameters, ScannerInfo, DataType


class MockInterface:
    """Mock interface enum."""
    value = 'usb'


class MockDevice:
    """Mock ScannerDevice for testing."""

    def __init__(self):
        self.vendor = "Nikon"
        self.model = "LS-40 ED"
        self.revision = "1.20"
        self.interface = MockInterface()
        self.device_path = "/dev/usb/scanner0"
        self.vendor_id = 0x04b0
        self.product_id = 0x4000


class MockScannerInfo:
    """Mock ScannerInfo dataclass."""

    def __init__(self):
        self.ad_bits = 14
        self.output_bits = 14
        self.max_resolution = 4000
        self.x_max_pixels = 2592
        self.y_max_pixels = 3888
        self.auto_feeder = 0
        self.analog_gamma = 1
        self.device_errors = 0


class TestCoolscanScannerInit:
    """Test CoolscanScanner initialization."""

    def test_init_sets_device(self):
        """Scanner stores device reference."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        assert scanner.device is device
        assert scanner.protocol is None
        assert scanner.is_connected is False
        assert scanner.scan_in_progress is False
        assert scanner.scanner_info is None


class TestCoolscanScannerConnect:
    """Test connection functionality."""

    @patch('coolscan.scanner.CoolscanProtocol')
    def test_connect_success(self, mock_protocol_class):
        """Successful connection initializes scanner."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        # Setup mock protocol
        mock_protocol = Mock()
        mock_protocol.initialize_scanner.return_value = True
        mock_protocol.get_internal_info.return_value = MockScannerInfo()
        mock_protocol_class.return_value = mock_protocol

        result = scanner.connect()

        assert result is True
        assert scanner.is_connected is True
        assert scanner.protocol is mock_protocol
        assert scanner.scanner_info is not None
        mock_protocol.initialize_scanner.assert_called_once()
        mock_protocol.get_internal_info.assert_called_once()

    @patch('coolscan.scanner.CoolscanProtocol')
    def test_connect_init_fails(self, mock_protocol_class):
        """Connection fails if initialization fails."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        mock_protocol = Mock()
        mock_protocol.initialize_scanner.return_value = False
        mock_protocol_class.return_value = mock_protocol

        result = scanner.connect()

        assert result is False
        assert scanner.is_connected is False

    @patch('coolscan.scanner.CoolscanProtocol')
    def test_connect_exception(self, mock_protocol_class):
        """Connection handles exceptions gracefully."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        mock_protocol_class.side_effect = Exception("USB error")

        result = scanner.connect()

        assert result is False
        assert scanner.is_connected is False


class TestCoolscanScannerDisconnect:
    """Test disconnection functionality."""

    def test_disconnect_releases_unit(self):
        """Disconnect releases scanner unit."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        mock_protocol = Mock()
        scanner.protocol = mock_protocol
        scanner.is_connected = True
        scanner.scanner_info = MockScannerInfo()

        scanner.disconnect()

        mock_protocol.release_unit.assert_called_once()
        mock_protocol.close.assert_called_once()
        assert scanner.protocol is None
        assert scanner.is_connected is False
        assert scanner.scanner_info is None

    def test_disconnect_cancels_scan_in_progress(self):
        """Disconnect cancels any ongoing scan."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        mock_protocol = Mock()
        mock_protocol.cancel_scan.return_value = True
        scanner.protocol = mock_protocol
        scanner.is_connected = True
        scanner.scan_in_progress = True

        scanner.disconnect()

        mock_protocol.cancel_scan.assert_called_once()

    def test_disconnect_handles_release_error(self):
        """Disconnect handles release_unit errors gracefully."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.protocol = Mock()
        scanner.protocol.release_unit.side_effect = Exception("Release failed")
        scanner.is_connected = True

        # Should not raise
        scanner.disconnect()

        assert scanner.is_connected is False

    def test_disconnect_no_protocol(self):
        """Disconnect works even without protocol."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        # Should not raise
        scanner.disconnect()

        assert scanner.is_connected is False


class TestCoolscanScannerGetDeviceInfo:
    """Test device info retrieval."""

    def test_get_device_info_not_connected(self):
        """Get device info raises if not connected."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.get_device_info()

    def test_get_device_info_with_inquiry(self):
        """Get device info parses inquiry data."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.scanner_info = MockScannerInfo()

        # Mock inquiry response (36+ bytes with vendor/product/revision)
        inquiry_data = bytearray(36)
        inquiry_data[8:16] = b'Nikon   '
        inquiry_data[16:32] = b'LS-40 ED        '
        inquiry_data[32:36] = b'1.20'
        scanner.protocol.inquiry.return_value = inquiry_data

        info = scanner.get_device_info()

        assert info['vendor'] == 'Nikon'
        assert info['product'] == 'LS-40 ED'
        assert info['revision'] == '1.20'
        assert info['ad_bits'] == 14
        assert info['max_resolution'] == 4000

    def test_get_device_info_short_inquiry(self):
        """Get device info falls back on short inquiry."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.inquiry.return_value = bytearray(10)  # Too short

        info = scanner.get_device_info()

        assert info['vendor'] == 'Nikon'
        assert info['product'] == 'LS-40 ED'

    def test_get_device_info_inquiry_error(self):
        """Get device info handles inquiry errors."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.inquiry.side_effect = Exception("Inquiry failed")

        info = scanner.get_device_info()

        assert 'error' in info
        assert info['vendor'] == 'Nikon'


class TestCoolscanScannerPrescan:
    """Test prescan functionality."""

    def test_prescan_not_connected(self):
        """Prescan raises if not connected."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.prescan()

    def test_prescan_already_in_progress(self):
        """Prescan raises if scan already in progress."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.scan_in_progress = True

        with pytest.raises(RuntimeError, match="Scan already in progress"):
            scanner.prescan()

    def test_prescan_success(self):
        """Prescan succeeds with correct protocol calls."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.reserve_unit.return_value = True
        scanner.protocol.prescan.return_value = True

        result = scanner.prescan()

        assert result is True
        scanner.protocol.reserve_unit.assert_called_once()
        scanner.protocol.prescan.assert_called_once()
        scanner.protocol.release_unit.assert_called_once()

    def test_prescan_reserve_fails(self):
        """Prescan fails if reserve fails."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.reserve_unit.return_value = False

        result = scanner.prescan()

        assert result is False
        scanner.protocol.prescan.assert_not_called()

    def test_prescan_releases_on_error(self):
        """Prescan releases unit even on error."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.reserve_unit.return_value = True
        scanner.protocol.prescan.side_effect = Exception("Prescan error")

        result = scanner.prescan()

        assert result is False
        scanner.protocol.release_unit.assert_called()


class TestCoolscanScannerAutoFocus:
    """Test auto focus functionality."""

    def test_auto_focus_not_connected(self):
        """Auto focus raises if not connected."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.auto_focus()

    def test_auto_focus_success(self):
        """Auto focus succeeds with correct protocol calls."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.reserve_unit.return_value = True
        scanner.protocol.auto_focus.return_value = True

        result = scanner.auto_focus()

        assert result is True
        scanner.protocol.reserve_unit.assert_called_once()
        scanner.protocol.auto_focus.assert_called_once()
        scanner.protocol.release_unit.assert_called_once()

    def test_auto_focus_reserve_fails(self):
        """Auto focus fails if reserve fails."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.reserve_unit.return_value = False

        result = scanner.auto_focus()

        assert result is False


class TestCoolscanScannerCancelScan:
    """Test scan cancellation."""

    def test_cancel_no_scan_in_progress(self):
        """Cancel returns True if no scan in progress."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.scan_in_progress = False

        result = scanner.cancel_scan()

        assert result is True

    def test_cancel_success(self):
        """Cancel succeeds and clears flag."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.protocol = Mock()
        scanner.protocol.cancel_scan.return_value = True
        scanner.scan_in_progress = True

        result = scanner.cancel_scan()

        assert result is True
        assert scanner.scan_in_progress is False

    def test_cancel_fails(self):
        """Cancel failure keeps flag set."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.protocol = Mock()
        scanner.protocol.cancel_scan.return_value = False
        scanner.scan_in_progress = True

        result = scanner.cancel_scan()

        assert result is False
        # Note: scan_in_progress stays True on failure


class TestCoolscanScannerWaitForReady:
    """Test wait for ready functionality."""

    def test_wait_not_connected(self):
        """Wait returns False if not connected."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        result = scanner.wait_for_ready()

        assert result is False

    def test_wait_success(self):
        """Wait delegates to protocol.scanner_ready."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.scanner_ready.return_value = True

        result = scanner.wait_for_ready(timeout=60)

        assert result is True
        scanner.protocol.scanner_ready.assert_called_once_with(60)


class TestCoolscanScannerGetStatus:
    """Test status retrieval."""

    def test_status_disconnected(self):
        """Status shows disconnected when not connected."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        status = scanner.get_scanner_status()

        assert status['status'] == 'disconnected'

    def test_status_ready(self):
        """Status shows ready when test_unit_ready succeeds."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.test_unit_ready.return_value = True
        scanner.scanner_info = MockScannerInfo()

        status = scanner.get_scanner_status()

        assert status['status'] == 'ready'
        assert status['scan_in_progress'] is False
        assert status['scanner_info'] is not None

    def test_status_not_ready(self):
        """Status shows not_ready when test_unit_ready fails."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.test_unit_ready.return_value = False

        status = scanner.get_scanner_status()

        assert status['status'] == 'not_ready'

    def test_status_error(self):
        """Status shows error on exception."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.test_unit_ready.side_effect = Exception("Test error")

        status = scanner.get_scanner_status()

        assert status['status'] == 'error'
        assert 'error' in status


class TestCoolscanScannerContextManager:
    """Test context manager functionality."""

    @patch('coolscan.scanner.CoolscanProtocol')
    def test_context_manager_connects(self, mock_protocol_class):
        """Context manager connects on entry."""
        device = MockDevice()

        mock_protocol = Mock()
        mock_protocol.initialize_scanner.return_value = True
        mock_protocol.get_internal_info.return_value = MockScannerInfo()
        mock_protocol_class.return_value = mock_protocol

        with CoolscanScanner(device) as scanner:
            assert scanner.is_connected is True

    @patch('coolscan.scanner.CoolscanProtocol')
    def test_context_manager_disconnects(self, mock_protocol_class):
        """Context manager disconnects on exit."""
        device = MockDevice()

        mock_protocol = Mock()
        mock_protocol.initialize_scanner.return_value = True
        mock_protocol.get_internal_info.return_value = MockScannerInfo()
        mock_protocol_class.return_value = mock_protocol

        with CoolscanScanner(device) as scanner:
            pass

        mock_protocol.release_unit.assert_called()
        mock_protocol.close.assert_called()

    @patch('coolscan.scanner.CoolscanProtocol')
    def test_context_manager_connect_fails(self, mock_protocol_class):
        """Context manager raises on connect failure."""
        device = MockDevice()

        mock_protocol = Mock()
        mock_protocol.initialize_scanner.return_value = False
        mock_protocol_class.return_value = mock_protocol

        with pytest.raises(RuntimeError, match="Failed to connect"):
            with CoolscanScanner(device) as scanner:
                pass


class TestCoolscanScannerScanPreview:
    """Test preview scan functionality."""

    def test_scan_preview_not_connected(self):
        """Preview raises if not connected."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.scan_preview("/tmp/test.png")

    def test_scan_preview_creates_params(self):
        """Preview creates correct ScanParameters."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.perform_scan_sequence.return_value = False

        # Will fail but we can check params
        scanner.scan_preview("/tmp/test.png", resolution=300)

        call_args = scanner.protocol.perform_scan_sequence.call_args
        params = call_args[0][0]
        assert params.resolution == 300
        assert params.preview is True


class TestCoolscanScannerScanFull:
    """Test full scan functionality."""

    def test_scan_full_not_connected(self):
        """Full scan raises if not connected."""
        device = MockDevice()
        scanner = CoolscanScanner(device)

        with pytest.raises(RuntimeError, match="Scanner not connected"):
            scanner.scan_full("/tmp/test.png")

    def test_scan_full_creates_params(self):
        """Full scan creates correct ScanParameters."""
        device = MockDevice()
        scanner = CoolscanScanner(device)
        scanner.is_connected = True
        scanner.protocol = Mock()
        scanner.protocol.perform_scan_sequence.return_value = False

        scanner.scan_full("/tmp/test.png", resolution=2700, negative=True, infrared=True)

        call_args = scanner.protocol.perform_scan_sequence.call_args
        params = call_args[0][0]
        assert params.resolution == 2700
        assert params.negative is True
        assert params.infrared is True
        assert params.preview is False


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    @patch('coolscan.scanner.CoolscanScanner')
    def test_prescan_scanner(self, mock_scanner_class):
        """prescan_scanner uses context manager correctly."""
        device = MockDevice()
        mock_scanner = Mock()
        mock_scanner.prescan.return_value = True
        mock_scanner_class.return_value.__enter__ = Mock(return_value=mock_scanner)
        mock_scanner_class.return_value.__exit__ = Mock(return_value=False)

        result = prescan_scanner(device)

        mock_scanner.prescan.assert_called_once()

    @patch('coolscan.scanner.CoolscanScanner')
    def test_auto_focus_scanner(self, mock_scanner_class):
        """auto_focus_scanner uses context manager correctly."""
        device = MockDevice()
        mock_scanner = Mock()
        mock_scanner.auto_focus.return_value = True
        mock_scanner_class.return_value.__enter__ = Mock(return_value=mock_scanner)
        mock_scanner_class.return_value.__exit__ = Mock(return_value=False)

        result = auto_focus_scanner(device)

        mock_scanner.auto_focus.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
