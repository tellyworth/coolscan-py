"""
Piece C: Integration test — full scan flow with synthetic image data.

Tests the complete control flow: setup → scan → image read → release,
using a minimal fixture with synthetic IN data (zeros) for the image block.

The 64-byte allocation proves the protocol transitions correctly from
scanner_ready → reserve_unit → object_position → set_window → send_lut →
start_scan → poll_until_ready → read_scan_data → release_unit, without
needing real image bytes from the capture.

We call the individual steps rather than perform_scan_sequence() because
that method calls release_unit() in its finally block, which would prevent
us from reading image data afterward.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from coolscan.protocol import CoolscanProtocol, DataType, ScanParameters
from coolscan.usb_replay import UsbCaptureReplay

CAPTURE = Path(__file__).resolve().parent.parent / "test_basic_scan_capture.txt"


class MockInterface:
    value = "usb"


class MockDevice:
    def __init__(self):
        self.vendor = "Nikon"
        self.model = "LS-40 ED"
        self.revision = "1.20"
        self.interface = MockInterface()
        self.device_path = "/dev/usb/scanner0"
        self.vendor_id = 0x04B0
        self.product_id = 0x4000


def test_full_scan_flow_with_synthetic_data(tmp_path):
    """
    Full control flow: scanner_ready → reserve → setup → start_scan →
    poll_until_ready → read_scan_data(64) → release_unit.

    Uses a minimal fixture with synthetic IN data (zeros) for the image block.
    Command bytes match CoolscanProtocol output (see test_basic_scan_capture.txt
    lines 210-252 for the same command set).
    """
    # Mode params: 20 bytes from set_window_wdb
    mode_params = (
        "000000080000000000000001030600000b540000"
    )
    # LUT data: 768 bytes of identity LUT (bytes 0-255 repeated 3 times)
    lut_hex = "".join(f"{i:02x}" for i in range(256)) * 3

    lines = [
        # === scanner_ready: TUR poll (READY on first attempt) ===
        "0.100000000\t0x01\t6\t000000000000",
        "0.101000000\t0x01\t1\td0",
        "0.102000000\t0x82\t1\t01",
        "0.103000000\t0x82\t8\t0000000000000000",

        # === reserve_unit ===
        "0.200000000\t0x01\t6\t160000000000",
        "0.201000000\t0x01\t1\td0",
        "0.202000000\t0x82\t1\t02",
        "0.203000000\t0x82\t8\t0000000000000000",

        # === object_position (10-byte CDB) ===
        "0.300000000\t0x01\t10\t31000000000000000000",
        "0.301000000\t0x01\t1\td0",
        "0.302000000\t0x82\t1\t03",
        "0.303000000\t0x82\t8\t0000000000000000",

        # === set_window (MODE_SELECT + 20-byte data OUT) ===
        "0.400000000\t0x01\t6\t151000001400",
        "0.401000000\t0x01\t1\td0",
        "0.402000000\t0x82\t1\t02",
        f"0.403000000\t0x01\t20\t{mode_params}",
        "0.404000000\t0x82\t8\t0000000000000000",

        # === send_lut (9-byte command + 768-byte data OUT) ===
        "0.500000000\t0x01\t9\t2a00c0000000000300",
        "0.501000000\t0x01\t1\td0",
        "0.502000000\t0x82\t1\t02",
        f"0.503000000\t0x01\t768\t{lut_hex}",
        "0.504000000\t0x82\t8\t0000000000000000",

        # === start_scan (6-byte CDB + 3-byte data OUT) ===
        "0.600000000\t0x01\t6\t1b0000000300",
        "0.601000000\t0x01\t1\td0",
        "0.602000000\t0x82\t1\t02",
        "0.603000000\t0x01\t3\t010203",
        "0.604000000\t0x82\t8\t0209800601000000",  # REISSUE

        # === re-issued start_scan (G2 fix: REISSUE handling) ===
        "0.610000000\t0x01\t6\t1b0000000300",
        "0.611000000\t0x01\t1\td0",
        "0.612000000\t0x82\t1\t02",
        "0.613000000\t0x01\t3\t010203",
        "0.614000000\t0x82\t8\t0000000000000000",  # READY

        # === post-scan polling: PROCESSING → READY ===
        "0.700000000\t0x01\t6\t000000000000",
        "0.701000000\t0x01\t1\td0",
        "0.702000000\t0x82\t1\t01",
        "0.703000000\t0x82\t8\t0202040100000000",  # PROCESSING

        "0.800000000\t0x01\t6\t000000000000",
        "0.801000000\t0x01\t1\td0",
        "0.802000000\t0x82\t1\t01",
        "0.803000000\t0x82\t8\t0202040100000000",  # PROCESSING

        "0.900000000\t0x01\t6\t000000000000",
        "0.901000000\t0x01\t1\td0",
        "0.902000000\t0x82\t1\t01",
        "0.903000000\t0x82\t8\t0000000000000000",  # READY

        # === read_scan_data(64) ===
        "0.910000000\t0x01\t10\t28000000000000004080",
        "0.911000000\t0x01\t1\td0",
        "0.912000000\t0x82\t1\t03",
        "0.913000000\t0x82\t64\t" + "00" * 64,
        "0.914000000\t0x82\t8\t0000000000000000",

        # === release_unit ===
        "0.920000000\t0x01\t6\t170000000000",
        "0.921000000\t0x01\t1\td0",
        "0.922000000\t0x82\t1\t02",
        "0.923000000\t0x82\t8\t0000000000000000",
    ]

    fixture_path = tmp_path / "full_scan_flow.txt"
    fixture_path.write_text("\n".join(lines))

    replay = UsbCaptureReplay.from_file(fixture_path)
    proto = CoolscanProtocol(MockDevice(), verbose=False, usb_capture_replay=replay)

    with patch("coolscan.protocol.time.sleep"):
        # Run setup + scan + poll manually (perform_scan_sequence calls
        # release_unit in finally, so we can't read data after it)
        assert proto.scanner_ready(timeout=30) is True
        assert proto.reserve_unit() is True
        assert proto.object_position() is True
        assert proto.set_window(ScanParameters()) is True
        lut_data = bytes([i for i in range(256)] * 3)
        assert proto.send_lut(lut_data) is True
        assert proto.start_scan() is True
        assert proto.scanner_ready(timeout=30) is True

        # Read image data before release
        data = proto.read_scan_data(64, DataType.IMAGE_DATA)
        assert len(data) == 64

        # Release unit
        proto.release_unit()

    assert replay.position == replay.total
    proto.close()
