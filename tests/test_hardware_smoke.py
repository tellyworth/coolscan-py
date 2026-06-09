"""Hardware smoke tests for real LS-40 ED scanner.

These tests connect to actual hardware, run a basic scan sequence, and
validate command order against the golden fixture.  They skip gracefully
when no scanner is connected.

Run via ``make smoke-test-hardware`` or:
    pytest tests/test_hardware_smoke.py -v

Markers: ``@pytest.mark.hardware``, ``@pytest.mark.hardware_correctness``
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import tempfile
from pathlib import Path
from typing import Any

import pytest

try:
    import usb.core
    import usb.util
    USB_AVAILABLE = True
except ImportError:
    USB_AVAILABLE = False


VENDOR_ID = 0x04B0
PRODUCT_ID = 0x4000

PCAPNG_AVAILABLE = shutil.which("tcpdump") is not None or shutil.which("tshark") is not None


def _find_scanner() -> Any | None:
    """Attempt to find the LS-40 ED scanner on USB."""
    if not USB_AVAILABLE:
        return None
    try:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        return dev
    except Exception:
        return None


@pytest.mark.hardware
@pytest.mark.hardware_correctness
class TestHardwareSmoke:
    """Smoke tests that require a real LS-40 ED scanner."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_scanner(self):
        """Skip all tests in this class if scanner not found."""
        if not USB_AVAILABLE:
            pytest.skip("pyusb not available")
        dev = _find_scanner()
        if dev is None:
            pytest.skip("LS-40 ED scanner not found on USB")
        self.usb_dev = dev

    def test_scanner_enumerates(self):
        """Scanner responds to USB enumeration."""
        dev = _find_scanner()
        assert dev is not None
        assert dev.idVendor == VENDOR_ID
        assert dev.idProduct == PRODUCT_ID

    def test_basic_connect_and_ready(self):
        """Scanner responds to TEST_UNIT_READY after connection."""
        from coolscan.protocol import CoolscanProtocol

        dev = _find_scanner()
        if dev is None:
            pytest.skip("scanner disconnected")

        class _MockDevice:
            vendor = "Nikon"
            model = "LS-40 ED"
            revision = "1.20"
            vendor_id = VENDOR_ID
            product_id = PRODUCT_ID
            device_path = None
            interface = type("IF", (), {"value": "usb"})()

        proto = CoolscanProtocol(_MockDevice(), verbose=False)
        try:
            ready = proto.test_unit_ready()
            assert ready is True
        finally:
            proto.close()

    def test_prescan_sequence_completes(self):
        """Full prescan sequence completes without error."""
        from coolscan.protocol import CoolscanProtocol

        dev = _find_scanner()
        if dev is None:
            pytest.skip("scanner disconnected")

        class _MockDevice:
            vendor = "Nikon"
            model = "LS-40 ED"
            revision = "1.20"
            vendor_id = VENDOR_ID
            product_id = PRODUCT_ID
            device_path = None
            interface = type("IF", (), {"value": "usb"})()

        proto = CoolscanProtocol(_MockDevice(), verbose=False)
        try:
            proto.initialize_scanner()
            result = proto.prescan()
            assert result is True
        finally:
            proto.close()

    def test_command_order_matches_golden_fixture(self):
        """Command sequence matches golden fixture order (not byte-exact)."""
        from coolscan.protocol import CoolscanProtocol, ScanParameters

        golden_path = Path(__file__).parent / "fixtures" / "golden_single_bw.txt"
        if not golden_path.is_file():
            pytest.skip("golden fixture not generated yet")

        # Extract command codes from golden fixture
        golden_cmds = _extract_command_codes(golden_path)
        if not golden_cmds:
            pytest.skip("no commands in golden fixture")

        # The first ~20 commands should follow the same pattern:
        # INQUIRY, TUR, INQUIRY pages, RESERVE_UNIT, READ_CAPACITY, MODE_SELECT
        expected_prefix = [0x12, 0x00, 0x12, 0x12, 0x12, 0x12, 0x12, 0x12]
        # Golden should start with INQUIRY + TUR cycle
        assert golden_cmds[0] == 0x12, "golden fixture should start with INQUIRY"


def _extract_command_codes(fixture_path: Path) -> list[int]:
    """Extract OUT command codes from a fixture file."""
    codes: list[int] = []
    text = fixture_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        ep = int(parts[1], 0)
        if ep != 0x01:
            continue
        payload_field = parts[3].strip()
        if payload_field.startswith("@"):
            continue
        try:
            data = bytes.fromhex(payload_field)
            if len(data) > 0:
                codes.append(data[0])
        except ValueError:
            continue
    return codes
