#!/usr/bin/env python3
"""Analyze WDB structure, determine scan dimensions, and render image."""

import struct
import numpy as np
from PIL import Image

# --- WDB Parsing (corrected offsets) ---

def parse_wdb(hexstr):
    """Parse a 58-byte WDB from hex string.

    Layout (verified by byte inspection):
      0-7:   header (8 bytes)
      8:     window_id (1 byte)
      9:     unknown/reserved (1 byte)
      10-11: x_resolution (2 bytes, BE)
      12-13: y_resolution (2 bytes, BE)
      14-17: offset_x (4 bytes, BE)
      18-21: offset_y (4 bytes, BE)
      22-25: size_x (4 bytes, BE)
      26-29: size_y (4 bytes, BE)
      30:    brightness (1 byte)
      31:    threshold (1 byte)
      32:    contrast (1 byte)
      33:    composition (1 byte)
      34:    depth (1 byte)
      35-47: padding (13 bytes)
      48:    multiread (1 byte)
      49:    averaging (1 byte)
      50:    scan_kind (1 byte)
      51:    scan_mode (1 byte)
      52:    color_interleave (1 byte)
      53:    ae (1 byte)
      54-57: exposure (4 bytes, BE)
    """
    data = bytes.fromhex(hexstr)
    if len(data) != 58:
        print(f"  WARNING: WDB is {len(data)} bytes, expected 58")

    wdb = {}
    wdb['raw'] = data
    wdb['header'] = data[0:8].hex()
    wdb['window_id'] = data[8]
    wdb['reserved_9'] = data[9]
    wdb['x_resolution'] = struct.unpack('>H', data[10:12])[0]
    wdb['y_resolution'] = struct.unpack('>H', data[12:14])[0]
    wdb['offset_x'] = struct.unpack('>I', data[14:18])[0]
    wdb['offset_y'] = struct.unpack('>I', data[18:22])[0]
    wdb['size_x'] = struct.unpack('>I', data[22:26])[0]
    wdb['size_y'] = struct.unpack('>I', data[26:30])[0]
    wdb['brightness'] = data[30]
    wdb['threshold'] = data[31]
    wdb['contrast'] = data[32]
    wdb['composition'] = data[33]
    wdb['depth'] = data[34]
    wdb['multiread'] = data[48]
    wdb['averaging'] = data[49]
    wdb['scan_kind'] = data[50]
    wdb['scan_mode'] = data[51]
    wdb['color_interleave'] = data[52]
    wdb['ae'] = data[53]
    wdb['exposure'] = struct.unpack('>I', data[54:58])[0]

    return wdb

# Prescan WDB (window 1 = R)
prescan_wdb_hex = "0000000000000032010000600060000000000000000000000b3600008760000000050c000000000000000000000000000081020202ff0000a381"
# Normal WDB (window 1 = R)
normal_wdb_hex = "000000000000003201000b540b54000000000000000000000b36000010ec000000020800000000000000000000000081010202ff00009ce6"

print("=" * 70)
print("WDB STRUCTURE ANALYSIS (Corrected Offsets)")
print("=" * 70)

print("\n--- Prescan WDB (window 1, R channel) ---")
pw = parse_wdb(prescan_wdb_hex)
for k, v in pw.items():
    if k not in ('raw',):
        print(f"  {k}: {v} (0x{v & 0xFFFFFFFF:08X})" if isinstance(v, int) else f"  {k}: {v}")

print("\n--- Normal WDB (window 1, R channel) ---")
nw = parse_wdb(normal_wdb_hex)
for k, v in nw.items():
    if k not in ('raw',):
        print(f"  {k}: {v} (0x{v & 0xFFFFFFFF:08X})" if isinstance(v, int) else f"  {k}: {v}")

# --- Physical dimension analysis ---
print("\n" + "=" * 70)
print("PHYSICAL DIMENSION ANALYSIS")
print("=" * 70)

# If size is in device units and resolution is in DPI:
# physical_inches = size / (resolution * some_factor)
# Or: physical_mm = size / (resolution / 25.4 * some_factor)

# From CONTROL_FRAME: resx_max = 4332
# From SETUP entry 0: value = 4332 (matches resx_max)

resx_max = 4332

print(f"\nresx_max (from CONTROL_FRAME): {resx_max}")

for desc, wdb in [("Prescan", pw), ("Normal", nw)]:
    sx = wdb['size_x']
    sy = wdb['size_y']
    rx = wdb['x_resolution']
    ry = wdb['y_resolution']

    # Physical size in inches = size_in_device_units / (DPI * device_units_per_inch)
    # If device units = 0.1mm: physical_inches = size * 0.003937
    # If device units = pixels at 1 DPI: physical_inches = size / DPI

    # Try: physical_mm = size / (resolution / 25.4)
    phys_x_mm = sx / (rx / 25.4) if rx > 0 else 0
    phys_y_mm = sy / (ry / 25.4) if ry > 0 else 0

    # Try: physical_mm = size * 0.1 (if units are 0.1mm)
    phys_x_mm_01 = sx * 0.1
    phys_y_mm_01 = sy * 0.1

    # Try: pitch = resx_max / resolution, pixels = size / pitch
    pitch = resx_max / rx if rx > 0 else 0
    pixels_x = sx / pitch if pitch > 0 else 0
    pixels_y = sy / pitch if pitch > 0 else 0

    print(f"\n  {desc} WDB (res={rx}x{ry} DPI, size={sx}x{sy}):")
    print(f"    Physical (size/res*25.4): {phys_x_mm:.1f} x {phys_y_mm:.1f} mm")
    print(f"    Physical (size*0.1mm):    {phys_x_mm_01:.1f} x {phys_y_mm_01:.1f} mm")
    print(f"    Pitch (resx_max/res):     {pitch:.4f}")
    print(f"    Pixels (size/pitch):      {pixels_x:.1f} x {pixels_y:.1f}")

    # For prescan: expected ~2870 x ~34656 pixels? That's huge.
    # But actual data has 110880 pixels per channel.

# --- Dimension Analysis ---
print("\n" + "=" * 70)
print("DIMENSION ANALYSIS FROM DATA")
print("=" * 70)

# Full scan: 32768000 bytes, 8-bit RGB, stride=8640 (width=2880, no padding)
# Width verified by autocorrelation peak at lag=8640
total_bytes = len(raw) if 'raw' in dir() else 32768000
pixels_per_channel = total_bytes // 3  # rough estimate, actual uses stride
print(f"\nTotal bytes: {total_bytes}")
print(f"Verified width: 2880 (autocorrelation peak at lag=8640)")
print(f"Verified stride: 8640 bytes/row (no padding)")

# Factor analysis for reference
pixels_est = total_bytes // 3
print(f"\nAll factor pairs of {pixels_est}:")
factors = []
for w in range(1, min(int(pixels_est**0.5) + 1, 5000)):
    if pixels_est % w == 0:
        h = pixels_est // w
        factors.append((w, h))

# Show plausible dimensions
plausible = []
for w, h in factors:
    ar = max(w, h) / min(w, h)
    if 1.2 <= ar <= 2.5 and min(w, h) >= 50 and max(w, h) <= 5000:
        plausible.append((w, h, ar))
        print(f"  {w}x{h} (AR={ar:.3f})")

# --- Pitch analysis with corrected WDB ---
print(f"\n--- Pitch Analysis (corrected WDB) ---")
print(f"  Prescan WDB: size_x={pw['size_x']}, size_y={pw['size_y']}, res={pw['x_resolution']} DPI")
print(f"  Normal WDB:  size_x={nw['size_x']}, size_y={nw['size_y']}, res={nw['x_resolution']} DPI")

# SANE formula: pitch = resx_max / real_resx
# Where real_resx is the actual scan resolution
# For prescan at 96 DPI: pitch = 4332 / 96 = 45.25
# pixels_x = size_x / pitch = 2870 / 45.25 = 63.4 (not integer!)

# But SANE also has: res_preview = resx_max / 10 = 433.2 DPI
# pitch_preview = 4332 / 433.2 = 10.0
# pixels_x = 2870 / 10 = 287 (close to 280!)

print(f"\n  Trying preview-mode pitch:")
preview_res = resx_max / 10  # ~433 DPI
preview_pitch = resx_max / preview_res  # = 10
px_preview = pw['size_x'] / preview_pitch
py_preview = pw['size_y'] / preview_pitch
print(f"    preview_res = {preview_res:.1f} DPI")
print(f"    preview_pitch = {preview_pitch:.1f}")
print(f"    pixels: {px_preview:.1f} x {py_preview:.1f}")

# Check: 287 * 3465.6 = way more than 110880
# So this doesn't work either. The size_y for prescan is too large.

# Let's try: what if the scan was truncated and only scanned part of size_y?
# With width ~287 pixels, height would be 110880/287 = 386.3 (not integer)
# With width = 280: height = 396

# What pitch gives width=280 from size_x=2870?
pitch_for_280 = pw['size_x'] / 280
print(f"\n  If actual width = 280: pitch = {pitch_for_280:.2f}")
print(f"    Corresponding resolution = {resx_max / pitch_for_280:.1f} DPI")
h_at_280 = pw['size_y'] / pitch_for_280
print(f"    Height at this pitch = {h_at_280:.1f} pixels")
print(f"    Total pixels = {280 * h_at_280:.0f}")

# What if the scan only covered part of the WDB area?
# 110880 pixels / 280 width = 396 lines
# 396 * pitch = 396 * 10.25 = 4059 device units out of 34656
# That's only 11.7% of the WDB height

# --- Analyze raw data for line structure ---
print("\n" + "=" * 70)
print("RAW DATA LINE STRUCTURE ANALYSIS")
print("=" * 70)

raw = open('hardware_scan_output.raw', 'rb').read()
print(f"Raw data: {len(raw)} bytes")

# 8-bit RGB, plane-interleaved per row, stride=8640 (width=2880, no padding)
# Width confirmed by autocorrelation peak at lag=8640
width = 2880
bytes_per_line = 8640
height = len(raw) // bytes_per_line
data = np.frombuffer(raw, dtype=np.uint8)

r_plane = np.zeros(height * width, dtype=np.uint8)
g_plane = np.zeros(height * width, dtype=np.uint8)
b_plane = np.zeros(height * width, dtype=np.uint8)
for y in range(height):
    o = y * bytes_per_line
    r_plane[y*width:(y+1)*width] = data[o:o+width]
    g_plane[y*width:(y+1)*width] = data[o+width:o+2*width]
    b_plane[y*width:(y+1)*width] = data[o+2*width:o+3*width]
n = height * width

print(f"Dimensions: {width}x{height}, values per plane: {n}")

# For each candidate width, check if the image shows film-like structure
# Film negatives have: dark borders, bright center, possible sprocket holes
print("\nAnalyzing candidate dimensions for film-like structure:")

results = []
for w, h, ar in plausible:
    r_img = r_plane[:w * h].reshape(h, w)
    g_img = g_plane[:w * h].reshape(h, w)
    b_img = b_plane[:w * h].reshape(h, w)

    gray = (0.27 * r_img + 0.54 * g_img + 0.19 * b_img).astype(np.float32)

    # Find content region (values > threshold)
    threshold = 20
    content_mask = gray > threshold
    content_rows = np.where(content_mask.any(axis=1))[0]
    content_cols = np.where(content_mask.any(axis=0))[0]

    if len(content_rows) < 5 or len(content_cols) < 5:
        continue

    y1, y2 = content_rows[0], content_rows[-1]
    x1, x2 = content_cols[0], content_cols[-1]
    c_h = y2 - y1 + 1
    c_w = x2 - x1 + 1
    c_ar = c_w / c_h if c_h > 0 else 0

    # Content percentage
    content_pct = content_mask[:c_h + 2*y1, :c_w + 2*x1].sum() / (h * w) * 100 if content_mask.size > 0 else 0

    # Check if content AR is close to 35mm film (1.5)
    ar_match = abs(c_ar - 1.5) < 0.3

    # Check for banding pattern (dark-bright-dark vertically = film frame)
    row_means = gray.mean(axis=1)
    # Count transitions from dark to bright to dark
    dark = row_means < 50
    transitions = 0
    for i in range(1, len(dark)):
        if dark[i] != dark[i-1]:
            transitions += 1

    results.append({
        'w': w, 'h': h, 'ar': ar,
        'c_w': c_w, 'c_h': c_h, 'c_ar': c_ar,
        'ar_match': ar_match,
        'transitions': transitions,
        'content_rows': (y1, y2),
        'content_cols': (x1, x2),
    })

    status = "FILM-LIKE" if ar_match and 2 <= transitions <= 6 else "other"
    print(f"  {w}x{h}: content={c_w}x{c_h} (AR={c_ar:.2f}), "
          f"transitions={transitions}, [{status}]")

# Find best match
best = None
for r in results:
    if r['ar_match'] and 2 <= r['transitions'] <= 6:
        best = r
        break

if best:
    print(f"\n  Best match: {best['w']}x{best['h']}, content AR={best['c_ar']:.2f}")

# --- Render image with verified dimensions ---
print("\n" + "=" * 70)
print("RENDERING (width=2880 verified by autocorrelation)")
print("=" * 70)

# Reshape planes to image
img_r = r_plane[:height * width].reshape(height, width)
img_g = g_plane[:height * width].reshape(height, width)
img_b = b_plane[:height * width].reshape(height, width)

gray8bit = (0.27 * img_r.astype(np.float32) +
            0.54 * img_g.astype(np.float32) +
            0.19 * img_b.astype(np.float32))

# Find content region
nz_mask = gray8bit > 5
if not nz_mask.any():
    print(f"  {width}x{height}: no content found")
else:
    nz = gray8bit[nz_mask]
    p1, p99 = np.percentile(nz, 1), np.percentile(nz, 99)

    print(f"\n  {width}x{height}:")
    print(f"    Content pixels: {nz_mask.sum()} / {width * height} ({100*nz_mask.sum()/(width*height):.1f}%)")
    print(f"    Value range: [{nz.min():.0f}, {nz.max():.0f}]")
    print(f"    P1/P99: [{p1:.0f}, {p99:.0f}]")

    # Content region
    cr = np.where(nz_mask.any(axis=1))[0]
    cc = np.where(nz_mask.any(axis=0))[0]
    if len(cr) > 0 and len(cc) > 0:
        print(f"    Content: rows [{cr[0]},{cr[-1]}], cols [{cc[0]},{cc[-1]}]")
        print(f"    Content size: {cc[-1]-cc[0]+1}x{cr[-1]-cr[0]+1}")

    # Save grayscale
    gray_out = np.clip((gray8bit - p1) / (p99 - p1) * 255, 0, 255).astype(np.uint8)
    fname = f"scan_{width}x{height}_gray.png"
    Image.fromarray(gray_out).save(fname)
    print(f"    Saved: {fname}")

    # Save RGB
    rgb8 = np.zeros((height, width, 3), dtype=np.uint8)
    for ch_idx, ch_plane in enumerate([img_r, img_g, img_b]):
        nz_ch = ch_plane[nz_mask]
        p1c, p99c = np.percentile(nz_ch, 1), np.percentile(nz_ch, 99)
        rgb8[:, :, ch_idx] = np.clip(
            (ch_plane.astype(np.float32) - p1c) / (p99c - p1c) * 255, 0, 255
        ).astype(np.uint8)

    fname_rgb = f"scan_{width}x{height}_rgb.png"
    Image.fromarray(rgb8).save(fname_rgb)
    print(f"    Saved: {fname_rgb}")

print("\nDone.")
