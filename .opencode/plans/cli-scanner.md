# CLI Scanner Plan — `coolscan` Command

## Overview

Replace the current test-oriented `cli.py` with a proper user-facing CLI tool for film scanning. The command will be `coolscan` (entry point) with subcommands for scanning, status, and eject.

## Subcommands

### `coolscan scan` — Perform a scan

```
coolscan scan --output-dir ./scans/ [options]
```

| Option | Default | Description |
|---|---|---|
| `--output-dir`, `-o` | *(required)* | Output directory for scan files |
| `--prefix`, `-p` | `img_` | Filename prefix (e.g. `img_001.tiff`) |
| `--resolution`, `-r` | `2700` | Scan resolution in DPI |
| `--depth` | `8` | Bit depth: `8` or `12` |
| `--film-type` | `negative` | Film type: `positive`, `negative`, `auto` |
| `--infrared`, `-i` | off | Capture IR channel (for DFR; stored in TIFF) |
| `--batch`, `-b` | off | Batch mode: scan multiple frames with auto-advance |
| `--frames`, `-n` | `6` | Number of frames in batch mode |
| `--auto-adjust`, `-a` | off | Apply negative inversion + histogram stretch + gamma to JPEG |
| `--preview` | off | Preview mode: prescan only, no full scan |
| `--scanner`, `-s` | auto | Scanner number (from `coolscan list`) |

### `coolscan status` — Report scanner state

```
coolscan status [--scanner N]
```

Reports: availability, connection state, film loaded, ready state.

### `coolscan eject` — Reset and eject film

```
coolscan eject [--scanner N]
```

Performs reset/eject sequence to release film.

### `coolscan list` — List scanners

Already exists. Keep as-is.

## Output Files

Per scan (single or each frame in batch), produce:

### TIFF (archival)
- **Main IFD**: Raw RGB data, no adjustments applied
- **Second IFD**: IR channel (when `--infrared` is set), with private tags identifying it as the IR layer
- **Compression**: ZSTD (via `libtiff` if available); Deflate/ZIP fallback
- **EXIF**: Resolution, film type, scan date, scanner model, depth, IR/DFR status, orientation

### JPEG (viewing)
- 8-bit RGB, derived from the TIFF data
- When `--auto-adjust` is set: negative inversion, histogram stretch, gamma 2.2
- EXIF: Same metadata as TIFF, plus orientation tag
- Auto-rotate detection via `check_orientation` → set EXIF Orientation tag (don't rotate pixel bytes)

### Filename scheme
```
./scans/img_001.tiff    # archival TIFF
./scans/img_001.jpg     # viewing JPEG
```
Sequence numbers start from N+1 where N is the highest existing `img_*.tiff` in the output directory, so multiple invocations continue numbering.

## USB Logging

Every scan invocation captures a USB log file, using the same `protocol.enable_usb_capture()` mechanism as `test_hardware_full_scan.py`:

- **Location**: `logs/` directory (relative to working dir, or configurable)
- **Filename**: `scan_YYYYMMDD_HHMMSS.txt` (timestamp-based)
- **Format**: Same tab-separated text format as existing capture logs

## Progress Output

Use `tqdm` for progress bars during:
- Data read phase (bytes transferred, time elapsed)
- Batch mode (frame X of N)

Phase announcements (plain `click.echo`):
- Connecting to scanner
- Initializing
- Scanner ready
- Prescan (if applicable)
- Scanning frame N of M (batch)
- Reading scan data (tqdm bar)
- Saving TIFF / JPEG
- Scan complete

## Batch Mode

- Scanner supports 6 frames at a time with auto-advance
- Uses existing `protocol.batch_scan_to_frames()` generator
- On first failure: abort batch, report error
- Each frame gets its own sequence number in the output directory

## Preview Mode

`--preview` flag triggers prescan-only mode:
- Connect → initialize → prescan → save prescan image → disconnect
- Useful for quick film inspection without full scan time

## Implementation Plan

### Phase 1: Core scan command
1. Rewrite `cli.py` with Click subcommands (`scan`, `status`, `eject`, `list`)
2. Scanner discovery, selection, connection lifecycle
3. Single-frame scan with TIFF + JPEG output
4. USB logging to `logs/` directory
5. Sequence number auto-increment

### Phase 2: Output processing
1. TIFF writing with ZSTD/Deflate compression (Pillow `imageio` or `libtiff`)
2. Dual-IFD TIFF for IR channel
3. JPEG with `--auto-adjust` pipeline
4. EXIF metadata injection
5. `check_orientation` integration

### Phase 3: Batch and polish
1. Batch mode with tqdm progress
2. `--preview` mode
3. `--status` and `--eject` subcommands
4. Error handling and clean disconnect on failure

## Dependencies (new)
- `tqdm` — progress bars
- `check_orientation` — auto-rotate detection
- Pillow already handles TIFF with multiple IFDs and EXIF
- ZSTD TIFF compression: Pillow supports `TIFF_ZSTD` if built with libtiff ≥ 4.5; fallback to `TIFF_DEFLETION`

## Open Questions
- Auto-crop: deferred, needs testing with different film border types
- DFR post-processing: out of scope for now (IR stored raw in TIFF)
