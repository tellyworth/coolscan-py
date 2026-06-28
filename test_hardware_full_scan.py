#!/usr/bin/env python3
"""Minimal hardware test: init -> prescan -> full scan -> save image.

Exercises the real USB path end-to-end with verbose logging.
Usage: python test_hardware_full_scan.py [output.png]
"""

import sys
import time

sys.path.insert(0, ".")

from PIL import Image
import numpy as np

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, DataType, ScanParameters
from coolscan.scanner import LS40_CHANNEL_OFFSETS, _parse_scan_data


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "hardware_scan_output.png"
    base = output_path.rsplit(".", 1)[0]

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
        protocol.enable_usb_capture("test_hardware_scan_capture.txt")

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

        # 4b. Focus setup (golden fixture lines 172-198)
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
            # Prescan data is 12-bit RGB plane-interleaved.  Scale the full-res
            # LS-40 ED channel offsets (0, 10, 20) by the 96/2900 DPI ratio.
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
            # 290 DPI IR preview is 12-bit plane-interleaved R, G, B, IR.
            # Scale the full-res LS-40 ED RGB offsets (0, 10, 20) by 290/2900.
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

        # Read exactly the expected frame size.  The golden fixture shows the
        # host reading a precise amount of image data and then going straight
        # to TUR/eject; reading trailing overscan in 64 KB chunks triggers a
        # scanner hang on the LS-40 ED.  Use a large line-group-sized request
        # (0x3f480 = 259200 bytes) like the capture, and make the final read
        # exactly the remaining bytes so it returns a full transfer, not a
        # short read.
        width = 2880
        height = 3888
        num_channels = 3
        bytes_per_channel = 1
        expected_bytes = width * height * num_channels * bytes_per_channel
        chunk_size = 0x3F480  # 259200 bytes, matches golden fixture reads

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

        # 8. Save image using decode-time channel alignment
        if scan_data:
            print(f"\n=== SAVING IMAGE ===")
            try:
                data_len = len(scan_data)
                width = 2880
                height = 3888
                num_channels = 3
                depth = 8

                # Decode as plane-interleaved with LS-40 ED channel offsets.
                # The workaround shifts G +10 px and B +20 px during decode
                # to compensate for trilinear-CCD misalignment.
                img_aligned, trailing = _parse_scan_data(
                    scan_data, width, height, num_channels, depth, "plane",
                    LS40_CHANNEL_OFFSETS,
                )
                print(
                    f"  Dimensions: {width}x{height}, "
                    f"bytes={data_len}, trailing={trailing}, "
                    f"offsets={LS40_CHANNEL_OFFSETS}"
                )

                # Save aligned image (with workaround)
                image = Image.fromarray(img_aligned, "RGB")
                image.save(output_path)
                print(f"Saved {width}x{height} aligned image to {output_path}")

                # Save unaligned copy (zero offsets) for comparison
                img_unaligned, _ = _parse_scan_data(
                    scan_data, width, height, num_channels, depth, "plane",
                    (0, 0, 0),
                )
                Image.fromarray(img_unaligned, "RGB").save(f"{base}_unaligned.png")
                print(f"  Unaligned copy saved: {base}_unaligned.png")

                # Save raw data for further analysis
                raw_path = output_path.rsplit(".", 1)[0] + ".raw"
                with open(raw_path, "wb") as f:
                    f.write(scan_data)
                print(f"Saved raw data ({data_len} bytes) to {raw_path}")

                scan_saved = True

            except Exception as img_err:
                print(f"Image save failed: {img_err}")
                import traceback
                traceback.print_exc()
                # Save raw data as fallback
                raw_path = output_path.rsplit(".", 1)[0] + ".raw"
                with open(raw_path, "wb") as f:
                    f.write(scan_data)
                print(f"Saved raw data to {raw_path}")

        # 8b. Brightness analysis of saved images
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
                print(f"  ⚠️  Brightness analysis failed: {analysis_err}")

        # Teardown scanner (golden fixture lines 1413-1478)
        print("\n=== SCAN TEARDOWN ===")
        try:
            protocol.scan_teardown()
            print("Teardown complete")
        except Exception as teardown_err:
            print(f"⚠️  Teardown encountered an error: {teardown_err}")
            print("   Scanner may need power cycling if it remains unresponsive.")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

        # Attempt teardown even after an error
        if protocol:
            print("\n=== ATTEMPTING TEARDOWN AFTER ERROR ===")
            try:
                protocol.scan_teardown()
                print("Teardown complete")
            except Exception as teardown_err:
                print(f"⚠️  Teardown also failed: {teardown_err}")
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
            print("\nUSB capture saved to test_hardware_scan_capture.txt")

    if scan_saved:
        print(f"\n✅ Scan completed successfully — image saved to {output_path}")
    else:
        print("\n⚠️  Scan did not produce an image")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
