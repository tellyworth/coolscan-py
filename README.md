# coolscan

Control Nikon Coolscan film scanners from Python (USB).

## Supported Scanners

| Model | Status |
|-------|--------|
| LS-40 ED | Tested and working |
| LS-50 ED | Supported, not tested |
| LS-5000 ED | Supported, not tested |

## Installation

```bash
pipx install git+https://github.com/<user>/coolscan-py.git
```

Or for development:

```bash
git clone https://github.com/<user>/coolscan-py.git
cd coolscan-py
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

On macOS, USB access may require `sudo`.

## Usage

```bash
# List connected scanners
coolscan list

# Check scanner status
coolscan status

# Single-frame scan at 2700 DPI
coolscan scan -o ./output_dir --depth 12 --film-type negative

# Batch scan (6 frames, with infrared channel)
coolscan scan -o ./output_dir --batch --frames 6 --infrared --depth 12

# Preview/prescan only
coolscan scan -o ./output_dir --preview

# Eject film
coolscan eject
```

See `coolscan scan --help` for all options.

Outputs are 16-bit TIFF (archival raw) + JPEG (viewing copy) per frame, with
EXIF metadata and optional auto-adjustment for negatives.

## Architecture

- `coolscan/device.py` — scanner detection and device management
- `coolscan/protocol.py` — USB communication protocol
- `coolscan/scanner.py` — high-level scanner operations
- `coolscan/cli.py` — Click-based command-line interface

## License

GNU GPL v3. See [LICENSE](LICENSE).
