"""
MagicMock-based test double for CoolscanProtocol.

Returns sensible defaults (True for bools, b'' for bytes, None for optionals)
so tests only configure methods relevant to the scenario.  Uses ``spec_set``
to enforce the real protocol's interface — calling a non-existent method or
wrong signature raises AttributeError/TypeError immediately.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from unittest.mock import MagicMock, create_autospec

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
    "release_unit",
    "reset_scanner",
    "reset_params",
    "object_position",
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
