"""Property-based tests for protocol data structures.

Uses Hypothesis to verify invariants on LUT generation and WDB serialization.
These tests explore edge cases and parameter combinations that deterministic
tests might miss.

Requires: pip install hypothesis

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

import struct

import pytest

pytest.importorskip("hypothesis")

import hypothesis.strategies as st
from hypothesis import given, settings

from coolscan.protocol import (
    CoolscanProtocol,
    _SCAN_WINDOW_WDB_TABLES,
    _SCAN_WINDOW_RESOLUTIONS,
    WindowDescriptorBlock,
)


@pytest.mark.property_test
class TestLutGeneration:
    """Property-based tests for _generate_identity_lut()."""

    @given(maxbits=st.integers(min_value=8, max_value=14))
    @settings(max_examples=50)
    def test_lut_size_matches_maxbits(self, maxbits):
        """LUT size is always 2 * 2^maxbits."""
        proto = _make_protocol(maxbits=maxbits)
        lut = proto._generate_identity_lut()
        expected_size = 2 * (1 << maxbits)
        assert len(lut) == expected_size, (
            f"maxbits={maxbits}: LUT size {len(lut)} != {expected_size}"
        )

    @given(maxbits=st.integers(min_value=8, max_value=12))
    @settings(max_examples=50)
    def test_lut_entries_monotonic(self, maxbits):
        """LUT 16-bit big-endian entries are monotonically non-decreasing."""
        proto = _make_protocol(maxbits=maxbits)
        lut = proto._generate_identity_lut()

        # LUT stores big-endian uint16 values, check as 16-bit entries
        n_entries = len(lut) // 2
        for i in range(n_entries):
            val = struct.unpack(">H", lut[i * 2 : i * 2 + 2])[0]
            assert val == i, (
                f"maxbits={maxbits}: LUT entry {i} = {val}, expected {i}"
            )

    @given(maxbits=st.integers(min_value=8, max_value=12))
    @settings(max_examples=50)
    def test_lut_range(self, maxbits):
        """LUT starts at 0 and ends at 255 (full uint8 range)."""
        proto = _make_protocol(maxbits=maxbits)
        lut = proto._generate_identity_lut()

        assert len(lut) > 0
        assert lut[0] == 0, f"maxbits={maxbits}: LUT[0] = {lut[0]}"
        assert lut[-1] == 255, f"maxbits={maxbits}: LUT[-1] = {lut[-1]}"


@pytest.mark.property_test
class TestWdbRoundTrip:
    """Property-based tests for WindowDescriptorBlock serialization."""

    @given(
        window_id=st.integers(min_value=0, max_value=255),
        x_res=st.integers(min_value=96, max_value=5000),
        y_res=st.integers(min_value=96, max_value=5000),
        ulx=st.integers(min_value=0, max_value=50000),
        uly=st.integers(min_value=0, max_value=50000),
        width=st.integers(min_value=100, max_value=5000),
        length=st.integers(min_value=100, max_value=50000),
        exposure=st.integers(min_value=1, max_value=0xFFFFFFFF),
    )
    @settings(max_examples=100)
    def test_wdb_roundtrip(self, window_id, x_res, y_res, ulx, uly, width, length, exposure):
        """WDB to_bytes/from_bytes round-trip preserves all fields."""
        original = WindowDescriptorBlock(
            window_id=window_id,
            x_resolution=x_res,
            y_resolution=y_res,
            ulx=ulx,
            uly=uly,
            width=width,
            length=length,
            exposure=exposure,
        )

        data = original.to_bytes()
        restored = WindowDescriptorBlock.from_bytes(data)

        assert restored.window_id == window_id
        assert restored.x_resolution == x_res
        assert restored.y_resolution == y_res
        assert restored.ulx == ulx
        assert restored.uly == uly
        assert restored.width == width
        assert restored.length == length
        assert restored.exposure == exposure

    @given(exposure=st.integers(min_value=0, max_value=0xFFFFFFFF))
    @settings(max_examples=50)
    def test_exposure_bytes_roundtrip(self, exposure):
        """Exposure value stored at bytes 0x54-0x57 round-trips correctly."""
        wdb = WindowDescriptorBlock(exposure=exposure)
        data = wdb.to_bytes()

        stored = struct.unpack(">I", data[0x54:0x58])[0]
        assert stored == exposure, (
            f"exposure {exposure} stored as {stored} at bytes 0x54-0x57"
        )

        restored = WindowDescriptorBlock.from_bytes(data)
        assert restored.exposure == exposure


@pytest.mark.property_test
class TestWdbBuilderConsistency:
    """Verify _build_scan_window_wdb produces valid WDBs."""

    @given(
        window_id=st.sampled_from([1, 2, 3, 9]),
        depth=st.sampled_from([8, 12]),
    )
    @settings(max_examples=100)
    def test_build_wdb_produces_58_bytes(self, window_id, depth):
        """_build_scan_window_wdb always returns 58 bytes."""
        proto = _make_protocol()
        for scan_type in _SCAN_WINDOW_WDB_TABLES:
            if window_id not in _SCAN_WINDOW_WDB_TABLES[scan_type]:
                continue
            result = proto._build_scan_window_wdb(window_id, scan_type, depth)
            assert result is not None, f"{scan_type}/{window_id}: WDB is None"
            assert len(result) == 58, (
                f"{scan_type}/{window_id}/depth={depth}: "
                f"WDB length {len(result)} != 58"
            )

    @given(
        window_id=st.sampled_from([1, 2, 3, 9]),
        depth=st.sampled_from([8, 12]),
        exposure=st.integers(min_value=1, max_value=0x7FFFFFFF),
    )
    @settings(max_examples=50)
    def test_build_wdb_exposure_override(self, window_id, depth, exposure):
        """Explicit exposure overrides table default at bytes 54-57."""
        proto = _make_protocol()
        for scan_type in _SCAN_WINDOW_WDB_TABLES:
            if window_id not in _SCAN_WINDOW_WDB_TABLES[scan_type]:
                continue
            result = proto._build_scan_window_wdb(
                window_id, scan_type, depth, exposure=exposure
            )
            if result is None:
                continue
            stored = struct.unpack(">I", result[54:58])[0]
            assert stored == exposure, (
                f"{scan_type}/{window_id}: exposure {exposure} stored as {stored}"
            )

    @given(
        window_id=st.sampled_from([1, 2, 3, 9]),
        y_offset=st.integers(min_value=0, max_value=50000),
        height=st.integers(min_value=100, max_value=50000),
    )
    @settings(max_examples=50)
    def test_build_wdb_y_offset_and_height(self, window_id, y_offset, height):
        """y_offset and height override table defaults at bytes 18-21 and 26-29."""
        proto = _make_protocol()
        for scan_type in _SCAN_WINDOW_WDB_TABLES:
            if window_id not in _SCAN_WINDOW_WDB_TABLES[scan_type]:
                continue
            result = proto._build_scan_window_wdb(
                window_id, scan_type, 8, y_offset=y_offset, height=height
            )
            if result is None:
                continue
            stored_uly = struct.unpack(">I", result[18:22])[0]
            stored_length = struct.unpack(">I", result[26:30])[0]
            assert stored_uly == y_offset, (
                f"{scan_type}/{window_id}: uly {y_offset} stored as {stored_uly}"
            )
            assert stored_length == height, (
                f"{scan_type}/{window_id}: height {height} stored as {stored_length}"
            )


def _make_protocol(maxbits: int = 12) -> CoolscanProtocol:
    """Create a minimal protocol instance for testing."""
    from unittest.mock import Mock

    class _MockInterface:
        value = "usb"

    device = Mock()
    device.vendor = "Nikon"
    device.model = "LS-40 ED"
    device.revision = "1.20"
    device.interface = _MockInterface()
    device.device_path = "/dev/usb/scanner0"
    device.vendor_id = 0x04B0
    device.product_id = 0x4000

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
    return proto
