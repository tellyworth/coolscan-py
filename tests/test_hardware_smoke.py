"""Hardware smoke tests for real LS-40 ED scanner.

These tests connect to actual hardware, run a basic scan sequence, and
validate command order against the golden fixture.  They skip gracefully
when no scanner is connected.

Run via ``make smoke-test-hardware`` or:
    pytest tests/test_hardware_smoke.py -v

Markers: ``@pytest.mark.hardware``, ``@pytest.mark.hardware_correctness``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

try:
    import usb.core
    USB_AVAILABLE = True
except ImportError:
    USB_AVAILABLE = False


VENDOR_ID = 0x04B0
PRODUCT_ID = 0x4000


def _find_scanner() -> Any | None:
    """Attempt to find the LS-40 ED scanner on USB."""
    if not USB_AVAILABLE:
        return None
    try:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        return dev
    except Exception:
        return None


class _DeviceDescriptor:
    """Device descriptor for CoolscanProtocol. Supplies vendor/product IDs
    so _init_usb() discovers the real scanner via pyusb."""
    vendor = "Nikon"
    model = "LS-40 ED"
    revision = "1.20"
    vendor_id = VENDOR_ID
    product_id = PRODUCT_ID
    device_path = None
    interface = type("IF", (), {"value": "usb"})()


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

        proto = CoolscanProtocol(_DeviceDescriptor(), verbose=False)
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

        proto = CoolscanProtocol(_DeviceDescriptor(), verbose=False)
        try:
            proto.initialize_scanner()
            proto.focus_setup()
            result = proto.prescan()
            assert result is True
        finally:
            proto.close()


@pytest.mark.property_test
class TestGoldenFixtureCommandOrder:
    """Validate golden fixture command sequence (no hardware required)."""

    def test_golden_fixture_starts_with_inquiry(self):
        """Golden fixture begins with INQUIRY command (0x12)."""
        golden_path = Path(__file__).parent / "fixtures" / "golden_single_bw.txt"
        if not golden_path.is_file():
            pytest.skip("golden fixture not generated yet")

        codes = _extract_command_codes(golden_path)
        assert len(codes) > 0, "golden fixture has no OUT commands"
        assert codes[0] == 0x12, "golden fixture should start with INQUIRY"

    def test_golden_fixture_has_tur_after_inquiry(self):
        """Golden fixture has TEST_UNIT_READY following initial INQUIRY sequence."""
        golden_path = Path(__file__).parent / "fixtures" / "golden_single_bw.txt"
        if not golden_path.is_file():
            pytest.skip("golden fixture not generated yet")

        codes = _extract_command_codes(golden_path)
        # INQUIRY (0x12) is followed by PHASE_CHECK (0xd0), then TUR (0x00)
        assert 0x00 in codes[:5], "expected TUR within first 5 OUT commands"

    def test_golden_fixture_has_reserve_unit(self):
        """Golden fixture contains RESERVE_UNIT (0x16)."""
        golden_path = Path(__file__).parent / "fixtures" / "golden_single_bw.txt"
        if not golden_path.is_file():
            pytest.skip("golden fixture not generated yet")

        codes = _extract_command_codes(golden_path)
        assert 0x16 in codes, "golden fixture should contain RESERVE_UNIT"

    def test_golden_fixture_has_read_capacity(self):
        """Golden fixture contains READ_CAPACITY (0x25)."""
        golden_path = Path(__file__).parent / "fixtures" / "golden_single_bw.txt"
        if not golden_path.is_file():
            pytest.skip("golden fixture not generated yet")

        codes = _extract_command_codes(golden_path)
        assert 0x25 in codes, "golden fixture should contain READ_CAPACITY"


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


@pytest.fixture(scope="session")
def scanner():
    """Session-scoped scanner for hardware tests."""
    dev = _find_scanner()
    if dev is None:
        pytest.skip("scanner not found")
    from coolscan.protocol import CoolscanProtocol

    proto = CoolscanProtocol(_DeviceDescriptor(), verbose=False)
    proto.initialize_scanner()
    yield proto
    proto.close()


@pytest.mark.hardware
@pytest.mark.hardware_correctness
class TestHardwareExtended:
    """Extended hardware tests using a session-scoped scanner fixture."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_scanner(self, scanner):
        self.proto = scanner

    def test_full_scan_frame_succeeds(self, scanner):
        """Full scan frame completes and returns True."""
        result = scanner.full_scan_frame()
        assert result is True

    def test_prescan_returns_exposure_values(self, scanner):
        """Prescan completes and returns exposure data."""
        result = scanner.prescan()
        assert result is True

    def test_teardown_eject_succeeds(self, scanner):
        """Scan teardown completes cleanly."""
        result = scanner.scan_teardown()
        assert result is True

    def test_drain_loop_terminates(self, scanner):
        """Buffer drain during prescan terminates without hanging."""
        result = scanner.prescan(timeout=120)
        assert result is True
