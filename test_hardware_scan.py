#!/usr/bin/env python3
"""Hardware test: full scan sequence with verbose USB logging.

Tests perform_scan_sequence() against real hardware:
  init -> scanner_ready -> reserve_unit -> object_position ->
  set_window -> 3x identity LUT upload -> start_scan ->
  poll_until_ready (PROCESSING -> READY)

All USB I/O logged to test_hardware_scan_capture.txt and dumped to stderr.
"""

import sys
sys.path.insert(0, '.')

from coolscan.device import find_scanners
from coolscan.protocol import CoolscanProtocol, ScanParameters


def main():
    scanners = find_scanners()
    if not scanners:
        print("No scanners found")
        return False

    scanner = scanners[0]
    print(f"Scanner: {scanner}")

    capture_file = "test_hardware_scan_capture.txt"
    try:
        protocol = CoolscanProtocol(scanner, verbose=True)
        protocol.enable_usb_capture(capture_file)

        if not protocol.initialize_scanner():
            print("Initialization had warnings, continuing...")

        params = ScanParameters()
        success = protocol.perform_scan_sequence(params)
        print(f"\nperform_scan_sequence: {'SUCCESS' if success else 'FAILED'}")
        return success

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        protocol.disable_usb_capture()
        protocol.close()
        print(f"USB capture saved to {capture_file}")


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
