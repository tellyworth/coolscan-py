#!/usr/bin/env python3
"""Check if scan data is blank and analyze data content."""

import numpy as np

raw = open('hardware_scan_output.raw', 'rb').read()
data = np.frombuffer(raw, dtype=np.uint8)

# 8-bit RGB, plane-interleaved per row, no padding
# Width=2880 confirmed by autocorrelation peak at lag=8640
width = 2880
bytes_per_line = 8640  # 3 * width
height = len(data) // bytes_per_line

r_plane = np.concatenate([data[y*bytes_per_line:(y+1)*bytes_per_line] for y in range(height)])[:width * height]
g_plane = np.concatenate([data[y*bytes_per_line+width:(y+1)*bytes_per_line+width] for y in range(height)])[:width * height]
b_plane = np.concatenate([data[y*bytes_per_line+2*width:(y+1)*bytes_per_line+2*width] for y in range(height)])[:width * height]
n = width * height

print("=== DATA CONTENT ANALYSIS ===")
print(f"Total values per plane: {n}")
print(f"\nR channel: min={r_plane.min()}, max={r_plane.max()}, mean={r_plane.mean():.1f}, std={r_plane.std():.1f}")
print(f"G channel: min={g_plane.min()}, max={g_plane.max()}, mean={g_plane.mean():.1f}, std={g_plane.std():.1f}")
print(f"B channel: min={b_plane.min()}, max={b_plane.max()}, mean={b_plane.mean():.1f}, std={b_plane.std():.1f}")

# Check distribution
print(f"\nR channel: { (r_plane == 0).sum() } zeros ({100*(r_plane==0).mean():.1f}%)")
print(f"G channel: { (g_plane == 0).sum() } zeros ({100*(g_plane==0).mean():.1f}%)")
print(f"B channel: { (b_plane == 0).sum() } zeros ({100*(b_plane==0).mean():.1f}%)")

# Check per-chunk content (64KB chunks from USB transfer)
chunk_bytes = 65536
chunk_values = chunk_bytes  # 8-bit: one value per byte
print(f"\n=== PER-CHUNK ANALYSIS ({chunk_values} values/chunk) ===")
for i in range(min(12, len(data) // chunk_values)):
    chunk = data[i*chunk_values:(i+1)*chunk_values]
    print(f"  Chunk {i}: bytes[{i*chunk_values}:{(i+1)*chunk_values}], "
          f"range=[{chunk.min()},{chunk.max()}], "
          f"mean={chunk.mean():.1f}, zeros={ (chunk==0).sum() }, ff={ (chunk==0xFF).sum() }")

# Check if there's ANY meaningful signal (std > noise floor)
gray = (0.27 * r_plane + 0.54 * g_plane + 0.19 * b_plane).astype(np.float32)
print(f"\nGrayscale: min={gray.min():.0f}, max={gray.max():.0f}, mean={gray.mean():.1f}, std={gray.std():.1f}")

# Signal-to-noise: if std is very low relative to mean, data is uniform (blank)
snr = gray.std() / max(gray.mean(), 1) * 100
print(f"Signal variation (std/mean * 100): {snr:.1f}%")
if snr < 5:
    print("  -> DATA APPEARS BLANK (very low variation)")
elif snr < 20:
    print("  -> DATA HAS LOW VARIATION (possibly blank or uniform exposure)")
else:
    print("  -> DATA HAS MEANINGFUL VARIATION")

# Check first/last portions
print(f"\nFirst 1000 values (R): min={r_plane[:1000].min()}, max={r_plane[:1000].max()}, mean={r_plane[:1000].mean():.1f}")
print(f"Last 1000 values (R):  min={r_plane[-1000:].min()}, max={r_plane[-1000:].max()}, mean={r_plane[-1000:].mean():.1f}")
print(f"Middle 1000 values(R): min={r_plane[n//2:n//2+1000].min()}, max={r_plane[n//2:n//2+1000].max()}, mean={r_plane[n//2:n//2+1000].mean():.1f}")
