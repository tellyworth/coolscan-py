"""Tests for scripts/analyze_capture.py --extract-images feature."""

import os
import tempfile
import struct
from pathlib import Path
from typing import List

import pytest

from scripts.analyze_capture import (
    Event,
    DecodedInfo,
    _decode_all,
    _build_frame_info,
    _classify_scan_type,
    _parse_frame_ids,
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


def _make_phase_check(index: int, ts: float) -> Event:
    """Create a PHASE_CHECK (0xd0) OUT event."""
    return _make_event(index, ts, "out", 0x01, bytes([0xd0]))


def _make_phase_resp(index: int, ts: float, phase: int = 0x02) -> Event:
    """Create a PHASE_RESP IN event."""
    return _make_event(index, ts, "in", 0x82, bytes([phase]))


def _make_wdb_payload(
    width: int,
    height: int,
    x_res: int,
    y_res: int,
    channel: int = 1,
    transfer_byte: int = 0x08,
    frame_offset: int = 0,
) -> bytes:
    """Build a 58-byte WDB payload for synthetic captures."""
    data = bytearray(58)
    # Bytes 4-7: window id (0x00000032)
    data[4:8] = struct.pack(">I", 0x00000032)
    # Byte 8: channel
    data[8] = channel
    # Bytes 10-11: x_resolution
    data[10:12] = struct.pack(">H", x_res)
    # Bytes 12-13: y_resolution
    data[12:14] = struct.pack(">H", y_res)
    # Bytes 18-21: frame_offset
    data[18:22] = struct.pack(">I", frame_offset)
    # Bytes 22-25: width
    data[22:26] = struct.pack(">I", width)
    # Bytes 26-29: height (length)
    data[26:30] = struct.pack(">I", height)
    # Byte 34: transfer_byte
    data[34] = transfer_byte
    # Bytes 54-57: exposure (0)
    return bytes(data)


def _make_read_image_cmd(index: int, ts: float) -> Event:
    """Create a READ(10) with datatype=0x00 (IMAGE_DATA) event."""
    return _make_event(index, ts, "out", 0x01, bytes([0x28, 0x00, 0x00] + [0] * 7))


def _make_data_block(index: int, ts: float, data: bytes) -> Event:
    """Create a DATA_BLOCK IN response event."""
    return _make_event(index, ts, "in", 0x82, data)


def _make_status_good(index: int, ts: float) -> Event:
    """Create a STATUS GOOD response."""
    return _make_event(index, ts, "in", 0x82, bytes(8))


def _make_tur_cmd(index: int, ts: float) -> Event:
    """Create a TUR (0x00) command event."""
    return _make_event(index, ts, "out", 0x01, bytes([0x00] * 6))


def _build_synthetic_capture(
    frame_count: int = 2,
    width: int = 10,
    height: int = 200,
    x_res: int = 2900,
    y_res: int = 2900,
    channel: int = 1,
    transfer_byte: int = 0x08,
    frame_offset: int = 0,
) -> List[Event]:
    """Build a synthetic capture with `frame_count` image frames.

    Each frame has:
    - SCAN command (0x24)
    - PHASE_CHECK + PHASE_RESP handshake
    - DATA_OUT with WDB payload (58 bytes)
    - STATUS GOOD
    - TUR + PHASE_CHECK + STATUS handshake
    - READ(10) with datatype=0x00
    - DATA_BLOCK with image data
    - STATUS GOOD
    """
    events: List[Event] = []
    idx = 0
    ts = 0.0

    channels = channel
    bytes_per_channel = 1  # 8-bit for synthetic tests
    bytes_per_pixel = channels * bytes_per_channel
    total_bytes = width * height * bytes_per_pixel

    for _ in range(frame_count):
        # SCAN command
        events.append(_make_scan_cmd(idx, ts))
        idx += 1
        ts += 0.01

        # PHASE_CHECK + PHASE_RESP (phase 0x02 = data out)
        events.append(_make_phase_check(idx, ts))
        idx += 1
        ts += 0.01
        events.append(_make_phase_resp(idx, ts, phase=0x02))
        idx += 1
        ts += 0.01

        # WDB DATA_OUT (58 bytes)
        wdb = _make_wdb_payload(width, height, x_res, y_res, channel, transfer_byte, frame_offset)
        events.append(_make_event(idx, ts, "out", 0x01, wdb))
        idx += 1
        ts += 0.01

        # STATUS GOOD
        events.append(_make_status_good(idx, ts))
        idx += 1
        ts += 0.01

        # TUR + PHASE_CHECK + STATUS handshake
        events.append(_make_tur_cmd(idx, ts))
        idx += 1
        ts += 0.01
        events.append(_make_phase_check(idx, ts))
        idx += 1
        ts += 0.01
        events.append(_make_phase_resp(idx, ts, phase=0x02))
        idx += 1
        ts += 0.01
        events.append(_make_status_good(idx, ts))
        idx += 1
        ts += 0.01

        # READ(10) with datatype=0x00
        events.append(_make_read_image_cmd(idx, ts))
        idx += 1
        ts += 0.01

        # DATA_BLOCK with image data (plane-interleaved: R...G...B... per line)
        data = bytes(list(range(256)) * (total_bytes // 256 + 1))[:total_bytes]
        events.append(_make_data_block(idx, ts, data))
        idx += 1
        ts += 0.01

        # STATUS GOOD
        events.append(_make_status_good(idx, ts))
        idx += 1
        ts += 0.01

    return events


class TestParseFrameIds:
    """Tests for _parse_frame_ids helper."""

    def test_parse_all(self) -> None:
        assert _parse_frame_ids("all") is None

    def test_parse_single(self) -> None:
        assert _parse_frame_ids("2") == [2]

    def test_parse_range(self) -> None:
        assert _parse_frame_ids("0-2") == [0, 1, 2]

    def test_parse_mixed(self) -> None:
        assert _parse_frame_ids("0,2-4,6") == [0, 2, 3, 4, 6]

    def test_parse_dedup(self) -> None:
        assert _parse_frame_ids("1,1,2") == [1, 2]


class TestClassifyScanType:
    """Tests for _classify_scan_type helper."""

    def test_prescan(self) -> None:
        assert _classify_scan_type(96, 1) == "prescan"

    def test_preview_rgb(self) -> None:
        assert _classify_scan_type(290, 1) == "preview"
        assert _classify_scan_type(290, 2) == "preview"
        assert _classify_scan_type(290, 3) == "preview"

    def test_preview_ir(self) -> None:
        assert _classify_scan_type(290, 9) == "preview_ir"

    def test_full_res_rgb(self) -> None:
        assert _classify_scan_type(2900, 1) == "full_res"
        assert _classify_scan_type(2900, 3) == "full_res"

    def test_full_res_ir(self) -> None:
        assert _classify_scan_type(2900, 9) == "full_res_ir"


class TestBuildFrameInfo:
    """Tests for _build_frame_info helper."""

    def test_basic_frame_detection(self) -> None:
        """Two-frame synthetic capture produces two frame info entries."""
        events = _build_synthetic_capture(frame_count=2)
        _decode_all(events)
        frames = _build_frame_info(events)
        assert len(frames) == 2

    def test_frame_params_from_wdb(self) -> None:
        """Frame parameters are auto-detected from WDB payload."""
        events = _build_synthetic_capture(frame_count=1, width=50, height=300, x_res=2900, y_res=2900)
        _decode_all(events)
        frames = _build_frame_info(events)
        assert len(frames) == 1
        fi = frames[0]
        assert fi["width"] == 50
        assert fi["h_declared"] == 300
        assert fi["scan_type"] == "full_res"
        assert fi["has_ir"] is False
        assert fi["num_channels"] == 3

    def test_prescan_frame(self) -> None:
        """96 DPI WDB produces a prescan frame."""
        events = _build_synthetic_capture(frame_count=1, x_res=96, y_res=96)
        _decode_all(events)
        frames = _build_frame_info(events)
        assert len(frames) == 1
        assert frames[0]["scan_type"] == "prescan"

    def test_ir_frame(self) -> None:
        """Channel=9 WDB produces an IR frame."""
        events = _build_synthetic_capture(frame_count=1, channel=9, x_res=290, y_res=290)
        _decode_all(events)
        frames = _build_frame_info(events)
        assert len(frames) == 1
        assert frames[0]["has_ir"] is True
        assert frames[0]["scan_type"] == "preview_ir"
        assert frames[0]["num_channels"] == 1

    def test_no_frames(self) -> None:
        """Capture with no image data returns empty list."""
        events = [
            _make_event(0, 0.0, "out", 0x01, bytes([0x00] * 6)),
        ]
        _decode_all(events)
        frames = _build_frame_info(events)
        assert frames == []


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
            frame_ids=[],
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
            frame_ids=[],
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
            frame_ids=[],
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
            frame_ids=[],
            fmt="jpeg",
        )

        assert results == []

    def test_small_frames_skipped(self, tmp_path: Path) -> None:
        """Prescan frames (96 DPI) are skipped by default (full-res only)."""
        events = _build_synthetic_capture(frame_count=1, x_res=96, y_res=96)
        _decode_all(events)

        output_dir = str(tmp_path / "images")
        # Empty list = default behavior: full-res only
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            frame_ids=[],
            fmt="jpeg",
        )

        assert results == []

    def test_auto_detect_params(self, tmp_path: Path) -> None:
        """WDB parameters are auto-detected and used for parsing."""
        events = _build_synthetic_capture(frame_count=1, width=20, height=100)
        _decode_all(events)

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            frame_ids=[],
            fmt="jpeg",
        )

        assert len(results) == 1
        assert os.path.exists(results[0]["jpeg_path"])

    def test_selective_frame_ids(self, tmp_path: Path) -> None:
        """frame_ids parameter selects specific frames."""
        events = _build_synthetic_capture(frame_count=3)
        _decode_all(events)

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            frame_ids=[1],
            fmt="jpeg",
        )

        assert len(results) == 1
        assert results[0]["frame_index"] == 1

    def test_truncation_warning(self, tmp_path: Path, capsys) -> None:
        """Warning printed when data is smaller than declared."""
        # Build a capture where the WDB declares height=200 but we only send
        # enough data for ~50 lines (< 0.5 * declared)
        events = _build_synthetic_capture(
            frame_count=1,
            width=10,
            height=200,
            x_res=2900,
            y_res=2900,
        )
        _decode_all(events)

        # Replace the DATA_BLOCK with truncated data (only 100 lines worth)
        for ev in events:
            if ev.decoded and ev.decoded.cmd_name == "DATA_BLOCK":
                truncated = ev.raw[:100 * 10 * 3]  # 100 lines instead of 200
                ev.raw = truncated
                break

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            frame_ids=[],
            fmt="jpeg",
        )

        captured = capsys.readouterr()
        assert "truncated" in captured.err.lower()

    def test_ir_frame_extraction(self, tmp_path: Path) -> None:
        """IR frames (channel=9) are extracted as single-channel images."""
        events = _build_synthetic_capture(
            frame_count=1,
            channel=9,
            x_res=2900,
            y_res=2900,
        )
        _decode_all(events)

        output_dir = str(tmp_path / "images")
        results = extract_image_frames(
            events,
            output_dir=output_dir,
            frame_ids=[],
            fmt="jpeg",
        )

        assert len(results) == 1
        assert results[0]["jpeg_path"] is not None
        assert os.path.exists(results[0]["jpeg_path"])
