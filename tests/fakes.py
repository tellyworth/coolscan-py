"""
Test doubles for fixture-independent scanner tests.

FakeCoolscanProtocol records every method call with arguments and returns
configurable defaults.  It is a standalone class -- no USB imports, no
hardware dependencies.  Scenario methods (prescan, full_scan_frame, etc.)
are stubbed so the scanner layer can be tested in isolation.
"""

from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from coolscan.protocol import (
    CoolscanProtocol,
    DataType,
    PhaseType,
    ScanParameters,
    ScanType,
    ScannerInfo,
    StatusType,
    WindowDescriptorBlock,
)


# Mapping of method name -> default return value.
# Bool methods return True, bytes methods return b"", Optional methods return None.
_DEFAULT_RESPONSES: Dict[str, Any] = {
    # Connection / init
    "initialize_scanner": True,
    "get_internal_info": ScannerInfo(),
    "inquiry": b" " * 36,
    "close": None,
    # Status
    "scanner_ready": True,
    "test_unit_ready": True,
    "_test_unit_ready_once": (StatusType.READY, {}),
    # Unit control
    "reserve_unit": True,
    "release_unit": True,
    "reset_scanner": True,
    "reset_params": True,
    "mode_sense": None,
    # Scan setup
    "object_position": True,
    "set_boundary": True,
    "set_boundary_for_prescan": True,
    "set_window_wdb": True,
    "set_window": True,
    "set_scan_window": True,
    "set_calibrated_exposure": None,
    # LUT
    "send_lut": True,
    "_generate_identity_lut": b"",
    "_upload_lut": True,
    "upload_identity_luts": True,
    # Scan execution
    "start_scan": True,
    "read_scan_data": b"",
    "poll_until_ready": True,
    "stop_scan": True,
    "cancel_scan": True,
    "scan_teardown": True,
    # Data reads
    "read_prescan_image_data": b"",
    "read_ir_preview_data": b"",
    "read_exposure_data": None,
    "read_control_frame": None,
    "read_control_params": None,
    "read_channel_state": None,
    "read_focus": None,
    "read_focus_info": None,
    "read_capacity": None,
    "get_window": None,
    "extract_exposure_from_wdb": None,
    "get_exposure_values": None,
    # Focus
    "focus_setup": None,
    "auto_focus": None,
    "post_prescan_autofocus": None,
    "_auto_focus_command": True,
    "set_focus_param": True,
    # Eject
    "eject_medium": True,
    # Scenario methods (composed from helpers -- stubbed for scanner tests)
    "prescan_frame": True,
    "prescan": True,
    "full_scan_setup_frame": True,
    "full_scan_capture_frame": True,
    "full_scan_frame": True,
    "perform_scan_sequence": True,
    "batch_full_scan_setup_frame": True,
    "batch_full_res_setup_frame": True,
    "batch_between_scan_setup_frame": True,
    "batch_scan_setup": True,
    "batch_scan_teardown": True,
    "batch_between_scan_setup": True,
    "batch_scan": True,
    "batch_full_scan_capture_frame": b"",
    "batch_full_res_capture_frame": b"",
    "batch_preview_capture_frame": b"",
    "batch_full_res_start_frame": True,
    "batch_scan_to_frames": [],
    # Internal I/O (overridden to record calls)
    "_usb_write_bulk": 0,
    "_usb_read_bulk": b"",
    "_check_phase": PhaseType.IN,
    "_check_phase_with_retry": PhaseType.IN,
    "_issue_command": (b"", StatusType.READY),
    "_execute_command": True,
    "_parse_status": (StatusType.READY, {}),
    "_drain_buffered_scan_data": 0,
    "_bus_reset_device": True,
    # Low-level helpers
    "_build_6byte_command": b"\x00" * 6,
    "_pack_byte": b"\x00",
    "_pack_word": b"\x00\x00",
    "_pack_long": b"\x00\x00\x00\x00",
    # USB capture
    "enable_usb_capture": None,
    "disable_usb_capture": None,
    # Scanner health
    "_on_usb_error": None,
    "_on_usb_success": None,
    "_check_scanner_alive": True,
    "_replay_reraise_if_needed": None,
    # Wait / replay helpers
    "wait_scanner": True,
    "_wait_ready_or_replay_once": True,
}


class FakeCoolscanProtocol:
    """Test double for CoolscanProtocol.

    Records every method call with arguments and returns configurable defaults.
    Does NOT import or use the ``usb`` module -- purely a test double.

    Usage::

        fake = FakeCoolscanProtocol()
        fake.set_response("initialize_scanner", True)
        fake.set_response("read_scan_data", b"\\x00" * 1000)

        scanner.protocol = fake
        scanner.is_connected = True

        # Now scanner methods will call the fake and record calls.
        scanner.prescan()
        assert fake.call_log[0][0] == "prescan"
    """

    def __init__(
        self,
        device=None,
        verbose: bool = False,
        *,
        usb_capture_replay=None,
        **kwargs,
    ) -> None:
        """Initialize the fake.  Signature matches CoolscanProtocol."""
        self.device = device
        self.verbose = verbose
        self._usb_capture_replay = usb_capture_replay
        self.maxbits = 12
        self._calibrated_exposure: Dict[int, int] = {}
        self._scanner_alive = True
        self._usb_error_count = 0
        self._last_status_raw = bytes(8)
        self._last_status_parsed = {
            "sense_key": 0,
            "sense_asc": 0,
            "sense_ascq": 0,
        }
        self._last_prescan_image_data = b""
        self._last_ir_preview_data = b""

        # Call log: list of (method_name, args, kwargs)
        self.call_log: List[Tuple[str, tuple, dict]] = []

        # Configurable responses per method name.
        self._responses: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Response configuration helpers
    # ------------------------------------------------------------------

    def set_response(self, method_name: str, value: Any) -> None:
        """Set a custom return value for a method."""
        self._responses[method_name] = value

    def set_responses(self, mapping: Dict[str, Any]) -> None:
        """Set multiple custom return values at once."""
        self._responses.update(mapping)

    def clear_log(self) -> None:
        """Clear the call log."""
        self.call_log.clear()

    def calls_to(self, method_name: str) -> List[Tuple[tuple, dict]]:
        """Return all (args, kwargs) for calls to *method_name*."""
        return [
            (args, kwargs)
            for name, args, kwargs in self.call_log
            if name == method_name
        ]

    def call_count(self, method_name: str) -> int:
        """Return the number of times *method_name* was called."""
        return sum(1 for name, _, _ in self.call_log if name == method_name)

    # ------------------------------------------------------------------
    # Core dispatch
    # ------------------------------------------------------------------

    def _log(self, name: str, args: tuple, kwargs: dict) -> Any:
        """Record a call and return the configured or default response."""
        self.call_log.append((name, args, kwargs))
        return self._responses.get(name, _DEFAULT_RESPONSES.get(name, None))

    # ------------------------------------------------------------------
    # Explicit stubs for methods called by the scanner layer
    # ------------------------------------------------------------------

    def initialize_scanner(self) -> bool:
        return self._log("initialize_scanner", (), {})

    def get_internal_info(self) -> Optional[ScannerInfo]:
        return self._log("get_internal_info", (), {})

    def inquiry(self, page: int = -1) -> bytes:
        return self._log("inquiry", (page,), {"page": page})

    def scanner_ready(self, timeout: int = 30) -> bool:
        return self._log("scanner_ready", (timeout,), {"timeout": timeout})

    def test_unit_ready(self) -> bool:
        return self._log("test_unit_ready", (), {})

    def reserve_unit(self) -> bool:
        return self._log("reserve_unit", (), {})

    def release_unit(self) -> bool:
        return self._log("release_unit", (), {})

    def close(self) -> None:
        return self._log("close", (), {})

    def cancel_scan(self) -> bool:
        return self._log("cancel_scan", (), {})

    def prescan(self, timeout: int = 120) -> bool:
        return self._log("prescan", (timeout,), {"timeout": timeout})

    def auto_focus(self, focus_x: int = 0, focus_y: int = 0) -> Optional[int]:
        return self._log("auto_focus", (focus_x, focus_y), {"focus_x": focus_x, "focus_y": focus_y})

    def full_scan_frame(
        self,
        params: Optional[ScanParameters] = None,
        timeout: int = 300,
        include_ir: bool = True,
        focus_x: int = 0,
        focus_y: int = 0,
        lut_map: Optional[Dict[int, bytes]] = None,
    ) -> bool:
        return self._log(
            "full_scan_frame",
            (params, timeout, include_ir, focus_x, focus_y, lut_map),
            {
                "params": params,
                "timeout": timeout,
                "include_ir": include_ir,
                "focus_x": focus_x,
                "focus_y": focus_y,
                "lut_map": lut_map,
            },
        )

    def read_scan_data(
        self, length: int, datatype: DataType = DataType.IMAGE_DATA
    ) -> bytes:
        return self._log("read_scan_data", (length, datatype), {"length": length, "datatype": datatype})

    def set_boundary(
        self, params: Optional[ScanParameters] = None, batch: bool = False
    ) -> bool:
        return self._log("set_boundary", (params, batch), {"params": params, "batch": batch})

    def set_boundary_for_prescan(self) -> bool:
        return self._log("set_boundary_for_prescan", (), {})

    def set_window(
        self, params: ScanParameters, scan_type: ScanType = ScanType.NORMAL
    ) -> bool:
        return self._log("set_window", (params, scan_type), {"params": params, "scan_type": scan_type})

    def set_window_wdb(self, wdb: WindowDescriptorBlock) -> bool:
        return self._log("set_window_wdb", (wdb,), {"wdb": wdb})

    def set_scan_window(
        self,
        window_id: int,
        scan_type: str = "normal",
        depth: int = 8,
        y_offset: Optional[int] = None,
        height: Optional[int] = None,
    ) -> bool:
        return self._log(
            "set_scan_window",
            (window_id, scan_type, depth, y_offset, height),
            {
                "window_id": window_id,
                "scan_type": scan_type,
                "depth": depth,
                "y_offset": y_offset,
                "height": height,
            },
        )

    def start_scan(self, scan_type: ScanType = ScanType.NORMAL) -> bool:
        return self._log("start_scan", (scan_type,), {"scan_type": scan_type})

    def poll_until_ready(
        self, timeout: int = 30, poll_interval: float = 0.1
    ) -> bool:
        return self._log(
            "poll_until_ready",
            (timeout, poll_interval),
            {"timeout": timeout, "poll_interval": poll_interval},
        )

    def stop_scan(self) -> bool:
        return self._log("stop_scan", (), {})

    def reset_scanner(self) -> bool:
        return self._log("reset_scanner", (), {})

    def reset_params(self) -> bool:
        return self._log("reset_params", (), {})

    def scan_teardown(self) -> bool:
        return self._log("scan_teardown", (), {})

    def eject_medium(self) -> bool:
        return self._log("eject_medium", (), {})

    def mode_sense(self) -> Optional[int]:
        return self._log("mode_sense", (), {})

    def object_position(self, auto_feed: int = 0x00) -> bool:
        return self._log("object_position", (auto_feed,), {"auto_feed": auto_feed})

    # LUT methods
    def send_lut(self, lut_data: bytes) -> bool:
        return self._log("send_lut", (lut_data,), {"lut_data": lut_data})

    def upload_identity_luts(
        self,
        include_ir: bool = False,
        lut_map: Optional[Dict[int, bytes]] = None,
    ) -> bool:
        return self._log(
            "upload_identity_luts",
            (include_ir, lut_map),
            {"include_ir": include_ir, "lut_map": lut_map},
        )

    def _upload_lut(self, channel: int, lut_data: bytes) -> bool:
        return self._log("_upload_lut", (channel, lut_data), {"channel": channel, "lut_data": lut_data})

    def _generate_identity_lut(self) -> bytes:
        return self._log("_generate_identity_lut", (), {})

    # Data reads
    def read_prescan_image_data(self) -> bytes:
        return self._log("read_prescan_image_data", (), {})

    def read_ir_preview_data(self) -> bytes:
        return self._log("read_ir_preview_data", (), {})

    def read_exposure_data(self) -> Optional[dict]:
        return self._log("read_exposure_data", (), {})

    def read_control_frame(self) -> Optional[bytes]:
        return self._log("read_control_frame", (), {})

    def read_control_params(self) -> Optional[bytes]:
        return self._log("read_control_params", (), {})

    def read_channel_state(self, channel: int) -> Optional[Dict[str, Any]]:
        return self._log("read_channel_state", (channel,), {"channel": channel})

    def read_focus(self) -> Optional[int]:
        return self._log("read_focus", (), {})

    def read_focus_info(self) -> Optional[bytes]:
        return self._log("read_focus_info", (), {})

    def read_capacity(self, window_id: int = 0) -> Optional[dict]:
        return self._log("read_capacity", (window_id,), {"window_id": window_id})

    def get_window(self, window_id: int) -> Optional[bytes]:
        return self._log("get_window", (window_id,), {"window_id": window_id})

    def extract_exposure_from_wdb(self, wdb: bytes) -> Optional[int]:
        return self._log("extract_exposure_from_wdb", (wdb,), {"wdb": wdb})

    def get_exposure_values(self, colors: list = None) -> Optional[dict]:
        if colors is None:
            colors = [1, 2, 3]
        return self._log("get_exposure_values", (colors,), {"colors": colors})

    def set_calibrated_exposure(self, channel: int, exposure: int) -> None:
        self._calibrated_exposure[channel] = exposure
        return self._log("set_calibrated_exposure", (channel, exposure), {"channel": channel, "exposure": exposure})

    # Focus
    def focus_setup(self) -> Optional[int]:
        return self._log("focus_setup", (), {})

    def post_prescan_autofocus(
        self, focus_x: int = 0, focus_y: int = 0
    ) -> Optional[int]:
        return self._log(
            "post_prescan_autofocus",
            (focus_x, focus_y),
            {"focus_x": focus_x, "focus_y": focus_y},
        )

    # Scenario methods (composed from helpers)
    def prescan_frame(self, timeout: int = 120) -> bool:
        return self._log("prescan_frame", (timeout,), {"timeout": timeout})

    def full_scan_setup_frame(
        self,
        params: Optional[ScanParameters] = None,
        timeout: int = 120,
        focus_x: int = 0,
        focus_y: int = 0,
    ) -> bool:
        return self._log(
            "full_scan_setup_frame",
            (params, timeout, focus_x, focus_y),
            {
                "params": params,
                "timeout": timeout,
                "focus_x": focus_x,
                "focus_y": focus_y,
            },
        )

    def full_scan_capture_frame(
        self,
        params: Optional[ScanParameters] = None,
        timeout: int = 300,
        lut_map: Optional[Dict[int, bytes]] = None,
    ) -> bool:
        return self._log(
            "full_scan_capture_frame",
            (params, timeout, lut_map),
            {
                "params": params,
                "timeout": timeout,
                "lut_map": lut_map,
            },
        )

    def perform_scan_sequence(
        self, params: ScanParameters, timeout: int = 300
    ) -> bool:
        return self._log(
            "perform_scan_sequence",
            (params, timeout),
            {"params": params, "timeout": timeout},
        )

    def batch_full_scan_setup_frame(
        self,
        params: Optional[ScanParameters] = None,
        timeout: int = 120,
        focus_x: int = 0x059B,
        focus_y: int = 0x0894,
        include_ir: bool = True,
    ) -> bool:
        return self._log(
            "batch_full_scan_setup_frame",
            (params, timeout, focus_x, focus_y, include_ir),
            {
                "params": params,
                "timeout": timeout,
                "focus_x": focus_x,
                "focus_y": focus_y,
                "include_ir": include_ir,
            },
        )

    def batch_full_res_setup_frame(
        self, lut_map: Optional[Dict[int, bytes]] = None
    ) -> bool:
        return self._log(
            "batch_full_res_setup_frame",
            (lut_map,),
            {"lut_map": lut_map},
        )

    def batch_between_scan_setup_frame(
        self,
        y_offset: Optional[int] = None,
        height: Optional[int] = None,
    ) -> bool:
        return self._log(
            "batch_between_scan_setup_frame",
            (y_offset, height),
            {"y_offset": y_offset, "height": height},
        )

    def batch_scan_setup(self) -> bool:
        return self._log("batch_scan_setup", (), {})

    def batch_scan_teardown(self) -> bool:
        return self._log("batch_scan_teardown", (), {})

    def batch_between_scan_setup(self) -> bool:
        return self._log("batch_between_scan_setup", (), {})

    def batch_scan(
        self,
        frames: int = 1,
        params: Optional[ScanParameters] = None,
        timeout: int = 600,
        focus_x: int = 0,
        focus_y: int = 0,
        include_ir: bool = True,
        lut_map: Optional[Dict[int, bytes]] = None,
    ) -> bool:
        return self._log(
            "batch_scan",
            (frames, params, timeout, focus_x, focus_y, include_ir, lut_map),
            {
                "frames": frames,
                "params": params,
                "timeout": timeout,
                "focus_x": focus_x,
                "focus_y": focus_y,
                "include_ir": include_ir,
                "lut_map": lut_map,
            },
        )

    def batch_full_scan_capture_frame(self) -> bytes:
        return self._log("batch_full_scan_capture_frame", (), {})

    def batch_full_res_capture_frame(self) -> bytes:
        return self._log("batch_full_res_capture_frame", (), {})

    def batch_preview_capture_frame(self) -> bytes:
        return self._log("batch_preview_capture_frame", (), {})

    def batch_full_res_start_frame(self) -> bool:
        return self._log("batch_full_res_start_frame", (), {})

    def batch_scan_to_frames(
        self,
        frames: int = 1,
        params: Optional[ScanParameters] = None,
        timeout: int = 600,
    ) -> list:
        return self._log(
            "batch_scan_to_frames",
            (frames, params, timeout),
            {"frames": frames, "params": params, "timeout": timeout},
        )

    # Low-level I/O (overridden for USB replay tests)
    def _usb_write_bulk(self, data: bytes) -> int:
        return self._log("_usb_write_bulk", (data,), {"data": data})

    def _usb_read_bulk(self, length: int) -> bytes:
        return self._log("_usb_read_bulk", (length,), {"length": length})

    def _check_phase(self) -> PhaseType:
        return self._log("_check_phase", (), {})

    def _check_phase_with_retry(self, max_retries: int = 3) -> PhaseType:
        return self._log(
            "_check_phase_with_retry",
            (max_retries,),
            {"max_retries": max_retries},
        )

    def _issue_command(
        self, cmd: bytes, data_in_length: int = 0, data_out: Optional[bytes] = None
    ) -> Tuple[bytes, StatusType]:
        return self._log(
            "_issue_command",
            (cmd, data_in_length, data_out),
            {"cmd": cmd, "data_in_length": data_in_length, "data_out": data_out},
        )

    def _execute_command(self) -> bool:
        return self._log("_execute_command", (), {})

    def _parse_status(self, status_data: bytes) -> Tuple[StatusType, dict]:
        return self._log(
            "_parse_status", (status_data,), {"status_data": status_data}
        )

    def _drain_buffered_scan_data(self) -> int:
        return self._log("_drain_buffered_scan_data", (), {})

    def _bus_reset_device(self) -> bool:
        return self._log("_bus_reset_device", (), {})

    # Low-level helpers
    def _build_6byte_command(
        self,
        cmd_code: int,
        page: int = 0,
        param2: int = 0,
        param3: int = 0,
        alloc_length: int = 0,
        control: int = 0x80,
    ) -> bytes:
        return self._log(
            "_build_6byte_command",
            (cmd_code, page, param2, param3, alloc_length, control),
            {
                "cmd_code": cmd_code,
                "page": page,
                "param2": param2,
                "param3": param3,
                "alloc_length": alloc_length,
                "control": control,
            },
        )

    def _pack_byte(self, byte: int) -> bytes:
        return self._log("_pack_byte", (byte,), {"byte": byte})

    def _pack_word(self, word: int) -> bytes:
        return self._log("_pack_word", (word,), {"word": word})

    def _pack_long(self, value: int) -> bytes:
        return self._log("_pack_long", (value,), {"value": value})

    # USB capture
    def enable_usb_capture(self, log_file: Any) -> None:
        return self._log("enable_usb_capture", (log_file,), {"log_file": log_file})

    def disable_usb_capture(self) -> None:
        return self._log("disable_usb_capture", (), {})

    # Scanner health
    def _on_usb_error(self, exc: BaseException) -> None:
        return self._log("_on_usb_error", (exc,), {"exc": exc})

    def _on_usb_success(self) -> None:
        return self._log("_on_usb_success", (), {})

    def _check_scanner_alive(self) -> bool:
        return self._log("_check_scanner_alive", (), {})

    def _replay_reraise_if_needed(self, exc: BaseException) -> None:
        return self._log(
            "_replay_reraise_if_needed", (exc,), {"exc": exc}
        )

    def wait_scanner(
        self,
        max_hard_errors: int = 3,
        timeout: float = 60.0,
        delay: float = 1.0,
        acceptable_statuses: tuple = (StatusType.READY, StatusType.NO_DOCS),
        min_polls: int = 0,
    ) -> bool:
        return self._log(
            "wait_scanner",
            (max_hard_errors, timeout, delay, acceptable_statuses, min_polls),
            {
                "max_hard_errors": max_hard_errors,
                "timeout": timeout,
                "delay": delay,
                "acceptable_statuses": acceptable_statuses,
                "min_polls": min_polls,
            },
        )

    def _wait_ready_or_replay_once(self, timeout: int = 30) -> bool:
        return self._log(
            "_wait_ready_or_replay_once",
            (timeout,),
            {"timeout": timeout},
        )

    def _test_unit_ready_once(self) -> Tuple[StatusType, dict]:
        return self._log("_test_unit_ready_once", (), {})

    # ------------------------------------------------------------------
    # Catch-all for any unlisted methods (e.g. __init__ internals)
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Callable:
        """Fallback for any method not explicitly defined above."""
        default = _DEFAULT_RESPONSES.get(name, None)

        def _fallback(*args: Any, **kwargs: Any) -> Any:
            return self._log(name, args, kwargs)

        return _fallback
