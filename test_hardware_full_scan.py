#!/usr/bin/env python3
"""Minimal hardware test: init -> prescan -> full scan -> save image.

Exercises the real USB path end-to-end with verbose logging.
Usage: python test_hardware_full_scan.py [output.png] [--batch --frames N ...]
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from PIL import Image
import numpy as np

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, DataType, ScanParameters
from coolscan.scanner import LS40_CHANNEL_OFFSETS, _parse_scan_data


def parse_args():
    parser = argparse.ArgumentParser(description="Hardware scan test for LS-40 ED")
    parser.add_argument("output", nargs="?", default="hardware_scan_output.png",
                        help="Output file path (default: hardware_scan_output.png)")
    parser.add_argument("--batch", action="store_true",
                        help="Enable batch mode (multi-frame scanning)")
    parser.add_argument("--frames", type=int, default=6,
                        help="Number of frames in batch mode (default: 6)")
    parser.add_argument("--first-y", type=int, default=30,
                        help="Y start of first frame (default: 30)")
    parser.add_argument("--frame-height", type=int, default=4332,
                        help="Height of each frame (default: 4332)")
    parser.add_argument("--step", type=int, default=4330,
                        help="Y step between frames (default: 4330)")
    parser.add_argument("--negative", action="store_true", default=True,
                        help="Color negative film (default)")
    parser.add_argument("--positive", action="store_true",
                        help="Positive/transparency film")
    parser.add_argument("--depth", type=int, choices=[8, 12], default=8,
                        help="Bit depth (default: 8)")
    parser.add_argument("--no-previews", action="store_true",
                        help="Don't save Stage A/B preview images")
    return parser.parse_args()


def save_frame_image(scan_data, width, height, num_channels, depth,
                     channel_offsets, output_path):
    """Parse and save a scan frame as PNG."""
    img_aligned, trailing = _parse_scan_data(
        bytearray(scan_data), width, height, num_channels, depth,
        "plane", channel_offsets,
    )
    image = Image.fromarray(img_aligned, "RGB")
    image.save(output_path)
    print(f"  Saved {width}x{height} image to {output_path}")

    # Save raw data
    raw_path = output_path.rsplit(".", 1)[0] + ".raw"
    with open(raw_path, "wb") as f:
        f.write(scan_data)
    print(f"  Saved raw data ({len(scan_data)} bytes) to {raw_path}")


def save_preview_image(data, width, height, num_channels, depth, output_path):
    """Parse and save a preview image (Stage A or B)."""
    if not data:
        return False
    arr, _ = _parse_scan_data(
        bytearray(data), width, height, num_channels, depth,
        "plane", (0, 0, 0) if num_channels == 3 else (0, 1, 2, 0),
    )
    if num_channels == 4:
        # Stage A: 4 channels (R, G, B, IR) - save RGB only
        image = Image.fromarray(arr[:, :, 0:3], "RGB")
    else:
        image = Image.fromarray(arr, "RGB")
    image.save(output_path)
    print(f"  Saved preview {width}x{height} to {output_path}")
    return True


def main():
    args = parse_args()
    output_path = args.output
    base = output_path.rsplit(".", 1)[0]

    # Determine film type
    negative = args.negative and not args.positive

    # 1. Discover scanner
    scanners = find_scanners()
    if not scanners:
        print("No scanners found")
        return False
    device = scanners[0]
    print(f"Found scanner: {device.vendor} {device.model} ({device.revision})")

    protocol = None
    scan_saved = False
    try:
        # 2. Create protocol with verbose logging + USB capture
        protocol = CoolscanProtocol(device, verbose=True)
        protocol.enable_usb_capture(f"{base}_capture.txt")

        # 3. Initialize
        print("\n=== INITIALIZING ===")
        if not protocol.initialize_scanner():
            print("Initialization had warnings, continuing...")

        # 4. Scanner ready check
        print("\n=== SCANNER READY ===")
        if not protocol.scanner_ready(timeout=15):
            print("Scanner not ready after 15s")
            return False
        print("Scanner is ready")

        if args.batch:
            # =============================================
            # BATCH MODE
            # =============================================
            print(f"\n=== BATCH SCAN ({args.frames} frames) ===")

            focus_x = 0x059B  # Default from batch capture
            frame_count = 0

            for frame_idx, full_res_data, previews in protocol.batch_scan_to_frames(
                frame_count=args.frames,
                first_y=args.first_y,
                frame_height=args.frame_height,
                step=args.step,
                focus_x=focus_x,
                negative=negative,
                depth=args.depth,
                save_previews=not args.no_previews,
            ):
                frame_count += 1
                print(f"\n=== FRAME {frame_idx + 1}: SAVING IMAGES ===")

                # Full-res image (2870 x 4332 for batch)
                full_res_path = f"{base}_frame_{frame_idx}.png"
                save_frame_image(
                    full_res_data,
                    width=2870,
                    height=args.frame_height,
                    num_channels=3,
                    depth=args.depth,
                    channel_offsets=LS40_CHANNEL_OFFSETS,
                    output_path=full_res_path,
                )
                scan_saved = True

                # Stage A preview (290 DPI, 4 channels: R, G, B, IR)
                # NOTE: The byte counts for the batch 290 DPI intermediate
                # stages do not match the single-frame 290 DPI preview
                # (Stage A: ~262 KB returned vs ~497 KB expected at 8-bit,
                # Stage B: ~197 KB vs ~373 KB expected). The 287x433x12-bit
                # decode below is speculative and may produce garbage; the raw
                # bytes are also saved for offline analysis.
                if "stage_a" in previews and previews["stage_a"]:
                    stage_a_path = f"{base}_frame_{frame_idx}_stage_a.png"
                    save_preview_image(
                        previews["stage_a"],
                        width=287,
                        height=433,
                        num_channels=4,
                        depth=12,
                        output_path=stage_a_path,
                    )

                # Stage B preview (290 DPI, 3 channels: R, G, B)
                if "stage_b" in previews and previews["stage_b"]:
                    stage_b_path = f"{base}_frame_{frame_idx}_stage_b.png"
                    save_preview_image(
                        previews["stage_b"],
                        width=287,
                        height=433,
                        num_channels=3,
                        depth=12,
                        output_path=stage_b_path,
                    )

            print(f"\nBatch scan completed: {frame_count} frames")
        else:
            # =============================================
            # SINGLE FRAME MODE (existing behavior)
            # =============================================
            # 4b. Focus setup
            print("\n=== FOCUS SETUP ===")
            focus = protocol.focus_setup()
            if focus is not None:
                print(f"Focus position: {focus} (0x{focus:04X})")
            else:
                print("Focus setup failed, using scanner default")

            # 5. Prescan (auto-exposure)
            print("\n=== PRESCAN ===")
            prescan_ok = protocol.prescan()
            print(f"Prescan: {'OK' if prescan_ok else 'FAILED'}")
            if not prescan_ok:
                return False

            if protocol._last_prescan_image_data:
                prescan_arr, _ = _parse_scan_data(
                    bytearray(protocol._last_prescan_image_data),
                    width=96,
                    height=474,
                    num_channels=3,
                    depth=12,
                    format="plane",
                    channel_offsets=(0, 0, 1),
                )
                Image.fromarray(prescan_arr, "RGB").save(f"{base}_prescan_96dpi.png")
                print(f"  Saved prescan image to {base}_prescan_96dpi.png")

            # 6. Full scan setup
            print("\n=== FULL SCAN SETUP ===")
            params = ScanParameters(resolution=2700)
            if not protocol.full_scan_frame(params):
                print("Scan sequence failed")
                return False
            print("Scan sequence complete, scanner ready for data read")

            if protocol._last_ir_preview_data:
                ir_arr, _ = _parse_scan_data(
                    bytearray(protocol._last_ir_preview_data),
                    width=288,
                    height=433,
                    num_channels=4,
                    depth=12,
                    format="plane",
                    channel_offsets=(0, 1, 2, 0),
                )
                Image.fromarray(ir_arr[:, :, 0:3], "RGB").save(f"{base}_ir_preview_290dpi.png")
                Image.fromarray(ir_arr[:, :, 3], "L").save(f"{base}_ir_preview_290dpi_ir.png")
                print(f"  Saved IR preview RGB to {base}_ir_preview_290dpi.png")
                print(f"  Saved IR preview IR  to {base}_ir_preview_290dpi_ir.png")

            # 7. Read scan data
            print("\n=== READING SCAN DATA ===")
            start = time.time()
            scan_data = bytearray()
            chunk_idx = 0

            width = 2880
            height = 3888
            num_channels = 3
            bytes_per_channel = 1
            expected_bytes = width * height * num_channels * bytes_per_channel
            chunk_size = 0x3F480  # 259200 bytes

            bytes_read = 0
            while bytes_read < expected_bytes:
                remaining = expected_bytes - bytes_read
                request_length = min(chunk_size, remaining)
                data = protocol.read_scan_data(request_length, DataType.IMAGE_DATA)
                if not data:
                    print(f"Empty read at chunk {chunk_idx}, stopping")
                    break
                scan_data.extend(data)
                bytes_read += len(data)
                chunk_idx += 1
                elapsed = time.time() - start
                mb = bytes_read / (1024 * 1024)
                print(f"  Chunk {chunk_idx}: {len(data)} bytes (total: {mb:.1f} MB, {elapsed:.1f}s)")

            elapsed = time.time() - start
            total_mb = len(scan_data) / (1024 * 1024)
            print(f"\nRead {chunk_idx} chunks, {total_mb:.1f} MB in {elapsed:.1f}s")

            # 8. Save image
            if scan_data:
                print(f"\n=== SAVING IMAGE ===")
                try:
                    data_len = len(scan_data)
                    width = 2880
                    height = 3888
                    num_channels = 3
                    depth = args.depth

                    img_aligned, trailing = _parse_scan_data(
                        scan_data, width, height, num_channels, depth, "plane",
                        LS40_CHANNEL_OFFSETS,
                    )
                    print(
                        f"  Dimensions: {width}x{height}, "
                        f"bytes={data_len}, trailing={trailing}, "
                        f"offsets={LS40_CHANNEL_OFFSETS}"
                    )

                    image = Image.fromarray(img_aligned, "RGB")
                    image.save(output_path)
                    print(f"Saved {width}x{height} aligned image to {output_path}")

                    # Save unaligned copy
                    img_unaligned, _ = _parse_scan_data(
                        scan_data, width, height, num_channels, depth, "plane",
                        (0, 0, 0),
                    )
                    Image.fromarray(img_unaligned, "RGB").save(f"{base}_unaligned.png")
                    print(f"  Unaligned copy saved: {base}_unaligned.png")

                    # Save raw data
                    raw_path = output_path.rsplit(".", 1)[0] + ".raw"
                    with open(raw_path, "wb") as f:
                        f.write(scan_data)
                    print(f"Saved raw data ({data_len} bytes) to {raw_path}")

                    scan_saved = True

                except Exception as img_err:
                    print(f"Image save failed: {img_err}")
                    import traceback
                    traceback.print_exc()
                    raw_path = output_path.rsplit(".", 1)[0] + ".raw"
                    with open(raw_path, "wb") as f:
                        f.write(scan_data)
                    print(f"Saved raw data to {raw_path}")

            # Brightness analysis
            if scan_saved:
                print("\n=== BRIGHTNESS ANALYSIS ===")
                try:
                    prescan_arr = np.array(Image.open(f"{base}_prescan_96dpi.png"))
                    preview_arr = np.array(Image.open(f"{base}_ir_preview_290dpi.png"))
                    final_arr = np.array(Image.open(output_path))

                    prescan_mean = prescan_arr.mean()
                    preview_mean = preview_arr.mean()
                    final_mean = final_arr.mean()

                    print(f"  96 DPI prescan mean:   {prescan_mean:.2f}/255")
                    print(f"  290 DPI preview mean:  {preview_mean:.2f}/255")
                    print(f"  2900 DPI final mean:   {final_mean:.2f}/255")

                    if prescan_mean > 0:
                        print(f"  Preview vs prescan:    {(preview_mean / prescan_mean - 1) * 100:+.1f}%")
                    if preview_mean > 0:
                        print(f"  Final vs preview:      {(final_mean / preview_mean - 1) * 100:+.1f}%")
                    if prescan_mean > 0:
                        print(f"  Final vs prescan:      {(final_mean / prescan_mean - 1) * 100:+.1f}%")
                except Exception as analysis_err:
                    print(f"  Brightness analysis failed: {analysis_err}")

        # Teardown scanner
        print("\n=== SCAN TEARDOWN ===")
        try:
            protocol.scan_teardown()
            print("Teardown complete")
        except Exception as teardown_err:
            print(f"Teardown encountered an error: {teardown_err}")
            print("   Scanner may need power cycling if it remains unresponsive.")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

        if protocol:
            print("\n=== ATTEMPTING TEARDOWN AFTER ERROR ===")
            try:
                protocol.scan_teardown()
                print("Teardown complete")
            except Exception as teardown_err:
                print(f"Teardown also failed: {teardown_err}")
                print("   Scanner may need power cycling if it remains unresponsive.")

        return False

    finally:
        if protocol:
            try:
                protocol.disable_usb_capture()
            except Exception:
                pass
            try:
                protocol.release_unit()
            except Exception:
                pass
            protocol.close()
            print(f"\nUSB capture saved to {base}_capture.txt")

    if scan_saved:
        print(f"\nScan completed successfully — image saved to {output_path}")
    else:
        print("\nScan did not produce an image")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
