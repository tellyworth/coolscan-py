"""
Command-line interface for Coolscan film scanner.

Provides scan, status, eject, and list subcommands.
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
import time
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

import click
import numpy as np
from PIL import Image

from .device import find_scanners, list_scanners, ScannerDevice
from .protocol import CoolscanProtocol, DataType, ScanParameters, ScanType
from .scanner import CoolscanScanner, LS40_CHANNEL_OFFSETS, _parse_scan_data


def _next_sequence_number(output_dir: Path, prefix: str) -> int:
    """Find the highest existing sequence number and return N+1."""
    pattern = re.compile(re.escape(prefix) + r"_(\d+)\.tiff")
    max_num = 0
    if output_dir.exists():
        for entry in output_dir.iterdir():
            m = pattern.match(entry.name)
            if m:
                max_num = max(max_num, int(m.group(1)))
    return max_num + 1


def _make_output_paths(
    output_dir: Path, prefix: str, seq: int
) -> Tuple[Path, Path]:
    """Return (tiff_path, jpeg_path) for a given sequence number."""
    return output_dir / f"{prefix}_{seq:03d}.tiff", output_dir / f"{prefix}_{seq:03d}.jpg"


def _ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return absolute path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _setup_usb_logging(protocol: CoolscanProtocol, logs_dir: Path) -> str:
    """Enable USB capture logging. Returns log filename."""
    logs_dir = _ensure_dir(logs_dir)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"scan_{timestamp}.txt"
    protocol.enable_usb_capture(str(log_file))
    return log_file.name


def _apply_auto_adjust(image_array: np.ndarray) -> np.ndarray:
    """Apply negative inversion + histogram stretch + gamma correction.

    Returns an 8-bit uint8 array.
    """
    arr = image_array.astype(np.float64)

    # Negative inversion
    arr = 255.0 - arr

    # Histogram stretch per channel
    for ch in range(arr.shape[2]):
        ch_min = arr[:, :, ch].min()
        ch_max = arr[:, :, ch].max()
        if ch_max > ch_min:
            arr[:, :, ch] = (arr[:, :, ch] - ch_min) / (ch_max - ch_min) * 255.0
        else:
            arr[:, :, ch] = 0

    # Gamma correction (2.2)
    arr = np.clip(arr, 0, 255)
    arr = 255.0 * np.power(arr / 255.0, 1.0 / 2.2)
    return arr.astype(np.uint8)


def _build_exif_data(
    scanner_info: Optional[dict],
    resolution: int,
    film_type: str,
    depth: int,
    infrared: bool,
) -> dict:
    """Build metadata dict for EXIF embedding."""
    from datetime import datetime

    info = {
        "Resolution": resolution,
        "FilmType": film_type,
        "BitDepth": depth,
        "InfraredCaptured": infrared,
        "ScanDate": datetime.now().isoformat(),
    }
    if scanner_info:
        info["ScannerModel"] = scanner_info.get("product", "Unknown")
        info["ScannerVendor"] = scanner_info.get("vendor", "Unknown")
    return info


def _write_tiff_16bit_rgb(
    rgb_array: np.ndarray,
    output_path: Path,
    ir_array: Optional[np.ndarray] = None,
    compression: str = "zstd",
    exif_data: Optional[dict] = None,
) -> None:
    """Write a 16-bit per channel RGB TIFF (with optional IR as 4th channel).

    Writes a proper multi-channel 16-bit TIFF using manual TIFF format.
    Pillow cannot handle uint16 RGB arrays directly.
    """
    height, width, channels = rgb_array.shape
    assert channels == 3

    # Ensure contiguous uint16 data
    data = np.ascontiguousarray(rgb_array, dtype=np.uint16)

    # If IR is present, include it as a 4th channel
    if ir_array is not None:
        ir_cont = np.ascontiguousarray(ir_array, dtype=np.uint16)
        samples_per_pixel = 4
        bits_per_sample = [16, 16, 16, 16]
        # Pack RGB + IR: reshape IR to match RGB shape
        ir_3d = ir_cont.reshape(height, width, 1)
        combined = np.concatenate([data, ir_3d], axis=2)
        combined = np.ascontiguousarray(combined)
        raw_bytes = combined.tobytes()
    else:
        samples_per_pixel = 3
        bits_per_sample = [16, 16, 16]
        raw_bytes = data.tobytes()

    # TIFF Header
    # Little-endian, magic 42, first IFD offset
    ifd_start = 8
    num_tags = 12
    ifd_size = 2 + num_tags * 12 + 4  # count + tags + next_ifd

    # Compute offsets for values that don't fit in 4 bytes
    bits_per_sample_offset = ifd_start + ifd_size
    x_res_offset = bits_per_sample_offset + len(bits_per_sample) * 2
    y_res_offset = x_res_offset + 8
    strip_offsets_offset = y_res_offset + 8
    strip_data_offset = strip_offsets_offset + 4

    with open(output_path, "wb") as f:
        # TIFF Header
        f.write(b"II")  # Little-endian
        f.write(struct.pack("<H", 42))  # Magic number
        f.write(struct.pack("<I", ifd_start))  # First IFD offset

        # Build tags (sorted by tag number)
        tags = bytearray()
        # 256: ImageWidth (LONG)
        tags += struct.pack("<HHII", 256, 4, 1, width)
        # 257: ImageLength (LONG)
        tags += struct.pack("<HHII", 257, 4, 1, height)
        # 258: BitsPerSample (SHORT, multiple values -> offset)
        tags += struct.pack("<HHII", 258, 3, samples_per_pixel, bits_per_sample_offset)
        # 259: Compression (SHORT, 1 = uncompressed)
        tags += struct.pack("<HHII", 259, 3, 1, 1)
        # 262: PhotometricInterpretation (SHORT, 2 = RGB)
        tags += struct.pack("<HHII", 262, 3, 1, 2)
        # 273: StripOffsets (LONG)
        tags += struct.pack("<HHII", 273, 4, 1, strip_data_offset)
        # 277: SamplesPerPixel (SHORT)
        tags += struct.pack("<HHII", 277, 3, 1, samples_per_pixel)
        # 278: RowsPerStrip (LONG)
        tags += struct.pack("<HHII", 278, 4, 1, height)
        # 279: StripByteCounts (LONG)
        tags += struct.pack("<HHII", 279, 4, 1, len(raw_bytes))
        # 282: XResolution (RATIONAL -> offset)
        tags += struct.pack("<HHII", 282, 5, 1, x_res_offset)
        # 283: YResolution (RATIONAL -> offset)
        tags += struct.pack("<HHII", 283, 5, 1, y_res_offset)
        # 296: ResolutionUnit (SHORT, 2 = inch)
        tags += struct.pack("<HHII", 296, 3, 1, 2)

        f.write(struct.pack("<H", num_tags))
        f.write(tags)
        f.write(struct.pack("<I", 0))  # Next IFD = 0 (no more IFDs)

        # Tag value data at offsets
        for bps in bits_per_sample:
            f.write(struct.pack("<H", bps))  # BitsPerSample
        f.write(struct.pack("<II", 2900, 1))  # XResolution
        f.write(struct.pack("<II", 2900, 1))  # YResolution
        f.write(struct.pack("<I", strip_data_offset))  # StripOffsets value

        # Image data
        f.write(raw_bytes)


def _save_tiff_dual_ifd(
    rgb_array: np.ndarray,
    ir_array: Optional[np.ndarray],
    output_path: Path,
    compression: str = "zstd",
    exif_data: Optional[dict] = None,
) -> None:
    """Save a TIFF with RGB in main IFD and IR in second IFD.

    Uses Pillow's append mode for the second IFD.
    """
    # Determine compression string
    if compression == "zstd":
        compress_str = "tiff_zstd"
    else:
        compress_str = "tiff_deflate"

    # Build TIFF metadata tags (only applied to first IFD)
    tiff_info: dict = {}
    if exif_data:
        # Embed metadata as TIFF tags.  Pillow's Image.Exif() is intended for
        # JPEG EXIF and crashes with our custom string keys when writing TIFF,
        # so we use standard TIFF tags instead.
        tiff_info[270] = json.dumps(exif_data, default=str)  # ImageDescription
        if exif_data.get("ScannerVendor"):
            tiff_info[271] = exif_data["ScannerVendor"]  # Make
        if exif_data.get("ScannerModel"):
            tiff_info[272] = exif_data["ScannerModel"]  # Model
        if exif_data.get("ScanDate"):
            # TIFF DateTime wants "YYYY:MM:DD HH:MM:SS"
            dt = exif_data["ScanDate"]
            if isinstance(dt, str) and "T" in dt:
                dt = dt.replace("T", " ", 1).split(".")[0].split("+")[0]
            tiff_info[306] = dt  # DateTime
        if exif_data.get("Resolution"):
            try:
                res = int(exif_data["Resolution"])
                tiff_info[282] = res  # XResolution
                tiff_info[283] = res  # YResolution
                tiff_info[296] = 2  # ResolutionUnit = inch
            except (ValueError, TypeError):
                pass

    is_16bit = rgb_array.dtype == np.uint16

    if is_16bit:
        _write_tiff_16bit_rgb(
            rgb_array, output_path, ir_array=ir_array,
            compression=compress_str, exif_data=tiff_info,
        )
    else:
        # 8-bit RGB: standard "RGB" mode
        rgb_image = Image.fromarray(np.ascontiguousarray(rgb_array), "RGB")
        rgb_image.save(
            str(output_path),
            format="TIFF",
            compression=compress_str,
            info=tiff_info,
        )

        # Append IR as second IFD
        if ir_array is not None:
            ir_mode = "I;16" if ir_array.dtype == np.uint16 else "L"
            ir_image = Image.fromarray(np.ascontiguousarray(ir_array), ir_mode)
            ir_image.save(
                str(output_path),
                format="TIFF",
                compression=compress_str,
                append=True,
            )


def _save_jpeg(
    image_array: np.ndarray,
    output_path: Path,
    exif_data: Optional[dict] = None,
    orientation: Optional[int] = None,
) -> None:
    """Save a JPEG with EXIF metadata."""
    # JPEG only supports 8-bit; down-convert uint16 (12-bit >> 4)
    if image_array.dtype != np.uint8:
        image_array = (image_array >> 4).astype(np.uint8)
    image = Image.fromarray(np.ascontiguousarray(image_array), "RGB")

    exif_bytes = None
    if exif_data:
        exif_info = Image.Exif()
        # Standard EXIF tags use integer IDs.  Put the full custom metadata
        # dict in UserComment as JSON, and map a few common fields to
        # standard tags.
        try:
            exif_info[37510] = json.dumps(exif_data, default=str)  # UserComment
        except Exception:
            pass
        if exif_data.get("ScannerVendor"):
            try:
                exif_info[271] = exif_data["ScannerVendor"]  # Make
            except Exception:
                pass
        if exif_data.get("ScannerModel"):
            try:
                exif_info[272] = exif_data["ScannerModel"]  # Model
            except Exception:
                pass
        if exif_data.get("ScanDate"):
            try:
                dt = exif_data["ScanDate"]
                if isinstance(dt, str) and "T" in dt:
                    dt = dt.replace("T", " ", 1).split(".")[0].split("+")[0]
                exif_info[306] = dt  # DateTime
            except Exception:
                pass
        if orientation:
            exif_info[274] = orientation  # Orientation tag
        exif_bytes = exif_info.tobytes()

    save_kwargs: dict = {"format": "JPEG", "quality": 95}
    if exif_bytes is not None:
        save_kwargs["exif"] = exif_bytes
    image.save(str(output_path), **save_kwargs)


def _detect_orientation(image_array: np.ndarray) -> Optional[int]:
    """Use check_orientation to detect image orientation.

    Returns EXIF orientation value (1-8) or None.
    """
    try:
        from check_orientation import check

        image = Image.fromarray(image_array, "RGB")
        result = check(image)
        if result:
            return int(result)
    except ImportError:
        pass
    except Exception:
        pass
    return None


def _get_scanner(
    scanners: List[ScannerDevice], scanner_num: Optional[int]
) -> ScannerDevice:
    """Select a scanner from the list."""
    if not scanners:
        click.echo("No Coolscan scanners found.", err=True)
        sys.exit(1)

    if scanner_num is None:
        if len(scanners) == 1:
            return scanners[0]
        click.echo("Multiple scanners found. Please specify one with --scanner:")
        list_scanners()
        sys.exit(1)

    if scanner_num < 1 or scanner_num > len(scanners):
        click.echo(f"Invalid scanner number. Available: 1-{len(scanners)}", err=True)
        sys.exit(1)
    return scanners[scanner_num - 1]


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Coolscan film scanner control."""
    pass


@cli.command("list")
def cmd_list():
    """List available Coolscan scanners."""
    list_scanners()


@cli.command()
@click.option("--scanner", "-s", type=int, default=None, help="Scanner number")
def status(scanner: Optional[int]):
    """Report scanner status."""
    scanners = find_scanners()
    device = _get_scanner(scanners, scanner)

    click.echo(f"Scanner: {device}")
    try:
        with CoolscanScanner(device) as scanner_obj:
            info = scanner_obj.get_device_info()
            click.echo(f"  Vendor: {info.get('vendor', 'Unknown')}")
            click.echo(f"  Product: {info.get('product', 'Unknown')}")
            click.echo(f"  Revision: {info.get('revision', 'Unknown')}")

            ready = scanner_obj.wait_for_ready(timeout=10)
            click.echo(f"  Ready: {'yes' if ready else 'no'}")
            click.echo(f"  Scan in progress: {'yes' if scanner_obj.scan_in_progress else 'no'}")
    except Exception as e:
        click.echo(f"  Status: error ({e})", err=True)
        sys.exit(1)


@cli.command()
@click.option("--scanner", "-s", type=int, default=None, help="Scanner number")
def eject(scanner: Optional[int]):
    """Eject film and reset scanner."""
    scanners = find_scanners()
    device = _get_scanner(scanners, scanner)

    click.echo(f"Ejecting film from {device}...")
    try:
        with CoolscanScanner(device) as scanner_obj:
            # Drain any buffered scan data before ejecting.
            # Unconsumed data causes eject_medium() to fail with
            # ILLEGAL REQUEST / COMMAND SEQUENCE ERROR.
            scanner_obj.protocol._drain_buffered_scan_data()
            if scanner_obj.protocol.eject_medium():
                click.echo("Film ejected successfully")
                if scanner_obj.protocol.reset_params():
                    click.echo("Scanner parameters reset")
            else:
                click.echo("Eject command failed", err=True)
                sys.exit(1)
    except Exception as e:
        click.echo(f"Eject failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory")
@click.option("--prefix", "-p", default="img_", help="Filename prefix (default: img_)")
@click.option("--resolution", "-r", default=2700, type=int, help="Scan resolution in DPI")
@click.option("--depth", default=8, type=click.Choice(["8", "12"]), help="Bit depth")
@click.option(
    "--film-type",
    default="negative",
    type=click.Choice(["positive", "negative", "auto"]),
    help="Film type",
)
@click.option("--infrared", "-i", is_flag=True, help="Capture IR channel for DFR")
@click.option("--batch", "-b", is_flag=True, help="Batch mode (multi-frame)")
@click.option("--frames", "-n", default=6, type=int, help="Number of frames in batch mode")
@click.option("--auto-adjust", "-a", is_flag=True, help="Apply auto-adjustment to JPEG")
@click.option("--preview", is_flag=True, help="Preview only (prescan)")
@click.option("--scanner", "-s", type=int, default=None, help="Scanner number")
@click.option("--logs-dir", type=click.Path(), default="logs", help="USB log directory")
def scan(
    output_dir: str,
    prefix: str,
    resolution: int,
    depth: int,
    film_type: str,
    infrared: bool,
    batch: bool,
    frames: int,
    auto_adjust: bool,
    preview: bool,
    scanner: Optional[int],
    logs_dir: str,
):
    """Scan film frames to TIFF + JPEG."""
    depth_int = int(depth)
    output_path = _ensure_dir(Path(output_dir))
    logs_path = _ensure_dir(Path(logs_dir))

    scanners = find_scanners()
    device = _get_scanner(scanners, scanner)

    click.echo(f"Using scanner: {device}")
    click.echo(f"Output directory: {output_path}")
    click.echo(f"Resolution: {resolution} DPI, depth: {depth_int}-bit")
    click.echo(f"Film type: {film_type}, IR: {'yes' if infrared else 'no'}")
    if batch:
        click.echo(f"Batch mode: {frames} frames")

    negative = film_type in ("negative", "auto")

    try:
        with CoolscanScanner(device) as scanner_obj:
            protocol = scanner_obj.protocol
            assert protocol is not None

            # USB logging
            log_name = _setup_usb_logging(protocol, logs_path)
            click.echo(f"USB log: {log_name}")

            # Wait for scanner ready
            click.echo("Waiting for scanner...")
            if not scanner_obj.wait_for_ready(timeout=30):
                click.echo("Scanner not ready", err=True)
                sys.exit(1)
            click.echo("Scanner ready")

            # Gather scanner info for metadata
            scanner_info = scanner_obj.get_device_info()

            if preview:
                _do_preview(
                    scanner_obj, output_path, prefix, resolution, scanner_info
                )
            elif batch:
                _do_batch_scan(
                    scanner_obj,
                    output_path,
                    prefix,
                    resolution,
                    depth_int,
                    negative,
                    infrared,
                    frames,
                    auto_adjust,
                    scanner_info,
                )
            else:
                _do_single_scan(
                    scanner_obj,
                    output_path,
                    prefix,
                    resolution,
                    depth_int,
                    negative,
                    infrared,
                    auto_adjust,
                    scanner_info,
                )

    except KeyboardInterrupt:
        click.echo("\nScan cancelled by user")
        sys.exit(130)
    except Exception as e:
        click.echo(f"\nScan failed: {e}", err=True)
        traceback.print_exc()
        sys.exit(1)


def _do_preview(
    scanner_obj: CoolscanScanner,
    output_dir: Path,
    prefix: str,
    resolution: int,
    scanner_info: dict,
) -> None:
    """Perform prescan-only mode."""
    click.echo("Running prescan...")
    if not scanner_obj.prescan():
        click.echo("Prescan failed", err=True)
        sys.exit(1)

    protocol = scanner_obj.protocol
    assert protocol is not None
    if protocol._last_prescan_image_data:
        seq = _next_sequence_number(output_dir, prefix)
        tiff_path, jpeg_path = _make_output_paths(output_dir, prefix, seq)

        prescan_data = protocol._last_prescan_image_data
        prescan_width = 96
        prescan_pixels = len(prescan_data) // (2 * 3)
        prescan_height = prescan_pixels // prescan_width

        arr, _ = _parse_scan_data(
            bytearray(prescan_data),
            width=prescan_width,
            height=prescan_height,
            num_channels=3,
            depth=12,
            format="plane",
            channel_offsets=(0, 0, 1),
        )

        exif_data = _build_exif_data(scanner_info, resolution, "preview", 12, False)

        _save_tiff_dual_ifd(arr, None, tiff_path, exif_data=exif_data)
        _save_jpeg(arr, jpeg_path, exif_data=exif_data)

        click.echo(f"Prescan saved: {tiff_path}, {jpeg_path}")
    else:
        click.echo("Prescan completed but no image data available")


def _do_single_scan(
    scanner_obj: CoolscanScanner,
    output_dir: Path,
    prefix: str,
    resolution: int,
    depth: int,
    negative: bool,
    infrared: bool,
    auto_adjust: bool,
    scanner_info: dict,
) -> None:
    """Perform a single-frame scan."""
    protocol = scanner_obj.protocol
    assert protocol is not None

    # Focus setup
    click.echo("Focus setup...")
    focus = protocol.focus_setup()
    if focus is not None:
        click.echo(f"Focus position: {focus} (0x{focus:04X})")
    else:
        click.echo("Focus setup failed, using scanner default")

    # Prescan
    click.echo("Running prescan...")
    if not protocol.prescan():
        click.echo("Prescan failed", err=True)
        sys.exit(1)

    # Full scan setup
    click.echo("Starting full scan...")
    params = ScanParameters(
        resolution=resolution,
        preview=False,
        negative=negative,
        infrared=infrared,
        depth=depth,
        x_min=0,
        y_min=0,
        x_max=0,
        y_max=0,
    )

    if not protocol.full_scan_frame(params):
        click.echo("Scan setup failed", err=True)
        sys.exit(1)

    # Read scan data
    click.echo("Reading scan data...")
    width = 2880
    height = 3888
    num_channels = 4 if infrared else 3
    bytes_per_channel = 2 if depth > 8 else 1
    total_bytes = width * height * num_channels * bytes_per_channel
    chunk_size = 0x3F480

    scan_data = bytearray()
    bytes_read = 0

    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    with tqdm(total=total_bytes, unit="B", unit_scale=True, desc="Reading") as bar:
        while bytes_read < total_bytes:
            remaining = total_bytes - bytes_read
            request_length = min(chunk_size, remaining)
            chunk = protocol.read_scan_data(request_length, DataType.IMAGE_DATA)
            if not chunk:
                click.echo(f"Empty read at {bytes_read}/{total_bytes}, stopping", err=True)
                break
            scan_data.extend(chunk)
            bytes_read += len(chunk)
            if tqdm and bar:
                bar.update(len(chunk))

    if not scan_data:
        click.echo("No scan data received", err=True)
        sys.exit(1)

    # Parse scan data
    click.echo("Processing image...")
    channel_offsets = LS40_CHANNEL_OFFSETS
    img_arr, trailing = _parse_scan_data(
        scan_data, width, height, num_channels, depth, "plane", channel_offsets
    )

    # Split RGB and IR
    if infrared and num_channels == 4:
        rgb_arr = np.ascontiguousarray(img_arr[:, :, 0:3])
        ir_arr = np.ascontiguousarray(img_arr[:, :, 3])
    else:
        rgb_arr = np.ascontiguousarray(img_arr[:, :, 0:3] if img_arr.shape[2] >= 3 else img_arr)
        ir_arr = None

    # Save outputs
    seq = _next_sequence_number(output_dir, prefix)
    tiff_path, jpeg_path = _make_output_paths(output_dir, prefix, seq)

    film_type_str = "negative" if negative else "positive"
    exif_data = _build_exif_data(scanner_info, resolution, film_type_str, depth, infrared)

    # TIFF (raw archival)
    click.echo(f"Saving TIFF: {tiff_path}")
    _save_tiff_dual_ifd(rgb_arr, ir_arr, tiff_path, exif_data=exif_data)

    # JPEG (viewing copy)
    if auto_adjust:
        jpeg_arr = _apply_auto_adjust(rgb_arr)
    else:
        jpeg_arr = rgb_arr if rgb_arr.dtype == np.uint8 else (rgb_arr >> 4).astype(np.uint8)
    jpeg_arr = np.ascontiguousarray(jpeg_arr)

    # Orientation detection
    orientation = _detect_orientation(jpeg_arr)
    if orientation:
        exif_data["Orientation"] = orientation

    click.echo(f"Saving JPEG: {jpeg_path}")
    _save_jpeg(jpeg_arr, jpeg_path, exif_data=exif_data, orientation=orientation)

    click.echo(f"Scan complete: seq {seq}")


def _do_batch_scan(
    scanner_obj: CoolscanScanner,
    output_dir: Path,
    prefix: str,
    resolution: int,
    depth: int,
    negative: bool,
    infrared: bool,
    frame_count: int,
    auto_adjust: bool,
    scanner_info: dict,
) -> None:
    """Perform batch scan with auto-advance."""
    protocol = scanner_obj.protocol
    assert protocol is not None

    click.echo(f"Starting batch scan ({frame_count} frames)...")

    seq = _next_sequence_number(output_dir, prefix)
    film_type_str = "negative" if negative else "positive"

    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    frame_iter = protocol.batch_scan_to_frames(
        frame_count=frame_count,
        first_y=30,
        frame_height=4332,
        step=4330,
        focus_x=0x059B,
        negative=negative,
        depth=depth,
        save_previews=True,
    )

    with tqdm(total=frame_count, desc="Frames") as bar:
        for frame_idx, full_res_data, previews in frame_iter:
            click.echo(f"\nFrame {frame_idx + 1}/{frame_count}: processing...")

            # Parse full-res data
            batch_width = 2880
            bytes_per_channel = 2 if depth > 8 else 1
            batch_height = len(full_res_data) // (batch_width * 3 * bytes_per_channel)
            if batch_height < 100:
                click.echo(f"  ⚠️  Suspicious data size: {len(full_res_data)} bytes (height={batch_height})", err=True)
            expected_bytes = batch_height * batch_width * 3 * bytes_per_channel
            if expected_bytes != len(full_res_data):
                click.echo(f"  ⚠️  Data size mismatch: expected {expected_bytes}, got {len(full_res_data)}", err=True)
            channel_offsets = LS40_CHANNEL_OFFSETS

            img_arr, _ = _parse_scan_data(
                bytearray(full_res_data),
                width=batch_width,
                height=batch_height,
                num_channels=3,
                depth=depth,
                format="plane",
                channel_offsets=channel_offsets,
            )

            rgb_arr = np.ascontiguousarray(img_arr[:, :, 0:3])

            # Scale 12-bit raw values to full 16-bit range for TIFF storage.
            # Without this, 12-bit data (0-4095) in a uint16 container appears
            # nearly black in viewers that expect the full 0-65535 range.
            if depth > 8 and rgb_arr.dtype == np.uint16:
                rgb_arr = (rgb_arr.astype(np.uint32) * 65535 // 4095).astype(np.uint16)

            ir_arr = None

            # IR from Stage A preview (4 channels: R, G, B, IR)
            if infrared and "stage_a" in previews and previews["stage_a"]:
                stage_a = previews["stage_a"]
                stage_w = 288
                stage_h = 433
                stage_arr, _ = _parse_scan_data(
                    bytearray(stage_a),
                    width=stage_w,
                    height=stage_h,
                    num_channels=4,
                    depth=12,
                    format="plane",
                    channel_offsets=(0, 1, 2, 0),
                )
                ir_arr = np.ascontiguousarray(stage_arr[:, :, 3])

            current_seq = seq + frame_idx
            tiff_path, jpeg_path = _make_output_paths(output_dir, prefix, current_seq)

            exif_data = _build_exif_data(
                scanner_info, resolution, film_type_str, depth, infrared
            )
            exif_data["FrameIndex"] = frame_idx + 1

            _save_tiff_dual_ifd(rgb_arr, ir_arr, tiff_path, exif_data=exif_data)

            if auto_adjust:
                jpeg_arr = _apply_auto_adjust(rgb_arr)
            else:
                jpeg_arr = rgb_arr if rgb_arr.dtype == np.uint8 else (rgb_arr >> 4).astype(np.uint8)
            jpeg_arr = np.ascontiguousarray(jpeg_arr)

            orientation = _detect_orientation(jpeg_arr)
            if orientation:
                exif_data["Orientation"] = orientation

            _save_jpeg(jpeg_arr, jpeg_path, exif_data=exif_data, orientation=orientation)

            click.echo(f"  Saved: {tiff_path}, {jpeg_path}")
            if tqdm and bar:
                bar.update(1)

    click.echo(f"Batch scan complete: {frame_count} frames, seq {seq}-{seq + frame_count - 1}")


if __name__ == "__main__":
    cli()
