#!/usr/bin/env python3
"""
Phase 4: Batch state-machine transition tests.

Deterministic, parameterized tests that verify the sequence of method calls
made by CoolscanProtocol.batch_scan() for different frame counts.  Uses a
mock protocol to bind the real batch_scan method and verify call ordering.

State machine model:

    idle -> setup -> stage_a_capture -> between -> stage_b_capture
         -> full_res_setup -> full_res_start -> full_res_capture
         -> (loop back to setup for next frame)
         -> teardown -> done

Transitions per frame:
    1. batch_full_scan_setup_frame()      : setup -> stage_a_capture
    2. start_scan(BATCH)                   : stage_a_capture -> scanning
    3. batch_full_scan_capture_frame()     : stage_a_capture data read
    4. 2x _wait_ready_or_replay_once()    : transition polls (TUR)
    5. batch_between_scan_setup_frame()    : between -> stage_b_capture
    6. batch_preview_capture_frame()       : stage_b_capture data read
    7. batch_full_res_setup_frame()        : full_res_setup
    8. batch_full_res_start_frame()        : full_res_start
    9. batch_full_res_capture_frame()      : full_res_capture
    After all frames:
    10. scan_teardown()                    : teardown -> done
"""

import types
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from coolscan.protocol import CoolscanProtocol, ScanType, StatusType


# =========================================================================
# Mock protocol for binding real batch_scan
# =========================================================================

class _MockProtocol:
    """Minimal mock that records all method calls for batch_scan verification."""

    def __init__(self):
        self.call_log: List[Tuple[str, tuple, dict]] = []

    def _log(self, name: str, args: tuple = (), kwargs: dict = None) -> Any:
        if kwargs is None:
            kwargs = {}
        self.call_log.append((name, args, kwargs))
        # Return sensible defaults so batch_scan proceeds
        if name in ("batch_full_scan_capture_frame", "batch_full_res_capture_frame",
                     "batch_preview_capture_frame"):
            return b""
        return True

    # Methods called by batch_scan
    def batch_full_scan_setup_frame(
        self,
        params=None,
        timeout: int = 120,
        focus_x: int = 0,
        focus_y: int = 0,
        include_ir: bool = True,
    ) -> bool:
        return self._log("batch_full_scan_setup_frame", (params, timeout, focus_x, focus_y, include_ir),
                         {"params": params, "timeout": timeout, "focus_x": focus_x, "focus_y": focus_y,
                          "include_ir": include_ir})

    def start_scan(self, scan_type: ScanType = ScanType.NORMAL) -> bool:
        return self._log("start_scan", (scan_type,), {"scan_type": scan_type})

    def batch_full_scan_capture_frame(self) -> bytes:
        return self._log("batch_full_scan_capture_frame") or b"\x00"

    def _wait_ready_or_replay_once(self, timeout: int = 30) -> bool:
        return self._log("_wait_ready_or_replay_once", (timeout,), {"timeout": timeout})

    def batch_between_scan_setup_frame(
        self,
        y_offset: Optional[int] = None,
        height: Optional[int] = None,
    ) -> bool:
        return self._log("batch_between_scan_setup_frame", (y_offset, height),
                         {"y_offset": y_offset, "height": height})

    def batch_preview_capture_frame(self) -> bytes:
        return self._log("batch_preview_capture_frame") or b"\x00"

    def batch_full_res_setup_frame(
        self,
        lut_map: Optional[Dict[int, bytes]] = None,
    ) -> bool:
        return self._log("batch_full_res_setup_frame", (lut_map,), {"lut_map": lut_map})

    def batch_full_res_start_frame(self) -> bool:
        return self._log("batch_full_res_start_frame")

    def batch_full_res_capture_frame(self) -> bytes:
        return self._log("batch_full_res_capture_frame") or b"\x00"

    def stop_scan(self) -> bool:
        return self._log("stop_scan")

    def _drain_buffered_scan_data(self) -> int:
        return self._log("_drain_buffered_scan_data")

    def poll_until_ready(self, timeout: int = 30, poll_interval: float = 0.5) -> bool:
        return self._log("poll_until_ready", (timeout, poll_interval),
                         {"timeout": timeout, "poll_interval": poll_interval})

    def scan_teardown(self) -> bool:
        return self._log("scan_teardown")

    def clear_log(self):
        self.call_log.clear()

    def call_count(self, method_name: str) -> int:
        return sum(1 for name, _, _ in self.call_log if name == method_name)

    def call_names(self) -> List[str]:
        return [name for name, _, _ in self.call_log]


def _make_protocol() -> _MockProtocol:
    """Create a mock protocol with the real batch_scan method bound."""
    proto = _MockProtocol()
    # Bind the real batch_scan from CoolscanProtocol
    proto.batch_scan = types.MethodType(CoolscanProtocol.batch_scan, proto)
    return proto


# =========================================================================
# Per-frame call sequence
# =========================================================================

# The expected method calls for ONE frame (without teardown)
# Note: _drain_buffered_scan_data and stop_scan are NOT called between frames;
# the full-res capture reads the exact expected byte count so there is no
# residual data, and the scanner returns to READY naturally.
FRAME_SEQUENCE = [
    "batch_full_scan_setup_frame",
    "start_scan",
    "batch_full_scan_capture_frame",
    "_wait_ready_or_replay_once",
    "_wait_ready_or_replay_once",
    "batch_between_scan_setup_frame",
    "batch_preview_capture_frame",
    "batch_full_res_setup_frame",
    "batch_full_res_start_frame",
    "batch_full_res_capture_frame",
    "poll_until_ready",
]


# =========================================================================
# Parameterized frame count tests
# =========================================================================

@pytest.mark.property_test
class TestBatchScanTransitions:
    """Verify batch_scan call sequences for different frame counts."""

    @pytest.mark.parametrize("frames", [1, 2, 3])
    def test_batch_scan_call_sequence(self, frames):
        """Call sequence matches expected per-frame pattern, repeated N times."""
        proto = _make_protocol()
        proto.batch_scan(frames=frames, teardown=True)

        expected = list(FRAME_SEQUENCE) * frames + ["scan_teardown"]
        assert proto.call_names() == expected

    @pytest.mark.parametrize("frames", [1, 2, 3])
    def test_batch_scan_call_counts(self, frames):
        """Each method is called the right number of times per frame."""
        proto = _make_protocol()
        proto.batch_scan(frames=frames, teardown=True)

        # _wait_ready_or_replay_once appears 2× per frame; all others 1×
        for method in FRAME_SEQUENCE:
            expected = frames * 2 if method == "_wait_ready_or_replay_once" else frames
            actual = proto.call_count(method)
            assert actual == expected, (
                f"{method} called {actual} times, expected {expected}"
            )
        assert proto.call_count("scan_teardown") == 1

    @pytest.mark.parametrize("frames", [1, 2, 3])
    def test_batch_scan_without_teardown(self, frames):
        """When teardown=False, scan_teardown is never called."""
        proto = _make_protocol()
        proto.batch_scan(frames=frames, teardown=False)

        expected = list(FRAME_SEQUENCE) * frames
        assert proto.call_names() == expected
        assert proto.call_count("scan_teardown") == 0

    @pytest.mark.parametrize("frames", [1, 2, 3])
    def test_batch_scan_start_scan_uses_batch_type(self, frames):
        """start_scan is called with ScanType.BATCH for every frame."""
        proto = _make_protocol()
        proto.batch_scan(frames=frames, teardown=True)

        calls = [
            (args, kwargs)
            for name, args, kwargs in proto.call_log
            if name == "start_scan"
        ]
        assert len(calls) == frames
        for args, kwargs in calls:
            assert args[0] == ScanType.BATCH


# =========================================================================
# Illegal transition tests
# =========================================================================

@pytest.mark.property_test
class TestBatchScanIllegalTransitions:
    """Verify that illegal state transitions are structurally impossible."""

    def test_no_stage_b_before_stage_a(self):
        """batch_between_scan_setup_frame never appears before
        batch_full_scan_setup_frame in the call sequence."""
        proto = _make_protocol()
        proto.batch_scan(frames=2, teardown=True)

        names = proto.call_names()
        # Find first occurrence of each
        try:
            stage_a_idx = names.index("batch_full_scan_setup_frame")
            stage_b_idx = names.index("batch_between_scan_setup_frame")
        except ValueError:
            pytest.fail("Expected methods not found in call sequence")

        assert stage_a_idx < stage_b_idx, (
            "batch_between_scan_setup_frame appeared before batch_full_scan_setup_frame"
        )

    def test_no_teardown_mid_batch(self):
        """scan_teardown appears only at the very end of the sequence."""
        proto = _make_protocol()
        proto.batch_scan(frames=2, teardown=True)

        names = proto.call_names()
        teardown_indices = [
            i for i, n in enumerate(names) if n == "scan_teardown"
        ]
        assert len(teardown_indices) == 1
        assert teardown_indices[0] == len(names) - 1, (
            "scan_teardown appeared mid-batch instead of at the end"
        )

    def test_no_full_res_before_preview(self):
        """batch_full_res_setup_frame never appears before batch_preview_capture_frame."""
        proto = _make_protocol()
        proto.batch_scan(frames=3, teardown=True)

        names = proto.call_names()
        # For each frame, preview must come before full_res_setup
        preview_indices = [
            i for i, n in enumerate(names) if n == "batch_preview_capture_frame"
        ]
        full_res_setup_indices = [
            i for i, n in enumerate(names) if n == "batch_full_res_setup_frame"
        ]

        assert len(preview_indices) == len(full_res_setup_indices)
        for pi, frsi in zip(preview_indices, full_res_setup_indices):
            assert pi < frsi, (
                f"full_res_setup at {frsi} before preview_capture at {pi}"
            )

    def test_no_full_res_start_before_full_res_setup(self):
        """batch_full_res_start_frame never appears before batch_full_res_setup_frame."""
        proto = _make_protocol()
        proto.batch_scan(frames=1, teardown=True)

        names = proto.call_names()
        setup_idx = names.index("batch_full_res_setup_frame")
        start_idx = names.index("batch_full_res_start_frame")
        assert setup_idx < start_idx

    def test_no_capture_before_setup(self):
        """batch_full_scan_capture_frame never appears before batch_full_scan_setup_frame."""
        proto = _make_protocol()
        proto.batch_scan(frames=1, teardown=True)

        names = proto.call_names()
        setup_idx = names.index("batch_full_scan_setup_frame")
        capture_idx = names.index("batch_full_scan_capture_frame")
        assert setup_idx < capture_idx


# =========================================================================
# Loop structure scaling tests
# =========================================================================

@pytest.mark.property_test
class TestBatchScanLoopScaling:
    """Verify the loop structure scales correctly with frame count."""

    @pytest.mark.parametrize("frames", [1, 2, 3, 5])
    def test_total_calls_scale_linearly(self, frames):
        """Total call count = frames * len(FRAME_SEQUENCE) + 1 (teardown)."""
        proto = _make_protocol()
        proto.batch_scan(frames=frames, teardown=True)

        expected_total = frames * len(FRAME_SEQUENCE) + 1
        assert len(proto.call_log) == expected_total

    @pytest.mark.parametrize("frames", [1, 2, 3, 5])
    def test_total_calls_without_teardown(self, frames):
        """Without teardown: frames * len(FRAME_SEQUENCE)."""
        proto = _make_protocol()
        proto.batch_scan(frames=frames, teardown=False)

        expected_total = frames * len(FRAME_SEQUENCE)
        assert len(proto.call_log) == expected_total

    @pytest.mark.parametrize("frames", [1, 2, 3])
    def test_tur_polls_per_frame(self, frames):
        """Exactly 2 TUR polls per frame (between stage A and stage B)."""
        proto = _make_protocol()
        proto.batch_scan(frames=frames, teardown=True)

        tur_count = proto.call_count("_wait_ready_or_replay_once")
        assert tur_count == frames * 2

    def test_frame_boundaries(self):
        """Each frame's captures are bounded by setup and teardown calls."""
        proto = _make_protocol()
        proto.batch_scan(frames=2, teardown=True)

        names = proto.call_names()

        # First frame: setup -> capture
        f1_setup = names.index("batch_full_scan_setup_frame")
        f1_capture = names.index("batch_full_scan_capture_frame")
        assert f1_setup < f1_capture

        # Second frame: setup -> capture (indices should be larger)
        second_setup_idx = names.index("batch_full_scan_setup_frame", f1_setup + 1)
        second_capture_idx = names.index("batch_full_scan_capture_frame", f1_capture + 1)
        assert second_setup_idx > f1_setup
        assert second_capture_idx > f1_capture
        assert second_setup_idx < second_capture_idx


# =========================================================================
# Edge case: early failure
# =========================================================================

@pytest.mark.property_test
class TestBatchScanFailureModes:
    """Verify batch_scan stops on first failure."""

    def test_setup_failure_stops_scan(self):
        """If batch_full_scan_setup_frame fails, no further calls are made."""
        proto = _MockProtocol()
        proto.batch_scan = types.MethodType(CoolscanProtocol.batch_scan, proto)

        # Replace setup to return False on first call
        call_count = {"n": 0}

        def conditional_fail(*args, **kwargs):
            call_count["n"] += 1
            # Record the call in the log
            proto.call_log.append(("batch_full_scan_setup_frame", args, kwargs))
            if call_count["n"] == 1:
                return False
            return True

        proto.batch_full_scan_setup_frame = conditional_fail
        result = proto.batch_scan(frames=3, teardown=True)

        assert result is False
        # Only the first call was made
        assert proto.call_count("batch_full_scan_setup_frame") == 1
        assert proto.call_count("start_scan") == 0
        assert proto.call_count("scan_teardown") == 0

    def test_mid_frame_failure_stops_scan(self):
        """If capture fails mid-frame (returns falsy), remaining frames are skipped."""
        proto = _MockProtocol()
        proto.batch_scan = types.MethodType(CoolscanProtocol.batch_scan, proto)

        # Make the second frame's capture return falsy (empty bytes)
        capture_count = {"n": 0}

        def conditional_capture():
            capture_count["n"] += 1
            proto.call_log.append(("batch_full_scan_capture_frame", (), {}))
            if capture_count["n"] == 2:
                return b""  # falsy → triggers failure
            return b"\x00"  # truthy → success

        proto.batch_full_scan_capture_frame = conditional_capture
        result = proto.batch_scan(frames=3, teardown=True)

        assert result is False
        # First frame completes, second frame's capture fails
        assert proto.call_count("batch_full_scan_setup_frame") == 2
        assert proto.call_count("batch_full_scan_capture_frame") == 2
        assert proto.call_count("scan_teardown") == 0
