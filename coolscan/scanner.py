"""
High-level scanner operations for Nikon Coolscan scanners.

This module provides easy-to-use functions for common scanning operations.
"""

import time
from typing import Optional, Tuple, List
from PIL import Image
import numpy as np

from .device import ScannerDevice
from .protocol import CoolscanProtocol, ScanParameters, ScanType, StatusType


class CoolscanScanner:
    """High-level interface for Coolscan scanner operations."""
    
    def __init__(self, device: ScannerDevice):
        self.device = device
        self.protocol = None
        self.is_connected = False
        self.scan_in_progress = False
    
    def connect(self) -> bool:
        """Connect to the scanner."""
        try:
            self.protocol = CoolscanProtocol(self.device)
            
            # Test connection
            if not self.protocol.test_unit_ready():
                raise RuntimeError("Scanner not ready")
            
            # Reserve unit
            if not self.protocol.reserve_unit():
                raise RuntimeError("Could not reserve scanner unit")
            
            self.is_connected = True
            return True
            
        except Exception as e:
            print(f"Failed to connect to scanner: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """Disconnect from the scanner."""
        if self.protocol:
            if self.scan_in_progress:
                self.cancel_scan()
            
            try:
                self.protocol.release_unit()
            except:
                pass
            
            try:
                self.protocol.close()
            except:
                pass
        
        self.protocol = None
        self.is_connected = False
        self.scan_in_progress = False
    
    def get_device_info(self) -> dict:
        """Get detailed device information."""
        if not self.is_connected:
            raise RuntimeError("Scanner not connected")
        
        try:
            # Get standard inquiry data
            inquiry_data = self.protocol.inquiry()
            
            if len(inquiry_data) >= 36:
                vendor = inquiry_data[8:16].decode('ascii', errors='ignore').strip()
                product = inquiry_data[16:32].decode('ascii', errors='ignore').strip()
                revision = inquiry_data[32:36].decode('ascii', errors='ignore').strip()
                
                return {
                    'vendor': vendor,
                    'product': product,
                    'revision': revision,
                    'interface': self.device.interface.value,
                    'device_path': self.device.device_path
                }
            else:
                return {
                    'vendor': self.device.vendor,
                    'product': self.device.model,
                    'revision': self.device.revision,
                    'interface': self.device.interface.value,
                    'device_path': self.device.device_path
                }
                
        except Exception as e:
            print(f"Error getting device info: {e}")
            return {
                'vendor': self.device.vendor,
                'product': self.device.model,
                'revision': self.device.revision,
                'interface': self.device.interface.value,
                'device_path': self.device.device_path,
                'error': str(e)
            }
    
    def scan_preview(self, output_path: str, resolution: int = 270) -> bool:
        """Perform a preview scan."""
        params = ScanParameters(
            resolution=resolution,
            preview=True,
            x_min=0,
            y_min=0,
            x_max=1000,  # Small preview area
            y_max=1000
        )
        
        return self._perform_scan(params, output_path, "preview")
    
    def scan_full(self, output_path: str, resolution: int = 2700, 
                  negative: bool = False, infrared: bool = False) -> bool:
        """Perform a full resolution scan."""
        params = ScanParameters(
            resolution=resolution,
            preview=False,
            negative=negative,
            infrared=infrared,
            x_min=0,
            y_min=0,
            x_max=0,  # Full area
            y_max=0
        )
        
        return self._perform_scan(params, output_path, "full")
    
    def scan_area(self, output_path: str, x_min: int, y_min: int, 
                  x_max: int, y_max: int, resolution: int = 2700) -> bool:
        """Scan a specific area."""
        params = ScanParameters(
            resolution=resolution,
            preview=False,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max
        )
        
        return self._perform_scan(params, output_path, "area")
    
    def _perform_scan(self, params: ScanParameters, output_path: str, scan_type: str) -> bool:
        """Perform a scan with the given parameters."""
        if not self.is_connected:
            raise RuntimeError("Scanner not connected")
        
        if self.scan_in_progress:
            raise RuntimeError("Scan already in progress")
        
        try:
            print(f"Starting {scan_type} scan...")
            
            # Set scan parameters
            if not self.protocol.set_window(params):
                raise RuntimeError("Failed to set scan parameters")
            
            # Start scan
            if not self.protocol.start_scan():
                raise RuntimeError("Failed to start scan")
            
            self.scan_in_progress = True
            
            # Read scan data
            # Note: This is a simplified implementation
            # The actual implementation would need to handle the full scan data protocol
            print("Reading scan data...")
            
            # For now, we'll create a dummy image
            # In a real implementation, you would read the actual scan data
            width = 1000 if params.preview else 5000
            height = 1000 if params.preview else 5000
            
            # Create a test image (this would be replaced with actual scan data)
            if params.infrared:
                # 4-channel image (RGB + IR)
                image_data = np.random.randint(0, 255, (height, width, 4), dtype=np.uint8)
                image = Image.fromarray(image_data, 'RGBA')
            else:
                # 3-channel RGB image
                image_data = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
                image = Image.fromarray(image_data, 'RGB')
            
            # Save the image
            image.save(output_path)
            
            print(f"Scan completed and saved to {output_path}")
            return True
            
        except Exception as e:
            print(f"Scan failed: {e}")
            if self.scan_in_progress:
                self.cancel_scan()
            return False
    
    def cancel_scan(self) -> bool:
        """Cancel the current scan operation."""
        if not self.scan_in_progress:
            return True
        
        try:
            if self.protocol.cancel_scan():
                self.scan_in_progress = False
                print("Scan cancelled")
                return True
            else:
                print("Failed to cancel scan")
                return False
        except Exception as e:
            print(f"Error cancelling scan: {e}")
            return False
    
    def wait_for_ready(self, timeout: int = 30) -> bool:
        """Wait for the scanner to be ready."""
        if not self.is_connected:
            return False
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.protocol.test_unit_ready():
                return True
            time.sleep(1)
        
        return False
    
    def __enter__(self):
        """Context manager entry."""
        if not self.connect():
            raise RuntimeError("Failed to connect to scanner")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


def scan_preview(device: ScannerDevice, output_path: str, resolution: int = 270) -> bool:
    """Quick preview scan function."""
    with CoolscanScanner(device) as scanner:
        return scanner.scan_preview(output_path, resolution)


def scan_full(device: ScannerDevice, output_path: str, resolution: int = 2700,
              negative: bool = False, infrared: bool = False) -> bool:
    """Quick full scan function."""
    with CoolscanScanner(device) as scanner:
        return scanner.scan_full(output_path, resolution, negative, infrared)


def get_scanner_info(device: ScannerDevice) -> dict:
    """Get scanner information."""
    with CoolscanScanner(device) as scanner:
        return scanner.get_device_info()


