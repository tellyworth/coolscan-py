"""Tests for CLI image processing functions.

Tests _apply_auto_adjust, _write_tiff_16bit_rgb, _save_tiff_dual_ifd,
and _parse_scan_data with 4-channel (IR) data.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from coolscan.cli import (
    _apply_auto_adjust,
    _save_tiff_dual_ifd,
    _write_tiff_16bit_rgb,
)
from coolscan.scanner import _parse_scan_data


@pytest.mark.property_test
class TestApplyAutoAdjust:
    """Tests for _apply_auto_adjust with various input types."""

    def test_uint16_input(self):
        """uint16 input (0-65535 range) produces sensible uint8 output."""
        # Create a varied 16-bit image (gradient across pixels)
        h, w = 8, 8
        arr = np.zeros((h, w, 3), dtype=np.uint16)
        for y in range(h):
            for x in range(w):
                arr[y, x, 0] = (x * 1000 + y * 500 + 1000) % 65536
                arr[y, x, 1] = (x * 800 + y * 600 + 500) % 65536
                arr[y, x, 2] = (x * 600 + y * 700 + 2000) % 65536

        result = _apply_auto_adjust(arr)

        assert result.dtype == np.uint8
        assert result.shape == (h, w, 3)
        # Values should be in 0-255 range
        assert result.min() >= 0
        assert result.max() <= 255
        # Should have meaningful variation
        assert result.max() - result.min() > 100

    def test_uint8_input(self):
        """uint8 input (0-255 range) produces sensible uint8 output."""
        h, w = 8, 8
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        for y in range(h):
            for x in range(w):
                arr[y, x, 0] = (x * 30 + y * 20 + 50) % 256
                arr[y, x, 1] = (x * 25 + y * 30 + 30) % 256
                arr[y, x, 2] = (x * 20 + y * 25 + 100) % 256

        result = _apply_auto_adjust(arr)

        assert result.dtype == np.uint8
        assert result.shape == (h, w, 3)
        assert result.min() >= 0
        assert result.max() <= 255
        # Should have meaningful variation
        assert result.max() - result.min() > 50

    def test_all_zero_input(self):
        """All-zero array should not crash and produce valid output."""
        arr = np.zeros((4, 4, 3), dtype=np.uint16)
        result = _apply_auto_adjust(arr)

        assert result.dtype == np.uint8
        assert result.shape == (4, 4, 3)
        # Inverted zeros become 1.0, which after stretch is uniform
        assert result.min() >= 0
        assert result.max() <= 255

    def test_all_max_input(self):
        """All-max (65535) uint16 array should not crash."""
        arr = np.full((4, 4, 3), 65535, dtype=np.uint16)
        result = _apply_auto_adjust(arr)

        assert result.dtype == np.uint8
        assert result.shape == (4, 4, 3)
        assert result.min() >= 0
        assert result.max() <= 255

    def test_varied_values_produce_varied_output(self):
        """Input with varied values produces non-trivial output."""
        h, w = 16, 16
        arr = np.zeros((h, w, 3), dtype=np.uint16)
        # Create a gradient
        for y in range(h):
            for x in range(w):
                arr[y, x, 0] = (x * 1000 + y * 500) % 65536
                arr[y, x, 1] = (x * 800 + y * 600) % 65536
                arr[y, x, 2] = (x * 600 + y * 700) % 65536

        result = _apply_auto_adjust(arr)

        assert result.dtype == np.uint8
        # Output should have meaningful range
        assert result.max() - result.min() > 100

    def test_inversion_works(self):
        """Spatial inversion: darker input corners become brighter output."""
        h, w = 8, 8
        arr = np.zeros((h, w, 3), dtype=np.uint16)
        # Create a gradient: top-left is dark, bottom-right is bright
        for y in range(h):
            for x in range(w):
                val = (x + y) * 2000 + 1000
                arr[y, x, 0] = val
                arr[y, x, 1] = val
                arr[y, x, 2] = val

        result = _apply_auto_adjust(arr)

        # After inversion, top-left (originally dark) should be brighter
        # than bottom-right (originally bright)
        top_left = result[0, 0, 0]
        bottom_right = result[h - 1, w - 1, 0]
        assert top_left > bottom_right


@pytest.mark.property_test
class TestWriteTiff16bit:
    """Tests for _write_tiff_16bit_rgb."""

    def test_writes_valid_tiff(self):
        """Writing a small 4x4 uint16 RGB array produces valid TIFF."""
        rgb = np.zeros((4, 4, 3), dtype=np.uint16)
        rgb[:, :, 0] = 1000
        rgb[:, :, 1] = 2000
        rgb[:, :, 2] = 3000

        with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
            path = Path(f.name)

        try:
            _write_tiff_16bit_rgb(rgb, path)

            assert path.exists()
            # Verify TIFF magic bytes (II = little-endian, 42 = magic)
            with open(path, "rb") as f:
                header = f.read(4)
            assert header == b"II" + b"\x2a\x00"  # II + 0x002A (42 LE)

            # Verify file has content beyond header
            assert path.stat().st_size > 100
        finally:
            path.unlink()

    def test_larger_image(self):
        """Writing a larger image works correctly."""
        rgb = np.random.randint(0, 65536, size=(50, 50, 3), dtype=np.uint16)

        with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
            path = Path(f.name)

        try:
            _write_tiff_16bit_rgb(rgb, path)

            assert path.exists()
            with open(path, "rb") as f:
                header = f.read(4)
            assert header[:2] == b"II"
        finally:
            path.unlink()

    def test_no_ir_parameter(self):
        """Function signature no longer accepts ir_array parameter."""
        rgb = np.zeros((4, 4, 3), dtype=np.uint16)

        with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
            path = Path(f.name)

        try:
            # Should work without ir_array
            _write_tiff_16bit_rgb(rgb, path)

            # Should NOT accept ir_array (parameter removed)
            import inspect
            sig = inspect.signature(_write_tiff_16bit_rgb)
            params = list(sig.parameters.keys())
            assert "ir_array" not in params
            assert "compression" not in params
        finally:
            path.unlink()


@pytest.mark.property_test
class TestSaveTiffDualIfd:
    """Tests for _save_tiff_dual_ifd."""

    def test_no_compression_parameter(self):
        """Function signature no longer accepts compression parameter."""
        import inspect
        sig = inspect.signature(_save_tiff_dual_ifd)
        params = list(sig.parameters.keys())
        assert "compression" not in params

    def test_8bit_saves_with_pillow(self):
        """8-bit RGB saves with Pillow (supports IR append)."""
        rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        rgb[:, :, 0] = 100
        rgb[:, :, 1] = 150
        rgb[:, :, 2] = 200

        with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
            path = Path(f.name)

        try:
            _save_tiff_dual_ifd(rgb, None, path)
            assert path.exists()
        finally:
            path.unlink()

    def test_16bit_saves_without_ir(self):
        """16-bit RGB saves without IR (IR is skipped for 16-bit)."""
        rgb = np.zeros((4, 4, 3), dtype=np.uint16)
        rgb[:, :, 0] = 1000
        rgb[:, :, 1] = 2000
        rgb[:, :, 2] = 3000

        # IR array that would have caused a crash before the fix
        ir = np.zeros((288, 433), dtype=np.uint16)

        with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
            path = Path(f.name)

        try:
            # Should not crash (IR is skipped for 16-bit)
            _save_tiff_dual_ifd(rgb, ir, path)
            assert path.exists()
        finally:
            path.unlink()


@pytest.mark.property_test
class TestParseScanData4Channel:
    """Tests for _parse_scan_data with 4-channel (IR) data."""

    def test_4channel_zero_offsets(self):
        """4-channel data with (0,0,0,0) offsets preserves all channels."""
        w, h = 4, 2
        # Generate plane data for 4 channels, 12-bit
        samples = []
        for y in range(h):
            for ch in range(4):
                for x in range(w):
                    val = (x * 37 + y * 13 + ch * 53) % 256
                    val = val << 4  # 12-bit shift
                    samples.append(val)

        # Pack as big-endian uint16
        flat = bytearray()
        for s in samples:
            flat.extend(s.to_bytes(2, "big"))

        arr, trailing = _parse_scan_data(
            flat,
            width=w,
            height=h,
            num_channels=4,
            depth=12,
            format="plane",
            channel_offsets=(0, 0, 0, 0),
        )

        assert arr.shape == (h, w, 4)
        assert arr.dtype == np.uint16
        assert trailing == 0

        # Verify all 4 channels have distinct values
        for y in range(h):
            for x in range(w):
                for ch in range(4):
                    expected = ((x * 37 + y * 13 + ch * 53) % 256) << 4
                    assert arr[y, x, ch] == expected

    def test_4channel_ir_channel_separate(self):
        """IR channel (index 3) is correctly extracted with zero offsets."""
        w, h = 3, 3
        samples = []
        for y in range(h):
            for ch in range(4):
                for x in range(w):
                    val = (x * 37 + y * 13 + ch * 53) % 256
                    val = val << 4
                    samples.append(val)

        flat = bytearray()
        for s in samples:
            flat.extend(s.to_bytes(2, "big"))

        arr, _ = _parse_scan_data(
            flat,
            width=w,
            height=h,
            num_channels=4,
            depth=12,
            format="plane",
            channel_offsets=(0, 0, 0, 0),
        )

        ir_channel = arr[:, :, 3]

        # IR channel should be independent, not shifted
        for y in range(h):
            for x in range(w):
                expected = ((x * 37 + y * 13 + 3 * 53) % 256) << 4
                assert ir_channel[y, x] == expected
