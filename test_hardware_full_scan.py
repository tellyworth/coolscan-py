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

                # Try RGB first (3 channels)
                data_len = len(scan_data)
                for channels, mode in [(3, "RGB"), (1, "L")]:
                    if data_len % channels == 0:
                        # Estimate dimensions: LS-40 ED at 2700 DPI
                        # A typical 35mm frame is ~2592x3888 at 2700 DPI
                        total_pixels = data_len // channels
                        # Try common dimensions
                        for w, h in [(2592, 3888), (3888, 2592), (2400, 3600)]:
                            if w * h == total_pixels:
                                arr = np.frombuffer(scan_data, dtype=np.uint8)
                                arr = arr.reshape((h, w, channels))
                                img = Image.fromarray(arr, mode)
                                img.save(output_path)
                                print(f"Saved {w}x{h} {mode} image to {output_path}")
                                break
                        else:
                            continue
                        break
                    else:
                        continue
                else:
                    # Can't decode as image, save raw
                    with open(output_path.replace(".png", ".raw"), "wb") as f:
                        f.write(scan_data)
                    print(f"Saved raw data to {output_path.replace('.png', '.raw')}")

            except Exception as img_err:
                print(f"Image save failed: {img_err}")
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
