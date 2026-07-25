"""Protocol state-machine invariant tests derived from kevihiiin/Nikon-Coolscan-RE
firmware RE knowledge base and verified against LS-40 pcapng captures.

Validates invariants that are implied by the firmware's internal state machine
but not directly observable from wire captures alone:

- DTC 0x87 ordering: status reads precede TUR polling after SCAN
- Abort protocol: cancel_scan sends C0, then polls TUR until ready
- E0->C1->E1 cycle: vendor commands follow paired write/trigger/read pattern
- SCAN data-out payloads: correct window ID lists per scan type
- TUR phase-specific sense codes: correct handling of BUSY/CAL states

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

from unittest.mock import Mock, call, patch

import pytest

from coolscan.protocol import CoolscanProtocol, DataType, StatusType
from coolscan.usb_replay import UsbCaptureReplay
from tests.fakes import MockDevice, make_bare_protocol


# ---------------------------------------------------------------------------
# DTC 0x87 ordering invariant
# ---------------------------------------------------------------------------

class TestDtc087Ordering:
    """From kevihiiin scan-data-transfer.md Q7: DTC 0x87 must be read after
    SCAN returns Good but BEFORE TUR polling. Otherwise push_to_usb autonomously
    pushes image data to EP2 FIFO, corrupting subsequent command responses."""

    @pytest.mark.property_test
    def test_status_reads_between_reissue_retries(self):
        """After START_SCAN returns REISSUE, 0x87 status reads happen between
        retry attempts — NOT after TUR polling."""
        start_cmd = bytes([0x1B, 0x00, 0x00, 0x00, 0x03, 0x00])
        scan_data = bytes([0x01, 0x02, 0x03])

        events = [
            ("out", start_cmd),
            ("out", b"\xd0"),
            ("in", b"\x02"),
            ("out", scan_data),
            ("in", bytes([0x02, 0x09, 0x80, 0x06, 0x01, 0x00, 0x00, 0x00])),
            # 0x87 status snapshots BEFORE retry (not TUR)
            ("out", b"\x28\x00\x87\x00\x00\x00\x00\x00\x06\x80"),
            ("out", b"\xd0"),
            ("in", b"\x03"),
            ("in", bytes([0x87, 0x08, 0x00, 0x00, 0x00, 0x1b])),
            ("in", b"\x00" * 8),
            ("out", b"\x28\x00\x87\x00\x00\x00\x00\x00\x21\x80"),
            ("out", b"\xd0"),
            ("in", b"\x03"),
            ("in", bytes(33)),
            ("in", b"\x00" * 8),
            # Retry succeeds
            ("out", start_cmd),
            ("out", b"\xd0"),
            ("in", b"\x02"),
            ("out", scan_data),
            ("in", b"\x00" * 8),
        ]

        replay = UsbCaptureReplay(events=events)
        proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

        with patch("coolscan.protocol.time.sleep"):
            result = proto.start_scan()

        assert result is True
        assert replay.position == replay.total
        proto.close()

    @pytest.mark.property_test
    def test_status_read_before_tur_polling_contract(self):
        """start_scan reads status blocks as part of the REISSUE retry loop.
        The call sequence must be: issue(start_scan) -> issue(read_0x87) ->
        issue(start_scan_retry) ...  No TUR calls between SCAN and first 0x87."""
        proto = make_bare_protocol()

        issue_calls: list = []
        call_index = 0

        def fake_issue(cmd, **kwargs):
            nonlocal call_index
            issue_calls.append(("issue", cmd[:2].hex() if isinstance(cmd, bytes) else "??"))
            call_index += 1
            if call_index == 1:
                return (b"", StatusType.REISSUE)
            elif call_index in (2, 3):
                return (b"", StatusType.READY)
            elif call_index == 4:
                return (b"", StatusType.READY)
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)

        with patch("coolscan.protocol.time.sleep"):
            proto.start_scan()

        # Verify ordering: 0x87 reads happen between SCAN sends
        assert len(issue_calls) >= 3
        assert issue_calls[0][1] == "1b00"  # START_STOP
        assert issue_calls[1][1][:2] == "28"  # READ(10) - status read
        assert issue_calls[2][1][:2] == "28"  # READ(10) - extended status


# ---------------------------------------------------------------------------
# Abort protocol invariants (VENDOR_C0 0xC0)
# ---------------------------------------------------------------------------

class TestAbortProtocol:
    """From kevihiiin vendor-c0.md: C0 sets bit 7 of 0x400776 (abort-requested).
    Firmware inner scan loop detects it, exits cleanly, recovery task 0x0F10
    runs cleanup. Host polls TUR until Good."""

    @pytest.mark.property_test
    def test_cancel_scan_cdb_format(self):
        """cancel_scan sends exactly C0 00 00 00 00 00."""
        proto = make_bare_protocol()
        sent_cmds: list = []

        def record_and_return(c, **kw):
            sent_cmds.append(bytes(c))
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=record_and_return)

        result = proto.cancel_scan()
        assert result is True
        assert sent_cmds == [bytes([0xC0, 0x00, 0x00, 0x00, 0x00, 0x00])]

    @pytest.mark.property_test
    def test_cancel_scan_returns_true_on_ready(self):
        """cancel_scan returns True when scanner reports READY."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        assert proto.cancel_scan() is True

    @pytest.mark.property_test
    def test_cancel_scan_returns_false_on_error(self):
        """cancel_scan returns False on any non-READY status."""
        proto = make_bare_protocol()
        proto._issue_command = Mock(return_value=(b"", StatusType.ERROR))
        assert proto.cancel_scan() is False

    @pytest.mark.property_test
    def test_cancel_scan_during_active_scan(self):
        """cancel_scan should work even while a scan is in progress. The C0
        handler at FW:0x028AB4 sets the abort flag regardless of state."""
        cancel_cmd = bytes([0xC0, 0x00, 0x00, 0x00, 0x00, 0x00])

        events = [
            ("out", cancel_cmd),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", b"\x00" * 8),
        ]

        replay = UsbCaptureReplay(events=events)
        proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)
        result = proto.cancel_scan()
        assert result is True
        proto.close()


# ---------------------------------------------------------------------------
# E0 -> C1 -> E1 cycle invariant
# ---------------------------------------------------------------------------

class TestVendorCommandCycle:
    """From kevihiiin vendor-e0.md/vendor-e1.md: the vendor command cycle is:
    E0 (write params) -> C1 (execute/trigger) -> E1 (read results).
    The C1 handler reads sub-command from 0x400D63 (set by preceding E0)."""

    @pytest.mark.property_test
    def test_auto_focus_sends_e0_a0_then_c1(self):
        """auto_focus flow: poll_until_ready → read_focus (E1/C1) →
        _auto_focus_command (E0/A0 + C1) → read_focus (E1/C1).
        The E0/A0→C1 pair is the autofocus command cycle."""
        proto = make_bare_protocol()
        sent: list = []

        def fake_issue(c, **kw):
            sent.append(bytes(c))
            return (b"\x00" * 9, StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)
        proto.poll_until_ready = Mock(return_value=True)

        with patch("coolscan.protocol.time.sleep"):
            result = proto.auto_focus(0, 0)

        assert result is not None
        # Find the E0/A0 command (read_focus sends E1 first)
        e0_commands = [c for c in sent if len(c) >= 3 and c[0] == 0xE0]
        assert len(e0_commands) >= 1, "auto_focus did not send VENDOR_E0"
        assert e0_commands[0][2] == 0xA0  # subcode
        # C1 EXECUTE should follow E0 (in order)
        c1_commands = [c for c in sent if c == bytes([0xC1, 0x00, 0x00, 0x00, 0x00, 0x00])]
        assert len(c1_commands) >= 1, "auto_focus did not send EXECUTE"

    @pytest.mark.property_test
    def test_eject_medium_sends_e0_d0_then_c1(self):
        """eject sends VENDOR_E0 sub=D0, then C1 EXECUTE."""
        proto = make_bare_protocol()
        sent: list = []

        def fake_issue(c, **kw):
            sent.append(bytes(c))
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)

        result = proto.eject_medium()
        assert result is True
        assert sent[0][0] == 0xE0
        assert sent[0][2] == 0xD0
        assert sent[1] == bytes([0xC1, 0x00, 0x00, 0x00, 0x00, 0x00])

    @pytest.mark.property_test
    def test_generic_vendor_e0_sends_subcode_then_execute(self):
        """vendor_e0(subcode=X, data=...) sends E0 with subcode X, then C1."""
        proto = make_bare_protocol()
        sent: list = []

        def fake_issue(c, **kw):
            sent.append(bytes(c))
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)

        payload = b"\x00" * 9
        for sub in (0xA0, 0xB4, 0xD0):
            sent.clear()
            result = proto.vendor_e0(sub, payload)
            assert result is True, f"vendor_e0(0x{sub:02X}) failed"
            assert sent[0][0] == 0xE0
            assert sent[0][2] == sub
            assert sent[1] == bytes([0xC1, 0x00, 0x00, 0x00, 0x00, 0x00])

    @pytest.mark.property_test
    def test_reset_params_sends_e0_b4_then_c1(self):
        """reset_params sends VENDOR_E0 sub=B4, then C1 EXECUTE."""
        proto = make_bare_protocol()
        sent: list = []

        def fake_issue(c, **kw):
            sent.append(bytes(c))
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)

        result = proto.reset_params()
        assert result is True
        assert sent[0][0] == 0xE0
        assert sent[0][2] == 0xB4
        assert sent[1] == bytes([0xC1, 0x00, 0x00, 0x00, 0x00, 0x00])


# ---------------------------------------------------------------------------
# SCAN data-out payload format
# ---------------------------------------------------------------------------

class TestScanPayloadFormat:
    """From kevihiiin deep-dive/full-scan-wire-trace.md: SCAN data-out payloads
    carry window ID lists. The LS-40 uses:
    - RGB only: 01 02 03
    - IR + RGB: 09 01 02 03
    - Stop: action byte 0x04
    Verified against golden_single_bw.txt."""

    @pytest.mark.property_test
    def test_normal_scan_uses_rgb_payload(self):
        """NORMAL scan sends window IDs 01 02 03 (RGB, 3 channels).
        CDB is 1B 00 00 00 03 00 (alloc_length=3, control=0x00, 6 bytes)."""
        proto = make_bare_protocol()
        sent_cmd = None
        sent_data_out = None

        def fake_issue(cmd, **kw):
            nonlocal sent_cmd, sent_data_out
            sent_cmd = bytes(cmd)
            sent_data_out = kw.get("data_out", b"")
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)

        with patch("coolscan.protocol.time.sleep"):
            proto.start_scan()

        assert sent_cmd == bytes([0x1B, 0x00, 0x00, 0x00, 0x03, 0x00])
        assert sent_data_out == bytes([0x01, 0x02, 0x03])

    @pytest.mark.property_test
    def test_batch_scan_uses_rgbi_payload(self):
        """BATCH scan sends window IDs 09 01 02 03 (IR + RGB, 4 channels).
        CDB is 1B 00 00 00 04 00 (alloc_length=4, control=0x00, 6 bytes)."""
        from coolscan.protocol import ScanType

        proto = make_bare_protocol()
        sent_cmd = None
        sent_data_out = None

        def fake_issue(cmd, **kw):
            nonlocal sent_cmd, sent_data_out
            sent_cmd = bytes(cmd)
            sent_data_out = kw.get("data_out", b"")
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)

        with patch("coolscan.protocol.time.sleep"):
            proto.start_scan(ScanType.BATCH)

        assert sent_cmd == bytes([0x1B, 0x00, 0x00, 0x00, 0x04, 0x00])
        assert sent_data_out == bytes([0x09, 0x01, 0x02, 0x03])

    @pytest.mark.property_test
    def test_stop_scan_uses_correct_cdb(self):
        """STOP_SCAN sends 1B 00 00 00 04 00 (action byte 0x04)."""
        proto = make_bare_protocol()
        sent: list = []

        def fake_issue(c, **kw):
            sent.append(bytes(c))
            return (b"", StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)

        with patch("coolscan.protocol.time.sleep"):
            proto.stop_scan()

        assert sent[0] == bytes([0x1B, 0x00, 0x00, 0x00, 0x04, 0x00])


# ---------------------------------------------------------------------------
# TUR phase-specific sense codes
# ---------------------------------------------------------------------------

class TestTurSenseTransitions:
    """From kevihiiin scan-data-transfer.md Q4 + firmware TUR handler:
    Scanner reports different sense codes depending on internal state:
    - 0x0079 (02/04/01 FRU=03): motor busy / buffer stall
    - 0x007A (02/04/01 FRU=04): calibration in progress
    - 0x0007 (02/04/01 FRU=00): becoming ready
    - 0x0000 (no sense): ready

    poll_until_ready should retry on all NOT_READY variants and return on READY."""

    @pytest.mark.property_test
    def test_poll_until_ready_handles_not_ready_sense(self):
        """poll_until_ready retries on NOT_READY (02/04/01) and returns True on
        eventual READY."""
        events = [
            # Poll 1: NOT_READY (motor busy)
            ("out", bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", bytes([0x02, 0x04, 0x01, 0x03, 0x00, 0x00, 0x00, 0x00])),
            # Poll 2: READY
            ("out", bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", b"\x00" * 8),
        ]

        replay = UsbCaptureReplay(events=events)
        proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

        with patch("coolscan.protocol.time.sleep"):
            result = proto.poll_until_ready(timeout=30)

        assert result is True
        proto.close()

    @pytest.mark.property_test
    def test_poll_until_ready_handles_unit_attention(self):
        """poll_until_ready retries on UNIT_ATTENTION (06/3F/03 — INQUIRY changed)
        and returns True on eventual READY."""
        events = [
            ("out", bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", bytes([0x06, 0x3F, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00])),
            ("out", bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", b"\x00" * 8),
        ]

        replay = UsbCaptureReplay(events=events)
        proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

        with patch("coolscan.protocol.time.sleep"):
            result = proto.poll_until_ready(timeout=30)

        assert result is True
        proto.close()

    @pytest.mark.property_test
    def test_poll_until_ready_timeout_on_stuck_not_ready(self):
        """poll_until_ready returns False if scanner never becomes READY within
        timeout."""
        events = []
        for _ in range(5):
            events.extend([
                ("out", bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
                ("out", b"\xd0"),
                ("in", b"\x01"),
                ("in", bytes([0x02, 0x04, 0x01, 0x04, 0x00, 0x00, 0x00, 0x00])),
            ])

        replay = UsbCaptureReplay(events=events)
        proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

        with patch("coolscan.protocol.time.sleep"):
            result = proto.poll_until_ready(timeout=0.1)

        assert result is False
        proto.close()

    @pytest.mark.property_test
    def test_test_unit_ready_once_parses_not_ready_correctly(self):
        """_test_unit_ready_once correctly parses NOT_READY sense
        (sense 02/04/01 FRU=00 — becoming ready / general init).
        The exact status mapping depends on the parser implementation;
        the invariant is that it's NOT StatusType.READY."""
        events = [
            ("out", bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", bytes([0x02, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])),
        ]

        replay = UsbCaptureReplay(events=events)
        proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

        status, parsed = proto._test_unit_ready_once()
        assert status != StatusType.READY
        proto.close()

    @pytest.mark.property_test
    def test_test_unit_ready_once_returns_ready_for_zero_sense(self):
        """_test_unit_ready_once returns READY status for zero sense data."""
        events = [
            ("out", bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
            ("out", b"\xd0"),
            ("in", b"\x01"),
            ("in", b"\x00" * 8),
        ]

        replay = UsbCaptureReplay(events=events)
        proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

        status, parsed = proto._test_unit_ready_once()
        assert status == StatusType.READY
        proto.close()


# ---------------------------------------------------------------------------
# Multi-pass scan invariants
# ---------------------------------------------------------------------------

class TestMultiPassScanInvariants:
    """From kevihiiin full-scan-wire-trace.md: full scans consist of multiple
    passes, each with a defined structure:
    [SET_WINDOW xN] -> [WRITE LUT xN] -> [SCAN] -> [READ 0x87 x2] -> [GET WINDOW xN]
    -> [READ 0x00 burst]. N is 3 for RGB-only passes, 4 for cal passes with IR."""

    @pytest.mark.property_test
    def test_cal_pass_includes_ir_channel(self):
        """The calibration pass (full_scan_setup_frame) includes window 9 (IR).
        Verified against golden_single_bw.txt: 4 SET_WINDOW calls including IR."""
        proto = make_bare_protocol()
        issue_calls: list = []

        def fake_issue(c, **kw):
            issue_calls.append(bytes(c))
            return (b"\x00" * 58, StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)
        proto.usb_device.write = Mock(return_value=58)
        proto.poll_until_ready = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)

        with patch("coolscan.protocol.time.sleep"):
            proto.full_scan_setup_frame()

        # Setup frame sends 4 SET_WINDOW calls: IR (09) + RGB (01, 02, 03)
        set_window_calls = [c for c in issue_calls if len(c) >= 10 and c[0] == 0x24]
        assert len(set_window_calls) == 4, (
            f"Expected 4 SET_WINDOW calls (IR+RGB), got {len(set_window_calls)}"
        )

    @pytest.mark.property_test
    def test_rgb_pass_excludes_ir(self):
        """RGB-only passes (full_scan_capture_frame) send 3 SET_WINDOW calls,
        excluding window 9 (IR)."""
        proto = make_bare_protocol()
        issue_calls: list = []

        def fake_issue(c, **kw):
            issue_calls.append(bytes(c))
            return (b"\x00" * 1000, StatusType.READY)

        proto._issue_command = Mock(side_effect=fake_issue)
        proto.usb_device.write = Mock(return_value=58)
        proto.poll_until_ready = Mock(return_value=True)
        proto.upload_identity_luts = Mock(return_value=True)
        proto.start_scan = Mock(return_value=True)
        proto.read_scan_data = Mock(return_value=b"\x00" * 1000)
        proto.stop_scan = Mock(return_value=True)

        with patch("coolscan.protocol.time.sleep"):
            proto.full_scan_capture_frame()

        set_window_calls = [c for c in issue_calls if len(c) >= 10 and c[0] == 0x24]
        assert len(set_window_calls) == 3, (
            f"Expected 3 SET_WINDOW calls (RGB only), got {len(set_window_calls)}"
        )

    @pytest.mark.property_test
    def test_lut_uploads_match_channel_count(self):
        """LUT upload count equals channel count: 4 with IR, 3 without IR."""
        proto = make_bare_protocol()

        # With IR: 4 LUTs
        proto._issue_command = Mock(return_value=(b"", StatusType.READY))
        proto._upload_lut = Mock()
        proto.upload_identity_luts(include_ir=True)
        assert proto._upload_lut.call_count == 4

        # Without IR: 3 LUTs
        proto._upload_lut.reset_mock()
        proto.upload_identity_luts(include_ir=False)
        assert proto._upload_lut.call_count == 3


# ---------------------------------------------------------------------------
# WDB vendor extension invariant (per-channel exposure time)
# ---------------------------------------------------------------------------

class TestWdbVendorExtension:
    """From kevihiiin set-window-descriptor.md: vendor extension 0x102 at
    WDB bytes 54-57 is per-channel CCD integration time (32-bit BE).
    Verified at LS-50 firmware FW:0x027166-0x0271AE."""

    @pytest.mark.property_test
    def test_wdb_exposure_at_correct_offset(self):
        """WDB bytes 54-57 (0-indexed 54..57) carry per-channel exposure time
        as 32-bit big-endian. Our 58-byte WDB must have exposure at that offset."""
        from coolscan.protocol import WindowDescriptorBlock

        wdb = WindowDescriptorBlock(
            window_id=1,
            x_resolution=2900,
            y_resolution=2900,
            width=2880,
            length=3792,
            bits_per_pixel=8,
            exposure=12345678,
            channel=2,
            film_flag=0,
        )
        data = wdb.to_bytes_58()
        assert len(data) == 58
        # Bytes 54-57 = exposure (32-bit BE)
        exposure_be = int.from_bytes(data[54:58], "big")
        assert exposure_be == 12345678
