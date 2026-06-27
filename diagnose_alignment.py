#!/usr/bin/env python3
"""
diagnose_alignment.py — Diagnostic-only script for channel alignment.

Loads hardware_scan_output.raw, decodes as plane-interleaved (R|G|B per line),
applies horizontal shifts to G and B channels, and searches for the best
alignment using a gradient-based sharpness metric.

DOES NOT modify any production files. Safe to delete afterwards.
"""

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

# ── Constants ───────────────────────────────────────────────────────────────
RAW_PATH = Path("/Users/alex/dev/coolscan-py/hardware_scan_output.raw")
OUT_DIR = Path("/Users/alex/dev/coolscan-py")

WIDTH = 2880
HEIGHT = 3888
CHANNELS = 3
BYTES_PER_LINE = WIDTH * CHANNELS  # 8640
EXPECTED_SIZE = WIDTH * HEIGHT * CHANNELS  # 33,592,320

# Grid search ranges (R is always 0 = reference)
G_RANGE = range(6, 15)   # 6..14 inclusive
B_RANGE = range(16, 25)  # 16..24 inclusive


def load_and_split(raw_path: Path) -> tuple:
    """Load raw file and split into (R, G, B) each shaped (HEIGHT, WIDTH)."""
    data = np.fromfile(raw_path, dtype=np.uint8)
    if len(data) != EXPECTED_SIZE:
        raise ValueError(
            f"File size mismatch: expected {EXPECTED_SIZE}, got {len(data)}"
        )

    # Reshape to (HEIGHT, BYTES_PER_LINE) then split channels
    lines = data.reshape(HEIGHT, BYTES_PER_LINE)
    R = lines[:, :WIDTH].copy()
    G = lines[:, WIDTH:WIDTH * 2].copy()
    B = lines[:, WIDTH * 2:].copy()
    return R, G, B


def shift_channel(channel: np.ndarray, offset: int) -> np.ndarray:
    """
    Shift a single channel horizontally by `offset` pixels.
    Positive offset = shift right (data moves right, left edge filled with 0).
    Negative offset = shift left (data moves left, right edge filled with 0).
    """
    h, w = channel.shape
    result = np.zeros_like(channel)
    if offset == 0:
        result[:] = channel
    elif offset > 0:
        # Shift right: new[:, offset:] = old[:, :-offset]
        result[:, offset:] = channel[:, :w - offset]
    else:
        # Shift left: new[:, :offset] = old[:, -offset:]
        abs_off = -offset
        result[:, :w - abs_off] = channel[:, abs_off:]
    return result


def build_rgb(R: np.ndarray, G: np.ndarray, B: np.ndarray,
              g_offset: int, b_offset: int) -> np.ndarray:
    """Build (H, W, 3) RGB array with given horizontal offsets."""
    g_shifted = shift_channel(G, g_offset)
    b_shifted = shift_channel(B, b_offset)
    return np.stack([R, g_shifted, b_shifted], axis=-1)


def luminance(rgb: np.ndarray) -> np.ndarray:
    """Convert RGB to luminance (Rec. 709 weights)."""
    return (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2])


def sharpness_metric(lum: np.ndarray) -> float:
    """
    Sum of absolute horizontal gradient on luminance.
    Higher = sharper (more edge content).
    We use a downsampled version for speed.
    """
    # Downsample 4x for speed (still plenty of edge data)
    ds = 4
    small = lum[::ds, ::ds]
    # Horizontal gradient
    dx = np.abs(np.diff(small, axis=1))
    return float(np.sum(dx))


def channel_correlations(rgb: np.ndarray) -> dict:
    """Pearson correlations between channels (downsampled for speed)."""
    ds = 8
    r = rgb[::ds, ::ds, 0].ravel().astype(np.float64)
    g = rgb[::ds, ::ds, 1].ravel().astype(np.float64)
    b = rgb[::ds, ::ds, 2].ravel().astype(np.float64)

    def pearson(a, b):
        a_mean = np.mean(a)
        b_mean = np.mean(b)
        da, db = a - a_mean, b - b_mean
        num = np.sum(da * db)
        den = np.sqrt(np.sum(da * da) * np.sum(db * db))
        return num / den if den > 0 else 0.0

    return {
        "R-G": pearson(r, g),
        "R-B": pearson(r, b),
        "G-B": pearson(g, b),
    }


def save_png(rgb: np.ndarray, path: Path):
    """Save RGB array as PNG."""
    img = Image.fromarray(rgb, mode="RGB")
    img.save(path)
    print(f"  Saved: {path.name} ({rgb.shape[1]}x{rgb.shape[0]})")


def main():
    print("=" * 70)
    print("CHANNEL ALIGNMENT DIAGNOSTIC")
    print("=" * 70)

    # ── Load ────────────────────────────────────────────────────────────────
    print(f"\nLoading {RAW_PATH.name}...")
    t0 = time.time()
    R, G, B = load_and_split(RAW_PATH)
    print(f"  Shape: R={R.shape}, G={G.shape}, B={B.shape}")
    print(f"  Loaded in {time.time() - t0:.1f}s")

    # ── Unaligned baseline ──────────────────────────────────────────────────
    print("\n--- Unaligned (R=0, G=0, B=0) ---")
    rgb_unaligned = build_rgb(R, G, B, g_offset=0, b_offset=0)
    lum_unaligned = luminance(rgb_unaligned)
    sharp_unaligned = sharpness_metric(lum_unaligned)
    corr_unaligned = channel_correlations(rgb_unaligned)
    print(f"  Sharpness: {sharp_unaligned:>12.0f}")
    print(f"  Correlations: R-G={corr_unaligned['R-G']:.4f}, "
          f"R-B={corr_unaligned['R-B']:.4f}, G-B={corr_unaligned['G-B']:.4f}")
    save_png(rgb_unaligned, OUT_DIR / "diagnostic_unaligned.png")

    # ── Starting-point offsets ──────────────────────────────────────────────
    print("\n--- Starting point (R=0, G=+10, B=+20) ---")
    rgb_start = build_rgb(R, G, B, g_offset=10, b_offset=20)
    lum_start = luminance(rgb_start)
    sharp_start = sharpness_metric(lum_start)
    corr_start = channel_correlations(rgb_start)
    print(f"  Sharpness: {sharp_start:>12.0f}")
    print(f"  Correlations: R-G={corr_start['R-G']:.4f}, "
          f"R-B={corr_start['R-B']:.4f}, G-B={corr_start['G-B']:.4f}")
    save_png(rgb_start, OUT_DIR / "diagnostic_start_g10_b20.png")

    # ── Grid search ─────────────────────────────────────────────────────────
    print(f"\n--- Grid search: G in [{min(G_RANGE)}..{max(G_RANGE)}], "
          f"B in [{min(B_RANGE)}..{max(B_RANGE)}] ---")
    print(f"  Searching {len(G_RANGE) * len(B_RANGE)} combinations...\n")

    best_score = -1
    best_g, best_b = 0, 0
    t_search = time.time()

    for g_off in G_RANGE:
        for b_off in B_RANGE:
            rgb = build_rgb(R, G, B, g_offset=g_off, b_offset=b_off)
            lum = luminance(rgb)
            score = sharpness_metric(lum)
            if score > best_score:
                best_score = score
                best_g, best_b = g_off, b_off

    elapsed = time.time() - t_search
    print(f"  Search completed in {elapsed:.1f}s")

    # ── Best result ─────────────────────────────────────────────────────────
    print(f"\n  Best offsets: R=0, G=+{best_g}, B=+{best_b}")
    print(f"  Best sharpness: {best_score:>12.0f}")

    rgb_best = build_rgb(R, G, B, g_offset=best_g, b_offset=best_b)
    lum_best = luminance(rgb_best)
    corr_best = channel_correlations(rgb_best)
    print(f"  Correlations: R-G={corr_best['R-G']:.4f}, "
          f"R-B={corr_best['R-B']:.4f}, G-B={corr_best['G-B']:.4f}")
    save_png(rgb_best, OUT_DIR / "diagnostic_aligned_best.png")

    # ── Summary table ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"  {'Configuration':<30} {'Sharpness':>12} {'R-G':>8} {'R-B':>8} {'G-B':>8}")
    print(f"  {'-'*30} {'-'*12} {'-'*8} {'-'*8} {'-'*8}")
    print(f"  {'Unaligned (0, 0, 0)':<30} {sharp_unaligned:>12.0f} "
          f"{corr_unaligned['R-G']:>8.4f} {corr_unaligned['R-B']:>8.4f} "
          f"{corr_unaligned['G-B']:>8.4f}")
    print(f"  {'Start (0, +10, +20)':<30} {sharp_start:>12.0f} "
          f"{corr_start['R-G']:>8.4f} {corr_start['R-B']:>8.4f} "
          f"{corr_start['G-B']:>8.4f}")
    best_label = f"Best (0, +{best_g}, +{best_b})"
    print(f"  {best_label:<30} {best_score:>12.0f} "
          f"{corr_best['R-G']:>8.4f} {corr_best['R-B']:>8.4f} "
          f"{corr_best['G-B']:>8.4f}")

    improvement = (best_score - sharp_unaligned) / sharp_unaligned * 100
    print(f"\n  Sharpness improvement (best vs unaligned): {improvement:+.1f}%")

    # ── Top 5 candidates ────────────────────────────────────────────────────
    print("\n  Top 5 candidates:")
    scores = []
    for g_off in G_RANGE:
        for b_off in B_RANGE:
            rgb = build_rgb(R, G, B, g_offset=g_off, b_offset=b_off)
            lum = luminance(rgb)
            score = sharpness_metric(lum)
            scores.append((score, g_off, b_off))

    scores.sort(reverse=True)
    for i, (score, g_off, b_off) in enumerate(scores[:5]):
        marker = " << BEST" if g_off == best_g and b_off == best_b else ""
        print(f"    {i+1}. G=+{g_off:2d}, B=+{b_off:2d}  sharpness={score:>12.0f}{marker}")

    # Save top-3 as PNGs for visual comparison
    for i, (score, g_off, b_off) in enumerate(scores[:3]):
        if i == 0:
            continue  # Already saved as "best"
        tag = f"g{g_off:+d}_b{b_off:+d}"
        rgb_cand = build_rgb(R, G, B, g_offset=g_off, b_offset=b_off)
        save_png(rgb_cand, OUT_DIR / f"diagnostic_candidate_{tag}.png")

    print(f"\nTotal runtime: {time.time() - t0:.1f}s")
    print("\nDiagnostic PNGs saved:")
    print(f"  {OUT_DIR / 'diagnostic_unaligned.png'}")
    print(f"  {OUT_DIR / 'diagnostic_aligned_best.png'}")
    print(f"  {OUT_DIR / 'diagnostic_start_g10_b20.png'}")
    for i, (score, g_off, b_off) in enumerate(scores[:3]):
        if i == 0:
            continue
        tag = f"g{g_off:+d}_b{b_off:+d}"
        print(f"  {OUT_DIR / f'diagnostic_candidate_{tag}.png'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
