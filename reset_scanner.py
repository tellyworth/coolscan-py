#!/usr/bin/env python3
"""
Scanner Reset Script

Attempts to reset/recover a Nikon Coolscan scanner that's in a non-responsive state.
Uses very short timeouts and simple commands to avoid hanging.

Usage: python reset_scanner.py
"""

import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:
    print("Error: pyusb not installed. Run: pip install pyusb")
    sys.exit(1)


# Nikon Coolscan USB IDs
SCANNER_IDS = [
    (0x04b0, 0x4000, "LS-40 ED"),
    (0x04b0, 0x4001, "LS-50 ED"),
    (0x04b0, 0x4002, "LS-5000 ED"),
]


def find_scanner():
    """Find a connected Coolscan scanner."""
    for vendor_id, product_id, name in SCANNER_IDS:
        device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if device:
            return device, name
    return None, None


def reset_scanner():
    """Attempt to reset the scanner to a responsive state."""
    print("🔍 Looking for Coolscan scanner...")

    device, name = find_scanner()
    if not device:
        print("❌ No scanner found")
        return False

    print(f"✅ Found: {name}")

    # Set very short timeout
    device.default_timeout = 500  # 500ms

    # Try to get configuration
    try:
        cfg = device.get_active_configuration()
        print(f"  Configuration: {cfg.bConfigurationValue}")
    except:
        try:
            device.set_configuration(1)
            print("  Set configuration to 1")
        except Exception as e:
            print(f"  ⚠️  Could not set configuration: {e}")

    # Find endpoints
    try:
        cfg = device.get_active_configuration()
        intf = cfg.interfaces()[0]

        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
        )

        if not ep_out or not ep_in:
            # Fallback to common endpoints
            ep_out_addr = 0x01
            ep_in_addr = 0x82
            print(f"  Using default endpoints: OUT=0x{ep_out_addr:02x}, IN=0x{ep_in_addr:02x}")
        else:
            ep_out_addr = ep_out.bEndpointAddress
            ep_in_addr = ep_in.bEndpointAddress
            print(f"  Endpoints: OUT=0x{ep_out_addr:02x}, IN=0x{ep_in_addr:02x}")
    except Exception as e:
        print(f"  ⚠️  Could not find endpoints: {e}")
        ep_out_addr = 0x01
        ep_in_addr = 0x82
        print(f"  Using default endpoints: OUT=0x{ep_out_addr:02x}, IN=0x{ep_in_addr:02x}")

    # Try to claim interface
    try:
        usb.util.claim_interface(device, 0)
        print("  Interface claimed")
    except Exception as e:
        print(f"  ⚠️  Could not claim interface: {e}")

    print("\n🔄 Attempting reset sequence...")

    # Step 1: Drain any pending data
    print("  Step 1: Draining pending data...")
    for i in range(10):
        try:
            data = device.read(ep_in_addr, 512, timeout=100)
            print(f"    Drained {len(data)} bytes")
        except:
            break

    time.sleep(0.3)

    # Step 2: Send RELEASE_UNIT command
    print("  Step 2: Sending RELEASE_UNIT (0x17)...")
    try:
        release_cmd = bytes([0x17, 0x00, 0x00, 0x00, 0x00, 0x00])
        device.write(ep_out_addr, release_cmd, timeout=200)
        print("    Sent")
    except Exception as e:
        print(f"    ⚠️  Failed: {e}")

    time.sleep(0.3)

    # Step 3: Drain again
    print("  Step 3: Draining response...")
    for i in range(10):
        try:
            data = device.read(ep_in_addr, 512, timeout=100)
            print(f"    Drained {len(data)} bytes: {data.tobytes().hex()[:32]}...")
        except:
            break

    time.sleep(0.3)

    # Step 4: Try TEST_UNIT_READY
    print("  Step 4: Sending TEST_UNIT_READY (0x00)...")
    try:
        tur_cmd = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        device.write(ep_out_addr, tur_cmd, timeout=200)
        print("    Sent")

        # Send phase check
        device.write(ep_out_addr, bytes([0xd0]), timeout=200)
        print("    Phase check sent")

        # Try to read response
        try:
            response = device.read(ep_in_addr, 8, timeout=500)
            print(f"    Response: {response.tobytes().hex()}")
            if len(response) >= 1 and response[0] in [0x01, 0x03]:
                print("    ✅ Scanner responded!")
                # Try to read status
                try:
                    status = device.read(ep_in_addr, 8, timeout=500)
                    print(f"    Status: {status.tobytes().hex()}")
                except:
                    pass
        except Exception as e:
            print(f"    ⚠️  No response: {e}")
    except Exception as e:
        print(f"    ⚠️  Failed: {e}")

    # Release interface
    try:
        usb.util.release_interface(device, 0)
        print("\n  Interface released")
    except:
        pass

    print("\n✅ Reset sequence completed")
    print("   If scanner is still unresponsive, power cycle it.")
    return True


if __name__ == "__main__":
    try:
        reset_scanner()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
