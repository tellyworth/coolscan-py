#!/usr/bin/env python3
"""Minimal hardware test: init -> prescan -> full scan -> save image.

Exercises the real USB path end-to-end with verbose logging.
Usage: python test_hardware_full_scan.py [output.png]
"""

import sys
import time

sys.path.insert(0, ".")

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, DataType, ScanParameters


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "hardware_scan_output.png"

    # 1. Discover scanner
    scanners = find_scanners()
    if not scanners:
        print("No scanners found")
        return False
    device = scanners[0]
    print(f"Found scanner: {device.vendor} {device.model} ({device.revision})")

    protocol = None
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

        # 5. Prescan (auto-exposure)
        print("\n=== PRESCAN ===")
        protocol.reserve_unit()
        prescan_ok = protocol.prescan()
        protocol.release_unit()
        print(f"Prescan: {'OK' if prescan_ok else 'FAILED'}")

        # 6. Full scan setup
        print("\n=== FULL SCAN SETUP ===")
        params = ScanParameters(resolution=2700)
        if not protocol.perform_scan_sequence(params):
            print("Scan sequence failed")
            return False
        print("Scan sequence complete, scanner ready for data read")

        # 7. Read scan data
        print("\n=== READING SCAN DATA ===")
        start = time.time()
        scan_data = bytearray()
        chunk_idx = 0

        # Read in 64KB chunks. The scanner signals end-of-data via a non-READY
        # status or a short read. We use a generous upper bound and stop early
        # if the scanner signals completion.
        max_chunks = 500  # ~32MB max
        chunk_size = 64 * 1024

        for i in range(max_chunks):
            data = protocol.read_scan_data(chunk_size, DataType.IMAGE_DATA)
            if not data:
                print(f"Empty read at chunk {i}, stopping")
                break
            scan_data.extend(data)
            chunk_idx += 1
            elapsed = time.time() - start
            mb = len(scan_data) / (1024 * 1024)
            print(f"  Chunk {i + 1}: {len(data)} bytes (total: {mb:.1f} MB, {elapsed:.1f}s)")

            # If we got less than requested, scanner may be done
            if len(data) < chunk_size:
                print(f"Short read ({len(data)} < {chunk_size}), scanner done")
                break

        elapsed = time.time() - start
        total_mb = len(scan_data) / (1024 * 1024)
        print(f"\nRead {chunk_idx} chunks, {total_mb:.1f} MB in {elapsed:.1f}s")

        # 8. Save image
        if scan_data:
            print(f"\n=== SAVING IMAGE ===")
            try:
                import numpy as np
                from PIL import Image

                data_len = len(scan_data)

                # LS-40 ED scan data format (verified by autocorrelation analysis):
                # - 8-bit RGB (NOT 16-bit), plane-interleaved per line
                # - Each line: [R_plane][G_plane][B_plane] -- no padding
                # - Stride: 8640 bytes (3 * 2880)
                # - Autocorrelation peak at lag=8640 confirms width=2880
                width = 2880
                bytes_per_line = 8640  # 3*width, no padding
                height = data_len // bytes_per_line

                print(f"  Dimensions: {width}x{height} "
                      f"(bytes_per_line={bytes_per_line})")
                print(f"  Actual bytes: {data_len} ({data_len % bytes_per_line} trailing)")

                # Parse 8-bit RGB, plane-interleaved per line
                # Layout: [R_0..R_{w-1}][G_0..G_{w-1}][B_0..B_{w-1}]
                raw_arr = np.frombuffer(scan_data, dtype=np.uint8)
                img_r = np.zeros((height, width), dtype=np.uint8)
                img_g = np.zeros((height, width), dtype=np.uint8)
                img_b = np.zeros((height, width), dtype=np.uint8)

                offset = 0
                for y in range(height):
                    line_end = offset + bytes_per_line
                    if line_end > data_len:
                        print(f"  Short line at y={y}, stopping")
                        height = y
                        break
                    # Plane-interleaved: R plane, G plane, B plane (each = width bytes)
                    img_r[y, :] = raw_arr[offset:offset + width]
                    img_g[y, :] = raw_arr[offset + width:offset + 2*width]
                    img_b[y, :] = raw_arr[offset + 2*width:offset + 3*width]
                    offset = line_end

                # Grayscale with SANE weights (0.27 R + 0.54 G + 0.19 B)
                gray8 = (0.27 * img_r.astype(np.float32) +
                         0.54 * img_g.astype(np.float32) +
                         0.19 * img_b.astype(np.float32)).astype(np.uint8)

                # Contrast stretch using percentiles (film negatives need this)
                p1, p99 = np.percentile(gray8, 0.5), np.percentile(gray8, 99.5)
                if p99 > p1:
                    gray8 = np.clip((gray8.astype(np.float32) - p1) / (p99 - p1) * 255, 0, 255).astype(np.uint8)

                img = Image.fromarray(gray8)
                img.save(output_path)
                print(f"Saved {width}x{height} grayscale image to {output_path}")

                # Also save raw data for further analysis
                raw_path = output_path.replace(".png", ".raw")
                with open(raw_path, "wb") as f:
                    f.write(scan_data)
                print(f"Saved raw data ({data_len} bytes) to {raw_path}")

            except Exception as img_err:
                print(f"Image save failed: {img_err}")
                import traceback
                traceback.print_exc()
                # Save raw data as fallback
                raw_path = output_path.replace(".png", ".raw")
                with open(raw_path, "wb") as f:
                    f.write(scan_data)
                print(f"Saved raw data to {raw_path}")

        return True

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
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


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
