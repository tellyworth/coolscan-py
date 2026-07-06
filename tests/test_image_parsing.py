"""End-to-end image data parsing tests.

Generates known raw bytes, runs them through _parse_scan_data, and verifies
decoded pixel values.  Also tests channel offset application and depth handling.

Markers: ``@pytest.mark.property_test`` (fixture-agnostic invariants)
"""

from __future__ import annotations

import struct
from typing import Tuple

import numpy as np
import pytest

from coolscan.scanner import _parse_scan_data


# ---------------------------------------------------------------------------
# Helpers to generate raw scan bytes
# ---------------------------------------------------------------------------

def _make_pixel_data(
    width: int, height: int, channels: int, fmt: str, depth: int = 8
) -> bytearray:
    """Generate raw scan bytes with deterministic pixel values.

    For pixel format: RGBRGB... per line.
    For plane format: RRR...GGG...BBB... per line.

    Pixel value at (x, y, ch) = (x * 37 + y * 13 + ch * 53) % 256
    For 12-bit depth, values are left-shifted by 4 bits.
    """
    expected_fn = lambda x, y, ch: (x * 37 + y * 13 + ch * 53) % 256

    samples = []
    for y in range(height):
        for x in range(width):
            for ch in range(channels):
                val = expected_fn(x, y, ch)
                if depth > 8:
                    val = val << 4  # 12-bit: shift left 4 bits
                samples.append(val)

    if fmt == "pixel":
        # Pixel-interleaved: [R,G,B][R,G,B]... per line (already in this order)
        if depth > 8:
            flat = []
            for s in samples:
                flat.extend(struct.pack(">H", s))
            return bytearray(flat)
        return bytearray(samples)
    else:
        # Plane-interleaved per line: [R...][G...][B...] per line
        plane_samples = []
        for y in range(height):
            for ch in range(channels):
                for x in range(width):
                    val = expected_fn(x, y, ch)
                    if depth > 8:
                        val = val << 4
                    plane_samples.append(val)
        if depth > 8:
            flat = []
            for s in plane_samples:
                flat.extend(struct.pack(">H", s))
            return bytearray(flat)
        return bytearray(plane_samples)


@pytest.mark.property_test
class TestParseScanDataPixelFormat:
    """Tests for pixel-interleaved format (RGBRGB...)."""

    def test_pixel_8bit_3channel(self):
        """Basic pixel-interleaved, 8-bit, 3-channel."""
        w, h, ch = 4, 3, 3
        data = _make_pixel_data(w, h, ch, "pixel", depth=8)

        arr, trailing = _parse_scan_data(data, w, h, ch, 8, "pixel")

        assert trailing == 0
        assert arr.shape == (h, w, ch)
        assert arr.dtype == np.uint8

        # Verify specific pixels
        for y in range(h):
            for x in range(w):
                for c in range(ch):
                    expected = (x * 37 + y * 13 + c * 53) % 256
                    assert arr[y, x, c] == expected, (
                        f"pixel ({x},{y},{c}): got {arr[y,x,c]}, expected {expected}"
                    )

    def test_pixel_4channel(self):
        """Pixel-interleaved with 4 channels (CMYK-like)."""
        w, h, ch = 2, 2, 4
        data = _make_pixel_data(w, h, ch, "pixel", depth=8)

        arr, trailing = _parse_scan_data(data, w, h, ch, 8, "pixel")

        assert trailing == 0
        assert arr.shape == (h, w, ch)

    def test_pixel_short_data_pads(self):
        """When data is too short, remaining pixels are zero-padded."""
        w, h, ch = 4, 2, 3
        full_data = _make_pixel_data(w, h, ch, "pixel", depth=8)
        # Truncate to 80% of expected
        expected_bytes = w * h * ch
        truncated = bytearray(full_data[: int(expected_bytes * 0.8)])

        arr, trailing = _parse_scan_data(truncated, w, h, ch, 8, "pixel")

        assert arr.shape == (h, w, ch)
        # Trailing should be 0 (padded internally)
        assert trailing == 0
        # Last pixels should be zero (padded)
        assert arr[h - 1, w - 1, 2] == 0


@pytest.mark.property_test
class TestParseScanDataPlaneFormat:
    """Tests for plane-interleaved format (RRR...GGG...BBB... per line)."""

    def test_plane_8bit_3channel(self):
        """Basic plane-interleaved, 8-bit, 3-channel."""
        w, h, ch = 4, 3, 3
        data = _make_pixel_data(w, h, ch, "plane", depth=8)

        arr, trailing = _parse_scan_data(data, w, h, ch, 8, "plane")

        assert trailing == 0
        assert arr.shape == (h, w, ch)
        assert arr.dtype == np.uint8

        for y in range(h):
            for x in range(w):
                for c in range(ch):
                    expected = (x * 37 + y * 13 + c * 53) % 256
                    assert arr[y, x, c] == expected, (
                        f"pixel ({x},{y},{c}): got {arr[y,x,c]}, expected {expected}"
                    )

    def test_plane_no_channel_offsets(self):
        """Plane format with zero offsets produces same result as pixel format
        for the same pixel values."""
        w, h, ch = 3, 2, 3
        pixel_data = _make_pixel_data(w, h, ch, "pixel", depth=8)
        plane_data = _make_pixel_data(w, h, ch, "plane", depth=8)

        arr_pixel, _ = _parse_scan_data(pixel_data, w, h, ch, 8, "pixel")
        arr_plane, _ = _parse_scan_data(plane_data, w, h, ch, 8, "plane")

        np.testing.assert_array_equal(arr_pixel, arr_plane)

    def test_plane_short_data_pads(self):
        """When plane data is too short, remaining pixels are zero-padded."""
        w, h, ch = 4, 2, 3
        full_data = _make_pixel_data(w, h, ch, "plane", depth=8)
        expected_bytes = w * h * ch
        truncated = bytearray(full_data[: int(expected_bytes * 0.7)])

        arr, trailing = _parse_scan_data(truncated, w, h, ch, 8, "plane")

        assert arr.shape == (h, w, ch)
        assert trailing == 0


@pytest.mark.property_test
class TestParseScanDataChannelOffsets:
    """Tests for per-channel horizontal shift (LS40_CHANNEL_OFFSETS workaround)."""

    def test_positive_offset_shifts_right(self):
        """Positive channel_offset shifts channel data right."""
        w, h, ch = 10, 1, 3
        data = _make_pixel_data(w, h, ch, "plane", depth=8)

        # Channel 0 offset = 3: source[i] → output[i + 3]
        arr, _ = _parse_scan_data(data, w, h, ch, 8, "plane", (3, 0, 0))

        # First 3 pixels of channel 0 should be zero (not written to)
        assert np.all(arr[0, :3, 0] == 0)

        # Pixels 3+ of channel 0 should match original source[0:7]
        # output[x] = source[x - 3]
        for x in range(3, w):
            src_x = x - 3
            expected = (src_x * 37 + 0 * 13 + 0 * 53) % 256
            assert arr[0, x, 0] == expected, (
                f"ch0[x={x}]: got {arr[0,x,0]}, expected source[{src_x}]={expected}"
            )

        # Last 3 source values (x=7,8,9) are dropped (no room in output)
        # Output pixels 0-2 are zero

    def test_negative_offset_shifts_left(self):
        """Negative channel_offset shifts channel data left."""
        w, h, ch = 10, 1, 3
        data = _make_pixel_data(w, h, ch, "plane", depth=8)

        # Channel 0 offset = -3: data shifted left 3 pixels
        arr, _ = _parse_scan_data(data, w, h, ch, 8, "plane", (-3, 0, 0))

        # Pixels 0+ of channel 0 should match original 3+
        for x in range(w - 3):
            orig_val = ((x + 3) * 37 + 0 * 13 + 0 * 53) % 256
            assert arr[0, x, 0] == orig_val

        # Last 3 pixels should be zero
        assert np.all(arr[0, w - 3 :, 0] == 0)

    def test_zero_offset_no_change(self):
        """Zero offsets produce identical output to no-offset baseline."""
        w, h, ch = 4, 2, 3
        data = _make_pixel_data(w, h, ch, "plane", depth=8)

        arr_offset, _ = _parse_scan_data(data, w, h, ch, 8, "plane", (0, 0, 0))
        arr_none, _ = _parse_scan_data(data, w, h, ch, 8, "plane")

        np.testing.assert_array_equal(arr_offset, arr_none)


@pytest.mark.property_test
class TestParseScanDataDepth:
    """Tests for 12-bit depth handling."""

    def test_12bit_depth_shift(self):
        """12-bit values are shifted right 4 bits to produce 8-bit output."""
        w, h, ch = 2, 2, 3
        data = _make_pixel_data(w, h, ch, "pixel", depth=12)

        arr, trailing = _parse_scan_data(data, w, h, ch, 12, "pixel")

        assert arr.dtype == np.uint8
        assert trailing == 0

        # Values should match 8-bit equivalent (shift right 4 bits)
        for y in range(h):
            for x in range(w):
                for c in range(ch):
                    expected = (x * 37 + y * 13 + c * 53) % 256
                    assert arr[y, x, c] == expected

    def test_12bit_plane_format(self):
        """12-bit values work correctly in plane format."""
        w, h, ch = 3, 2, 3
        data = _make_pixel_data(w, h, ch, "plane", depth=12)

        arr, trailing = _parse_scan_data(data, w, h, ch, 12, "plane")

        assert arr.dtype == np.uint8
        assert trailing == 0

        for y in range(h):
            for x in range(w):
                for c in range(ch):
                    expected = (x * 37 + y * 13 + c * 53) % 256
                    assert arr[y, x, c] == expected


@pytest.mark.property_test
class TestParseScanDataTrailing:
    """Tests for trailing byte count."""

    def test_trailing_bytes_counted(self):
        """Extra bytes at end are reported as trailing."""
        w, h, ch = 2, 2, 3
        data = _make_pixel_data(w, h, ch, "pixel", depth=8)
        # Add 17 extra bytes
        data.extend(b"\x00" * 17)

        arr, trailing = _parse_scan_data(data, w, h, ch, 8, "pixel")

        assert trailing == 17
        assert arr.shape == (h, w, ch)

    def test_no_trailing_when_exact(self):
        """Exact-sized data produces zero trailing bytes."""
        w, h, ch = 3, 2, 3
        data = _make_pixel_data(w, h, ch, "pixel", depth=8)

        arr, trailing = _parse_scan_data(data, w, h, ch, 8, "pixel")

        assert trailing == 0


@pytest.mark.property_test
class TestParseScanDataToPIL:
    """End-to-end: raw scan bytes → _parse_scan_data → PIL Image → pixel values."""

    def test_roundtrip_pixel_format_to_pil(self):
        """Raw bytes → numpy array → PIL Image → pixel values match source."""
        from PIL import Image

        w, h, ch = 8, 6, 3
        data = _make_pixel_data(w, h, ch, "pixel", depth=8)

        arr, _ = _parse_scan_data(data, w, h, ch, 8, "pixel")
        img = Image.fromarray(arr, mode="RGB")

        assert img.size == (w, h)

        # Verify specific pixel values
        for y in range(h):
            for x in range(w):
                px = img.getpixel((x, y))
                for c in range(ch):
                    expected = (x * 37 + y * 13 + c * 53) % 256
                    assert px[c] == expected, (
                        f"PIL pixel ({x},{y},{c}): got {px[c]}, expected {expected}"
                    )

    def test_roundtrip_plane_format_to_pil(self):
        """Plane-interleaved bytes → numpy array → PIL Image → pixel match."""
        from PIL import Image

        w, h, ch = 6, 4, 3
        data = _make_pixel_data(w, h, ch, "plane", depth=8)

        arr, _ = _parse_scan_data(data, w, h, ch, 8, "plane")
        img = Image.fromarray(arr, mode="RGB")

        assert img.size == (w, h)

        for y in range(h):
            for x in range(w):
                px = img.getpixel((x, y))
                for c in range(ch):
                    expected = (x * 37 + y * 13 + c * 53) % 256
                    assert px[c] == expected

