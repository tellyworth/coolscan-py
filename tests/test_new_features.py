"""Tests for new vendor commands, WDB58, analyzer, and selective batch scan.

Contract tests for vendor_e0/e1 helpers, WDB 58-byte builder, and
selective batch scan state machine.  Fixture-agnostic — no capture files
imported.
"""

from __future__ import annotations

import struct
from unittest.mock import Mock, MagicMock, call

import pytest

from coolscan.protocol import (
    CoolscanProtocol,
    WindowDescriptorBlock,
    StatusType,
    DataType,
    ScanType,
    CHANNEL_RED,
    CHANNEL_GREEN,
    CHANNEL_BLUE,
    CHANNEL_IR,
    WDB_MODE_PRESCAN,
    WDB_MODE_PREVIEW_MAIN,
    WDB_TRANSFER_PRESCAN_MAIN,
    WDB_TRANSFER_LOW_RES_PREVIEW,
    WDB_FILM_PRESCAN,
    WDB_FILM_IR_PREVIEW,
    WDB_FILM_MAIN_SCAN,
    WDB_SUBMODE_PRESCAN_MAIN,
    WDB_SUBMODE_LOW_RES_96DPI,
)
from tests.fakes import make_bare_protocol


# =========================================================================
# VENDOR_E0 command helpers
# =========================================================================

class TestVendorE0Generic:
    """Generic vendor_e0(subcode, data) contract tests."""

    def test_vendor_e0_sends_correct_cdb(self):
        """vendor_e0 sends 10-byte CDB with subcode in byte 2."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        data = b"\x00" * 9
        proto.vendor_e0(0xB4, data)

        args, _ = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0xE0
        assert cmd[2] == 0xB4
        assert cmd[8:10] == b"\x09\x00"  # data length = 9

    def test_vendor_e0_sends_9byte_data(self):
        """vendor_e0 sends the provided 9-byte data payload."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        data = bytes(range(9))
        proto.vendor_e0(0xA0, data)

        _, kwargs = proto._issue_command.call_args
        assert kwargs["data_out"] == data

    def test_vendor_e0_calls_execute(self):
        """vendor_e0 calls _execute_command after successful CDB."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0(0xB0, b"\x00" * 9)

        assert proto._execute_command.call_count == 1

    def test_vendor_e0_returns_false_on_bad_status(self):
        """vendor_e0 returns False when CDB fails."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))
        proto._execute_command = Mock(return_value=True)

        result = proto.vendor_e0(0xB0, b"\x00" * 9)

        assert result is False
        assert proto._execute_command.call_count == 0

    def test_vendor_e0_requires_9byte_data(self):
        """vendor_e0 raises ValueError for non-9-byte data."""
        proto = make_bare_protocol()

        with pytest.raises(ValueError, match="9-byte"):
            proto.vendor_e0(0xB0, b"\x00" * 8)


class TestVendorE0B4:
    """ICE/densitometry setup (VENDOR_E0 0xb4)."""

    def test_default_payload(self):
        """Default payload is initial-prescan value."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_b4()

        _, kwargs = proto._issue_command.call_args
        assert kwargs["data_out"] == bytes.fromhex("0000000e1000000001")

    def test_custom_payload(self):
        """Custom payload overrides default."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        custom = bytes.fromhex("000000025800000001")
        proto.vendor_e0_b4(custom)

        _, kwargs = proto._issue_command.call_args
        assert kwargs["data_out"] == custom

    def test_sends_subcode_b4(self):
        """Subcode byte is 0xb4."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_b4()

        args, _ = proto._issue_command.call_args
        assert args[0][2] == 0xB4


class TestVendorE0B0:
    """Calibrate (VENDOR_E0 0xb0)."""

    def test_all_zero_payload(self):
        """Sends all-zero 9-byte payload."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_b0()

        _, kwargs = proto._issue_command.call_args
        assert kwargs["data_out"] == b"\x00" * 9

    def test_sends_subcode_b0(self):
        """Subcode byte is 0xb0."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_b0()

        args, _ = proto._issue_command.call_args
        assert args[0][2] == 0xB0


class TestVendorE0A0:
    """Autofocus (VENDOR_E0 0xa0)."""

    def test_payload_structure(self):
        """Payload has 05 9b at bytes 3-4, position at bytes 7-8."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_a0(position=0x092A)

        _, kwargs = proto._issue_command.call_args
        data = kwargs["data_out"]
        assert len(data) == 9
        assert data[3:5] == bytes([0x05, 0x9b])
        assert data[7:9] == struct.pack(">H", 0x092A)

    def test_sends_subcode_a0(self):
        """Subcode byte is 0xa0."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_a0(position=1000)

        args, _ = proto._issue_command.call_args
        assert args[0][2] == 0xA0


class TestVendorE0C1:
    """Frame select (VENDOR_E0 0xc1)."""

    def test_payload_structure(self):
        """Frame offset in byte 5 of payload."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_c1(frame_offset=0xE0)

        _, kwargs = proto._issue_command.call_args
        data = kwargs["data_out"]
        assert len(data) == 9
        assert data[5] == 0xE0
        assert data[:5] == b"\x00" * 5
        assert data[6:] == b"\x00" * 3

    def test_sends_subcode_c1(self):
        """Subcode byte is 0xc1."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_c1(frame_offset=0xE0)

        args, _ = proto._issue_command.call_args
        assert args[0][2] == 0xC1


class TestVendorE0D0:
    """Eject (VENDOR_E0 0xd0)."""

    def test_default_payload(self):
        """Default payload is common eject variant."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_d0()

        _, kwargs = proto._issue_command.call_args
        assert kwargs["data_out"] == bytes.fromhex("000000001000000000")

    def test_custom_payload(self):
        """Custom payload overrides default."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        custom = bytes.fromhex("000000000c0000000a")
        proto.vendor_e0_d0(custom)

        _, kwargs = proto._issue_command.call_args
        assert kwargs["data_out"] == custom

    def test_sends_subcode_d0(self):
        """Subcode byte is 0xd0."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._execute_command = Mock(return_value=True)

        proto.vendor_e0_d0()

        args, _ = proto._issue_command.call_args
        assert args[0][2] == 0xD0


# =========================================================================
# VENDOR_E1 command helpers
# =========================================================================

class TestVendorE1Generic:
    """Generic vendor_e1(subcode) contract tests."""

    def test_sends_correct_cdb(self):
        """vendor_e1 sends 10-byte CDB with subcode in byte 2."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"\x00" * 9, StatusType.READY))

        proto.vendor_e1(0x91)

        args, _ = proto._issue_command.call_args
        cmd = args[0]
        assert cmd[0] == 0xE1
        assert cmd[2] == 0x91

    def test_requests_9byte_response(self):
        """vendor_e1 reads 9 bytes of IN data."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"\x00" * 9, StatusType.READY))

        proto.vendor_e1(0xC1)

        _, kwargs = proto._issue_command.call_args
        assert kwargs["data_in_length"] == 9

    def test_returns_response(self):
        """vendor_e1 returns the 9-byte response."""
        proto = make_bare_protocol()
        expected = bytes(range(9))
        proto._issue_command = Mock(return_value=(expected, StatusType.READY))

        result = proto.vendor_e1(0x91)

        assert result == expected

    def test_returns_none_on_error(self):
        """vendor_e1 returns None when status is not READY."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))

        result = proto.vendor_e1(0x91)

        assert result is None

    def test_returns_none_on_short_response(self):
        """vendor_e1 returns None when response is < 9 bytes."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"\x00\x01", StatusType.READY))

        result = proto.vendor_e1(0x91)

        assert result is None


class TestVendorE1C1:
    """Get focus (VENDOR_E1 0xc1)."""

    def test_sends_subcode_c1(self):
        """Subcode byte is 0xc1."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"\x00" * 9, StatusType.READY))

        proto.vendor_e1_c1()

        args, _ = proto._issue_command.call_args
        assert args[0][2] == 0xC1


class TestVendorE191:
    """Densitometry/status gate (VENDOR_E1 0x91)."""

    def test_sends_subcode_91(self):
        """Subcode byte is 0x91."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"\x00" * 9, StatusType.READY))

        proto.vendor_e1_91()

        args, _ = proto._issue_command.call_args
        assert args[0][2] == 0x91


# =========================================================================
# WDB 58-byte builder
# =========================================================================

class TestWdb58Builder:
    """WindowDescriptorBlock.to_bytes_58() tests."""

    def test_produces_58_bytes(self):
        """to_bytes_58 returns exactly 58 bytes."""
        wdb = WindowDescriptorBlock()
        result = wdb.to_bytes_58()
        assert len(result) == 58

    def test_reserved_prefix_zeros(self):
        """Bytes 0-3 are zeros."""
        wdb = WindowDescriptorBlock()
        result = wdb.to_bytes_58()
        assert result[0:4] == b"\x00\x00\x00\x00"

    def test_window_id_50(self):
        """Bytes 4-7 are always 00000032 (= 50)."""
        wdb = WindowDescriptorBlock()
        result = wdb.to_bytes_58()
        assert result[4:8] == struct.pack(">I", 0x00000032)

    def test_channel_byte(self):
        """Byte 8 is the channel field."""
        wdb = WindowDescriptorBlock(channel=9)
        result = wdb.to_bytes_58()
        assert result[8] == 9

    def test_resolution_bytes(self):
        """Bytes 10-13 are x/y resolution."""
        wdb = WindowDescriptorBlock(x_resolution=2900, y_resolution=2900)
        result = wdb.to_bytes_58()
        assert result[10:12] == struct.pack(">H", 2900)
        assert result[12:14] == struct.pack(">H", 2900)

    def test_frame_offset(self):
        """Bytes 18-21 are frame offset."""
        wdb = WindowDescriptorBlock(frame_offset=0x0000010E)
        result = wdb.to_bytes_58()
        assert result[18:22] == struct.pack(">I", 0x0000010E)

    def test_width_bytes(self):
        """Bytes 22-25 are image width."""
        wdb = WindowDescriptorBlock(width=2870)
        result = wdb.to_bytes_58()
        assert result[22:26] == struct.pack(">I", 2870)

    def test_line_count(self):
        """Bytes 30-31 are line count."""
        wdb = WindowDescriptorBlock(length=4332)
        result = wdb.to_bytes_58()
        assert result[30:32] == struct.pack(">H", 4332)

    def test_mode_bytes(self):
        """Bytes 32-33 are mode."""
        wdb = WindowDescriptorBlock(wdb_mode=WDB_MODE_PRESCAN)
        result = wdb.to_bytes_58()
        assert result[32:34] == struct.pack(">H", WDB_MODE_PRESCAN)

    def test_transfer_byte(self):
        """Byte 34 is transfer byte."""
        wdb = WindowDescriptorBlock(transfer_byte=0x0C)
        result = wdb.to_bytes_58()
        assert result[34] == 0x0C

    def test_status_byte(self):
        """Byte 48 is status byte."""
        wdb = WindowDescriptorBlock(status_byte=0x03)
        result = wdb.to_bytes_58()
        assert result[48] == 0x03

    def test_film_flag(self):
        """Byte 49 is film/preview flag."""
        wdb = WindowDescriptorBlock(film_flag=0x81)
        result = wdb.to_bytes_58()
        assert result[49] == 0x81

    def test_sub_mode(self):
        """Byte 50 is sub-mode."""
        wdb = WindowDescriptorBlock(sub_mode=0x02)
        result = wdb.to_bytes_58()
        assert result[50] == 0x02

    def test_constant_tail(self):
        """Bytes 51-53 are 02 02 ff."""
        wdb = WindowDescriptorBlock()
        result = wdb.to_bytes_58()
        assert result[51:54] == bytes([0x02, 0x02, 0xFF])

    def test_exposure_bytes(self):
        """Bytes 54-57 are exposure."""
        wdb = WindowDescriptorBlock(exposure=0x00009A34)
        result = wdb.to_bytes_58()
        assert result[54:58] == struct.pack(">I", 0x00009A34)

    def test_reserved_bytes_are_zero(self):
        """Reserved bytes are zeros."""
        wdb = WindowDescriptorBlock()
        result = wdb.to_bytes_58()
        assert result[9] == 0
        assert result[14:18] == b"\x00" * 4
        assert result[26:30] == b"\x00" * 4
        assert result[35:48] == b"\x00" * 13


class TestWdb58FromBytes:
    """WindowDescriptorBlock.from_bytes_58() tests."""

    def test_parses_channel(self):
        """Channel byte is correctly parsed."""
        data = b"\x00" * 58
        data = data[:8] + bytes([9]) + data[9:]
        wdb = WindowDescriptorBlock.from_bytes_58(data)
        assert wdb.channel == 9

    def test_parses_resolution(self):
        """Resolution bytes are correctly parsed."""
        data = bytearray(58)
        data[10:12] = struct.pack(">H", 2900)
        data[12:14] = struct.pack(">H", 2900)
        wdb = WindowDescriptorBlock.from_bytes_58(bytes(data))
        assert wdb.x_resolution == 2900
        assert wdb.y_resolution == 2900

    def test_parses_frame_offset(self):
        """Frame offset is correctly parsed."""
        data = bytearray(58)
        data[18:22] = struct.pack(">I", 0x0000010E)
        wdb = WindowDescriptorBlock.from_bytes_58(bytes(data))
        assert wdb.frame_offset == 0x0000010E

    def test_parses_width(self):
        """Width is correctly parsed."""
        data = bytearray(58)
        data[22:26] = struct.pack(">I", 2870)
        wdb = WindowDescriptorBlock.from_bytes_58(bytes(data))
        assert wdb.width == 2870

    def test_parses_line_count(self):
        """Line count is correctly parsed."""
        data = bytearray(58)
        data[30:32] = struct.pack(">H", 4332)
        wdb = WindowDescriptorBlock.from_bytes_58(bytes(data))
        assert wdb.length == 4332

    def test_parses_mode(self):
        """Mode bytes are correctly parsed."""
        data = bytearray(58)
        data[32:34] = struct.pack(">H", WDB_MODE_PRESCAN)
        wdb = WindowDescriptorBlock.from_bytes_58(bytes(data))
        assert wdb.wdb_mode == WDB_MODE_PRESCAN

    def test_parses_transfer_byte(self):
        """Transfer byte is correctly parsed."""
        data = bytearray(58)
        data[34] = 0x0C
        wdb = WindowDescriptorBlock.from_bytes_58(bytes(data))
        assert wdb.transfer_byte == 0x0C

    def test_parses_film_flag(self):
        """Film flag is correctly parsed."""
        data = bytearray(58)
        data[49] = 0x80
        wdb = WindowDescriptorBlock.from_bytes_58(bytes(data))
        assert wdb.film_flag == 0x80

    def test_parses_exposure(self):
        """Exposure is correctly parsed."""
        data = bytearray(58)
        data[54:58] = struct.pack(">I", 0x0001C305)
        wdb = WindowDescriptorBlock.from_bytes_58(bytes(data))
        assert wdb.exposure == 0x0001C305

    def test_roundtrip(self):
        """to_bytes_58 -> from_bytes_58 preserves all fields."""
        original = WindowDescriptorBlock(
            channel=9,
            x_resolution=290,
            y_resolution=290,
            frame_offset=0x0000024E,
            width=2870,
            length=4332,
            wdb_mode=WDB_MODE_PREVIEW_MAIN,
            transfer_byte=0x0C,
            status_byte=0x00,
            film_flag=0x80,
            sub_mode=0x01,
            exposure=0x0001C305,
        )
        data = original.to_bytes_58()
        parsed = WindowDescriptorBlock.from_bytes_58(data)

        assert parsed.channel == original.channel
        assert parsed.x_resolution == original.x_resolution
        assert parsed.y_resolution == original.y_resolution
        assert parsed.frame_offset == original.frame_offset
        assert parsed.width == original.width
        assert parsed.length == original.length
        assert parsed.wdb_mode == original.wdb_mode
        assert parsed.transfer_byte == original.transfer_byte
        assert parsed.status_byte == original.status_byte
        assert parsed.film_flag == original.film_flag
        assert parsed.sub_mode == original.sub_mode
        assert parsed.exposure == original.exposure

    def test_rejects_short_data(self):
        """from_bytes_58 raises ValueError for short data."""
        with pytest.raises(ValueError, match="too short"):
            WindowDescriptorBlock.from_bytes_58(b"\x00" * 30)


# =========================================================================
# Constants verification
# =========================================================================

class TestWdbConstants:
    """Verify channel and WDB constants match capture values."""

    def test_channel_ids(self):
        assert CHANNEL_RED == 1
        assert CHANNEL_GREEN == 2
        assert CHANNEL_BLUE == 3
        assert CHANNEL_IR == 9

    def test_wdb_modes(self):
        assert WDB_MODE_PRESCAN == 0x0002
        assert WDB_MODE_PREVIEW_MAIN == 0x0005

    def test_wdb_transfer_bytes(self):
        assert WDB_TRANSFER_PRESCAN_MAIN == 0x08
        assert WDB_TRANSFER_LOW_RES_PREVIEW == 0x0C

    def test_wdb_film_flags(self):
        assert WDB_FILM_PRESCAN == 0x81
        assert WDB_FILM_IR_PREVIEW == 0x80
        assert WDB_FILM_MAIN_SCAN == 0x00

    def test_wdb_submodes(self):
        assert WDB_SUBMODE_PRESCAN_MAIN == 0x01
        assert WDB_SUBMODE_LOW_RES_96DPI == 0x02


# =========================================================================
# Analyzer command decoding
# =========================================================================

class TestAnalyzerDecoding:
    """Verify analyze_capture.py decodes new commands correctly."""

    def test_decode_vendore0_b4(self):
        from scripts.analyze_capture import decode_out_command

        raw = bytes([0xE0, 0x00, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
        result = decode_out_command(raw)

        assert result.cmd_name == "VENDOR_E0"
        assert "0xb4" in result.params["subcode"]
        assert "ice_setup" in result.params["subcode"]

    def test_decode_vendore0_b0(self):
        from scripts.analyze_capture import decode_out_command

        raw = bytes([0xE0, 0x00, 0xB0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
        result = decode_out_command(raw)

        assert result.cmd_name == "VENDOR_E0"
        assert "0xb0" in result.params["subcode"]
        assert "calibrate" in result.params["subcode"]

    def test_decode_vendore0_a0(self):
        from scripts.analyze_capture import decode_out_command

        raw = bytes([0xE0, 0x00, 0xA0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
        result = decode_out_command(raw)

        assert result.cmd_name == "VENDOR_E0"
        assert "0xa0" in result.params["subcode"]
        assert "autofocus" in result.params["subcode"]

    def test_decode_vendore0_c1(self):
        from scripts.analyze_capture import decode_out_command

        raw = bytes([0xE0, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
        result = decode_out_command(raw)

        assert result.cmd_name == "VENDOR_E0"
        assert "0xc1" in result.params["subcode"]
        assert "frame_select" in result.params["subcode"]

    def test_decode_vendore0_d0(self):
        from scripts.analyze_capture import decode_out_command

        raw = bytes([0xE0, 0x00, 0xD0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
        result = decode_out_command(raw)

        assert result.cmd_name == "VENDOR_E0"
        assert "0xd0" in result.params["subcode"]
        assert "eject" in result.params["subcode"]

    def test_decode_vendore1_91(self):
        from scripts.analyze_capture import decode_out_command

        raw = bytes([0xE1, 0x00, 0x91, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
        result = decode_out_command(raw)

        assert result.cmd_name == "VENDOR_E1"
        assert "0x91" in result.params["subcode"]
        assert "densitometry" in result.params["subcode"]

    def test_decode_vendore1_c1(self):
        from scripts.analyze_capture import decode_out_command

        raw = bytes([0xE1, 0x00, 0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00])
        result = decode_out_command(raw)

        assert result.cmd_name == "VENDOR_E1"
        assert "0xc1" in result.params["subcode"]
        assert "get_focus" in result.params["subcode"]

    def test_decode_wdb58(self):
        from scripts.analyze_capture import decode_out_command

        # Build a minimal 58-byte WDB
        data = bytearray(58)
        data[8] = 1  # channel R
        data[10:12] = struct.pack(">H", 2900)  # 2900 DPI
        data[22:26] = struct.pack(">I", 2870)  # width
        data[30:32] = struct.pack(">H", 4332)  # lines
        data[32:34] = struct.pack(">H", 0x0002)  # prescan mode

        result = decode_out_command(bytes(data))

        assert result.cmd_name == "DATA_OUT(WDB58)"
        assert "R" in result.params["channel"]
        assert "2900" in result.params["resolution"]
        assert "prescan" in result.params["mode"]

    def test_decode_channel_list_with_ir(self):
        from scripts.analyze_capture import decode_out_command

        # Channel list 09 01 02 03 (IR, R, G, B)
        raw = bytes([0x09, 0x01, 0x02, 0x03])
        result = decode_out_command(raw)

        assert result.cmd_name == "SHORT_OUT"
        assert result.params.get("has_ir") is True

    def test_read_capacity_channel_name(self):
        from scripts.analyze_capture import decode_out_command

        # READ_CAPACITY for channel 9 (IR)
        raw = bytes([0x25, 0x09, 0x00, 0x00, 0x00, 0x09, 0x00, 0x00, 0x3A, 0x80])
        result = decode_out_command(raw)

        assert result.cmd_name == "READ_CAPACITY"
        assert "IR" in result.params["channel"]
        assert "9" in result.params["channel"]

    def test_write_8f_flagged(self):
        from scripts.analyze_capture import decode_out_command

        # WRITE 0x8f
        raw = bytes.fromhex("2a008f00000300003400")
        result = decode_out_command(raw)

        assert result.params.get("purpose") == "frame_table"


# =========================================================================
# Channel constants
# =========================================================================

@pytest.mark.property_test
class TestChannelConstants:
    """Verify channel constants match capture-derived values."""

    def test_channel_red_is_1(self):
        assert CHANNEL_RED == 1

    def test_channel_green_is_2(self):
        assert CHANNEL_GREEN == 2

    def test_channel_blue_is_3(self):
        assert CHANNEL_BLUE == 3

    def test_channel_ir_is_9(self):
        assert CHANNEL_IR == 9
