"""Contract tests for CoolscanProtocol helpers and scenario methods.

These tests verify that each protocol method calls the correct low-level I/O
methods in the expected order with the expected arguments.  They use
``unittest.mock.patch`` to mock I/O on a real ``CoolscanProtocol`` instance
and assert call patterns.

No fixture files, no line numbers, no replay — all knowledge is embedded as
constants and contract assertions.

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

import struct
import time
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from coolscan.protocol import (
    CoolscanProtocol,
    DataType,
    ScanType,
    StatusType,
)
from tests.fakes import make_bare_protocol


# ---------------------------------------------------------------------------
# Protocol factory — delegates to shared fakes module
# ---------------------------------------------------------------------------

def _make_protocol() -> CoolscanProtocol:
    """Create a CoolscanProtocol with mock device for contract testing."""
    return make_bare_protocol()


# =========================================================================
#  TestHelperContracts — individual helper method contracts
# =========================================================================

class TestHelperContracts:
    """Verify each protocol helper calls the right low-level methods."""

    # -----------------------------------------------------------------------
    # set_boundary_for_prescan
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_set_boundary_for_prescan_contract(self):
        """set_boundary_for_prescan sends one _issue_command with 0x2a CDB,
        datatype 0x92, 4-byte payload 04000000; returns True on READY."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        result = proto.set_boundary_for_prescan()

        assert result is True
        assert proto._issue_command.call_count == 1
        args, kwargs = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x2a  # SEND opcode
        assert cmd[2] == 0x92  # BORDER_POSITION datatype
        assert kwargs.get("data_out") == bytes.fromhex("04000000")

    @pytest.mark.property_test
    def test_set_boundary_for_prescan_returns_false_on_error(self):
        """set_boundary_for_prescan returns False when scanner is not READY."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))

        result = proto.set_boundary_for_prescan()
        assert result is False

    # -----------------------------------------------------------------------
    # read_exposure_data
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_read_exposure_data_two_phase_read(self):
        """read_exposure_data sends read_scan_data(6, EXPOSURE_CALIBRATION) for
        header, parses bytes 4-5 as big-endian table length, then sends
        read_scan_data(table_length, EXPOSURE_CALIBRATION) for table."""
        proto = _make_protocol()

        # Header: 6 bytes with table_length = 0x0d7c at bytes 4-5
        table_length = 0x0D7C
        header = bytes.fromhex(f"008e0000{table_length:04x}")
        table_data = b"\x00" * table_length

        proto.read_scan_data = Mock(side_effect=[header, table_data])

        result = proto.read_exposure_data()

        assert result is not None
        assert "header" in result
        assert "table" in result
        assert proto.read_scan_data.call_count == 2
        calls = proto.read_scan_data.call_args_list
        # First call: header read
        assert calls[0].args[0] == 6
        assert calls[0].args[1] == DataType.EXPOSURE_CALIBRATION
        # Second call: table read with length from header
        assert calls[1].args[0] == table_length
        assert calls[1].args[1] == DataType.EXPOSURE_CALIBRATION

    @pytest.mark.property_test
    def test_read_exposure_data_returns_none_on_short_header(self):
        """read_exposure_data returns None when header is too short."""
        proto = _make_protocol()
        proto.read_scan_data = Mock(return_value=b"\x00\x01")

        result = proto.read_exposure_data()
        assert result is None

    # -----------------------------------------------------------------------
    # read_control_frame
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_read_control_frame_contract(self):
        """read_control_frame sends _issue_command with READ(10) for datatype
        0x8f, reading 58 bytes; returns the data on READY."""
        proto = _make_protocol()
        expected_data = b"\x00" * 58
        proto._issue_command = Mock(return_value=(expected_data, StatusType.READY))

        result = proto.read_control_frame()

        assert result == expected_data
        assert proto._issue_command.call_count == 1
        args, _ = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x28  # READ(10)
        assert cmd[2] == 0x8F  # CONTROL_FRAME datatype

    # -----------------------------------------------------------------------
    # read_channel_state
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_read_channel_state_contract(self):
        """read_channel_state(n) sends _issue_command with READ(10) for
        datatype 0x8c, channel encoded; returns dict with exposure and raw."""
        proto = _make_protocol()
        # 10-byte response: exposure = 0x00ABCD01 at bytes 6-9
        response = bytes([0x8c, 0x0a, 0x00, 0x00, 0x00, 0x00, 0x00, 0xAB, 0xCD, 0x01])
        proto._issue_command = Mock(return_value=(response, StatusType.READY))

        result = proto.read_channel_state(channel=2)

        assert result is not None
        assert "exposure" in result
        assert "raw" in result
        assert result["exposure"] == 0x00ABCD01
        assert proto._issue_command.call_count == 1
        args, _ = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x28  # READ(10)
        assert cmd[2] == 0x8C  # CHANNEL_STATE datatype
        assert cmd[4] == 2     # channel ID

    @pytest.mark.property_test
    def test_read_channel_state_stores_calibrated_exposure(self):
        """read_channel_state stores parsed exposure in _calibrated_exposure."""
        proto = _make_protocol()
        response = bytes([0x8c, 0x0a, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x10, 0x00])
        proto._issue_command = Mock(return_value=(response, StatusType.READY))

        proto.read_channel_state(channel=1)

        assert proto._calibrated_exposure[1] == 0x1000

    # -----------------------------------------------------------------------
    # upload_identity_luts
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_upload_identity_luts_rgb_only(self):
        """upload_identity_luts(include_ir=False) calls _upload_lut for
        channels 1, 2, 3 in order."""
        proto = _make_protocol()
        proto._upload_lut = Mock(return_value=True)
        proto._generate_identity_lut = Mock(return_value=b"\x00" * 8192)

        result = proto.upload_identity_luts(include_ir=False)

        assert result is True
        assert proto._upload_lut.call_count == 3
        channels_called = [c[0][0] for c in proto._upload_lut.call_args_list]
        assert channels_called == [1, 2, 3]

    @pytest.mark.property_test
    def test_upload_identity_luts_with_ir(self):
        """upload_identity_luts(include_ir=True) calls _upload_lut for
        channels 9, 1, 2, 3 in order."""
        proto = _make_protocol()
        proto._upload_lut = Mock(return_value=True)
        proto._generate_identity_lut = Mock(return_value=b"\x00" * 8192)

        result = proto.upload_identity_luts(include_ir=True)

        assert result is True
        assert proto._upload_lut.call_count == 4
        channels_called = [c[0][0] for c in proto._upload_lut.call_args_list]
        assert channels_called == [9, 1, 2, 3]

    @pytest.mark.property_test
    def test_upload_identity_luts_returns_false_on_failure(self):
        """upload_identity_luts returns False if any channel upload fails."""
        proto = _make_protocol()
        proto._upload_lut = Mock(side_effect=[True, False, True])
        proto._generate_identity_lut = Mock(return_value=b"\x00" * 8192)

        result = proto.upload_identity_luts(include_ir=False)

        assert result is False
        assert proto._upload_lut.call_count == 2  # stops at first failure

    # -----------------------------------------------------------------------
    # start_scan
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_start_scan_sends_0x1b_command(self):
        """start_scan sends _issue_command with 0x1b opcode, 3-byte data
        for NORMAL scan type."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        result = proto.start_scan()

        assert result is True
        assert proto._issue_command.call_count == 1
        args, kwargs = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x1B
        data_out = kwargs.get("data_out")
        assert data_out == bytes([0x01, 0x02, 0x03])  # R, G, B

    @pytest.mark.property_test
    def test_start_scan_batch_sends_4_byte_data(self):
        """start_scan(BATCH) sends 4-byte data including IR channel."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        proto.start_scan(scan_type=ScanType.BATCH)

        args, kwargs = proto._issue_command.call_args
        data_out = kwargs.get("data_out")
        assert data_out == bytes([0x09, 0x01, 0x02, 0x03])  # IR, R, G, B

    @pytest.mark.property_test
    def test_start_scan_retries_on_reissue(self):
        """start_scan re-issues command on REISSUE status."""
        proto = _make_protocol()
        proto._issue_command = Mock(side_effect=[
            (b"", StatusType.REISSUE),
            (b"", StatusType.READY),
        ])
        proto._last_status_parsed = {"sense_key": 0x09, "sense_asc": 0x80, "sense_ascq": 0x06}
        proto._last_status_raw = bytes([0x02, 0x09, 0x80, 0x06, 0x00, 0x00, 0x00, 0x00])
        proto.read_scan_data = Mock(return_value=b"")

        with patch("coolscan.protocol.time.sleep"):
            result = proto.start_scan()

        assert result is True
        assert proto._issue_command.call_count == 2

    # -----------------------------------------------------------------------
    # stop_scan
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_stop_scan_contract(self):
        """stop_scan sends _issue_command with 0x1b opcode, action 0x04."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        result = proto.stop_scan()

        assert result is True
        assert proto._issue_command.call_count == 1
        args, kwargs = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x1B
        assert cmd[4] == 0x04  # action = stop
        data_out = kwargs.get("data_out")
        assert data_out == bytes([0x09, 0x01, 0x02, 0x03])

    # -----------------------------------------------------------------------
    # auto_focus
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_auto_focus_sequence(self):
        """auto_focus calls read_focus, _auto_focus_command, read_focus."""
        proto = _make_protocol()
        proto.read_focus = Mock(side_effect=[100, 200])
        proto._auto_focus_command = Mock(return_value=True)

        result = proto.auto_focus(focus_x=0x059B, focus_y=0x0894)

        assert result == 200
        assert proto.read_focus.call_count == 2
        assert proto._auto_focus_command.call_count == 1
        args, _ = proto._auto_focus_command.call_args
        assert args == (0x059B, 0x0894)

    # -----------------------------------------------------------------------
    # set_boundary (full scan)
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_set_boundary_sends_control_frame(self):
        """set_boundary sends _issue_command with SEND 0x8f, 52-byte payload."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        result = proto.set_boundary(params=None)

        assert result is True
        assert proto._issue_command.call_count == 1
        args, kwargs = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x2A  # SEND
        assert cmd[2] == 0x8F  # CONTROL_FRAME datatype
        data_out = kwargs.get("data_out")
        assert len(data_out) == 52

    # -----------------------------------------------------------------------
    # read_focus
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_read_focus_contract(self):
        """read_focus sends _issue_command with 0xe1/0xc1 command, 9-byte
        response; returns byte at index 4."""
        proto = _make_protocol()
        # 9-byte response: focus value at byte 4 = 0xF3
        response = bytes([0x00, 0x00, 0x00, 0x00, 0xF3, 0x00, 0x00, 0x00, 0x00])
        proto._issue_command = Mock(return_value=(response, StatusType.READY))

        result = proto.read_focus()

        assert result == 0xF3
        assert proto._issue_command.call_count == 1
        args, _ = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0xE1
        assert cmd[2] == 0xC1

    # -----------------------------------------------------------------------
    # set_scan_window
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_set_scan_window_calls_issue_command(self):
        """set_scan_window builds a WDB and sends _issue_command with SET_WINDOW
        CDB (0x24) and data_out = WDB."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        result = proto.set_scan_window(window_id=1, scan_type="prescan")

        assert result is True
        assert proto._issue_command.call_count == 1
        args, kwargs = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x24  # SET_WINDOW
        data_out = kwargs.get("data_out")
        assert len(data_out) == 58  # WDB size

    # -----------------------------------------------------------------------
    # test_unit_ready
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_test_unit_ready_sends_tur(self):
        """test_unit_ready sends _test_unit_ready_once (which builds TUR CDB)."""
        proto = _make_protocol()
        proto._test_unit_ready_once = Mock(return_value=(StatusType.READY, {}))

        result = proto.test_unit_ready()

        assert result is True
        assert proto._test_unit_ready_once.call_count >= 1

    # -----------------------------------------------------------------------
    # poll_until_ready
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_poll_until_ready_polls_until_ready(self):
        """poll_until_ready calls _test_unit_ready_once repeatedly until READY."""
        proto = _make_protocol()
        proto._test_unit_ready_once = Mock(side_effect=[
            (StatusType.PROCESSING, {}),
            (StatusType.PROCESSING, {}),
            (StatusType.READY, {}),
        ])

        with patch("coolscan.protocol.time.sleep"):
            result = proto.poll_until_ready(timeout=10, poll_interval=0.01)

        assert result is True
        assert proto._test_unit_ready_once.call_count == 3

    # -----------------------------------------------------------------------
    # reserve_unit
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_reserve_unit_contract(self):
        """reserve_unit sends _issue_command with 0x16 opcode."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        result = proto.reserve_unit()

        assert result is True
        assert proto._issue_command.call_count == 1
        args, _ = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x16

    # -----------------------------------------------------------------------
    # eject_medium
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_eject_medium_contract(self):
        """eject_medium sends _issue_command with 0xe0/0xd0 command, then
        _execute_command (0xc1)."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        result = proto.eject_medium()

        assert result is True
        assert proto._issue_command.call_count == 1
        args, kwargs = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0xE0
        assert cmd[2] == 0xD0
        assert proto._execute_command.call_count == 1

    # -----------------------------------------------------------------------
    # reset_params
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_reset_params_contract(self):
        """reset_params sends _issue_command with 0xe0/0xb4 command, then
        _execute_command (0xc1)."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        result = proto.reset_params()

        assert result is True
        assert proto._issue_command.call_count == 1
        args, kwargs = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0xE0
        assert cmd[2] == 0xB4
        assert proto._execute_command.call_count == 1

    # -----------------------------------------------------------------------
    # _auto_focus_command
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_auto_focus_command_two_commands(self):
        """_auto_focus_command sends _issue_command (0xe0/a0) then
        _execute_command (0xc1)."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        result = proto._auto_focus_command(focus_x=0x059B, focus_y=0x0894)

        assert result is True
        assert proto._issue_command.call_count == 1
        args, kwargs = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0xE0
        assert cmd[2] == 0xA0
        assert proto._execute_command.call_count == 1

    # -----------------------------------------------------------------------
    # read_capacity
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_read_capacity_contract(self):
        """read_capacity sends _issue_command with READ_CAPACITY CDB (0x25)."""
        proto = _make_protocol()
        response = b"\x00" * 58
        proto._issue_command = Mock(return_value=(response, StatusType.READY))

        result = proto.read_capacity(window_id=1)

        assert result is not None
        assert proto._issue_command.call_count == 1
        args, _ = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x25

    # -----------------------------------------------------------------------
    # inquiry
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_inquiry_standard_sends_one_command(self):
        """Standard inquiry (page=-1) sends one _issue_command with 0x12 opcode."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"\x00" * 36, StatusType.READY))

        result = proto.inquiry(page=-1)

        assert len(result) == 36
        assert proto._issue_command.call_count == 1
        args, _ = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0x12

    @pytest.mark.property_test
    def test_inquiry_page_sends_two_commands(self):
        """Page-specific inquiry sends two _issue_command calls (length + data)."""
        proto = _make_protocol()
        # First call returns length header: byte 3 = 0x10 (16), so total = 20
        length_header = bytes([0x06, 0x01, 0x00, 0x10])
        full_data = b"\x00" * 20
        proto._issue_command = Mock(side_effect=[
            (length_header, StatusType.READY),
            (full_data, StatusType.READY),
        ])

        proto.inquiry(page=0xD1)

        assert proto._issue_command.call_count == 2

    # -----------------------------------------------------------------------
    # Error path: set_boundary
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_set_boundary_returns_false_on_error(self):
        """set_boundary returns False when _issue_command returns ERROR status."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))

        result = proto.set_boundary(params=None)
        assert result is False

    @pytest.mark.property_test
    def test_set_boundary_raises_usb_error(self):
        """set_boundary propagates exceptions from _issue_command."""
        proto = _make_protocol()
        proto._issue_command = Mock(side_effect=OSError("device gone"))

        with pytest.raises(OSError, match="device gone"):
            proto.set_boundary(params=None)

    # -----------------------------------------------------------------------
    # Error path: set_scan_window
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_set_scan_window_returns_false_on_error(self):
        """set_scan_window returns False when _issue_command returns ERROR."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))

        result = proto.set_scan_window(window_id=1, scan_type="prescan")
        assert result is False

    @pytest.mark.property_test
    def test_set_scan_window_raises_usb_error(self):
        """set_scan_window propagates exceptions from _issue_command."""
        proto = _make_protocol()
        proto._issue_command = Mock(side_effect=OSError("device gone"))

        with pytest.raises(OSError, match="device gone"):
            proto.set_scan_window(window_id=1, scan_type="prescan")

    # -----------------------------------------------------------------------
    # Error path: set_window_wdb
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_set_window_wdb_returns_false_on_error(self):
        """set_window_wdb returns False when MODE_SELECT returns ERROR."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))

        from coolscan.protocol import WindowDescriptorBlock

        result = proto.set_window_wdb(WindowDescriptorBlock())
        assert result is False

    # -----------------------------------------------------------------------
    # Error path: upload_identity_luts USBError
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_upload_identity_luts_raises_exception(self):
        """upload_identity_luts propagates exceptions from _upload_lut."""
        proto = _make_protocol()
        proto._upload_lut = Mock(side_effect=OSError("device gone"))
        proto._generate_identity_lut = Mock(return_value=b"\x00" * 8192)

        with pytest.raises(OSError, match="device gone"):
            proto.upload_identity_luts(include_ir=False)

    # -----------------------------------------------------------------------
    # Error path: read_exposure_data exception
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_read_exposure_data_returns_none_on_exception(self):
        """read_exposure_data catches exceptions from read_scan_data and
        returns None."""
        proto = _make_protocol()
        proto.read_scan_data = Mock(side_effect=RuntimeError("device gone"))

        result = proto.read_exposure_data()
        assert result is None

    # -----------------------------------------------------------------------
    # Error path: reserve_unit
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_reserve_unit_returns_false_on_error(self):
        """reserve_unit returns False when _issue_command returns ERROR."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))

        result = proto.reserve_unit()
        assert result is False

    # -----------------------------------------------------------------------
    # Error path: read_channel_state
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_read_channel_state_returns_none_on_error(self):
        """read_channel_state returns None when _issue_command returns ERROR."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))

        result = proto.read_channel_state(channel=1)
        assert result is None

    # -----------------------------------------------------------------------
    # Error path: read_control_frame
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_read_control_frame_returns_none_on_error(self):
        """read_control_frame returns None when _issue_command returns ERROR."""
        proto = _make_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))

        result = proto.read_control_frame()
        assert result is None


# =========================================================================
#  TestScenarioContracts — composed scenario method contracts
# =========================================================================

class TestScenarioContracts:
    """Verify scenario methods compose helpers in the correct order."""

    # -----------------------------------------------------------------------
    # prescan_frame
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_prescan_frame_call_sequence(self):
        """prescan_frame calls helpers in the correct order matching the
        golden fixture sequence."""
        proto = _make_protocol()

        # Mock all sub-methods
        proto.set_boundary_for_prescan = Mock(return_value=True)
        # read_exposure_data internally calls read_scan_data, mock that
        table_length = 0x0D7C
        header = bytes.fromhex(f"008e0000{table_length:04x}")
        proto.read_scan_data = Mock(side_effect=[
            header,
            b"\x00" * table_length,  # exposure table
        ])
        proto.read_control_frame = Mock(return_value=b"\x00" * 58)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b"\x00" * 10})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.poll_until_ready = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            result = proto.prescan_frame(timeout=120)

        assert result is True

        # Verify call order of top-level methods (skipping read_scan_data internals)
        assert proto.set_boundary_for_prescan.call_count == 1
        # read_exposure_data calls read_scan_data twice
        assert proto.read_scan_data.call_count == 2
        assert proto.read_control_frame.call_count == 1
        # 3 TURs before channel state + 3 TURs before SET_WINDOW + 1 TUR before LUTs
        assert proto._wait_ready_or_replay_once.call_count == 7
        assert proto.read_channel_state.call_count == 3
        # Window IDs for channels 1, 2, 3
        window_calls = [c[0][0] for c in proto.read_channel_state.call_args_list]
        assert window_calls == [1, 2, 3]
        assert proto.set_scan_window.call_count == 4  # channels 1, 2, 3, 9
        assert proto.upload_identity_luts.call_count == 1
        upload_kwargs = proto.upload_identity_luts.call_args[1]
        assert upload_kwargs.get("include_ir") is True
        assert proto.start_scan.call_count == 1
        assert proto.poll_until_ready.call_count == 1

    # -----------------------------------------------------------------------
    # initialize_scanner
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_initialize_scanner_call_sequence(self):
        """initialize_scanner calls inquiry, wait_scanner, 6x inquiry pages,
        reserve_unit, read_capacity(0), 5x read_capacity, MODE_SELECT."""
        proto = _make_protocol()

        proto.inquiry = Mock(return_value=b"\x00" * 36)
        proto.wait_scanner = Mock(return_value=True)
        proto.reserve_unit = Mock(return_value=True)
        proto.read_capacity = Mock(return_value={"status": 0})
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        with patch("coolscan.protocol.time.sleep"):
            result = proto.initialize_scanner()

        assert result is True

        # 1 standard inquiry + 6 page inquiries
        assert proto.inquiry.call_count == 7
        # Pages called: 0x01, 0xD1, 0xC1, 0xE1, 0xF0, 0xF8
        page_calls = [c[1]["page"] for c in proto.inquiry.call_args_list[1:]]
        assert page_calls == [0x01, 0xD1, 0xC1, 0xE1, 0xF0, 0xF8]

        assert proto.reserve_unit.call_count == 1
        # read_capacity(0) + 4 for windows [1,2,3,9]
        assert proto.read_capacity.call_count == 5

        # MODE_SELECT via _issue_command
        cmd_calls = [c[0][0] for c in proto._issue_command.call_args_list]
        assert 0x15 in cmd_calls[0]  # MODE_SELECT opcode

    # -----------------------------------------------------------------------
    # full_scan_frame
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_full_scan_frame_composition(self):
        """full_scan_frame calls full_scan_setup_frame, optionally
        read_ir_preview_data, then full_scan_capture_frame."""
        proto = _make_protocol()
        proto.full_scan_setup_frame = Mock(return_value=True)
        proto.read_ir_preview_data = Mock(return_value=b"\x00" * 100)
        proto.full_scan_capture_frame = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            result = proto.full_scan_frame(include_ir=True)

        assert result is True
        assert proto.full_scan_setup_frame.call_count == 1
        assert proto.read_ir_preview_data.call_count == 1
        assert proto.full_scan_capture_frame.call_count == 1

    @pytest.mark.property_test
    def test_full_scan_frame_skips_ir_when_disabled(self):
        """full_scan_frame(include_ir=False) skips read_ir_preview_data."""
        proto = _make_protocol()
        proto.full_scan_setup_frame = Mock(return_value=True)
        proto.read_ir_preview_data = Mock(return_value=b"\x00" * 100)
        proto.full_scan_capture_frame = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            proto.full_scan_frame(include_ir=False)

        assert proto.read_ir_preview_data.call_count == 0

    # -----------------------------------------------------------------------
    # full_scan_setup_frame
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_full_scan_setup_frame_sequence(self):
        """full_scan_setup_frame: set_boundary -> TUR -> _auto_focus_command ->
        3x TUR -> read_focus -> TUR -> read_channel_state(9) -> 2x TUR ->
        4x set_scan_window -> TUR -> upload_identity_luts(ir=True) -> stop_scan."""
        proto = _make_protocol()
        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b"\x00" * 10})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.stop_scan = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            result = proto.full_scan_setup_frame()

        assert result is True
        assert proto.set_boundary.call_count == 1
        # TUR counts: 1 before autofocus + 3 before read_focus + 1 before
        # channel_state + 2 before set_scan_window + 1 before LUTs = 8
        assert proto._wait_ready_or_replay_once.call_count == 8
        assert proto._auto_focus_command.call_count == 1
        assert proto.read_focus.call_count == 1
        assert proto.read_channel_state.call_count == 1
        # Window IDs: 9, 1, 2, 3
        window_calls = [c[0][0] for c in proto.set_scan_window.call_args_list]
        assert window_calls == [9, 1, 2, 3]
        assert proto.upload_identity_luts.call_count == 1
        upload_kwargs = proto.upload_identity_luts.call_args[1]
        assert upload_kwargs.get("include_ir") is True
        assert proto.stop_scan.call_count == 1

    # -----------------------------------------------------------------------
    # full_scan_capture_frame
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_full_scan_capture_frame_sequence(self):
        """full_scan_capture_frame: 2x TUR -> 3x set_scan_window(single_bw) ->
        TUR -> upload_identity_luts(ir=False) -> start_scan -> poll_until_ready."""
        proto = _make_protocol()
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.poll_until_ready = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            result = proto.full_scan_capture_frame()

        assert result is True
        # 2 TURs before windows + 1 TUR before LUTs = 3
        assert proto._wait_ready_or_replay_once.call_count == 3
        assert proto.set_scan_window.call_count == 3
        # scan_type should be "single_bw"
        for c in proto.set_scan_window.call_args_list:
            assert c[1].get("scan_type") == "single_bw"
        assert proto.upload_identity_luts.call_count == 1
        assert proto.start_scan.call_count == 1
        assert proto.poll_until_ready.call_count == 1

    # -----------------------------------------------------------------------
    # perform_scan_sequence (deprecated, but documented)
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_perform_scan_sequence_call_sequence(self):
        """perform_scan_sequence (deprecated) composes: scanner_ready ->
        _check_scanner_alive -> read_capacity -> _check_scanner_alive ->
        read_control_frame -> 3x TUR -> 3x read_channel_state(1/2/3) ->
        3x TUR -> 3x set_scan_window(normal) -> get_exposure_values ->
        TUR -> _check_scanner_alive -> upload_identity_luts -> start_scan ->
        poll_until_ready."""
        import warnings

        proto = _make_protocol()
        proto.scanner_ready = Mock(return_value=True)
        proto._check_scanner_alive = Mock(return_value=True)
        proto.read_capacity = Mock(return_value={"status": 0})
        proto.read_control_frame = Mock(return_value=b"\x00" * 58)
        proto.test_unit_ready = Mock(return_value=True)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b"\x00" * 10})
        proto.set_scan_window = Mock(return_value=True)
        proto.get_exposure_values = Mock(return_value={"R": 100, "G": 200, "B": 300})
        proto.upload_identity_luts = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.poll_until_ready = Mock(return_value=True)

        from coolscan.protocol import ScanParameters

        params = ScanParameters()

        with (
            patch("coolscan.protocol.time.time", side_effect=lambda: 0.0),
            warnings.catch_warnings(record=True) as w,
        ):
            result = proto.perform_scan_sequence(params, timeout=300)

        # Verify deprecation warning
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "perform_scan_sequence" in str(w[0].message)

        assert result is True

        # Call counts
        assert proto.scanner_ready.call_count == 1
        assert proto._check_scanner_alive.call_count == 3
        assert proto.read_capacity.call_count == 1
        assert proto.read_control_frame.call_count == 1
        # 3 TURs before channel state + 3 TURs before set_scan_window + 1 after = 7
        assert proto.test_unit_ready.call_count == 7
        # read_channel_state for channels 1, 2, 3
        assert proto.read_channel_state.call_count == 3
        channel_calls = [c[0][0] for c in proto.read_channel_state.call_args_list]
        assert channel_calls == [1, 2, 3]
        # set_scan_window for windows 1, 2, 3 with "normal" type
        assert proto.set_scan_window.call_count == 3
        for c in proto.set_scan_window.call_args_list:
            assert c[1].get("scan_type") == "normal"
        assert proto.get_exposure_values.call_count == 1
        assert proto.upload_identity_luts.call_count == 1
        assert proto.start_scan.call_count == 1
        assert proto.poll_until_ready.call_count == 1

    @pytest.mark.property_test
    def test_perform_scan_sequence_returns_false_on_scanner_not_ready(self):
        """perform_scan_sequence returns False when scanner_ready fails."""
        import warnings

        proto = _make_protocol()
        proto.scanner_ready = Mock(return_value=False)

        from coolscan.protocol import ScanParameters

        params = ScanParameters()

        with warnings.catch_warnings(record=True):
            result = proto.perform_scan_sequence(params, timeout=300)

        assert result is False
        assert proto.scanner_ready.call_count == 1

    @pytest.mark.property_test
    def test_perform_scan_sequence_returns_false_on_scan_window_fail(self):
        """perform_scan_sequence returns False when set_scan_window fails."""
        import warnings

        proto = _make_protocol()
        proto.scanner_ready = Mock(return_value=True)
        proto._check_scanner_alive = Mock(return_value=True)
        proto.read_capacity = Mock(return_value={"status": 0})
        proto.read_control_frame = Mock(return_value=b"\x00" * 58)
        proto.test_unit_ready = Mock(return_value=True)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b"\x00" * 10})
        # First set_scan_window call fails
        proto.set_scan_window = Mock(side_effect=[True, False])
        proto.get_exposure_values = Mock(return_value=None)

        from coolscan.protocol import ScanParameters

        params = ScanParameters()

        with (
            patch("coolscan.protocol.time.time", side_effect=lambda: 0.0),
            warnings.catch_warnings(record=True),
        ):
            result = proto.perform_scan_sequence(params, timeout=300)

        assert result is False

    # -----------------------------------------------------------------------
    # scan_teardown
    # -----------------------------------------------------------------------

    @pytest.mark.property_test
    def test_scan_teardown_sequence(self):
        """scan_teardown: 3x test_unit_ready -> eject_medium -> 3x TUR ->
        reset_params -> TUR -> 4x set_scan_window."""
        proto = _make_protocol()
        proto.test_unit_ready = Mock(return_value=True)
        proto.eject_medium = Mock(return_value=True)
        proto.reset_params = Mock(return_value=True)
        proto.set_scan_window = Mock(return_value=True)

        with patch("coolscan.protocol.time.sleep"):
            result = proto.scan_teardown()

        assert result is True
        # 3 initial TURs + 3 post-eject TURs + 1 final TUR = 7
        assert proto.test_unit_ready.call_count == 7
        assert proto.eject_medium.call_count == 1
        assert proto.reset_params.call_count == 1
        assert proto.set_scan_window.call_count == 4
        window_calls = [c[0][0] for c in proto.set_scan_window.call_args_list]
        assert window_calls == [1, 2, 3, 9]


# =========================================================================
#  TestBatchContracts — batch scan composition tests
# =========================================================================

class TestBatchContracts:
    """Verify batch scan methods compose correctly."""

    @pytest.mark.property_test
    def test_batch_full_scan_setup_frame_sequence(self):
        """batch_full_scan_setup_frame: set_boundary -> TUR -> _auto_focus_command ->
        3x TUR -> read_focus -> TUR -> read_channel_state(9) -> 2x TUR ->
        4x set_scan_window(batch) -> TUR -> upload_identity_luts(ir=True)."""
        proto = _make_protocol()

        # Mock read_scan_data for the internal calls within set_boundary
        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b"\x00" * 10})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            result = proto.batch_full_scan_setup_frame()

        assert result is True
        assert proto.set_boundary.call_count == 1
        # TUR counts: 1 + 3 + 1 + 2 + 1 = 8
        assert proto._wait_ready_or_replay_once.call_count == 8
        assert proto._auto_focus_command.call_count == 1
        assert proto.read_focus.call_count == 1
        assert proto.read_channel_state.call_count == 1
        # Window IDs: 9, 1, 2, 3 with scan_type "batch"
        window_calls = [c.kwargs.get("window_id") for c in proto.set_scan_window.call_args_list]
        assert window_calls == [9, 1, 2, 3]
        for c in proto.set_scan_window.call_args_list:
            assert c.kwargs.get("scan_type") == "batch"
        assert proto.upload_identity_luts.call_count == 1
        upload_kwargs = proto.upload_identity_luts.call_args[1]
        assert upload_kwargs.get("include_ir") is True

    @pytest.mark.property_test
    def test_batch_full_scan_setup_frame_skip_autofocus(self):
        """When skip_autofocus=True, batch setup uses 4x TUR instead of
        autofocus sequence."""
        proto = _make_protocol()
        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b"\x00" * 10})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            proto.batch_full_scan_setup_frame(skip_autofocus=True)

        # 4 TURs for skip_autofocus path + 2 before windows + 1 before LUTs = 7
        assert proto._wait_ready_or_replay_once.call_count == 7
        assert proto._auto_focus_command.call_count == 0
        assert proto.read_focus.call_count == 0
        assert proto.read_channel_state.call_count == 0

    @pytest.mark.property_test
    def test_batch_between_scan_setup_frame_sequence(self):
        """batch_between_scan_setup_frame: 3x set_scan_window(batch_between) ->
        TUR -> upload_identity_luts(ir=False) -> start_scan -> poll_until_ready."""
        proto = _make_protocol()
        proto.set_scan_window = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.poll_until_ready = Mock(return_value=True)

        result = proto.batch_between_scan_setup_frame()

        assert result is True
        assert proto.set_scan_window.call_count == 3
        assert proto._wait_ready_or_replay_once.call_count == 1
        assert proto.upload_identity_luts.call_count == 1
        assert proto.start_scan.call_count == 1
        assert proto.poll_until_ready.call_count == 1

    @pytest.mark.property_test
    def test_batch_full_res_setup_frame_sequence(self):
        """batch_full_res_setup_frame: 3x set_scan_window(normal) -> TUR ->
        upload_identity_luts(ir=False)."""
        proto = _make_protocol()
        proto.set_scan_window = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        result = proto.batch_full_res_setup_frame()

        assert result is True
        assert proto.set_scan_window.call_count == 3
        # Windows 1, 2, 3 with "normal" type
        window_calls = [c.kwargs.get("window_id") for c in proto.set_scan_window.call_args_list]
        assert window_calls == [1, 2, 3]
        for c in proto.set_scan_window.call_args_list:
            assert c.kwargs.get("scan_type") == "normal"
        assert proto._wait_ready_or_replay_once.call_count == 1
        assert proto.upload_identity_luts.call_count == 1

    @pytest.mark.property_test
    def test_batch_full_res_start_frame_sequence(self):
        """batch_full_res_start_frame: start_scan(NORMAL) -> poll_until_ready."""
        proto = _make_protocol()
        proto.start_scan = Mock(return_value=True)
        proto.poll_until_ready = Mock(return_value=True)

        result = proto.batch_full_res_start_frame()

        assert result is True
        assert proto.start_scan.call_count == 1
        args, kwargs = proto.start_scan.call_args
        assert kwargs.get("scan_type") == ScanType.NORMAL
        assert proto.poll_until_ready.call_count == 1

    @pytest.mark.property_test
    def test_batch_scan_frame_iteration(self):
        """batch_scan iterates over frames calling the right sub-methods."""
        proto = _make_protocol()
        proto.batch_full_scan_setup_frame = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.batch_full_scan_capture_frame = Mock(return_value=b"\x00" * 100)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto.batch_between_scan_setup_frame = Mock(return_value=True)
        proto.batch_preview_capture_frame = Mock(return_value=b"\x00" * 50)
        proto.batch_full_res_setup_frame = Mock(return_value=True)
        proto.batch_full_res_start_frame = Mock(return_value=True)
        proto.batch_full_res_capture_frame = Mock(return_value=b"\x00" * 200)
        proto.scan_teardown = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            result = proto.batch_scan(frames=2, teardown=True)

        assert result is True
        # Each frame calls these once
        assert proto.batch_full_scan_setup_frame.call_count == 2
        assert proto.start_scan.call_count == 2
        assert proto.batch_full_scan_capture_frame.call_count == 2
        # 2 TUR polls per frame
        assert proto._wait_ready_or_replay_once.call_count == 4
        assert proto.batch_between_scan_setup_frame.call_count == 2
        assert proto.batch_preview_capture_frame.call_count == 2
        assert proto.batch_full_res_setup_frame.call_count == 2
        assert proto.batch_full_res_start_frame.call_count == 2
        assert proto.batch_full_res_capture_frame.call_count == 2
        assert proto.scan_teardown.call_count == 1

    @pytest.mark.property_test
    def test_batch_scan_skips_teardown_when_disabled(self):
        """batch_scan with teardown=False skips scan_teardown."""
        proto = _make_protocol()
        proto.batch_full_scan_setup_frame = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.batch_full_scan_capture_frame = Mock(return_value=b"\x00" * 100)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto.batch_between_scan_setup_frame = Mock(return_value=True)
        proto.batch_preview_capture_frame = Mock(return_value=b"\x00" * 50)
        proto.batch_full_res_setup_frame = Mock(return_value=True)
        proto.batch_full_res_start_frame = Mock(return_value=True)
        proto.batch_full_res_capture_frame = Mock(return_value=b"\x00" * 200)
        proto.scan_teardown = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            proto.batch_scan(frames=1, teardown=False)

        assert proto.scan_teardown.call_count == 0
