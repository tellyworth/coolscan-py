"""Regression tests for error handling and recovery paths.

These tests are fixture-free: they use mocked protocol methods and small
synthetic replays to verify that the protocol responds correctly to hardware
error conditions (ILLEGAL_REQ, COMMAND SEQUENCE ERROR, etc.) instead of
silently ignoring them.

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from coolscan.protocol import CoolscanProtocol, StatusType
from tests.fakes import make_bare_protocol


# ---------------------------------------------------------------------------
# read_focus retry / failure handling
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestReadFocusErrorHandling:
    """Verify read_focus() handles non-READY status robustly."""

    def test_read_focus_retries_then_succeeds(self):
        """read_focus polls ready and retries after ILLEGAL_REQ."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(side_effect=[
            (b"\x00" * 4 + b"\x00\x00\x00\x00\x00", StatusType.ERROR),  # fail
            (b"\x00" * 4 + b"\x00\x00\x00\x00\x00", StatusType.ERROR),  # fail
            (b"\x00" * 4 + b"\x00\x00\x00\x00\x00", StatusType.ERROR),  # fail
            (b"\x00" * 4 + b"\x00\x00\x00\x00\x00", StatusType.READY),  # succeed
        ])
        proto._wait_ready_or_replay_once = Mock(return_value=True)

        result = proto.read_focus()

        assert result == 0
        assert proto._issue_command.call_count == 4
        assert proto._wait_ready_or_replay_once.call_count == 3

    def test_read_focus_returns_none_after_retries_exhausted(self):
        """read_focus returns None if all retries fail."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))
        proto._wait_ready_or_replay_once = Mock(return_value=True)

        result = proto.read_focus(retries=2)

        assert result is None
        assert proto._issue_command.call_count == 3

    def test_read_focus_returns_none_when_scanner_never_ready(self):
        """read_focus returns None if the scanner never becomes ready for retry."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))
        proto._wait_ready_or_replay_once = Mock(return_value=False)

        result = proto.read_focus()

        assert result is None
        assert proto._issue_command.call_count == 1
        assert proto._wait_ready_or_replay_once.call_count == 1


# ---------------------------------------------------------------------------
# Setup frame failure handling
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestSetupFrameFailureHandling:
    """Verify setup frames fail fast when read_focus cannot succeed."""

    def test_full_scan_setup_frame_fails_when_read_focus_fails(self):
        """full_scan_setup_frame returns False if read_focus never succeeds."""
        proto = make_bare_protocol()
        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=None)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b"\x00" * 10})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.stop_scan = Mock(return_value=True)

        result = proto.full_scan_setup_frame()

        assert result is False
        assert proto.read_focus.call_count == 1
        assert proto.set_scan_window.call_count == 0

    def test_batch_full_scan_setup_frame_fails_when_read_focus_fails(self):
        """batch_full_scan_setup_frame returns False if read_focus never succeeds."""
        proto = make_bare_protocol()
        proto.set_boundary = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto._auto_focus_command = Mock(return_value=True)
        proto.read_focus = Mock(return_value=None)
        proto.read_channel_state = Mock(return_value={"exposure": 0, "raw": b"\x00" * 10})
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        result = proto.batch_full_scan_setup_frame()

        assert result is False
        assert proto.read_focus.call_count == 1
        assert proto.set_scan_window.call_count == 0


# ---------------------------------------------------------------------------
# Inter-frame autofocus sequencing
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestInterFrameAutofocusSequencing:
    """Verify post_prescan_autofocus waits for ready before focus reads."""

    def test_post_prescan_autofocus_polls_before_read_focus(self):
        """post_prescan_autofocus calls poll_until_ready before the first
        read_focus, avoiding ILLEGAL_REQ when the scanner is still in scan
        state."""
        proto = make_bare_protocol()
        call_order = []

        def poll_side_effect(*args, **kwargs):
            call_order.append("poll_until_ready")
            return True

        def read_focus_side_effect(*args, **kwargs):
            call_order.append("read_focus")
            return 100

        proto.poll_until_ready = Mock(side_effect=poll_side_effect)
        proto.read_focus = Mock(side_effect=read_focus_side_effect)
        proto._auto_focus_command = Mock(return_value=True)
        proto._execute_command = Mock(return_value=True)
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        with patch("coolscan.protocol.time.sleep"):
            result = proto.post_prescan_autofocus(focus_x=0x059B, focus_y=0x0894)

        assert result == 100
        # First poll, first read_focus, then (autofocus), then poll, then read_focus.
        assert call_order[0] == "poll_until_ready"
        assert call_order[1] == "read_focus"

    def test_post_prescan_autofocus_returns_none_when_not_ready(self):
        """If scanner never becomes ready, post_prescan_autofocus returns None
        without attempting focus reads."""
        proto = make_bare_protocol()
        proto.poll_until_ready = Mock(return_value=False)
        proto.read_focus = Mock(return_value=100)
        proto._auto_focus_command = Mock(return_value=True)
        proto._execute_command = Mock(return_value=True)
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))

        with patch("coolscan.protocol.time.sleep"):
            result = proto.post_prescan_autofocus(focus_x=0x059B, focus_y=0x0894)

        assert result is None
        assert proto.poll_until_ready.call_count == 1
        assert proto.read_focus.call_count == 0


# ---------------------------------------------------------------------------
# scan_teardown recovery on COMMAND SEQUENCE ERROR
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestScanTeardownRecovery:
    """Verify scan_teardown recovers from eject COMMAND SEQUENCE ERROR."""

    def test_scan_teardown_retries_eject_after_command_sequence_error(self):
        """If eject fails with ILLEGAL_REQ / COMMAND SEQUENCE ERROR,
        scan_teardown stops scan, drains, and retries eject."""
        proto = make_bare_protocol()
        proto.test_unit_ready = Mock(return_value=True)
        proto._drain_buffered_scan_data = Mock(return_value=0)
        proto.stop_scan = Mock(return_value=True)
        proto.reset_params = Mock(return_value=True)
        proto.set_scan_window = Mock(return_value=True)

        # First eject fails with ILLEGAL_REQ/COMMAND SEQUENCE ERROR;
        # second eject succeeds.
        proto.eject_medium = Mock(side_effect=[
            False,
            True,
        ])
        proto._last_status_parsed = {
            "sense_key": 0x05,
            "sense_asc": 0x2C,
            "sense_ascq": 0x00,
        }

        with patch("coolscan.protocol.time.sleep"):
            result = proto.scan_teardown()

        assert result is True
        assert proto.eject_medium.call_count == 2
        assert proto.stop_scan.call_count == 1
        # scan_teardown always drains once before first eject, then again
        # during recovery.
        assert proto._drain_buffered_scan_data.call_count == 2

    def test_scan_teardown_does_not_retry_eject_for_other_errors(self):
        """Eject retries only happen for COMMAND SEQUENCE ERROR."""
        proto = make_bare_protocol()
        proto.test_unit_ready = Mock(return_value=True)
        proto._drain_buffered_scan_data = Mock(return_value=0)
        proto.stop_scan = Mock(return_value=True)
        proto.reset_params = Mock(return_value=True)
        proto.set_scan_window = Mock(return_value=True)

        proto.eject_medium = Mock(return_value=False)
        proto._last_status_parsed = {
            "sense_key": 0x03,  # medium error
            "sense_asc": 0x11,
            "sense_ascq": 0x00,
        }

        with patch("coolscan.protocol.time.sleep"):
            result = proto.scan_teardown()

        assert result is False
        assert proto.eject_medium.call_count == 1
        assert proto.stop_scan.call_count == 0
        # Initial drain still happens; no retry means no second drain.
        assert proto._drain_buffered_scan_data.call_count == 1

    def test_scan_teardown_returns_true_on_first_eject_success(self):
        """No recovery needed when eject succeeds on first try."""
        proto = make_bare_protocol()
        proto.test_unit_ready = Mock(return_value=True)
        proto._drain_buffered_scan_data = Mock(return_value=0)
        proto.stop_scan = Mock(return_value=True)
        proto.reset_params = Mock(return_value=True)
        proto.set_scan_window = Mock(return_value=True)

        proto.eject_medium = Mock(return_value=True)

        with patch("coolscan.protocol.time.sleep"):
            result = proto.scan_teardown()

        assert result is True
        assert proto.eject_medium.call_count == 1
        assert proto.stop_scan.call_count == 0


# ---------------------------------------------------------------------------
# Data-volume invariants on capture methods
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestCaptureDataVolumeInvariants:
    """Verify capture methods read expected byte counts."""

    def test_batch_preview_capture_frame_reads_exact_byte_count(self):
        """batch_preview_capture_frame reads exactly 748,224 bytes in 3 chunks."""
        proto = make_bare_protocol()
        proto.get_window = Mock(return_value=b"\x00" * 58)

        chunk_sizes = [0x03F480, 0x03F480, 0x0381C0]
        proto.read_scan_data = Mock(side_effect=[
            bytes(n) for n in chunk_sizes
        ])
        proto._wait_ready_or_replay_once = Mock(return_value=True)

        data = proto.batch_preview_capture_frame()

        assert len(data) == sum(chunk_sizes)
        assert proto.read_scan_data.call_count == 3
        calls = proto.read_scan_data.call_args_list
        assert calls[0].args[0] == chunk_sizes[0]
        assert calls[1].args[0] == chunk_sizes[1]
        assert calls[2].args[0] == chunk_sizes[2]

    def test_batch_full_res_capture_frame_8bit_reads_expected_bytes(self):
        """8-bit batch full-res reads width*height*channels bytes."""
        proto = make_bare_protocol()
        proto.get_window = Mock(return_value=b"\x00" * 58)
        proto._usb_capture_replay = None

        expected = 2880 * 4332 * 3
        chunk_size = 259200
        proto.read_scan_data = Mock(return_value=bytes(chunk_size))

        data = proto.batch_full_res_capture_frame(depth=8)

        assert len(data) >= expected
        assert len(data) < expected + chunk_size

    def test_batch_full_res_capture_frame_12bit_reads_expected_bytes(self):
        """12-bit batch full-res reads width*height*channels*2 bytes."""
        proto = make_bare_protocol()
        proto.get_window = Mock(return_value=b"\x00" * 58)
        proto._usb_capture_replay = None

        expected = 2880 * 4332 * 3 * 2
        chunk_size = 259200
        proto.read_scan_data = Mock(return_value=bytes(chunk_size))

        data = proto.batch_full_res_capture_frame(depth=12)

        assert len(data) >= expected
        assert len(data) < expected + chunk_size

    def test_drain_buffered_scan_data_stops_on_short_read(self):
        """_drain_buffered_scan_data stops when read_scan_data returns short chunk."""
        proto = make_bare_protocol()
        proto.read_scan_data = Mock(side_effect=[
            b"\x00" * 259200,
            b"\x00" * 100000,
        ])

        drained = proto._drain_buffered_scan_data()

        assert drained == 259200 + 100000
        assert proto.read_scan_data.call_count == 2

    def test_drain_buffered_scan_data_stops_on_empty_read(self):
        """_drain_buffered_scan_data stops when read_scan_data returns empty."""
        proto = make_bare_protocol()
        proto.read_scan_data = Mock(return_value=b"")

        drained = proto._drain_buffered_scan_data()

        assert drained == 0
        assert proto.read_scan_data.call_count == 1


# ---------------------------------------------------------------------------
# Batch inter-frame stop / exposure behavior
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestBatchInterFrameBehavior:
    """Verify batch_scan_to_frames does NOT stop the scanner between frames and uses
    table-default exposure for full-res windows (matching golden_batch.txt)."""

    def _make_batch_mocks(self, proto, frame_count: int = 2):
        """Patch the methods batch_scan_to_frames calls during one frame."""
        proto.prescan = Mock(return_value=True)
        proto._last_prescan_image_data = b"dummy"
        # Prescan WDB with height large enough to avoid frame_count clamping.
        prescan_wdb = bytearray(58)
        prescan_wdb[4] = 1  # window_id
        prescan_wdb[26:30] = (frame_count * 4330).to_bytes(4, "big")
        proto.get_window = Mock(return_value=bytes(prescan_wdb))
        proto.set_boundary = Mock(return_value=True)
        proto._control_frame_positions = Mock(return_value=[30 + i * 4330 for i in range(frame_count)])
        proto.batch_full_scan_setup_frame = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.batch_full_scan_capture_frame = Mock(return_value=b"stage_a")
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto.batch_between_scan_setup_frame = Mock(return_value=True)
        proto.batch_preview_capture_frame = Mock(return_value=b"stage_b")
        proto.set_scan_window = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.poll_until_ready = Mock(return_value=True)
        proto.batch_full_res_capture_frame = Mock(return_value=b"full_res")
        proto.stop_scan = Mock(return_value=True)
        proto._drain_buffered_scan_data = Mock(return_value=0)
        proto.post_prescan_autofocus = Mock(return_value=None)
        proto.scan_teardown = Mock(return_value=True)

    def test_batch_scan_to_frames_does_not_stop_scan_between_frames(self):
        """No stop_scan or drain between frames; poll_until_ready follows capture."""
        proto = make_bare_protocol()
        self._make_batch_mocks(proto, frame_count=3)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            results = list(proto.batch_scan_to_frames(frame_count=3))

        assert len(results) == 3
        # stop_scan is never called inside batch_scan_to_frames; the scanner returns
        # to READY naturally after the exact full-res byte count is consumed.
        assert proto.stop_scan.call_count == 0
        # Drain is never called inside batch_scan_to_frames; scan_teardown handles it.
        assert proto._drain_buffered_scan_data.call_count == 0
        # poll_until_ready: once after full-res start_scan, once after capture, per frame.
        assert proto.poll_until_ready.call_count == 3 + 3

    def test_batch_scan_to_frames_fails_when_scanner_not_ready_after_frame(self):
        """If poll_until_ready fails after a frame, scanning aborts before the next."""
        proto = make_bare_protocol()
        self._make_batch_mocks(proto, frame_count=2)
        # frame 0: poll before start (True), poll after capture (True)
        # frame 1: poll before start (True), poll after capture (False) -> abort
        proto.poll_until_ready = Mock(side_effect=[True, True, True, False])

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            results = list(proto.batch_scan_to_frames(frame_count=2))

        # Frame 0 was yielded before the post-capture poll failure.
        assert len(results) == 1
        assert proto.stop_scan.call_count == 0
        assert proto._drain_buffered_scan_data.call_count == 0
        assert proto.scan_teardown.call_count == 0  # aborted before teardown

    def test_batch_scan_to_frames_never_calls_stop_scan(self):
        """Regression: stop_scan is not called between frames or before teardown.

        The golden batch pcapng shows the scanner returning to READY naturally
        after each full-res capture; issuing STOP_SCAN caused ILLEGAL_REQ /
        COMMAND SEQUENCE ERROR at every frame boundary.
        """
        proto = make_bare_protocol()
        self._make_batch_mocks(proto, frame_count=3)
        # Even if stop_scan would fail, the sequence must not depend on it.
        proto.stop_scan = Mock(return_value=False)

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            results = list(proto.batch_scan_to_frames(frame_count=3))

        assert len(results) == 3
        assert proto.stop_scan.call_count == 0
        assert proto.scan_teardown.call_count == 1

    def test_batch_scan_to_frames_uses_table_default_exposure_for_full_res(self):
        """Full-res SET_WINDOW calls disable calibrated exposure in batch mode."""
        proto = make_bare_protocol()
        self._make_batch_mocks(proto, frame_count=2)
        # Inject a fake calibrated value so we can verify it is NOT used.
        proto._calibrated_exposure = {1: 0x1234, 2: 0x5678, 3: 0x9ABC}

        with patch("coolscan.protocol.time.time", side_effect=lambda: 0.0):
            list(proto.batch_scan_to_frames(frame_count=2))

        full_res_calls = [
            call for call in proto.set_scan_window.call_args_list
            if call.kwargs.get("scan_type") == "normal"
        ]
        assert len(full_res_calls) == 6  # 3 windows x 2 frames
        for call in full_res_calls:
            assert call.kwargs.get("use_calibrated_exposure") is False

    def test_batch_full_res_setup_frame_uses_table_default_exposure(self):
        """batch_full_res_setup_frame disables calibrated exposure."""
        proto = make_bare_protocol()
        proto.set_scan_window = Mock(return_value=True)
        proto._wait_ready_or_replay_once = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto._calibrated_exposure = {1: 0x1234, 2: 0x5678, 3: 0x9ABC}

        proto.batch_full_res_setup_frame()

        assert proto.set_scan_window.call_count == 3
        for call in proto.set_scan_window.call_args_list:
            assert call.kwargs.get("use_calibrated_exposure") is False


# ---------------------------------------------------------------------------
# Exact data volume and timeout-safe drain
# ---------------------------------------------------------------------------

@pytest.mark.property_test
class TestBatchDataVolumeAndDrain:
    """Verify batch full-res capture reads exact byte counts and drain is safe."""

    def test_batch_full_res_capture_8bit_exact_chunks(self):
        """8-bit full-res reads 144×259200 + 1×103680 bytes."""
        proto = make_bare_protocol()
        proto._usb_capture_replay = None
        proto.get_window = Mock(return_value=b"\x00" * 58)

        expected_lengths = [259200] * 144 + [103680]
        proto.read_scan_data = Mock(side_effect=[b"\x00" * n for n in expected_lengths])

        data = proto.batch_full_res_capture_frame(depth=8)

        assert proto.read_scan_data.call_count == 145
        assert len(data) == 37_428_480

    def test_batch_full_res_capture_12bit_exact_chunks(self):
        """12-bit full-res reads 288×259200 + 1×207360 bytes."""
        proto = make_bare_protocol()
        proto._usb_capture_replay = None
        proto.get_window = Mock(return_value=b"\x00" * 58)

        expected_lengths = [259200] * 288 + [207360]
        proto.read_scan_data = Mock(side_effect=[b"\x00" * n for n in expected_lengths])

        data = proto.batch_full_res_capture_frame(depth=12)

        assert proto.read_scan_data.call_count == 289
        assert len(data) == 74_856_960

    def test_batch_full_res_capture_no_extra_read_after_expected_bytes(self):
        """The exact chunk pattern does not probe past EOF."""
        proto = make_bare_protocol()
        proto._usb_capture_replay = None
        proto.get_window = Mock(return_value=b"\x00" * 58)

        # Return full chunks for every read; the exact-chunk pattern still
        # stops after 145 reads instead of looping until a short read/EOF.
        proto.read_scan_data = Mock(return_value=b"\x00" * 259200)

        proto.batch_full_res_capture_frame(depth=8)

        assert proto.read_scan_data.call_count == 145

    def test_drain_buffered_scan_data_breaks_on_timeout(self):
        """_drain_buffered_scan_data returns immediately on read timeout."""
        proto = make_bare_protocol()
        proto.read_scan_data = Mock(side_effect=OSError("USB timeout"))

        import time

        start = time.monotonic()
        result = proto._drain_buffered_scan_data()
        elapsed = time.monotonic() - start

        assert result == 0
        assert proto.read_scan_data.call_count == 1
        assert elapsed < 2.0

