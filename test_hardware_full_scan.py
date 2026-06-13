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
                import struct
                import numpy as np
                from PIL import Image

                data_len = len(scan_data)
                pixels_per_channel = data_len // 6  # RGB, 2 bytes/pixel

                # Compute dimensions from WDB parameters
                # Normal WDB: size_x=2870, size_y=4332, resolution=2900 DPI
                # pitch = resx_max / resolution = 4332 / 2900
                # width = size_x / pitch, height = size_y / pitch
                resx_max = 4332
                scan_resolution = 2900
                size_x = 2870
                size_y = 4332
                pitch = resx_max / scan_resolution
                width = int(size_x / pitch)
                height = int(size_y / pitch)
                expected_pixels = width * height

                print(f"  Computed dimensions: {width}x{height} "
                      f"(pitch={pitch:.4f}, expected={expected_pixels} pixels/ch)")
                print(f"  Actual pixels/ch: {pixels_per_channel}")

                # If dimensions don't match, try to derive from data
                if pixels_per_channel != expected_pixels:
                    print(f"  Dimension mismatch! Trying factorization...")
                    # Find best factor pair close to 35mm film AR (1.5)
                    best_w, best_h = None, None
                    best_diff = float('inf')
                    for w in range(100, min(3000, int(pixels_per_channel**0.5) + 100)):
                        if pixels_per_channel % w == 0:
                            h = pixels_per_channel // w
                            ar = max(w, h) / min(w, h)
                            diff = abs(ar - 1.5)
                            if diff < best_diff and 1.2 <= ar <= 2.0:
                                best_diff = diff
                                best_w, best_h = w, h
                    if best_w and best_h:
                        width, height = best_w, best_h
                        print(f"  Using factorized dimensions: {width}x{height}")

                # Parse BE uint16, 12-bit (shift 4), RGB plane-interleaved per line
                bytes_per_line = 6 * width
                img_r = np.zeros((height, width), dtype=np.uint16)
                img_g = np.zeros((height, width), dtype=np.uint16)
                img_b = np.zeros((height, width), dtype=np.uint16)

                offset = 0
                for y in range(height):
                    line_data = scan_data[offset:offset + bytes_per_line]
                    if len(line_data) < bytes_per_line:
                        print(f"  Short line at y={y}, stopping")
                        height = y
                        break
                    offset += bytes_per_line
                    for x in range(width):
                        img_r[y, x] = struct.unpack_from('>H', line_data, 2 * x)[0] >> 4
                        img_g[y, x] = struct.unpack_from('>H', line_data, 2*width + 2*x)[0] >> 4
                        img_b[y, x] = struct.unpack_from('>H', line_data, 4*width + 2*x)[0] >> 4

                # Grayscale with SANE weights
                gray12 = (0.27 * img_r.astype(np.float32) +
                          0.54 * img_g.astype(np.float32) +
                          0.19 * img_b.astype(np.float32))

                # Contrast stretch using percentiles (film negatives need this)
                nz = gray12[gray12 > 5]
                if len(nz) > 10:
                    p1, p99 = np.percentile(nz, 1), np.percentile(nz, 99)
                    gray8 = np.clip((gray12 - p1) / (p99 - p1) * 255, 0, 255).astype(np.uint8)
                else:
                    gray8 = (gray12 / 4095 * 255).astype(np.uint8)

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
