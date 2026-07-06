"""WDB table invariant tests.

Validates that the capture-derived constants in protocol.py are internally
consistent.  These are high-value, low-effort tests that catch corruption or
bad edits to the hardcoded tables.

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

import struct

import pytest

from coolscan.protocol import (
    _SCAN_WINDOW_RESOLUTIONS,
    _SCAN_WINDOW_WDB_TABLES,
)


# Valid window IDs observed in captures (1=R, 2=G, 3=B, 9=IR)
_VALID_WINDOW_IDS = {1, 2, 3, 9}


@pytest.mark.property_test
class TestWdbTableConsistency:
    """Invariant tests for _SCAN_WINDOW_WDB_TABLES."""

    @pytest.mark.parametrize("scan_type", list(_SCAN_WINDOW_WDB_TABLES.keys()))
    def test_table_entry_length(self, scan_type):
        """Every WDB table entry is exactly 58 bytes."""
        table = _SCAN_WINDOW_WDB_TABLES[scan_type]
        for window_id, data in table.items():
            assert len(data) == 58, (
                f"{scan_type}/{window_id}: expected 58 bytes, got {len(data)}"
            )

    @pytest.mark.parametrize("scan_type", list(_SCAN_WINDOW_WDB_TABLES.keys()))
    def test_valid_window_ids(self, scan_type):
        """Every window ID in a table is one of {1, 2, 3, 9}."""
        table = _SCAN_WINDOW_WDB_TABLES[scan_type]
        for window_id in table:
            assert window_id in _VALID_WINDOW_IDS, (
                f"{scan_type}: unexpected window_id {window_id}"
            )

    @pytest.mark.parametrize("scan_type", list(_SCAN_WINDOW_WDB_TABLES.keys()))
    def test_wdb_byte8_matches_key(self, scan_type):
        """Byte 8 (window_id field) of each entry matches its dict key."""
        table = _SCAN_WINDOW_WDB_TABLES[scan_type]
        for window_id, data in table.items():
            actual_id = data[8]
            assert actual_id == window_id, (
                f"{scan_type}/{window_id}: byte 8 is {actual_id}, key is {window_id}"
            )

    @pytest.mark.parametrize("scan_type", list(_SCAN_WINDOW_WDB_TABLES.keys()))
    def test_resolution_matches_constant(self, scan_type):
        """Bytes 10-11 (x_resolution) and 12-13 (y_resolution) match
        _SCAN_WINDOW_RESOLUTIONS for the scan type.

        Exception: the IR window (9) in 'normal' type uses 290 DPI (setup
        resolution) rather than 2900, matching the pcapng capture.
        """
        expected = _SCAN_WINDOW_RESOLUTIONS[scan_type]
        table = _SCAN_WINDOW_WDB_TABLES[scan_type]
        for window_id, data in table.items():
            x_res = struct.unpack(">H", data[10:12])[0]
            y_res = struct.unpack(">H", data[12:14])[0]
            # IR window in 'normal' type uses 290 DPI (verified against capture)
            if scan_type == "normal" and window_id == 9:
                expected = 290
            assert x_res == expected, (
                f"{scan_type}/{window_id}: x_res {x_res} != expected {expected}"
            )
            assert y_res == expected, (
                f"{scan_type}/{window_id}: y_res {y_res} != expected {expected}"
            )

    @pytest.mark.parametrize("scan_type", list(_SCAN_WINDOW_WDB_TABLES.keys()))
    def test_exposure_nonzero(self, scan_type):
        """Bytes 54-57 (32-bit big-endian exposure) are non-zero for every entry."""
        table = _SCAN_WINDOW_WDB_TABLES[scan_type]
        for window_id, data in table.items():
            exposure = struct.unpack(">I", data[54:58])[0]
            assert exposure != 0, (
                f"{scan_type}/{window_id}: exposure is zero"
            )

    def test_all_scan_types_have_resolutions(self):
        """Every scan_type in WDB tables has a corresponding resolution entry."""
        for scan_type in _SCAN_WINDOW_WDB_TABLES:
            assert scan_type in _SCAN_WINDOW_RESOLUTIONS, (
                f"{scan_type} missing from _SCAN_WINDOW_RESOLUTIONS"
            )

    def test_resolution_table_no_orphans(self):
        """Every scan_type in _SCAN_WINDOW_RESOLUTIONS has WDB table entries."""
        for scan_type in _SCAN_WINDOW_RESOLUTIONS:
            assert scan_type in _SCAN_WINDOW_WDB_TABLES, (
                f"{scan_type} in resolutions but not in WDB tables"
            )

    @pytest.mark.parametrize("scan_type", list(_SCAN_WINDOW_WDB_TABLES.keys()))
    def test_table_not_empty(self, scan_type):
        """Every scan type has at least one window entry."""
        table = _SCAN_WINDOW_WDB_TABLES[scan_type]
        assert len(table) >= 1, f"{scan_type}: table is empty"
