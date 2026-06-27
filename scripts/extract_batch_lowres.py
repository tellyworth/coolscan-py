#!/usr/bin/env python3
"""Extract low-resolution (96 DPI prescan and 290 DPI Stage A/B) scan images
from tests/fixtures/golden_batch.txt to PNGs in tests/fixtures/extracted/.

The scanner outputs plane-interleaved data per line:
  [ch0[width]][ch1[width]][ch2[width]]...

Width depends on DPI (logical width sent by scanner, not fixed sensor width):
  2900 DPI: width=2880, 8-bit,  3ch -> bpl=8640
  290  DPI: width=288,  12-bit, 4ch -> bpl=2304 (Stage A, IR+RGB)
  290  DPI: width=288,  12-bit, 3ch -> bpl=1728 (Stage B, RGB)
   96  DPI: width=96,   12-bit, 3ch -> bpl=576  (prescan, RGB)

Widths are derived from READ(10) length factorization, verified against
SANE's logical_width = (xmax-xmin+1) / (resx_max/res).

USB transfer boundaries (65508 bytes) do not align with line boundaries,
so all chunks for a phase are concatenated before decoding.  Trailing bytes
that do not form a complete line are discarded.

12-bit samples are big-endian uint16; convert to 8-bit by (raw16 >> 8).
"""

import struct
from pathlib import Path

import numpy as np
from PIL import Image

FIXTURE = Path("tests/fixtures/golden_batch.txt")
BIN_DIR = Path("tests/fixtures")
OUT_DIR = Path("tests/fixtures/extracted")

# Width lookup derived from READ(10) factorization:
#   96 DPI:  130752 / (3ch * 2B) = 21792 samples; 21792/227lines = 96px
#   290 DPI: 258048 / (4ch * 2B) = 32256 samples; 32256/112lines = 288px
#   2900 DPI: 259200 / (3ch * 1B) = 259200 samples; 259200/30lines = 2880px
WIDTH_TABLE = {96: 96, 290: 288, 2900: 2880}


def parse_wdb58(data: bytes) -> dict:
    """Parse a 58-byte WDB (or 60-byte with 2-byte length prefix)."""
    if len(data) == 60:
        data = data[2:]
    if len(data) != 58:
        raise ValueError(f"WDB len {len(data)}")
    return {
        "window_id": data[8],
        "x_res": struct.unpack(">H", data[10:12])[0],
        "y_res": struct.unpack(">H", data[12:14])[0],
        "bpp": data[34],
    }


def read_data(field: str) -> bytes:
    """Read hex data or @ref from a fixture field."""
    field = field.strip()
    if field.startswith("@"):
        with open(BIN_DIR / field[1:], "rb") as f:
            return f.read()
    return bytes.fromhex(field)


def get_cmd(hex_str: str):
    """Extract command code from a hex data string."""
    s = hex_str.strip()
    if len(s) < 20 or s.startswith("@"):
        return None
    return int(s[:2], 16)


def decode_samples(data: bytes, bpp: int) -> np.ndarray:
    """Convert raw bytes to 8-bit sample values."""
    if bpp == 0x0C:
        raw16 = np.frombuffer(data, dtype=np.uint16)
        return (raw16 >> 8).astype(np.uint8)
    return np.frombuffer(data, dtype=np.uint8)


def decode_image(data: bytes, width: int, height: int,
                  num_channels: int, bpp: int):
    """Decode plane-interleaved scan data into PIL Image(s).

    Data layout: [ch0[width]][ch1[width]][ch2[width]]... per line.
    Returns Image or (rgb_image, ir_image) for 4-channel data.
    """
    bytes_per_sample = 2 if bpp == 0x0C else 1
    bytes_per_line = num_channels * width * bytes_per_sample
    total_needed = bytes_per_line * height

    samples = decode_samples(data[:total_needed], bpp)

    if num_channels == 1:
        arr = samples[:width * height].reshape(height, width)
        return Image.fromarray(arr, mode="L")

    arr = np.zeros((height, width, num_channels), dtype=np.uint8)
    idx = 0
    for y in range(height):
        for ch in range(num_channels):
            end = idx + width
            arr[y, :, ch] = samples[idx:end]
            idx = end

    if num_channels == 3:
        return Image.fromarray(arr, mode="RGB")
    elif num_channels == 4:
        # Channel order: IR, R, G, B (window 9, 1, 2, 3)
        rgb = Image.fromarray(arr[:, :, 1:4], mode="RGB")
        ir = Image.fromarray(arr[:, :, 0], mode="L")
        return rgb, ir
    else:
        raise ValueError(f"Unsupported channel count: {num_channels}")


def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = FIXTURE.read_text().splitlines()

    # ---- FSM states ----
    IDLE = 0
    W_D0, W_PH, W_WDB, W_ST = 1, 2, 3, 4
    C_D0, C_PH, C_WDB, C_ST = 5, 6, 7, 8
    R_D0, R_PH, R_DATA, R_ST = 9, 10, 11, 12
    S_D0, S_PH, S_PL, S_ST = 13, 14, 15, 16

    # ---- Parse fixture ----
    state = IDLE
    wdb_ctx = None
    wdb_write_count = 0    # WRITE(WDB) count since last image READ phase
    read_len = 0           # READ(10) requested length
    is_image = False
    image_reads = []       # (line_no, data, wdb_ctx, num_channels)

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 3)
        if len(parts) < 4:
            continue
        ep, length, df = parts[1], int(parts[2]), parts[3]

        if state == IDLE:
            if ep == "0x01":
                cmd = get_cmd(df)
                if cmd == 0x24:
                    wdb_write_count += 1
                    state = W_D0
                elif cmd == 0x25:
                    state = C_D0
                elif cmd == 0x28:
                    b = bytes.fromhex(df.strip())
                    is_image = b[2] == 0x00
                    if is_image:
                        read_len = (b[6] << 16) | (b[7] << 8) | b[8]
                    state = R_D0
                elif cmd == 0x2A:
                    state = S_D0
            continue

        if state in (W_D0, C_D0, R_D0, S_D0):
            if ep == "0x01" and length == 1:
                state = {W_D0: W_PH, C_D0: C_PH, R_D0: R_PH, S_D0: S_PH}[state]
            continue

        if state in (W_PH, C_PH, R_PH, S_PH):
            if ep == "0x82" and length == 1:
                state = {W_PH: W_WDB, C_PH: C_WDB, R_PH: R_DATA, S_PH: S_PL}[state]
            continue

        if state == W_WDB:
            if ep == "0x01" and length == 58:
                try:
                    wdb_ctx = parse_wdb58(read_data(df))
                except Exception:
                    pass
            state = W_ST
            continue

        if state == C_WDB:
            if ep == "0x82" and length in (58, 60):
                try:
                    wdb_ctx = parse_wdb58(read_data(df))
                except Exception:
                    pass
            state = C_ST
            continue

        if state == R_DATA:
            if ep == "0x82" and is_image and wdb_ctx:
                chunk = read_data(df)
                nch = wdb_write_count  # channels = # of WDBs written this phase
                image_reads.append((i, chunk, wdb_ctx.copy(), nch, read_len))
                if wdb_write_count > 0:
                    wdb_write_count = 0  # reset after first image read of phase
            state = R_ST
            continue

        if state == S_PL:
            state = S_ST
            continue

        if state in (W_ST, C_ST, R_ST, S_ST):
            if ep == "0x82":
                state = IDLE
            continue

    # ---- Group by gaps (>15 lines = new phase) ----
    groups = []
    current = []
    for entry in image_reads:
        if current and entry[0] - current[-1][0] > 15:
            groups.append(current)
            current = []
        current.append(entry)
    if current:
        groups.append(current)

    # ---- Filter to 96 and 290 DPI only ----
    lowres = [g for g in groups if g[0][2]["x_res"] in (96, 290)]

    # ---- Separate prescan and 290 DPI ----
    prescan_groups = [g for g in lowres if g[0][2]["x_res"] == 96]
    dpi290_groups = [g for g in lowres if g[0][2]["x_res"] == 290]

    # ---- Decode and save ----
    saved = 0
    summary = []

    def save_group(group, label, res):
        nonlocal saved
        total_bytes = sum(len(e[1]) for e in group)
        nch = group[0][3]  # channel count from WDB write count
        bpp = group[0][2]["bpp"]
        width = WIDTH_TABLE.get(res, 2880)
        bytes_per_sample = 2 if bpp == 0x0C else 1
        bytes_per_line = nch * width * bytes_per_sample
        height = total_bytes // bytes_per_line
        trail = total_bytes % bytes_per_line

        data = b"".join(e[1] for e in group)

        try:
            result = decode_image(data, width, height, nch, bpp)
            if nch == 4:
                rgb_img, ir_img = result
                fname_rgb = f"{label}.png"
                fname_ir = f"{label}_ir.png"
                rgb_img.save(OUT_DIR / fname_rgb)
                ir_img.save(OUT_DIR / fname_ir)
                summary.append((fname_rgb, width, height, 3, res, total_bytes, trail))
                summary.append((fname_ir, width, height, 1, res, 0, 0))
                saved += 2
            else:
                fname = f"{label}.png"
                result.save(OUT_DIR / fname)
                summary.append((fname, width, height, nch, res, total_bytes, trail))
                saved += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            summary.append((f"{label}.png", "ERROR", 0, 0, 0, res, 0, 0))

    # Save prescan
    for gi, g in enumerate(prescan_groups):
        save_group(g, f"segment{gi}_prescan_{g[0][2]['x_res']}dpi", g[0][2]["x_res"])

    # Save 290 DPI: pair as (Stage A with IR, Stage B RGB) per segment
    seg_idx = 0
    i = 0
    while i < len(dpi290_groups):
        g = dpi290_groups[i]
        nch = g[0][3]
        if nch == 4:
            save_group(g, f"segment{seg_idx}_stageA_{g[0][2]['x_res']}dpi", g[0][2]["x_res"])
            i += 1
        else:
            save_group(g, f"segment{seg_idx}_stageB_{g[0][2]['x_res']}dpi", g[0][2]["x_res"])
            i += 1
            seg_idx += 1

    # Print summary
    print(f"\nSaved {saved} images to {OUT_DIR}/")
    print(f"\n{'File':<50} {'W':>6} {'H':>6} {'Ch':>4} {'DPI':>6} {'Bytes':>10} {'Trail':>8}")
    print("-" * 94)
    for entry in summary:
        fname, w, h, ch, dpi, nbytes, trail = entry
        wh = f"{w}x{h}" if isinstance(w, int) else str(w)
        print(f"{fname:<50} {wh:>6} {ch:>4} {dpi:>6} {nbytes:>10} {trail:>8}")


if __name__ == "__main__":
    run()
