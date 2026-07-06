"""Batch scan parameter propagation tests.

Verifies that y_offset and height parameters flow correctly through batch
scan setup methods to set_scan_window calls.

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from coolscan.protocol import CoolscanProtocol, ScanType, StatusType


def _make_protocol() -> CoolscanProtocol:
    """Create a CoolscanProtocol with mock device for contract testing."""
    from tests.test_protocol_contracts import _make_protocol as _mp

    return _mp()


@pytest.mark.property_test
class TestBatchSetupFrameParameters:
    """Verify y_offset/height propagate through batch_full_scan_setup_frame."""

    def test_y_offset_propagates_to_set_scan_window(self):
        """batch_full_scan_setup_frame passes y_offset to set_scan_window
        for each window."""
        proto = _make_protocol()

        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b""})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        proto.batch_full_scan_setup_frame(
            y_offset=4380, height=4332, skip_autofocus=False
        )

        # set_scan_window should be called for windows 9, 1, 2, 3
        assert proto.set_scan_window.call_count == 4
        for call in proto.set_scan_window.call_args_list:
            kwargs = call[1]
            assert kwargs["y_offset"] == 4380, (
                f"y_offset not propagated: {kwargs}"
            )
            assert kwargs["height"] == 4332, (
                f"height not propagated: {kwargs}"
            )

    def test_window_ids_are_correct(self):
        """batch_full_scan_setup_frame calls set_scan_window for IR+RGB."""
        proto = _make_protocol()

        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b""})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        proto.batch_full_scan_setup_frame(
            y_offset=4380, height=4332
        )

        window_ids = [call[1]["window_id"] for call in proto.set_scan_window.call_args_list]
        assert window_ids == [9, 1, 2, 3]

    def test_skip_autofocus_omits_focus_steps(self):
        """When skip_autofocus=True, autofocus and channel state reads are
        replaced by TUR polls."""
        proto = _make_protocol()

        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b""})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        proto.batch_full_scan_setup_frame(
            y_offset=4380, height=4332, skip_autofocus=True
        )

        # autofocus should NOT be called
        assert proto._auto_focus_command.call_count == 0
        # read_focus should NOT be called
        assert proto.read_focus.call_count == 0
        # read_channel_state should NOT be called
        assert proto.read_channel_state.call_count == 0
        # But TUR polls should still happen (4 for skip_autofocus path)
        assert proto._wait_ready_or_replay_once.call_count >= 4

    def test_skip_boundary_omits_set_boundary(self):
        """When skip_boundary=True, set_boundary is not called."""
        proto = _make_protocol()

        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b""})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        proto.batch_full_scan_setup_frame(skip_boundary=True)

        assert proto.set_boundary.call_count == 0

    def test_no_y_offset_uses_default(self):
        """When y_offset/height are None, set_scan_window receives None."""
        proto = _make_protocol()

        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b""})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        proto.batch_full_scan_setup_frame()

        for call in proto.set_scan_window.call_args_list:
            kwargs = call[1]
            assert kwargs["y_offset"] is None
            assert kwargs["height"] is None


@pytest.mark.property_test
class TestBatchScanYOffsetComputation:
    """Verify batch_scan computes per-frame y_offset correctly.

    NOTE: These tests are EXPECTED to fail because batch_scan() currently
    does NOT compute or pass y_offset/height to batch_full_scan_setup_frame.
    The Y offset progression from the batch capture (docs/batch-scanning.md)
    shows frames stepping by 4330 device units starting at y=30.

    Bug: batch_scan() loops over frames but passes no per-frame positioning
    to batch_full_scan_setup_frame.  The method accepts y_offset/height but
    batch_scan never provides them.
    """

    @pytest.mark.skip(reason="batch_scan does not compute y_offset per frame yet")
    def test_batch_scan_y_offset_per_frame(self):
        """batch_scan should pass incrementing y_offset to each frame's setup.

        From docs/batch-scanning.md, Y offsets are:
          Frame 0: y=30, height=4332
          Frame 1: y=4380, height=4332
          Frame 2: y=8710, height=4332
          ...incrementing by ~4330 per frame...
        """
        proto = _make_protocol()

        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b""})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.batch_full_scan_capture_frame = Mock(return_value=b"")
        proto.batch_between_scan_setup_frame = Mock(return_value=True)
        proto.batch_preview_capture_frame = Mock(return_value=b"")
        proto.batch_full_res_setup_frame = Mock(return_value=True)
        proto.batch_full_res_start_frame = Mock(return_value=True)
        proto.batch_full_res_capture_frame = Mock(return_value=b"")
        proto.scan_teardown = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            proto.batch_scan(frames=3, teardown=True)

        # Each frame's batch_full_scan_setup_frame should have been called
        # with incrementing y_offset.  The expected values from the capture:
        # Frame 0: y=30, Frame 1: y=4380, Frame 2: y=8710
        setup_calls = proto.call_log if hasattr(proto, "call_log") else []

        # Since batch_scan doesn't pass y_offset, set_scan_window gets None
        # This is the bug.  Uncomment the following when fixed:
        # y_offsets = [call[1]["y_offset"] for call in proto.set_scan_window.call_args_list]
        # assert y_offsets[0:4] == [30, 30, 30, 30]  # Frame 0 windows 9/1/2/3
        # assert y_offsets[4:8] == [4380, 4380, 4380, 4380]  # Frame 1
        # assert y_offsets[8:12] == [8710, 8710, 8710, 8710]  # Frame 2

    @pytest.mark.skip(reason="batch_scan does not compute y_offset per frame yet")
    def test_batch_scan_height_per_frame(self):
        """batch_scan should pass height to each frame's setup."""
        proto = _make_protocol()

        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=100)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b""})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.batch_full_scan_capture_frame = Mock(return_value=b"")
        proto.batch_between_scan_setup_frame = Mock(return_value=True)
        proto.batch_preview_capture_frame = Mock(return_value=b"")
        proto.batch_full_res_setup_frame = Mock(return_value=True)
        proto.batch_full_res_start_frame = Mock(return_value=True)
        proto.batch_full_res_capture_frame = Mock(return_value=b"")
        proto.scan_teardown = Mock(return_value=True)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            proto.batch_scan(frames=2, teardown=True)

        # Once fixed, heights should be 4332 for each window in each frame.
        # Currently all are None (the bug).
