"""Shared pytest configuration for coolscan-py tests."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "property_test: fixture-agnostic invariant tests (resilient to "
        "non-determinism)",
    )
    config.addinivalue_line(
        "markers",
        "hardware: tests that require a real LS-40 ED scanner connected",
    )
    config.addinivalue_line(
        "markers",
        "fixture_data: tests that load and validate against golden fixture "
        "data (derived from pcapng captures via analyze_capture.py)",
    )


# ---------------------------------------------------------------------------
# Paths to canonical capture artifacts
# ---------------------------------------------------------------------------

GOLDEN_SINGLE_BW = Path(__file__).resolve().parent.parent / "reference" / "golden_single_bw.txt"  # noqa: E501
GOLDEN_BATCH = Path(__file__).resolve().parent.parent / "reference" / "golden_batch.txt"  # noqa: E501


# ---------------------------------------------------------------------------
# Fixture-derived data (session-scoped: loaded once per test run)
# ---------------------------------------------------------------------------

def _lazy_load_golden():
    """Lazy-load and cache golden fixture data."""
    from scripts.analyze_capture import (  # noqa: PLC0415
        _decode_all,
        detect_phases,
        extract_control_frames,
        extract_read_capacity,
        extract_wdbs,
        load_capture,
    )

    events = load_capture(str(GOLDEN_SINGLE_BW))
    _decode_all(events)
    events = detect_phases(events)
    wdbs = extract_wdbs(events)
    cfs = extract_control_frames(events)
    rcs = extract_read_capacity(events)

    command_sequence: List[Dict[str, Any]] = []
    for ev in events:
        if ev.direction == "out" and ev.decoded:
            command_sequence.append({
                "line_num": ev.index,
                "timestamp": ev.timestamp,
                "cmd": ev.decoded.cmd_name,
                "cmd_hex": ev.decoded.cmd_hex,
                "params": ev.decoded.params,
                "phase": ev.phase,
            })

    return {
        "events": events,
        "wdbs": wdbs,
        "control_frames": cfs,
        "read_capacity": rcs,
        "command_sequence": command_sequence,
    }


@pytest.fixture(scope="session")
def golden_events() -> List[Any]:
    """All decoded events from golden_single_bw.txt (1472 events)."""
    return _lazy_load_golden()["events"]


@pytest.fixture(scope="session")
def golden_wdbs() -> List[Any]:
    """Extracted WDB rows from golden_single_bw.txt (18 SET_WINDOW commands)."""
    return _lazy_load_golden()["wdbs"]


@pytest.fixture(scope="session")
def golden_control_frames() -> List[Any]:
    """Extracted CONTROL_FRAME rows from golden_single_bw.txt (3 WRITE 0x8f)."""
    return _lazy_load_golden()["control_frames"]


@pytest.fixture(scope="session")
def golden_read_capacity() -> List[Any]:
    """Extracted READ_CAPACITY rows from golden_single_bw.txt (16 responses)."""
    return _lazy_load_golden()["read_capacity"]


@pytest.fixture(scope="session")
def golden_command_sequence() -> List[Dict[str, Any]]:
    """Ordered command sequence from golden_single_bw.txt.

    Each entry: {line_num, timestamp, cmd, cmd_hex, params, phase}
    """
    return _lazy_load_golden()["command_sequence"]


# ---------------------------------------------------------------------------
# Batch fixture data (session-scoped)
# ---------------------------------------------------------------------------

def _lazy_load_batch():
    """Lazy-load and cache batch fixture data."""
    from scripts.analyze_capture import (  # noqa: PLC0415
        _decode_all,
        detect_phases,
        load_capture,
    )

    events = load_capture(str(GOLDEN_BATCH))
    _decode_all(events)
    events = detect_phases(events)

    command_sequence: List[Dict[str, Any]] = []
    for ev in events:
        if ev.direction == "out" and ev.decoded:
            command_sequence.append({
                "line_num": ev.index,
                "timestamp": ev.timestamp,
                "cmd": ev.decoded.cmd_name,
                "cmd_hex": ev.decoded.cmd_hex,
                "params": ev.decoded.params,
                "phase": ev.phase,
            })

    return {
        "events": events,
        "command_sequence": command_sequence,
    }


@pytest.fixture(scope="session")
def batch_events() -> List[Any]:
    """All decoded events from golden_batch.txt (6863 events)."""
    return _lazy_load_batch()["events"]


@pytest.fixture(scope="session")
def batch_command_sequence() -> List[Dict[str, Any]]:
    """Ordered command sequence from golden_batch.txt."""
    return _lazy_load_batch()["command_sequence"]
