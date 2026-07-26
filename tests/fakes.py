"""
Test utilities for CoolscanProtocol testing.

Provides:
- ``make_protocol_mock()`` — spec'd MagicMock for scanner-layer tests
- ``configure_mock()`` — override defaults on an existing mock
- ``configure_failure()`` — inject failure at a specific call index
- ``make_bare_protocol()`` — bypasses __init__ for contract testing
- ``make_mock_device()`` — mock device descriptor for protocol construction
- ``MockDevice`` — plain class for UsbCaptureReplay tests
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from unittest.mock import MagicMock, Mock, create_autospec

from coolscan.protocol import (
    CoolscanProtocol,
    DataType,
    PhaseType,
    ScanParameters,
    ScanType,
    ScannerInfo,
    StatusType,
)


# Methods that return bool -> True by default
_BOOL_METHODS = frozenset([
    "initialize_scanner",
    "scanner_ready",
    "test_unit_ready",
    "reserve_unit",
    "reset_scanner",
    "reset_params",
    "set_boundary",
    "set_boundary_for_prescan",
    "set_window",
    "set_window_wdb",
    "set_scan_window",
    "send_lut",
    "_upload_lut",
    "upload_identity_luts",
    "start_scan",
    "poll_until_ready",
    "stop_scan",
    "cancel_scan",
    "scan_teardown",
    "eject_medium",
    "prescan",
    "prescan_frame",
    "full_scan_setup_frame",
    "full_scan_capture_frame",
    "full_scan_frame",
    "perform_scan_sequence",
    "batch_full_scan_setup_frame",
    "batch_full_res_setup_frame",
    "batch_between_scan_setup_frame",
    "batch_scan_setup",
    "batch_scan_teardown",
    "batch_between_scan_setup",
    "batch_scan",
    "batch_full_res_start_frame",
    "_auto_focus_command",
    "set_focus_param",
    "_execute_command",
    "_bus_reset_device",
    "_check_scanner_alive",
    "wait_scanner",
    "_wait_ready_or_replay_once",
    # New vendor command helpers
    "vendor_e0",
    "vendor_e0_b4",
    "vendor_e0_b0",
    "vendor_e0_a0",
    "vendor_e0_c1",
    "vendor_e0_d0",
    "selective_batch_scan",
    "_preview_scan_frame",
    "_main_scan_frame",
    "_send_short_out",
])

# Methods that return bytes -> b"" by default
_BYTES_METHODS = frozenset([
    "inquiry",
    "read_scan_data",
    "read_prescan_image_data",
    "read_ir_preview_data",
    "read_focus_info",
    "batch_full_scan_capture_frame",
    "batch_full_res_capture_frame",
    "batch_preview_capture_frame",
    "_build_6byte_command",
    "_pack_byte",
    "_pack_word",
    "_pack_long",
    "_generate_identity_lut",
    # New vendor command helpers
    "vendor_e1",
    "vendor_e1_c1",
    "vendor_e1_91",
])

# Methods that return Optional[T] -> None by default
_OPTIONAL_METHODS = frozenset([
    "get_internal_info",
    "mode_sense",
    "read_exposure_data",
    "read_control_frame",
    "read_control_params",
    "read_channel_state",
    "read_focus",
    "read_capacity",
    "get_window",
    "extract_exposure_from_wdb",
    "get_exposure_values",
    "focus_setup",
    "auto_focus",
    "post_prescan_autofocus",
])

# Methods that return specific non-trivial defaults
_SPECIAL_DEFAULTS: Dict[str, Any] = {
    "close": None,
    "enable_usb_capture": None,
    "disable_usb_capture": None,
    "_on_usb_error": None,
    "_on_usb_success": None,
    "_replay_reraise_if_needed": None,
    "set_calibrated_exposure": None,
    "_check_phase": PhaseType.IN,
    "_check_phase_with_retry": PhaseType.IN,
    "_issue_command": (b"", StatusType.READY),
    "_parse_status": (StatusType.READY, {}),
    "_test_unit_ready_once": (StatusType.READY, {}),
    "_drain_buffered_scan_data": 0,
    "batch_scan_to_frames": [],
}


def _apply_defaults(mock: MagicMock) -> None:
    """Configure sensible return values for all known protocol methods."""
    for name in _BOOL_METHODS:
        method = getattr(mock, name, None)
        if method is not None:
            method.return_value = True

    for name in _BYTES_METHODS:
        method = getattr(mock, name, None)
        if method is not None:
            method.return_value = b""

    for name in _OPTIONAL_METHODS:
        method = getattr(mock, name, None)
        if method is not None:
            method.return_value = None

    for name, value in _SPECIAL_DEFAULTS.items():
        method = getattr(mock, name, None)
        if method is not None:
            method.return_value = value


def make_protocol_mock() -> MagicMock:
    """Create a spec'd mock of CoolscanProtocol with sensible defaults.

    Usage::

        mock = make_protocol_mock()
        mock.initialize_scanner.return_value = True
        mock.read_scan_data.return_value = b"\\x00" * 64

        # Inspect calls
        assert mock.initialize_scanner.call_count == 1
        mock.read_scan_data.assert_called_with(64, DataType.IMAGE_DATA)
        mock.reset_mock()  # clear call history
    """
    mock = create_autospec(CoolscanProtocol, instance=True)
    _apply_defaults(mock)

    # Mirror state attributes used by scanner layer
    mock.maxbits = 12
    mock._calibrated_exposure = {}
    mock._scanner_alive = True
    mock._usb_error_count = 0
    mock._last_status_raw = bytes(8)
    mock._last_status_parsed = {
        "sense_key": 0,
        "sense_asc": 0,
        "sense_ascq": 0,
    }
    mock._last_prescan_image_data = b""
    mock._last_ir_preview_data = b""
    mock._usb_capture_replay = None

    return mock


def configure_mock(
    mock: MagicMock,
    responses: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """Override default return values on an existing mock.

    Usage::

        mock = make_protocol_mock()
        configure_mock(mock, {
            "initialize_scanner": False,
            "read_scan_data": b"\\xff" * 64,
        })
    """
    if responses:
        for name, value in responses.items():
            method = getattr(mock, name, None)
            if method is not None:
                method.return_value = value
    return mock


def calls_to(mock: MagicMock, method_name: str) -> List:
    """Return all call arguments for *method_name*.

    Equivalent to the old ``fake.calls_to(name)``.
    """
    method = getattr(mock, method_name)
    return method.call_args_list


def configure_failure(
    mock: MagicMock,
    method_name: str,
    call_index: int,
    failure_value: Any = False,
    raise_exc: Optional[Exception] = None,
) -> MagicMock:
    """Configure a mock method to fail on its Nth call (0-indexed).

    Before call_index: returns normal default.
    At call_index: returns failure_value or raises raise_exc.
    After call_index: returns normal default.

    Usage::

        mock = make_protocol_mock()
        configure_failure(mock, "read_scan_data", call_index=2, failure_value=b"")
        # First two calls return b"", third call returns b"", subsequent return b""
    """
    original = getattr(mock, method_name)
    default = original.return_value

    def side_effect(*args: Any, **kwargs: Any):
        nonlocal call_index
        call_index -= 1
        if call_index < 0:
            if raise_exc is not None:
                raise raise_exc
            return failure_value
        return default

    original.side_effect = side_effect
    return mock


# ---------------------------------------------------------------------------
# Bare protocol factory — bypasses __init__ for contract testing
# ---------------------------------------------------------------------------

class MockDevice:
    """Plain device descriptor for UsbCaptureReplay tests."""

    def __init__(self):
        self.vendor = "Nikon"
        self.model = "LS-40 ED"
        self.revision = "1.20"
        self.interface = type("IF", (), {"value": "usb"})()
        self.device_path = "/dev/usb/scanner0"
        self.vendor_id = 0x04B0
        self.product_id = 0x4000


def make_mock_device(**kwargs: Any) -> Mock:
    """Create a minimal mock device descriptor for protocol construction."""
    device = Mock()
    device.vendor = kwargs.get("vendor", "Nikon")
    device.model = kwargs.get("model", "LS-40 ED")
    device.revision = kwargs.get("revision", "1.20")
    device.interface = type("IF", (), {"value": "usb"})()
    device.device_path = kwargs.get("device_path", "/dev/usb/scanner0")
    device.vendor_id = kwargs.get("vendor_id", 0x04B0)
    device.product_id = kwargs.get("product_id", 0x4000)
    return device


def make_bare_protocol(maxbits: int = 12, **kwargs: Any) -> CoolscanProtocol:
    """Create a CoolscanProtocol bypassing __init__ (for contract testing).

    Returns a protocol instance with mock device and default state attributes.
    Override any attribute via kwargs.

    Usage::

        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto.set_boundary_for_prescan()

        proto = make_bare_protocol(maxbits=8)
    """
    device = make_mock_device(**{k: v for k, v in kwargs.items() if k in (
        "vendor", "model", "revision", "device_path", "vendor_id", "product_id"
    )})

    proto = object.__new__(CoolscanProtocol)
    proto.device = device
    proto.verbose = False
    proto.maxbits = maxbits
    proto._calibrated_exposure = {}
    proto._usb_capture_replay = None
    proto.usb_device = Mock()
    proto.usb_device.default_timeout = 30000
    proto._last_status_raw = bytes(8)
    proto._last_status_parsed = {"sense_key": 0, "sense_asc": 0, "sense_ascq": 0}
    proto._usb_inited = False
    proto._scanner_alive = True
    proto._usb_error_count = 0
    proto._last_prescan_image_data = b""
    proto._last_ir_preview_data = b""

    # Apply any remaining kwargs as attribute overrides
    for key, value in kwargs.items():
        if key not in (
            "vendor", "model", "revision", "device_path", "vendor_id", "product_id"
        ):
            setattr(proto, key, value)

    return proto
