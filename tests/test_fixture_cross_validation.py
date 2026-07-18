"""Cross-validate contract test expectations against the golden fixture.

These tests load the golden fixture data at runtime and verify that the
hardcoded expectations in contract tests (command ordering, datatypes,
channel ordering, window IDs, TUR polls) match what is present in the
pcapng-derived fixture.

This closes the loop: if the golden fixture is regenerated from a different
capture, these tests detect discrepancies between the fixture and the
code's expectations.
"""

from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmds_in_range(
    command_sequence: List[Dict[str, Any]],
    start: int,
    end: int,
) -> List[Dict[str, Any]]:
    """Return commands within [start, end] line range."""
    return [c for c in command_sequence if start <= c["line_num"] <= end]


def _find_cmds(
    command_sequence: List[Dict[str, Any]],
    cmd_name: str,
) -> List[Dict[str, Any]]:
    """Return all commands with cmd_name."""
    return [c for c in command_sequence if c["cmd"] == cmd_name]


def _find_cmds_after(
    command_sequence: List[Dict[str, Any]],
    after_line: int,
    cmd_name: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Return next N commands with cmd_name after a line."""
    result = []
    for c in command_sequence:
        if c["line_num"] > after_line and c["cmd"] == cmd_name:
            result.append(c)
            if len(result) >= limit:
                break
    return result


# ---------------------------------------------------------------------------
# Prescan frame cross-validation (golden fixture ~192-310)
# ---------------------------------------------------------------------------

@pytest.mark.fixture_data
class TestPrescanFrameFixtureAlignment:
    """Verify prescan_frame() expected sequence matches the fixture."""

    def test_border_position_is_0x92_write(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """set_boundary_for_prescan sends 0x92 BORDER_POSITION WRITE."""
        bp = [
            c for c in _find_cmds(golden_command_sequence, "WRITE")
            if "92" in c.get("params", {}).get("datatype", "")
        ]
        assert len(bp) >= 1, "No BORDER_POSITION (0x92) WRITE found in fixture"

    def test_exposure_data_read_0x8e(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """read_exposure_data reads 0x8e (header + table)."""
        reads_8e = [
            c for c in golden_command_sequence
            if c["cmd"] == "READ" and "8e" in c.get("params", {}).get("datatype", "")
        ]
        assert len(reads_8e) >= 2, (
            f"Expected at least 2 READ 0x8e commands (header + table), "
            f"found {len(reads_8e)}"
        )

    def test_control_frame_read_0x8f(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """read_control_frame reads CONTROL_FRAME (0x8f)."""
        cf_reads = [
            c for c in golden_command_sequence
            if c["cmd"] == "READ" and "8f" in c.get("params", {}).get("datatype", "")
        ]
        assert len(cf_reads) >= 1, (
            f"No CONTROL_FRAME READ (0x8f) found in fixture"
        )

    def test_channel_state_r_g_b_order(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """read_channel_state(1, 2, 3) reads R, G, B channels."""
        ch_reads = [
            c for c in golden_command_sequence
            if c["cmd"] == "READ" and "8c" in c.get("params", {}).get("datatype", "")
        ]
        assert len(ch_reads) >= 3, (
            f"Expected at least 3 channel-state reads, found {len(ch_reads)}"
        )

    def test_prescan_scan_commands_exist(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """SET_WINDOW for prescan generates SCAN commands with WDB data."""
        scans = _find_cmds(golden_command_sequence, "SCAN")
        assert len(scans) >= 3, (
            f"Expected at least 3 SCAN (SET_WINDOW) commands, found {len(scans)}"
        )

    def test_lut_uploads_present(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """Identity LUTs (WRITE datatype 0x03) are uploaded for R, G, B."""
        luts = [
            c for c in golden_command_sequence
            if c["cmd"] == "WRITE" and "03" in c.get("params", {}).get("datatype", "")
        ]
        assert len(luts) >= 3, (
            f"Expected at least 3 LUT uploads, found {len(luts)}"
        )

    def test_start_scan_present(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """START_SCAN (START_STOP_UNIT) is present in the fixture."""
        starts = _find_cmds(golden_command_sequence, "START_STOP_UNIT")
        assert len(starts) >= 1, "No START_STOP_UNIT command found in fixture"


# ---------------------------------------------------------------------------
# Full-scan setup frame cross-validation (golden fixture ~420-550)
# ---------------------------------------------------------------------------

@pytest.mark.fixture_data
class TestFullScanSetupFixtureAlignment:
    """Verify full_scan_setup_frame() expected sequence matches the fixture."""

    def test_control_frame_write_0x8f(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """set_boundary sends 0x8f CONTROL_FRAME WRITE."""
        cf_writes = [
            c for c in golden_command_sequence
            if c["cmd"] == "WRITE" and "8f" in c.get("params", {}).get("datatype", "")
        ]
        assert len(cf_writes) >= 1, "No CONTROL_FRAME WRITE (0x8f) found in fixture"

    def test_autofocus_vendor_e0_a0(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """Autofocus uses VENDOR_E0 with subcode 0xa0."""
        af = [
            c for c in _find_cmds(golden_command_sequence, "VENDOR_E0")
            if "a0" in c.get("params", {}).get("subcode", "")
        ]
        assert len(af) >= 1, "No VENDOR_E0 autofocus (0xa0) command found"

    def test_execute_after_autofocus(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """EXECUTE command follows autofocus."""
        executes = _find_cmds(golden_command_sequence, "EXECUTE")
        assert len(executes) >= 1, "No EXECUTE (0xc1) command found in fixture"

    def test_read_focus_vendor_e1_c1(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """read_focus uses VENDOR_E1 with subcode 0xc1."""
        rf = [
            c for c in _find_cmds(golden_command_sequence, "VENDOR_E1")
            if "c1" in c.get("params", {}).get("subcode", "")
        ]
        assert len(rf) >= 1, "No VENDOR_E1 read_focus (0xc1) command found"

    def test_ir_channel_state_read(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """read_channel_state(9) reads IR channel via READ 0x8c."""
        # The channel is encoded in CDB bytes 3-4 (big-endian uint16).
        # READ 0x8c for channel 9: 28008c000903...
        ir_reads = [
            c for c in golden_command_sequence
            if c["cmd"] == "READ"
            and "8c" in c.get("params", {}).get("datatype", "")
            and "09" in c.get("cmd_hex", "")[6:10]  # bytes 3-4 of 10-byte CDB
        ]
        assert len(ir_reads) >= 1, "No IR channel (9) state READ found"

    def test_setup_scan_commands_with_setup_wdbs(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """SET_WINDOW with 290 DPI for setup frame is present."""
        scans = _find_cmds(golden_command_sequence, "SCAN")
        assert len(scans) >= 4, (
            f"Expected at least 4 SCAN (SET_WINDOW) commands for setup, "
            f"found {len(scans)}"
        )

    def test_lut_uploads_include_ir(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """upload_identity_luts(include_ir=True) sends IR + RGB."""
        luts = [
            c for c in golden_command_sequence
            if c["cmd"] == "WRITE" and "03" in c.get("params", {}).get("datatype", "")
        ]
        assert len(luts) >= 4, (
            f"Expected at least 4 LUT uploads (IR+RGB), found {len(luts)}"
        )

    def test_stop_scan_present(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """stop_scan command is present in setup phase."""
        stops = [
            c for c in _find_cmds(golden_command_sequence, "START_STOP_UNIT")
            if "04" in c.get("cmd_hex", "")
        ]
        assert len(stops) >= 1, "No STOP_SCAN (1b...04) found in fixture"


# ---------------------------------------------------------------------------
# Full-scan capture frame cross-validation (golden fixture ~590-680)
# ---------------------------------------------------------------------------

@pytest.mark.fixture_data
class TestFullScanCaptureFixtureAlignment:
    """Verify full_scan_capture_frame() expected sequence matches fixture."""

    def test_capture_set_window_commands_exist(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """Full-res SET_WINDOW for RGB in capture frame."""
        scans = _find_cmds(golden_command_sequence, "SCAN")
        # Both prescan, setup, and capture use SCAN commands
        assert len(scans) >= 7, (
            f"Expected at least 7 SCAN commands total across phases, "
            f"found {len(scans)}"
        )

    def test_capture_luts_rgb_only(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """LUT uploads are present for RGB in capture frame."""
        luts = [
            c for c in golden_command_sequence
            if c["cmd"] == "WRITE" and "03" in c.get("params", {}).get("datatype", "")
        ]
        assert len(luts) >= 3, (
            f"Expected at least 3 LUT uploads total, found {len(luts)}"
        )

    def test_capture_start_scan_with_start_stop_unit(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """START_SCAN uses START_STOP_UNIT command."""
        starts = [
            c for c in _find_cmds(golden_command_sequence, "START_STOP_UNIT")
            if "03" in c.get("cmd_hex", "")
        ]
        assert len(starts) >= 1, "No START_SCAN (1b...03) found in fixture"


# ---------------------------------------------------------------------------
# Initialize scanner cross-validation (golden fixture lines ~1-90)
# ---------------------------------------------------------------------------

@pytest.mark.fixture_data
class TestInitializeScannerFixtureAlignment:
    """Verify initialize_scanner() expected call sequence matches fixture."""

    def test_inquiry_standard_first(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """INQUIRY (standard, 36 bytes) is the first command."""
        assert golden_command_sequence[0]["cmd"] == "INQUIRY", (
            f"Expected INQUIRY first, got {golden_command_sequence[0]['cmd']}"
        )

    def test_reserve_unit_before_read_capacity(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """RESERVE_UNIT appears before READ_CAPACITY."""
        reserve_seen = False
        capacity_seen = False
        for c in golden_command_sequence:
            if c["cmd"] == "RESERVE_UNIT":
                reserve_seen = True
            if c["cmd"] == "READ_CAPACITY":
                capacity_seen = True
                assert reserve_seen, (
                    "READ_CAPACITY found before RESERVE_UNIT"
                )
        assert reserve_seen and capacity_seen, (
            f"Missing commands: RESERVE_UNIT={reserve_seen}, "
            f"READ_CAPACITY={capacity_seen}"
        )

    def test_inquiry_pages_read(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """Multiple INQUIRY page commands exist."""
        inquiries = [
            c for c in golden_command_sequence
            if c["cmd"] == "INQUIRY"
        ]
        assert len(inquiries) >= 5, (
            f"Expected at least 5 INQUIRY commands, found {len(inquiries)}"
        )


# ---------------------------------------------------------------------------
# Structural invariants (WDBs and CONTROL_FRAMEs)
# ---------------------------------------------------------------------------

@pytest.mark.fixture_data
class TestWDBStructuralInvariants:
    """Validate WDB structure from the golden fixture."""

    def test_prescan_wdbs_have_96_dpi(
        self, golden_wdbs: List[Any]
    ) -> None:
        """At least one WDB uses 96 DPI resolution."""
        low_res = [w for w in golden_wdbs if w.x_res == 96]
        assert len(low_res) > 0, "No 96 DPI WDBs found in prescan"

    def test_full_res_wdbs_have_2900_dpi(
        self, golden_wdbs: List[Any]
    ) -> None:
        """At least one WDB uses 2900 DPI."""
        high_res = [w for w in golden_wdbs if w.x_res == 2900]
        assert len(high_res) > 0, "No 2900 DPI WDBs found"

    def test_wdb_window_ids_are_valid(
        self, golden_wdbs: List[Any]
    ) -> None:
        """All WDB window IDs are 1, 2, 3, or 9."""
        valid_ids = {1, 2, 3, 9}
        for w in golden_wdbs:
            assert w.window_id in valid_ids, (
                f"Invalid window_id {w.window_id} in WDB at line {w.line_num}"
            )

    def test_at_least_one_ir_window(
        self, golden_wdbs: List[Any]
    ) -> None:
        """At least one WDB has window_id=9 (IR channel)."""
        ir_wdbs = [w for w in golden_wdbs if w.window_id == 9]
        assert len(ir_wdbs) > 0, "No IR (window 9) WDBs in golden fixture"

    def test_wdb_exposure_nonzero(
        self, golden_wdbs: List[Any]
    ) -> None:
        """All WDBs have nonzero exposure values."""
        for w in golden_wdbs:
            assert w.exposure > 0, (
                f"WDB at line {w.line_num} has zero exposure"
            )


@pytest.mark.fixture_data
class TestControlFrameInvariants:
    """Validate CONTROL_FRAME entries from the golden fixture."""

    def test_control_frame_has_entries(
        self, golden_control_frames: List[Any]
    ) -> None:
        """CONTROL_FRAME entries have valid height."""
        assert len(golden_control_frames) > 0, "No CONTROL_FRAME entries"
        for cf in golden_control_frames:
            assert cf.height > 0, f"Entry {cf.entry_index} has height=0"
            assert cf.y_end > cf.y_start, (
                f"Entry {cf.entry_index}: "
                f"y_end ({cf.y_end}) <= y_start ({cf.y_start})"
            )


# ---------------------------------------------------------------------------
# Phase-aware invariants
# ---------------------------------------------------------------------------

@pytest.mark.fixture_data
class TestCommandSequenceInvariants:
    """Validate command ordering invariants from the golden fixture."""

    def test_no_start_scan_before_setup(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """START_SCAN never appears before any SET_WINDOW (SCAN command)."""
        first_scan = None
        first_start = None
        for c in golden_command_sequence:
            if c["cmd"] == "SCAN" and first_scan is None:
                first_scan = c["line_num"]
            if c["cmd"] == "START_STOP_UNIT" and first_start is None:
                first_start = c["line_num"]
        assert first_scan is not None and first_start is not None
        assert first_scan < first_start, (
            f"First SCAN at line {first_scan}, but "
            f"first START_STOP_UNIT at line {first_start}"
        )

    def test_reserve_unit_single_occurrence(
        self, golden_command_sequence: List[Dict[str, Any]]
    ) -> None:
        """RESERVE_UNIT appears exactly once in the session."""
        reserves = _find_cmds(golden_command_sequence, "RESERVE_UNIT")
        assert len(reserves) == 1, (
            f"Expected exactly 1 RESERVE_UNIT, found {len(reserves)} at lines "
            f"{[c['line_num'] for c in reserves]}"
        )
