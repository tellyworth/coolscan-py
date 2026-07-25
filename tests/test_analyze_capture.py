"""Tests for scripts/analyze_capture.py --extract-images feature."""

import os
import tempfile
from pathlib import Path
from typing import List

import pytest

from scripts.analyze_capture import (
    Event,
    DecodedInfo,
    _decode_all,
    extract_image_frames,
)


def _make_event(
    index: int,
    timestamp: float,
    direction: str,
    endpoint: int,
    raw: bytes,
) -> Event:
    """Helper to create an Event with decoded info."""
    return Event(
        index=index,
        timestamp=timestamp,
        direction=direction,
        endpoint=endpoint,
        raw=raw,
    )


def _make_scan_cmd(index: int, ts: float) -> Event:
    """Create a SCAN (0x24) command event."""
    return _make_event(index, ts, "out", 0x01, bytes([0x24] * 10))


def _make_read_image_cmd(index: int, ts: float) -> Event:
    """Create a READ(10) with datatype=0x00 (IMAGE_DATA) event."""
    return _make_event(index, ts, "out", 0x01, bytes([0x28, 0x00, 0x00] + [0] * 7))


def _make_data_block(index: int, ts: float, data: bytes) -> Event:
    """Create a DATA_BLOCK IN response event."""
    return _make_event(index, ts, "in", 0x82, data)


def _make_status_good(index: int, ts: float) -> Event:
    """Create a STATUS GOOD response."""
    return _make_event(index, ts, "in", 0x82, bytes(8))


def _build_synthetic_capture(frame_count: int = 2) -> List[Event]:
    """Build a synthetic capture with `frame_count` image frames.

    Each frame has:
    - SCAN command (0x24)
    - READ(10) with datatype=0x00
    - DATA_BLOCK with image data (width=10, height=200, 3 channels, 16-bit)
    - STATUS GOOD
    """
    events: List[Event] = []
    idx = 0
    ts = 0.0

    width, height, channels = 10, 200, 3
    bytes_per_channel = 2  # 16-bit
    bytes_per_pixel = channels * bytes_per_channel
    total_bytes = width * height * bytes_per_pixel

    for _ in range(frame_count):
        # SCAN command
        events.append(_make_scan_cmd(idx, ts))
        idx += 1
        ts += 0.1

        # READ(10) with datatype=0x00
        events.append(_make_read_image_cmd(idx, ts))
        idx += 1
        ts += 0.1

        # DATA_BLOCK with image data
        data = bytes(list(range(256)) * (total_bytes // 256 + 1))[:total_bytes]
        events.append(_make_data_block(idx, ts, data))
        idx += 1
        ts += 0.1

        # STATUS GOOD
        events.append(_make_status_good(idx, ts))
        idx += 1
        ts += 0.1

    return events


class TestExtractImageFrames:
    """Tests for extract_image_frames function."""

    def test_extract_two_frames(self, tmp_path: Path) -> None:
        """Two-frame synthetic capture produces two output files."""
        events = _build_synthetic_capture(frame_count=2)
        _decode_all(events)

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            depth=8,
            width=10,
            height=200,
            num_channels=3,
            fmt="both",
        )

        assert len(results) == 2
        for r in results:
            assert r["tiff_path"] is not None
            assert r["jpeg_path"] is not None
            assert os.path.exists(r["tiff_path"])
            assert os.path.exists(r["jpeg_path"])

    def test_extract_tiff_only(self, tmp_path: Path) -> None:
        """tiff format produces only TIFF files."""
        events = _build_synthetic_capture(frame_count=1)
        _decode_all(events)

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            depth=8,
            width=10,
            height=200,
            num_channels=3,
            fmt="tiff",
        )

        assert len(results) == 1
        assert results[0]["tiff_path"] is not None
        assert os.path.exists(results[0]["tiff_path"])
        assert results[0]["jpeg_path"] is None

    def test_extract_jpeg_only(self, tmp_path: Path) -> None:
        """jpeg format produces only JPEG files."""
        events = _build_synthetic_capture(frame_count=1)
        _decode_all(events)

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            depth=8,
            width=10,
            height=200,
            num_channels=3,
            fmt="jpeg",
        )

        assert len(results) == 1
        assert results[0]["tiff_path"] is None
        assert results[0]["jpeg_path"] is not None
        assert os.path.exists(results[0]["jpeg_path"])

    def test_no_frames_returns_empty(self, tmp_path: Path) -> None:
        """Capture with no image data returns empty list."""
        events = [
            _make_event(0, 0.0, "out", 0x01, bytes([0x00] * 6)),
        ]
        _decode_all(events)

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            depth=8,
            width=10,
            height=200,
            num_channels=3,
            fmt="both",
        )

        assert results == []

    def test_small_frames_skipped(self, tmp_path: Path) -> None:
        """Frames with height < 100 are skipped."""
        events: List[Event] = []
        idx = 0
        ts = 0.0

        # Very small frame (1x1 pixels, 6 bytes)
        data = bytes([0] * 6)
        events.append(_make_scan_cmd(idx, ts))
        idx += 1
        ts += 0.1
        events.append(_make_read_image_cmd(idx, ts))
        idx += 1
        ts += 0.1
        events.append(_make_data_block(idx, ts, data))
        idx += 1
        ts += 0.1
        events.append(_make_status_good(idx, ts))

        _decode_all(events)

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            depth=8,
            width=10,
            height=200,
            num_channels=3,
            fmt="both",
        )

        assert results == []
