"""Contract tests for protocol behavior (migrated from replay-based tests).

Verifies CDB construction, status parsing, payload sizes, call sequences,
WDB structure, and batch control logic — all using mocked _issue_command.

No USB replay, no byte-level event construction.

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

import struct
from unittest.mock import Mock, patch

import pytest

from coolscan.protocol import (
    CoolscanProtocol,
    DataType,
    StatusType,
)
from tests.fakes import make_bare_protocol


# =========================================================================
# CDB construction
# =========================================================================

@pytest.mark.property_test
class TestCdbConstruction:
    """Verify CDB byte layouts for SCSI commands."""

    def test_inquiry_cdb_standard_36_bytes(self):
        """Standard INQUIRY produces 6-byte CDB requesting 36 bytes."""
        proto = make_bare_protocol()
        cmd = proto._build_6byte_command(0x12, page=0x00, alloc_length=0x24, control=0x80)
        assert len(cmd) == 6
        assert cmd[0] == 0x12
        assert cmd[4] == 0x24  # 36 bytes
        assert cmd[5] == 0x80

    def test_read_capacity_cdb_format(self):
        """READ_CAPACITY produces 10-byte CDB."""
        cmd = struct.pack(
            "BBBBBBBBBB", 0x25, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3A, 0x80
        )
        assert len(cmd) == 10
        assert cmd[0] == 0x25

    def test_read_scan_data_cdb_10_byte(self):
        """read_scan_data builds a 10-byte READ(10) CDB."""
        cmd = struct.pack(
            "BBBBBBBBBB",
            0x28, 0x00, DataType.IMAGE_DATA.value, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x40, 0x80,
        )
        assert len(cmd) == 10
        assert cmd[0] == 0x28
        assert cmd[2] == DataType.IMAGE_DATA.value

    def test_set_window_cdb_format(self):
        """SET_WINDOW CDB has the correct opcode and structure."""
        cmd_hex = "24000000000000003a80"
        expected = struct.pack(
            "BBBBBBBBBB", 0x24, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3A, 0x80
        )
        assert expected.hex() == cmd_hex

    def test_read_focus_info_cdb_format(self):
        """read_focus_info sends e1/91 READ(10) requesting 9 bytes."""
        focus_info_cmd = struct.pack(
            "BBBBBBBBBB", 0xE1, 0x00, 0x91, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x00
        )
        assert len(focus_info_cmd) == 10
        assert focus_info_cmd[0] == 0xE1
        assert focus_info_cmd[2] == 0x91
        assert focus_info_cmd[8] == 0x09

    def test_read_control_params_cdb_format(self):
        """read_control_params sends MODE SENSE(10) for page 0x8f, 52 bytes."""
        ctrl_params_cmd = struct.pack(
            "BBBBBBBBBB", 0x1A, 0x00, 0x8F, 0x00, 0x00, 0x03, 0x00, 0x00, 0x34, 0x00
        )
        assert len(ctrl_params_cmd) == 10
        assert ctrl_params_cmd[0] == 0x1A
        assert ctrl_params_cmd[2] == 0x8F
        assert ctrl_params_cmd[8] == 0x34


# =========================================================================
# Status parsing
# =========================================================================

@pytest.mark.property_test
class TestStatusParsing:
    """Verify _parse_status decodes sense data correctly."""

    def test_parse_ready(self):
        """8-byte all-zeros status parses as READY."""
        proto = make_bare_protocol()
        status, _ = proto._parse_status(b"\x00" * 8)
        assert status == StatusType.READY

    def test_parse_reissue(self):
        """Sense key 0x09 + ASC 0x80 + ASCQ 0x06 parses as REISSUE."""
        proto = make_bare_protocol()
        status, _ = proto._parse_status(bytes([0x02, 0x09, 0x80, 0x06, 0x00, 0x00, 0x00, 0x00]))
        assert status == StatusType.REISSUE
        status2, _ = proto._parse_status(bytes([0x02, 0x09, 0x80, 0x06, 0x01, 0x00, 0x00, 0x00]))
        assert status2 == StatusType.REISSUE

    def test_parse_processing(self):
        """Sense key 0x02 + ASC 0x04 + ASCQ 0x01 parses as PROCESSING."""
        proto = make_bare_protocol()
        status, _ = proto._parse_status(bytes([0x02, 0x02, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00]))
        assert status == StatusType.PROCESSING


# =========================================================================
# LUT generation
# =========================================================================

@pytest.mark.property_test
class TestLutGeneration:
    """LUT size matches maxbits configuration."""

    def test_lut_12bit_size(self):
        """LUT upload with 12-bit maxbits produces 8192 bytes."""
        proto = make_bare_protocol(maxbits=12)
        lut = proto._generate_identity_lut()
        assert len(lut) == 2 * (1 << 12)

    def test_lut_11bit_size(self):
        """LUT upload with 11-bit maxbits produces 4096 bytes."""
        proto = make_bare_protocol(maxbits=11)
        lut = proto._generate_identity_lut()
        assert len(lut) == 2 * (1 << 11)


# =========================================================================
# Sequence verification
# =========================================================================

@pytest.mark.property_test
class TestSequenceContracts:
    """Verify method call ordering and payload structure."""

    def test_auto_focus_payload_is_9_bytes(self):
        """auto_focus sends 9-byte payload: 0x00 prefix + focusx(4) + focusy(4)."""
        focus_x, focus_y = 0x0000059B, 0x00000AC4
        expected = b"\x00" + struct.pack(">II", focus_x, focus_y)
        assert len(expected) == 9
        assert expected[0] == 0x00
        assert struct.unpack(">I", expected[1:5])[0] == focus_x
        assert struct.unpack(">I", expected[5:9])[0] == focus_y

    def test_session_has_one_reserve_unit(self):
        """A session issues exactly one RESERVE_UNIT before the first scan."""
        proto = make_bare_protocol()
        reserve_count = 0

        def counting_issue(cmd, data_out=b"", data_in_length=0):
            nonlocal reserve_count
            if cmd and len(cmd) >= 1 and cmd[0] == 0x16:
                reserve_count += 1
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=counting_issue)
        proto.reserve_unit()
        proto.start_scan()

        assert reserve_count == 1


# =========================================================================
# WDB structure
# =========================================================================

@pytest.mark.property_test
class TestWdbStructure:
    """WDB byte layout and parameter propagation."""

    def test_wdb_depth_byte_8bit(self):
        """WDB byte 34 (bits_per_pixel) is 0x08 for normal scan with depth=8."""
        proto = make_bare_protocol()
        captured_wdb = []

        def capture_issue(cmd, data_out=b"", data_in_length=0):
            captured_wdb.append(data_out)
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=capture_issue)
        proto.set_scan_window(1, scan_type="normal", depth=8)

        wdb = captured_wdb[-1]
        assert len(wdb) == 58
        assert wdb[34] == 0x08

    def test_wdb_depth_byte_12bit(self):
        """WDB byte 34 (bits_per_pixel) is 0x0c for normal scan with depth=12."""
        proto = make_bare_protocol()
        captured_wdb = []

        def capture_issue(cmd, data_out=b"", data_in_length=0):
            captured_wdb.append(data_out)
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=capture_issue)
        proto.set_scan_window(1, scan_type="normal", depth=12)

        wdb = captured_wdb[-1]
        assert len(wdb) == 58
        assert wdb[34] == 0x0C

    def test_wdb_prescan_depth_unchanged(self):
        """Prescan WDB byte 34 remains 0x0c regardless of depth parameter."""
        proto = make_bare_protocol()
        captured_wdb = []

        def capture_issue(cmd, data_out=b"", data_in_length=0):
            captured_wdb.append(data_out)
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=capture_issue)
        proto.set_scan_window(1, scan_type="prescan", depth=8)

        wdb = captured_wdb[-1]
        assert len(wdb) == 58
        assert wdb[34] == 0x0C

    def test_set_scan_window_wdb_length_and_window_id(self):
        """SET_WINDOW always sends a 58-byte WDB with window_id at byte 8."""
        proto = make_bare_protocol()

        valid_cases = [
            ("prescan", [1, 2, 3]),
            ("normal", [1, 2, 3, 9]),
            ("setup", [9, 1, 2, 3]),
            ("batch", [9, 1, 2, 3]),
            ("batch_between", [1, 2, 3]),
        ]

        for scan_type, window_ids in valid_cases:
            for window_id in window_ids:
                captured = []

                def capture_issue(cmd, data_out=b"", data_in_length=0):
                    captured.append((cmd, data_out))
                    return (b"", StatusType.READY)

                proto._issue_command = Mock(side_effect=capture_issue)
                proto.set_scan_window(window_id=window_id, scan_type=scan_type)

                assert len(captured) == 1, f"{scan_type}/{window_id}: expected one SET_WINDOW call"
                cmd, wdb = captured[0]
                assert cmd[0] == 0x24, f"{scan_type}/{window_id}: expected SET_WINDOW opcode 0x24"
                assert len(wdb) == 58, f"{scan_type}/{window_id}: WDB length {len(wdb)} != 58"
                assert wdb[8] == window_id, f"{scan_type}/{window_id}: WDB byte 8 0x{wdb[8]:02x} != {window_id}"

    def test_upload_identity_luts_chunk_count(self):
        """upload_identity_luts sends 3 (RGB) or 4 (RGB+IR) chunks of 8192 bytes."""
        proto = make_bare_protocol()

        for include_ir, expected_count in [(False, 3), (True, 4)]:
            captured = []

            def capture_issue(cmd, data_out=b"", data_in_length=0):
                captured.append((cmd, data_out))
                return (b"", StatusType.READY)

            proto._issue_command = Mock(side_effect=capture_issue)
            proto.upload_identity_luts(include_ir=include_ir)

            data_outs = [d for _, d in captured if len(d) > 0]
            assert len(data_outs) == expected_count, (
                f"include_ir={include_ir}: expected {expected_count} LUT chunks, got {len(data_outs)}"
            )
            for idx, payload in enumerate(data_outs):
                assert len(payload) == 8192, f"include_ir={include_ir} chunk {idx}: {len(payload)} != 8192"

    def test_read_scan_data_uses_correct_datatype(self):
        """Image data READ(10) uses datatype 0x00; status/progress uses 0x87."""
        proto = make_bare_protocol()
        captured = []

        def capture_issue(cmd, data_out=b"", data_in_length=0):
            captured.append(cmd)
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=capture_issue)
        proto.read_scan_data(64, DataType.IMAGE_DATA)
        proto.read_scan_data(6, DataType.STATUS_PROGRESS)

        assert len(captured) == 2
        assert captured[0][2] == DataType.IMAGE_DATA.value
        assert captured[1][2] == DataType.STATUS_PROGRESS.value


# =========================================================================
# WDB builder
# =========================================================================

@pytest.mark.property_test
class TestWdbBuilder:
    """_build_scan_window_wdb and set_scan_window integration."""

    def test_build_wdb_matches_hardcoded_tables(self):
        """_build_scan_window_wdb reproduces hardcoded tables for default depth=8."""
        from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

        proto = make_bare_protocol()

        for scan_type, windows in _SCAN_WINDOW_WDB_TABLES.items():
            for window_id, expected_bytes in windows.items():
                built = proto._build_scan_window_wdb(window_id, scan_type, depth=8)
                assert built is not None, f"{scan_type}/{window_id}: builder returned None"
                assert len(built) == 58
                assert built == expected_bytes

    def test_build_wdb_depth_12bit(self):
        """_build_scan_window_wdb sets byte 34 to 0x0C for normal/single_bw RGB with depth=12."""
        from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

        proto = make_bare_protocol()

        for scan_type in ("normal", "single_bw"):
            for window_id in [1, 2, 3]:
                built = proto._build_scan_window_wdb(window_id, scan_type, depth=12)
                assert built is not None
                assert built[34] == 0x0C

    def test_build_wdb_preserves_ir_depth(self):
        """IR window (9) in normal keeps capture-derived depth, not overridden."""
        from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

        proto = make_bare_protocol()
        built = proto._build_scan_window_wdb(9, "normal", depth=8)
        expected = _SCAN_WINDOW_WDB_TABLES["normal"][9]
        assert built is not None
        assert built[34] == expected[34]
        assert built == expected

    def test_build_wdb_unknown_returns_none(self):
        """_build_scan_window_wdb returns None for invalid combinations."""
        proto = make_bare_protocol()
        assert proto._build_scan_window_wdb(9, "prescan", 8) is None
        assert proto._build_scan_window_wdb(5, "normal", 8) is None
        assert proto._build_scan_window_wdb(1, "invalid", 8) is None

    def test_set_scan_window_integration(self):
        """set_scan_window produces the same WDB as hardcoded tables."""
        from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

        proto = make_bare_protocol()
        captured_wdb = []

        def capture_issue(cmd, data_out=b"", data_in_length=0):
            captured_wdb.append(data_out)
            return (b"", StatusType.READY)

        valid_cases = [
            ("prescan", [1, 2, 3]),
            ("setup", [9, 1, 2, 3]),
            ("single_bw", [1, 2, 3]),
            ("normal", [1, 2, 3, 9]),
            ("batch", [9, 1, 2, 3]),
            ("batch_between", [1, 2, 3]),
        ]

        for scan_type, window_ids in valid_cases:
            for window_id in window_ids:
                captured_wdb.clear()
                proto._issue_command = Mock(side_effect=capture_issue)
                proto.set_scan_window(window_id=window_id, scan_type=scan_type)

                assert len(captured_wdb) == 1
                built_wdb = captured_wdb[0]
                expected = _SCAN_WINDOW_WDB_TABLES[scan_type][window_id]
                assert len(built_wdb) == 58
                assert built_wdb == expected

    def test_wdb_y_offset_and_height(self):
        """_build_scan_window_wdb writes y_offset and height to correct offsets."""
        from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

        proto = make_bare_protocol()
        base = _SCAN_WINDOW_WDB_TABLES["batch"][9]
        built = proto._build_scan_window_wdb(9, "batch", depth=8, y_offset=30, height=4332)
        assert built is not None

        assert built[14:18] == base[14:18]  # ulx preserved
        assert built[22:26] == base[22:26]  # width preserved
        assert struct.unpack(">I", built[18:22])[0] == 30  # y_offset
        assert struct.unpack(">I", built[26:30])[0] == 4332  # height
        assert built[28:32] == base[28:32]  # preserved

    def test_wdb_batch_window_9_golden_geometry(self):
        """Batch window 9 with y_offset=30, height=4332 matches golden fixture."""
        from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES

        proto = make_bare_protocol()
        expected = _SCAN_WINDOW_WDB_TABLES["batch"][9]
        built = proto._build_scan_window_wdb(9, "batch", depth=8, y_offset=30, height=4332)
        assert built == expected


# =========================================================================
# Batch control frame
# =========================================================================

@pytest.mark.property_test
class TestControlFrame:
    """_build_control_frame_payload and _control_frame_positions."""

    def test_control_frame_default_geometry(self):
        """Default 6-frame batch geometry produces 52-byte payload."""
        payload = CoolscanProtocol._build_control_frame_payload(
            frame_count=6, first_y=30, frame_height=4332, step=4330
        )
        assert len(payload) == 52
        assert payload[:4] == b"\x00\x32\x06\x00"

        y_start_0 = struct.unpack(">I", payload[4:8])[0]
        assert y_start_0 == 30
        assert struct.unpack(">I", payload[8:12])[0] == 0x00000006
        assert struct.unpack(">I", payload[12:16])[0] == 4380
        assert struct.unpack(">I", payload[16:20])[0] == 0x0008000c

    def test_control_frame_x_fields_match_fixture(self):
        """X fields match golden_batch.txt pattern."""
        payload = CoolscanProtocol._build_control_frame_payload(
            frame_count=6, first_y=30, frame_height=4332, step=4330
        )
        x1_values = [
            struct.unpack(">I", payload[8:12])[0],
            struct.unpack(">I", payload[24:28])[0],
            struct.unpack(">I", payload[40:44])[0],
        ]
        assert x1_values == [0x00000006, 0x0010000e, 0x00200014]

        x2_values = [
            struct.unpack(">I", payload[16:20])[0],
            struct.unpack(">I", payload[32:36])[0],
            struct.unpack(">I", payload[48:52])[0],
        ]
        assert x2_values == [0x0008000c, 0x0018000c, 0x00280010]

    def test_control_frame_single_frame(self):
        """frame_count=1 produces one entry, padded to 52 bytes."""
        payload = CoolscanProtocol._build_control_frame_payload(
            frame_count=1, first_y=100, frame_height=5000, step=5000
        )
        assert len(payload) == 52
        assert payload[:4] == b"\x00\x32\x06\x00"
        assert struct.unpack(">I", payload[4:8])[0] == 100
        assert struct.unpack(">I", payload[12:16])[0] == 10100
        assert payload[20:52] == b"\x00" * 32

    def test_control_frame_custom_geometry(self):
        """Non-default geometry with every-2-frames pattern."""
        payload = CoolscanProtocol._build_control_frame_payload(
            frame_count=4, first_y=50, frame_height=4000, step=4100
        )
        assert len(payload) == 52
        assert struct.unpack(">I", payload[4:8])[0] == 50
        assert struct.unpack(">I", payload[12:16])[0] == 8250
        assert struct.unpack(">I", payload[20:24])[0] == 8250
        assert struct.unpack(">I", payload[28:32])[0] == 16450

    def test_control_frame_positions_default(self):
        """Default 6-frame geometry returns golden positions."""
        positions = CoolscanProtocol._control_frame_positions(
            frame_count=6, first_y=30, frame_height=4332, step=4330
        )
        assert positions == [30, 4380, 8710, 13020, 17380, 21680]

    def test_control_frame_positions_partial(self):
        """frame_count < 6 with default geometry slices golden positions."""
        positions = CoolscanProtocol._control_frame_positions(
            frame_count=3, first_y=30, frame_height=4332, step=4330
        )
        assert positions == [30, 4380, 8710]

    def test_control_frame_positions_non_default(self):
        """Non-default geometry falls back to formula."""
        positions = CoolscanProtocol._control_frame_positions(
            frame_count=4, first_y=100, frame_height=4000, step=4100
        )
        assert positions == [100, 4200, 8300, 12400]


# =========================================================================
# Batch frame count estimation
# =========================================================================

@pytest.mark.property_test
class TestBatchFrameEstimation:
    """batch_scan_to_frames frame count estimation."""

    def test_frame_count_from_wdb_length(self):
        """Estimates frame count from WDB length field, not uly."""
        from coolscan.protocol import _SCAN_WINDOW_WDB_TABLES
        from contextlib import ExitStack

        proto = make_bare_protocol()
        prescan_wdb = bytearray(_SCAN_WINDOW_WDB_TABLES["prescan"][1])
        assert struct.unpack(">I", prescan_wdb[18:22])[0] == 0  # uly
        assert struct.unpack(">I", prescan_wdb[26:30])[0] == 34656  # length

        proto._last_prescan_image_data = b"dummy"

        return_values = {
            "prescan": True,
            "set_boundary": True,
            "batch_full_scan_setup_frame": True,
            "start_scan": True,
            "batch_full_scan_capture_frame": b"",
            "_wait_ready_or_replay_once": True,
            "stop_scan": True,
            "batch_between_scan_setup_frame": True,
            "batch_preview_capture_frame": b"",
            "set_scan_window": True,
            "upload_identity_luts": True,
            "poll_until_ready": True,
            "batch_full_res_capture_frame": b"",
            "post_prescan_autofocus": None,
            "scan_teardown": True,
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(proto, "get_window", return_value=bytes(prescan_wdb)))
            for name, value in return_values.items():
                stack.enter_context(patch.object(proto, name, return_value=value))
            results = list(
                proto.batch_scan_to_frames(
                    frame_count=6, first_y=30, frame_height=4332, step=4330
                )
            )
            assert len(results) == 6
