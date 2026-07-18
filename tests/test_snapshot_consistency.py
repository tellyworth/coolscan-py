"""Verify that analysis snapshots are in sync with their source fixtures.

These tests load the analysis JSON snapshot from reference/ and compare it
against a fresh analysis of the source fixture. If they differ, run
``make generate-fixture-snapshot`` to regenerate.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

REFERENCE = Path(__file__).resolve().parent.parent / "reference"


def _load_analysis_snapshot(name: str) -> Dict[str, Any] | None:
    """Load a cached analysis JSON snapshot."""
    path = REFERENCE / f"{name}_analysis.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _fresh_analysis(fixture: str, extract_wdbs: bool = True,
                    extract_cf: bool = True, extract_rc: bool = False) -> Dict[str, Any]:
    """Run a fresh analysis of a fixture (same as CLI --json with extract flags)."""
    # Import lazily so test collection doesn't fail without the module
    from scripts.analyze_capture import (  # noqa: PLC0415
        _decode_all,
        detect_phases,
        extract_control_frames,
        extract_read_capacity,
        extract_wdbs,
        group_phases,
        json_structured_output,
        load_capture,
    )

    events = load_capture(str(REFERENCE / fixture))
    _decode_all(events)
    events = detect_phases(events)
    phases = group_phases(events)

    # Detect issues (pass-through; not included in snapshot)
    issues: List[Any] = []

    return json_structured_output(
        events, phases, issues,
        wdbs=extract_wdbs(events) if extract_wdbs else None,
        control_frames=extract_control_frames(events) if extract_cf else None,
        read_capacity=extract_read_capacity(events) if extract_rc else None,
        verbose=True,
        max_events=0,
    )


def _strip_fresh_fields(fresh: Dict[str, Any]) -> Dict[str, Any]:
    """Remove volatile fields from fresh analysis for stable comparison."""
    fresh.pop("issues", None)
    # Don't compare raw_hex in structural rows (may differ in whitespace/normalization)
    for key in ("wdbs", "control_frames", "read_capacity"):
        if key in fresh and fresh[key]:
            for row in fresh[key]:
                row.pop("raw_hex", None)
    return fresh


def _strip_cached_fields(cached: Dict[str, Any]) -> Dict[str, Any]:
    """Remove volatile fields from cached snapshot."""
    cached = dict(cached)  # shallow copy
    cached.pop("issues", None)
    for key in ("wdbs", "control_frames", "read_capacity"):
        if key in cached and cached[key]:
            for row in cached[key]:
                row.pop("raw_hex", None)
    return cached


@pytest.mark.fixture_data
class TestAnalysisSnapshotInSync:
    """Verify golden_single_bw_analysis.json matches the current fixture."""

    def test_golden_single_bw_snapshot_exists(self) -> None:
        """Snapshot file exists."""
        assert (REFERENCE / "golden_single_bw_analysis.json").exists(), (
            "golden_single_bw_analysis.json not found. "
            "Run: make generate-fixture-snapshot"
        )

    def test_golden_single_bw_snapshot_in_sync(self) -> None:
        """Snapshot matches fresh analysis of golden_single_bw.txt."""
        cached = _load_analysis_snapshot("golden_single_bw")
        if cached is None:
            pytest.skip("snapshot not found — run make generate-fixture-snapshot")

        fresh = _fresh_analysis(
            "golden_single_bw.txt",
            extract_wdbs=True, extract_cf=True, extract_rc=True,
        )

        cached = _strip_cached_fields(cached)
        fresh = _strip_fresh_fields(fresh)

        # Compare summary
        assert cached.get("summary") == fresh.get("summary"), (
            "Summary differs. Run: make generate-fixture-snapshot"
        )

        # Compare event count
        assert len(cached.get("events", [])) == len(fresh.get("events", [])), (
            f"Event count differs: cached={len(cached.get('events', []))}, "
            f"fresh={len(fresh.get('events', []))}. "
            "Run: make generate-fixture-snapshot"
        )

        # Compare structural extractions
        for key in ("wdbs", "control_frames", "read_capacity"):
            cached_rows = cached.get(key, []) or []
            fresh_rows = fresh.get(key, []) or []
            assert len(cached_rows) == len(fresh_rows), (
                f"{key} row count differs: cached={len(cached_rows)}, "
                f"fresh={len(fresh_rows)}. "
                "Run: make generate-fixture-snapshot"
            )

        # Compare command frequency
        assert cached.get("command_frequency") == fresh.get("command_frequency"), (
            "Command frequency differs. Run: make generate-fixture-snapshot"
        )

        # Compare phases
        assert len(cached.get("phases", [])) == len(fresh.get("phases", [])), (
            "Phase count differs. Run: make generate-fixture-snapshot"
        )
