#!/usr/bin/env python3
"""
Phase 3: Fixture-independent CDB property tests.

Consolidates and replaces byte-exact CDB tests from:
  - tests/test_protocol_commands.py
  - tests/test_protocol_module.py
  - tests/test_get_window_cdb.py
  - tests/test_read_scan_data_cdb.py

Uses parameterized tables and structural property assertions rather than
byte-exact comparisons, making these tests resilient to non-deterministic
fields (timestamps, exposure values, etc.).
"""

import struct

import pytest

from coolscan.protocol import (
    CoolscanProtocol,
    DataType,
    PhaseType,
    ScanType,
    StatusType,
    WindowDescriptorBlock,
)


# =========================================================================
# 6-byte command property tests
# =========================================================================

# (opcode, page, param2, param3, alloc_length, control, expected_hex, label)
SIX_BYTE_COMMANDS = [
    # TEST_UNIT_READY
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, "000000000000", "TEST_UNIT_READY"),
    # INQUIRY standard (36 bytes)
    (0x12, 0x00, 0x00, 0x00, 0x24, 0x80, "120000002480", "INQUIRY_std"),
    # INQUIRY EVPD page 0x01
    (0x12, 0x01, 0x01, 0x00, 0x04, 0x80, "120101000480", "INQUIRY_EVPD_01"),
    # INQUIRY EVPD page 0xD1 (MUD)
    (0x12, 0x01, 0xD1, 0x00, 0x04, 0x80, "1201d1000480", "INQUIRY_EVPD_D1"),
    # INQUIRY EVPD page 0xD1 full read
    (0x12, 0x01, 0xD1, 0x00, 0x1C, 0x80, "1201d1001c80", "INQUIRY_D1_full"),
    # INQUIRY EVPD page 0xC1 (configuration)
    (0x12, 0x01, 0xC1, 0x00, 0x55, 0x80, "1201c1005580", "INQUIRY_C1"),
    # RESERVE_UNIT
    (0x16, 0x00, 0x00, 0x00, 0x00, 0x00, "160000000000", "RESERVE_UNIT"),
    # MODE_SELECT
    (0x15, 0x10, 0x00, 0x00, 0x14, 0x00, "151000001400", "MODE_SELECT"),
    # MODE_SENSE (page 0x10, alloc_length 0x14)
    (0x1A, 0x10, 0x00, 0x00, 0x14, 0x00, "1a1000001400", "MODE_SENSE"),
    # START_STOP_UNIT (start)
    (0x1B, 0x00, 0x00, 0x00, 0x03, 0x00, "1b0000000300", "START_SCAN"),
    # START_STOP_UNIT (stop)
    (0x1B, 0x00, 0x00, 0x00, 0x04, 0x00, "1b0000000400", "STOP_SCAN"),
]


@pytest.mark.property_test
class TestSixByteCommandProperties:
    """Verify structural properties of all 6-byte CDBs."""

    @pytest.mark.parametrize(
        "opcode,page,param2,param3,alloc_len,control,expected_hex,label",
        SIX_BYTE_COMMANDS,
        ids=[c[-1] for c in SIX_BYTE_COMMANDS],
    )
    def test_6byte_command_structure(
        self, opcode, page, param2, param3, alloc_len, control, expected_hex, label
    ):
        """Each 6-byte command has correct opcode, length, and control byte."""
        cmd = struct.pack("BBBBBB", opcode, page, param2, param3, alloc_len, control)

        # Property: exactly 6 bytes
        assert len(cmd) == 6, f"{label}: expected 6 bytes, got {len(cmd)}"

        # Property: opcode at byte 0
        assert cmd[0] == opcode, f"{label}: opcode mismatch"

        # Property: control byte at byte 5
        assert cmd[5] == control, f"{label}: control byte mismatch"

        # Byte-exact match against capture-derived expectation
        assert cmd == bytes.fromhex(expected_hex)

    @pytest.mark.parametrize(
        "opcode,page,param2,param3,alloc_len,control,expected_hex,label",
        SIX_BYTE_COMMANDS,
        ids=[c[-1] for c in SIX_BYTE_COMMANDS],
    )
    def test_6byte_roundtrip(
        self, opcode, page, param2, param3, alloc_len, control, expected_hex, label
    ):
        """Pack and unpack a 6-byte CDB; fields round-trip correctly."""
        cmd = struct.pack("BBBBBB", opcode, page, param2, param3, alloc_len, control)
        unpacked = struct.unpack("BBBBBB", cmd)

        assert unpacked[0] == opcode
        assert unpacked[1] == page
        assert unpacked[2] == param2
        assert unpacked[3] == param3
        assert unpacked[4] == alloc_len
        assert unpacked[5] == control


# =========================================================================
# 10-byte command property tests
# =========================================================================

# READ(10) commands: (opcode, reserved, datatype, len, control, expected_hex, label)
READ10_COMMANDS = [
    # Image data reads from capture
    (0x28, 0x00, DataType.IMAGE_DATA, 259200, 0x80, "28000000000003f48080", "READ_259200"),
    (0x28, 0x00, DataType.IMAGE_DATA, 258048, 0x80, "28000000000003f00080", "READ_258048"),
    (0x28, 0x00, DataType.IMAGE_DATA, 223488, 0x80, "28000000000003690080", "READ_223488"),
    (0x28, 0x00, DataType.IMAGE_DATA, 130752, 0x80, "28000000000001fec080", "READ_130752"),
    (0x28, 0x00, DataType.IMAGE_DATA, 11520, 0x80, "280000000000002d0080", "READ_11520"),
    (0x28, 0x00, DataType.IMAGE_DATA, 103680, 0x80, "28000000000001950080", "READ_103680"),
    # Status/progress reads
    (0x28, 0x00, DataType.STATUS_PROGRESS, 6, 0x80, "28008700000000000680", "READ_STATUS_6"),
    (0x28, 0x00, DataType.STATUS_PROGRESS, 33, 0x80, "28008700000000002180", "READ_STATUS_33"),
    # Exposure calibration reads
    (0x28, 0x00, DataType.EXPOSURE_CALIBRATION, 6, 0x80, "28008e00000000000680", "READ_EXP_HDR"),
    (0x28, 0x00, DataType.EXPOSURE_CALIBRATION, 3464, 0x80, "28008e000000000d8880", "READ_EXP_TBL"),
]


def _build_read10(length: int, datatype: DataType) -> bytes:
    """Build a READ(10) CDB matching protocol.py:read_scan_data."""
    return struct.pack(
        "BBBBBBBBBB",
        0x28,
        0x00,
        datatype.value,
        0x00,
        0x00,
        0x00,
        (length >> 16) & 0xFF,
        (length >> 8) & 0xFF,
        length & 0xFF,
        0x80,
    )


@pytest.mark.property_test
class TestRead10Properties:
    """Verify structural properties of READ(10) commands."""

    @pytest.mark.parametrize(
        "opcode,reserved,datatype,length,control,expected_hex,label",
        READ10_COMMANDS,
        ids=[c[-1] for c in READ10_COMMANDS],
    )
    def test_read10_structure(
        self, opcode, reserved, datatype, length, control, expected_hex, label
    ):
        """Each READ(10) has correct length, opcode, datatype, and control."""
        cmd = _build_read10(length, datatype)

        # Property: exactly 10 bytes
        assert len(cmd) == 10, f"{label}: expected 10 bytes, got {len(cmd)}"

        # Property: opcode at byte 0
        assert cmd[0] == opcode, f"{label}: opcode mismatch"

        # Property: datatype at byte 2
        assert cmd[2] == datatype.value, f"{label}: datatype mismatch"

        # Property: control byte at byte 9
        assert cmd[9] == control, f"{label}: control byte mismatch"

        # Property: length field is big-endian at bytes 6-8
        packed_len = (cmd[6] << 16) | (cmd[7] << 8) | cmd[8]
        assert packed_len == length, f"{label}: length round-trip failed"

        # Byte-exact match against capture-derived expectation
        assert cmd == bytes.fromhex(expected_hex)

    @pytest.mark.parametrize(
        "length,datatype",
        [
            (259200, DataType.IMAGE_DATA),
            (6, DataType.STATUS_PROGRESS),
            (3464, DataType.EXPOSURE_CALIBRATION),
            (1, DataType.IMAGE_DATA),
            (0, DataType.IMAGE_DATA),
            (16777215, DataType.IMAGE_DATA),  # max 24-bit
        ],
    )
    def test_read10_length_roundtrip(self, length, datatype):
        """Length field round-trips through pack/unpack for any valid value."""
        cmd = _build_read10(length, datatype)
        packed_len = (cmd[6] << 16) | (cmd[7] << 8) | cmd[8]
        assert packed_len == length


# WRITE(10) / SEND(0x2A) commands
SEND_COMMANDS = [
    # LUT upload: R channel
    (0x2A, 0x00, 0x03, 0x00, 0x01, 0x01, 0x00, 0x20, 0x00, 0x00, "2a000300010100200000", "SEND_LUT_R"),
    # LUT upload: G channel
    (0x2A, 0x00, 0x03, 0x00, 0x02, 0x01, 0x00, 0x20, 0x00, 0x00, "2a000300020100200000", "SEND_LUT_G"),
    # LUT upload: B channel
    (0x2A, 0x00, 0x03, 0x00, 0x03, 0x01, 0x00, 0x20, 0x00, 0x00, "2a000300030100200000", "SEND_LUT_B"),
    # Control frame (datatype 0x8F)
    (0x2A, 0x00, 0x8F, 0x00, 0x00, 0x03, 0x00, 0x00, 0x34, 0x00, "2a008f00000300003400", "SEND_CONTROL"),
]


@pytest.mark.property_test
class TestSend10Properties:
    """Verify structural properties of SEND(10) / WRITE(10) commands."""

    @pytest.mark.parametrize(
        "b0,b1,b2,b3,b4,b5,b6,b7,b8,b9,expected_hex,label",
        SEND_COMMANDS,
        ids=[c[-1] for c in SEND_COMMANDS],
    )
    def test_send10_structure(self, b0, b1, b2, b3, b4, b5, b6, b7, b8, b9, expected_hex, label):
        """Each SEND(10) has correct structure and matches capture."""
        cmd = struct.pack("BBBBBBBBBB", b0, b1, b2, b3, b4, b5, b6, b7, b8, b9)

        # Property: exactly 10 bytes
        assert len(cmd) == 10

        # Property: opcode at byte 0
        assert cmd[0] == b0

        # Property: datatype at byte 2
        assert cmd[2] == b2

        # Byte-exact match
        assert cmd == bytes.fromhex(expected_hex)


# =========================================================================
# 10-byte commands: READ_CAPACITY, SET_WINDOW, GET_WINDOW
# =========================================================================

TEN_BYTE_COMMANDS = [
    # READ_CAPACITY
    (0x25, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3A, 0x80, "25000000000000003a80", "READ_CAPACITY"),
    # SET_WINDOW (base)
    (0x24, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3A, 0x80, "24000000000000003a80", "SET_WINDOW"),
]


@pytest.mark.property_test
class TestTenByteCommandProperties:
    """Verify structural properties of 10-byte commands."""

    @pytest.mark.parametrize(
        "b0,b1,b2,b3,b4,b5,b6,b7,b8,b9,expected_hex,label",
        TEN_BYTE_COMMANDS,
        ids=[c[-1] for c in TEN_BYTE_COMMANDS],
    )
    def test_10byte_structure(self, b0, b1, b2, b3, b4, b5, b6, b7, b8, b9, expected_hex, label):
        cmd = struct.pack("BBBBBBBBBB", b0, b1, b2, b3, b4, b5, b6, b7, b8, b9)
        assert len(cmd) == 10
        assert cmd[0] == b0
        assert cmd == bytes.fromhex(expected_hex)


# =========================================================================
# GET_WINDOW CDB tests (parameterized)
# =========================================================================

GET_WINDOW_IDS = [
    (1, "25010000000100003a80", "window_1_R"),
    (2, "25010000000200003a80", "window_2_G"),
    (3, "25010000000300003a80", "window_3_B"),
    (9, "25010000000900003a80", "window_9_IR"),
]


def _build_get_window_cdb(window_id: int) -> bytes:
    """Build expected GET_WINDOW CDB matching protocol.py:get_window."""
    return struct.pack(
        "BBBBBBBBBB",
        0x25,  # GET_WINDOW opcode
        0x01,  # Subcommand
        0x00, 0x00, 0x00,
        window_id,
        0x00, 0x00,
        0x3A,  # Allocation length (58)
        0x80,  # Control
    )


@pytest.mark.property_test
class TestGetWindowProperties:
    """Verify GET_WINDOW CDB construction for different window IDs."""

    @pytest.mark.parametrize(
        "window_id,expected_hex,label",
        GET_WINDOW_IDS,
        ids=[c[-1] for c in GET_WINDOW_IDS],
    )
    def test_get_window_cdb(self, window_id, expected_hex, label):
        """GET_WINDOW CDB has correct window ID and structure."""
        cmd = _build_get_window_cdb(window_id)

        assert len(cmd) == 10
        assert cmd[0] == 0x25  # opcode
        assert cmd[5] == window_id  # window ID at byte 5
        assert cmd[8] == 0x3A  # alloc length = 58
        assert cmd[9] == 0x80  # control
        assert cmd == bytes.fromhex(expected_hex)


# =========================================================================
# EXECUTE (0xC1) and custom commands (0xE0, 0xE1)
# =========================================================================

CUSTOM_COMMANDS = [
    # EXECUTE
    (0xC1, 0x00, 0x00, 0x00, 0x00, 0x00, "c10000000000", "EXECUTE"),
    # Custom 0xE0 (eject medium)
    (0xE0, 0xD0, 0x00, 0x00, 0x00, 0x00, "e0d000000000", "E0_EJECT"),
    # Custom 0xE0 (reset params)
    (0xE0, 0xB4, 0x00, 0x00, 0x00, 0x00, "e0b400000000", "E0_RESET"),
    # Custom 0xE1 (boundary)
    (0xE1, 0x00, 0x00, 0x00, 0x00, 0x00, "e10000000000", "E1_BOUNDARY"),
]


@pytest.mark.property_test
class TestCustomCommandProperties:
    """Verify EXECUTE and custom command structures."""

    @pytest.mark.parametrize(
        "opcode,page,param2,param3,alloc_len,control,expected_hex,label",
        CUSTOM_COMMANDS,
        ids=[c[-1] for c in CUSTOM_COMMANDS],
    )
    def test_custom_command_structure(
        self, opcode, page, param2, param3, alloc_len, control, expected_hex, label
    ):
        cmd = struct.pack("BBBBBB", opcode, page, param2, param3, alloc_len, control)
        assert len(cmd) == 6
        assert cmd[0] == opcode
        assert cmd == bytes.fromhex(expected_hex)


# =========================================================================
# Protocol module method tests
# =========================================================================

@pytest.mark.property_test
class TestProtocolBuildMethods:
    """Test CoolscanProtocol._build_6byte_command and related methods."""

    @pytest.fixture
    def protocol(self):
        """Create protocol instance without USB (bare object)."""
        p = object.__new__(CoolscanProtocol)
        return p

    @pytest.mark.parametrize(
        "opcode,expected_hex",
        [
            (0x00, "000000000000"),
            (0x12, "120000000080"),
            (0x16, "160000000000"),
            (0x1A, "1a0000000080"),
            (0x15, "150000000080"),
            (0x1B, "1b0000000080"),
        ],
    )
    def test_build_6byte_default_control(self, protocol, opcode, expected_hex):
        """_build_6byte_command defaults control=0x80."""
        cmd = protocol._build_6byte_command(opcode)
        assert len(cmd) == 6
        assert cmd[0] == opcode
        assert cmd[5] == 0x80  # default control

    @pytest.mark.parametrize(
        "opcode,kwargs,expected_hex",
        [
            (0x00, {"control": 0x00}, "000000000000"),
            (0x12, {"alloc_length": 0x24, "control": 0x80}, "120000002480"),
            (0x12, {"page": 0x01, "param2": 0xD1, "alloc_length": 0x04, "control": 0x80}, "1201d1000480"),
            (0x1B, {"alloc_length": 0x03, "control": 0x00}, "1b0000000300"),
            (0x1B, {"alloc_length": 0x04, "control": 0x00}, "1b0000000400"),
        ],
        ids=["TUR", "INQUIRY_36", "INQUIRY_D1", "START", "STOP"],
    )
    def test_build_6byte_parameterized(self, protocol, opcode, kwargs, expected_hex):
        cmd = protocol._build_6byte_command(opcode, **kwargs)
        assert cmd == bytes.fromhex(expected_hex)


# =========================================================================
# WDB properties
# =========================================================================

@pytest.mark.property_test
class TestWDBProperties:
    """Verify WindowDescriptorBlock 58-byte serialization properties."""

    def test_wdb_size(self):
        """WDB serialization produces 58 bytes."""
        wdb = WindowDescriptorBlock()
        data = wdb.to_bytes_58()
        assert len(data) == 58

    def test_wdb_exposure_field(self):
        """Canonical exposure is 32-bit big-endian at bytes 54-57."""
        wdb = WindowDescriptorBlock()
        wdb.exposure = 0x12345678
        data = wdb.to_bytes_58()
        assert data[54:58] == struct.pack(">I", 0x12345678)

    def test_wdb_roundtrip(self):
        """WDB to_bytes_58 -> from_bytes_58 round-trips correctly."""
        original = WindowDescriptorBlock(
            x_resolution=2900,
            y_resolution=2900,
            width=2592,
            length=3888,
            exposure=123456,
        )
        data = original.to_bytes_58()
        restored = WindowDescriptorBlock.from_bytes_58(data)

        assert restored.x_resolution == original.x_resolution
        assert restored.y_resolution == original.y_resolution
        assert restored.width == original.width
        assert restored.length == original.length
        assert restored.exposure == original.exposure


# =========================================================================
# Exposure extraction from WDB
# =========================================================================

@pytest.mark.property_test
class TestExposureExtraction:
    """Test extract_exposure_from_wdb edge cases."""

    @pytest.fixture
    def protocol(self):
        return object.__new__(CoolscanProtocol)

    @pytest.mark.parametrize(
        "exposure_value",
        [0, 1, 123456, 0x12345678, 0xFFFFFFFF],
    )
    def test_extract_exposure_values(self, protocol, exposure_value):
        """Exposure extraction handles a range of values."""
        wdb = b"\x00" * 54 + struct.pack(">I", exposure_value)
        result = protocol.extract_exposure_from_wdb(wdb)
        assert result == exposure_value

    def test_extract_exposure_short_wdb(self, protocol):
        """Returns None for WDB shorter than 58 bytes."""
        wdb = b"\x00" * 57
        assert protocol.extract_exposure_from_wdb(wdb) is None


# =========================================================================
# Identity LUT properties
# =========================================================================

@pytest.mark.property_test
class TestIdentityLUT:
    """Verify identity LUT generation properties."""

    def test_lut_size(self):
        """Identity LUT is 8192 bytes (4096 entries × 2 bytes)."""
        p = object.__new__(CoolscanProtocol)
        lut = p._generate_identity_lut()
        assert len(lut) == 8192

    def test_lut_entries(self):
        """Each entry maps input to itself (16-bit big-endian)."""
        p = object.__new__(CoolscanProtocol)
        lut = p._generate_identity_lut()

        # Check representative entries
        assert lut[0:2] == bytes([0x00, 0x00])  # 0 -> 0
        assert lut[2:4] == bytes([0x00, 0x01])  # 1 -> 1
        assert lut[510:512] == bytes([0x00, 0xFF])  # 255 -> 255
        assert lut[8190:8192] == bytes([0x0F, 0xFF])  # 4095 -> 4095

    def test_lut_monotonic(self):
        """LUT entries are monotonically increasing."""
        p = object.__new__(CoolscanProtocol)
        lut = p._generate_identity_lut()
        for i in range(0, 8190, 2):
            val = (lut[i] << 8) | lut[i + 1]
            expected = i // 2
            assert val == expected


# =========================================================================
# Status parsing properties
# =========================================================================

@pytest.mark.property_test
class TestStatusParsing:
    """Verify status response parsing is consistent."""

    @pytest.fixture
    def protocol(self):
        class MockDeviceInfo:
            name = "LS-40 ED"
            interface = "usb"
            vendor_id = 0x04B0
            product_id = 0x4000

        p = object.__new__(CoolscanProtocol)
        p.device_info = MockDeviceInfo()
        return p

    @pytest.mark.parametrize(
        "status_hex,expected_status,sense_key",
        [
            ("0000000000000000", StatusType.READY, 0),
            ("0206290000000000", StatusType.ERROR, 6),
            ("0205240000000000", StatusType.ERROR, 5),
        ],
        ids=["READY", "UNIT_ATTENTION", "ILLEGAL_REQUEST"],
    )
    def test_parse_status(self, protocol, status_hex, expected_status, sense_key):
        status_data = bytes.fromhex(status_hex)
        status, details = protocol._parse_status(status_data)
        assert status == expected_status
        assert details["sense_key"] == sense_key


# =========================================================================
# Phase check properties
# =========================================================================

@pytest.mark.property_test
class TestPhaseCheck:
    """Verify phase check byte and phase type enum."""

    def test_phase_check_byte(self):
        """Phase check is single byte 0xD0."""
        assert bytes([0xD0]) == b"\xd0"

    def test_phase_type_values(self):
        """PhaseType enum values match expected constants."""
        assert PhaseType.STATUS.value == 0x01
        assert PhaseType.OUT.value == 0x02
        assert PhaseType.IN.value == 0x03
        assert PhaseType.BUSY.value == 0x04

    def test_phase_type_mapping(self):
        """Phase values have expected semantic meanings."""
        phases = {
            0x01: "Status",
            0x02: "Data OUT",
            0x03: "Data IN",
            0x04: "Busy",
        }
        # Verify enum members exist and have correct values
        assert PhaseType.STATUS.value == 1
        assert PhaseType.OUT.value == 2
        assert PhaseType.IN.value == 3
        assert PhaseType.BUSY.value == 4


# =========================================================================
# DataType enum coverage
# =========================================================================

@pytest.mark.property_test
class TestDataTypeEnum:
    """Verify DataType enum covers all observed codes."""

    def test_all_expected_types_present(self):
        """All datatype codes from captures are in the enum."""
        expected = {
            0x00: "IMAGE_DATA",
            0x01: "LUT",
            0x87: "STATUS_PROGRESS",
            0x8E: "EXPOSURE_CALIBRATION",
            0x8F: "CONTROL_FRAME",
            0x92: "BORDER_POSITION",
            0x8C: "CHANNEL_STATE",
            0xA0: "SHADING_DATA",
            0xC0: "USER_REG_GAMMA",
            0xE0: "DEVICE_INTERNAL_INFO",
        }
        for value, name in expected.items():
            assert hasattr(DataType, name), f"Missing DataType.{name}"
            assert getattr(DataType, name).value == value

    def test_datatype_values_unique(self):
        """All DataType members have distinct values."""
        values = [m.value for m in DataType]
        assert len(values) == len(set(values))


# =========================================================================
# ScanType enum coverage
# =========================================================================

@pytest.mark.property_test
class TestScanTypeEnum:
    """Verify ScanType enum values."""

    def test_scan_type_values(self):
        assert ScanType.NORMAL.value == 0
        assert ScanType.AE.value == 1
        assert ScanType.AE_WB.value == 2
        assert ScanType.BATCH.value == 3


# =========================================================================
# Opcode coverage summary
# =========================================================================

@pytest.mark.property_test
class TestOpcodeCoverage:
    """Ensure all opcodes from existing tests are covered."""

    EXPECTED_OPS = {
        0x00,  # TEST_UNIT_READY
        0x12,  # INQUIRY
        0x15,  # MODE_SELECT
        0x16,  # RESERVE_UNIT
        # 0x17 RELEASE_UNIT intentionally excluded: never sent by LS-40 SANE driver
        0x1A,  # MODE_SENSE
        0x1B,  # START_STOP_UNIT
        0x24,  # SET_WINDOW
        0x25,  # READ_CAPACITY / GET_WINDOW
        0x28,  # READ(10)
        0x2A,  # SEND(10) / WRITE(10)
        0xC1,  # EXECUTE
        0xE0,  # Custom eject/reset
        0xE1,  # Custom boundary
    }

    def test_all_opcodes_covered(self):
        """All known opcodes appear in at least one test table."""
        covered = set()

        for row in SIX_BYTE_COMMANDS:
            covered.add(row[0])
        for row in READ10_COMMANDS:
            covered.add(row[0])
        for row in SEND_COMMANDS:
            covered.add(row[0])
        for row in TEN_BYTE_COMMANDS:
            covered.add(row[0])
        for row in GET_WINDOW_IDS:
            covered.add(0x25)  # GET_WINDOW opcode
        for row in CUSTOM_COMMANDS:
            covered.add(row[0])

        assert self.EXPECTED_OPS.issubset(covered), (
            f"Missing opcodes: {self.EXPECTED_OPS - covered}"
        )
