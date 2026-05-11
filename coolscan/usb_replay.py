"""
Replay USB bulk traffic from ``test_basic_scan_capture.txt``-style fixtures.

Columns: ``timestamp \\t endpoint \\t length \\t hex``. Host OUT uses ``0x01``,
host IN uses ``0x82`` (matches ``CoolscanProtocol`` hardcoded endpoints).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

BULK_OUT_EP = 0x01
BULK_IN_EP = 0x82


class ReplayError(Exception):
    """Base class for capture replay failures."""


class ReplayMismatchError(ReplayError):
    def __init__(self, message: str, *, expected: bytes, got: bytes):
        super().__init__(message)
        self.expected = expected
        self.got = got


class ReplayExhaustedError(ReplayError):
    """No more captured transactions but the stack issued another I/O."""


class ReplayDirectionError(ReplayError):
    """The next fixture event does not match the requested transfer direction."""


def _parse_capture_lines(
    lines: List[str],
    *,
    line_start: int = 1,
    line_end: Optional[int] = None,
) -> List[Tuple[Literal["out", "in"], bytes]]:
    """
    Parse capture lines into ordered (direction, payload) pairs.

    ``line_start`` / ``line_end`` are 1-based inclusive line numbers in ``lines``.
    """
    events: List[Tuple[Literal["out", "in"], bytes]] = []
    for lineno, line in enumerate(lines, start=1):
        if line_end is not None and lineno > line_end:
            break
        if lineno < line_start:
            continue
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        ep = int(parts[1], 0)
        declared = int(parts[2])
        payload = bytes.fromhex(parts[3])
        if len(payload) != declared:
            raise ValueError(
                f"Line {lineno}: length column {declared} != decoded hex length {len(payload)}"
            )
        if ep == BULK_OUT_EP:
            events.append(("out", payload))
        elif ep == BULK_IN_EP:
            events.append(("in", payload))
        else:
            raise ValueError(f"Line {lineno}: unsupported endpoint {ep:#x}")
    return events


@dataclass
class UsbCaptureReplay:
    """Strict bulk OUT/IN replay cursor over parsed capture events."""

    events: List[Tuple[Literal["out", "in"], bytes]]
    _index: int = 0

    @classmethod
    def from_file(
        cls,
        path: Union[str, Path],
        *,
        line_start: int = 1,
        line_end: Optional[int] = None,
    ) -> "UsbCaptureReplay":
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        return cls(_parse_capture_lines(lines, line_start=line_start, line_end=line_end))

    @property
    def position(self) -> int:
        return self._index

    @property
    def total(self) -> int:
        return len(self.events)

    def consume_out_write(self, data: bytes) -> int:
        if self._index >= len(self.events):
            raise ReplayExhaustedError("OUT write after end of capture")
        kind, expected = self.events[self._index]
        if kind != "out":
            raise ReplayDirectionError(
                f"Expected IN ({len(expected)} bytes) but host wrote {len(data)} bytes"
            )
        if data != expected:
            raise ReplayMismatchError(
                f"OUT payload mismatch at event {self._index}",
                expected=expected,
                got=data,
            )
        self._index += 1
        return len(data)

    def consume_in_read(self, length: int) -> bytes:
        if self._index >= len(self.events):
            raise ReplayExhaustedError("IN read after end of capture")
        kind, payload = self.events[self._index]
        if kind != "in":
            raise ReplayDirectionError(
                f"Expected OUT ({len(payload)} bytes) but host tried to read {length} bytes"
            )
        self._index += 1
        return payload


class ReplayUsbDevice:
    """
    Minimal PyUSB-like facade: ``read`` / ``write`` / ``default_timeout`` / ``clear_halt``.

    Used by ``CoolscanProtocol`` when ``usb_capture_replay`` is set.
    """

    def __init__(self, replay: UsbCaptureReplay, bulk_out_ep: int = BULK_OUT_EP, bulk_in_ep: int = BULK_IN_EP):
        self._replay = replay
        self._bulk_out_ep = bulk_out_ep
        self._bulk_in_ep = bulk_in_ep
        self.default_timeout = 30_000

    def write(self, ep, data, timeout=None):
        if ep != self._bulk_out_ep:
            raise ValueError(f"ReplayUsbDevice: unexpected OUT endpoint {ep:#x}")
        return self._replay.consume_out_write(bytes(data))

    def read(self, ep, length, timeout=None):
        if ep != self._bulk_in_ep:
            raise ValueError(f"ReplayUsbDevice: unexpected IN endpoint {ep:#x}")
        try:
            return self._replay.consume_in_read(length)
        except ReplayExhaustedError:
            # Prescan/idle drain reads after the fixture ends; behave like an empty IN.
            import usb.core

            raise usb.core.USBTimeoutError("timed out", errno=10060)

    def clear_halt(self, ep):
        return None
