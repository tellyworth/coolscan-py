"""
Command-line interface for Coolscan Tool.

This module provides a command-line interface for controlling Nikon Coolscan scanners.
"""

import click
import sys
from pathlib import Path

from .device import find_scanners, list_scanners
from .scanner import CoolscanScanner, scan_preview, scan_full, get_scanner_info


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Coolscan Tool - Control Nikon Coolscan film scanners."""
    pass


@cli.command()
def list():
    """List all available Coolscan scanners."""
    list_scanners()


@cli.command()
@click.option('--scanner', '-s', type=int, help='Scanner number (from list command)')
@click.option('--output', '-o', type=click.Path(), required=True, help='Output file path')
@click.option('--resolution', '-r', type=int, default=2700, help='Scan resolution in DPI')
@click.option('--preview', is_flag=True, help='Perform a preview scan')
@click.option('--negative', is_flag=True, help='Scan as negative film')
@click.option('--infrared', is_flag=True, help='Include infrared channel')
def scan(scanner, output, resolution, preview, negative, infrared):
    """Perform a scan."""
    # Find available scanners
    scanners = find_scanners()
    
    if not scanners:
        click.echo("No Coolscan scanners found.", err=True)
        sys.exit(1)
    
    # Select scanner
    if scanner is None:
        if len(scanners) == 1:
            selected_scanner = scanners[0]
        else:
            click.echo("Multiple scanners found. Please specify one with --scanner:")
            list_scanners()
            sys.exit(1)
    else:
        if scanner < 1 or scanner > len(scanners):
            click.echo(f"Invalid scanner number. Available: 1-{len(scanners)}", err=True)
            sys.exit(1)
        selected_scanner = scanners[scanner - 1]
    
    click.echo(f"Using scanner: {selected_scanner}")
    
    # Validate output path
    output_path = Path(output)
    if output_path.suffix.lower() not in ['.tiff', '.tif', '.png', '.jpg', '.jpeg']:
        click.echo("Output file must have .tiff, .tif, .png, .jpg, or .jpeg extension", err=True)
        sys.exit(1)
    
    # Perform scan
    try:
        if preview:
            success = scan_preview(selected_scanner, str(output_path), resolution)
        else:
            success = scan_full(selected_scanner, str(output_path), resolution, negative, infrared)
        
        if success:
            click.echo(f"Scan completed successfully: {output_path}")
        else:
            click.echo("Scan failed", err=True)
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"Error during scan: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--scanner', '-s', type=int, help='Scanner number (from list command)')
def info(scanner):
    """Get detailed information about a scanner."""
    # Find available scanners
    scanners = find_scanners()
    
    if not scanners:
        click.echo("No Coolscan scanners found.", err=True)
        sys.exit(1)
    
    # Select scanner
    if scanner is None:
        if len(scanners) == 1:
            selected_scanner = scanners[0]
        else:
            click.echo("Multiple scanners found. Please specify one with --scanner:")
            list_scanners()
            sys.exit(1)
    else:
        if scanner < 1 or scanner > len(scanners):
            click.echo(f"Invalid scanner number. Available: 1-{len(scanners)}", err=True)
            sys.exit(1)
        selected_scanner = scanners[scanner - 1]
    
    click.echo(f"Scanner: {selected_scanner}")
    click.echo()
    
    # Get detailed info
    try:
        info = get_scanner_info(selected_scanner)
        
        click.echo("Device Information:")
        click.echo(f"  Vendor: {info.get('vendor', 'Unknown')}")
        click.echo(f"  Product: {info.get('product', 'Unknown')}")
        click.echo(f"  Revision: {info.get('revision', 'Unknown')}")
        click.echo(f"  Interface: {info.get('interface', 'Unknown')}")
        click.echo(f"  Device Path: {info.get('device_path', 'Unknown')}")
        
        if 'error' in info:
            click.echo(f"  Error: {info['error']}")
            
    except Exception as e:
        click.echo(f"Error getting scanner info: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--scanner', '-s', type=int, help='Scanner number (from list command)')
def test(scanner):
    """Test scanner connection and basic functionality."""
    # Find available scanners
    scanners = find_scanners()
    
    if not scanners:
        click.echo("No Coolscan scanners found.", err=True)
        sys.exit(1)
    
    # Select scanner
    if scanner is None:
        if len(scanners) == 1:
            selected_scanner = scanners[0]
        else:
            click.echo("Multiple scanners found. Please specify one with --scanner:")
            list_scanners()
            sys.exit(1)
    else:
        if scanner < 1 or scanner > len(scanners):
            click.echo(f"Invalid scanner number. Available: 1-{len(scanners)}", err=True)
            sys.exit(1)
        selected_scanner = scanners[scanner - 1]
    
    click.echo(f"Testing scanner: {selected_scanner}")
    click.echo()
    
    try:
        with CoolscanScanner(selected_scanner) as scanner_obj:
            click.echo("✓ Connected to scanner")
            
            # Test device info
            info = scanner_obj.get_device_info()
            click.echo(f"✓ Device info retrieved: {info.get('product', 'Unknown')}")
            
            # Test ready state
            if scanner_obj.wait_for_ready(timeout=10):
                click.echo("✓ Scanner is ready")
            else:
                click.echo("⚠ Scanner not ready (this might be normal)")
            
            click.echo()
            click.echo("Scanner test completed successfully!")
            
    except Exception as e:
        click.echo(f"✗ Scanner test failed: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    cli()


