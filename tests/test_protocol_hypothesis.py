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
    """Property-based tests for WindowDescriptorBlock 58-byte serialization."""

    @given(
        channel=st.integers(min_value=1, max_value=9),
        x_res=st.integers(min_value=96, max_value=5000),
        y_res=st.integers(min_value=96, max_value=5000),
        frame_offset=st.integers(min_value=0, max_value=50000),
        width=st.integers(min_value=100, max_value=5000),
        length=st.integers(min_value=100, max_value=50000),
        exposure=st.integers(min_value=1, max_value=0xFFFFFFFF),
        wdb_mode=st.integers(min_value=0, max_value=0xFFFF),
        transfer_byte=st.integers(min_value=0, max_value=255),
        status_byte=st.integers(min_value=0, max_value=255),
        film_flag=st.integers(min_value=0, max_value=255),
        sub_mode=st.integers(min_value=0, max_value=255),
    )
    @settings(max_examples=100)
    def test_wdb_roundtrip(
        self, channel, x_res, y_res, frame_offset, width, length,
        exposure, wdb_mode, transfer_byte, status_byte, film_flag, sub_mode,
    ):
        """WDB to_bytes_58/from_bytes_58 round-trip preserves all 58-byte fields."""
        original = WindowDescriptorBlock(
            channel=channel,
            x_resolution=x_res,
            y_resolution=y_res,
            frame_offset=frame_offset,
            width=width,
            length=length,
            exposure=exposure,
            wdb_mode=wdb_mode,
            transfer_byte=transfer_byte,
            status_byte=status_byte,
            film_flag=film_flag,
            sub_mode=sub_mode,
        )

        data = original.to_bytes_58()
        restored = WindowDescriptorBlock.from_bytes_58(data)

        assert restored.channel == channel
        assert restored.x_resolution == x_res
        assert restored.y_resolution == y_res
        assert restored.frame_offset == frame_offset
        assert restored.width == width
        assert restored.length == length
        assert restored.exposure == exposure
        assert restored.wdb_mode == wdb_mode
        assert restored.transfer_byte == transfer_byte
        assert restored.status_byte == status_byte
        assert restored.film_flag == film_flag
        assert restored.sub_mode == sub_mode

    @given(exposure=st.integers(min_value=0, max_value=0xFFFFFFFF))
    @settings(max_examples=50)
    def test_exposure_bytes_roundtrip(self, exposure):
        """Exposure value stored at bytes 54-57 round-trips correctly."""
        wdb = WindowDescriptorBlock(exposure=exposure)
        data = wdb.to_bytes_58()

        stored = struct.unpack(">I", data[54:58])[0]
        assert stored == exposure, (
            f"exposure {exposure} stored as {stored} at bytes 54-57"
        )

        restored = WindowDescriptorBlock.from_bytes_58(data)
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
    from tests.fakes import make_bare_protocol
    return make_bare_protocol(maxbits=maxbits)
