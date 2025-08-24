"""
Coolscan Tool - A standalone tool for Nikon Coolscan film scanners.

This package provides direct access to Nikon Coolscan scanners without requiring
the full SANE backend installation.
"""

__version__ = "0.1.0"
__author__ = "Coolscan Tool Developer"

from .device import find_scanners, ScannerDevice
from .scanner import CoolscanScanner

__all__ = ['find_scanners', 'ScannerDevice', 'CoolscanScanner']


