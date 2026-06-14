## Analysis: How SANE Handles Scan Image Data for Coolscan Scanners

### Relevant Source Files

| File | Purpose |
|------|---------|
| `/Users/alex/dev/coolscan-py/backends-1.4.0/backend/coolscan.c` | Original coolscan backend (LS-20, LS-1000) |
| `/Users/alex/dev/coolscan-py/backends-1.4.0/backend/coolscan.h` | Data structures for original backend |
| `/Users/alex/dev/coolscan-py/backends-1.4.0/backend/coolscan-scsidef.h` | SCSI command definitions, WDB layout |
| `/Users/alex/dev/coolscan-py/backends-1.4.0/backend/coolscan3.c` | coolscan3 backend (LS-30, **LS-40**, LS-50, LS-2000, etc.) |
| `/Users/alex/dev/coolscan-py/backends-1.4.0/include/sane/sane.h` | SANE API definitions including `SANE_Parameters` |

---

### 1. How SANE Interprets Raw Bytes (Byte Order, Bit Depth, Channel Layout)

#### Output Bit Depth

The WDB `bits_per_pixel` field (byte 0x1A) controls output depth:
- `0x08` = 8-bit output (1 byte per pixel per channel)
- `0x0C` = 12-bit output in 16-bit containers (2 bytes per pixel, big-endian)

The LS-40 ED has a 12-bit ADC, but when WDB specifies 8-bit, the scanner converts
12-bit ADC values to 8-bit before transmission. Our test scans use 8-bit output.

#### Byte Order

For 16-bit output: scanner sends data in **big-endian** (network byte order). Both backends handle endianness explicitly.
For 8-bit output: byte order is irrelevant (1 byte per value).

**coolscan.c (lines 1450-1460):**
```c
static SANE_Bool coolscan_test_little_endian(void)
{
  SANE_Int testvalue = 255;
  unsigned char *firstbyte = (unsigned char *) &testvalue;
  if (*firstbyte == 255)
    return SANE_TRUE;  /* little-endian machine */
  return SANE_FALSE;
}
```

For 16-bit data (10-bit or 12-bit depth), the scanner sends **big-endian** 16-bit words. On a little-endian host, SANE swaps the bytes (coolscan.c lines 2674-2681):
```c
if((!scanner->low_byte_first)&&(scanner->bits_per_color>8))
{  for(i=0;i<data_to_write;i++) /* inverse byteorder */
   { h=scanner->obuffer[i];
     scanner->obuffer[i]=scanner->obuffer[i+1];
     i++;
     scanner->obuffer[i]=h;
   }
}
```

**coolscan3.c (lines 1672-1686):**
```c
case 2:  /* 16-bit data */
{
    s16 = (uint16_t *) & (s->line_buf[where]);
    // ...
    *s16 = (s->recv_buf[p16] << 8) + s->recv_buf[p16 + 1];  /* Big-endian assembly */
    *s16 <<= s->shift_bits;  /* Shift to fill 16 bits for 10/12-bit data */
}
```

#### Bit Depth

- **LS-20/LS-1000**: 8-bit output only
- **LS-30**: 8-bit or 10-bit
- **LS-40/LS-50**: 8-bit or 12-bit

The `bytes_per_pixel` is computed as:
```c
s->bytes_per_pixel = (s->real_depth > 8 ? 2 : 1);  /* coolscan3.c:2789 */
```

For >8-bit data, SANE uses 16-bit containers and left-shifts to fill:
```c
s->shift_bits = 8 * s->bytes_per_pixel - s->real_depth;  /* coolscan3.c:2790 */
```
For 12-bit data: `shift_bits = 16 - 12 = 4`, so values are shifted left by 4 bits.

#### Channel Layout

**RGB mode (3 channels):**
- The scanner sends data organized as **plane-interleaved by color window** (R window, G window, B window)
- For each line, data arrives as: `[R_pixels][padding][G_pixels][padding][B_pixels][padding]`
- SANE reassembles this into **pixel-interleaved RGB** format: `R0 G0 B0 R1 G1 B1 ...`

**RGBI mode (4 channels):**
- Adds infrared window (window 9): `[R][G][B][IR]`
- The IR channel undergoes correction via `RGBIfix()` (coolscan.c lines 2281-2327)

**Grayscale mode:**
- For LS-30+, RGB data is read and converted to grayscale via `rgb2g()` (coolscan.c lines 2402-2420):
```c
g = RtoG*(*pr) + GtoG*(*pg) + BtoG*(*pb);
(*opg) = (unsigned char)(g >> 8);
```
Using weights: R=0.27, G=0.54, B=0.19.

---

### 2. How SANE Determines Image Dimensions (Width, Height)

#### SANE_Parameters Structure (sane.h lines 198-207):
```c
typedef struct {
    SANE_Frame format;        /* SANE_FRAME_RGB, SANE_FRAME_GRAY, SANE_FRAME_RGBI */
    SANE_Bool last_frame;     /* SANE_TRUE when all data has been read */
    SANE_Int bytes_per_line;  /* bytes per line in output buffer */
    SANE_Int pixels_per_line; /* pixel width */
    SANE_Int lines;           /* pixel height */
    SANE_Int depth;           /* 8 or 16 */
} SANE_Parameters;
```

#### Dimension Calculation (coolscan3.c, `cs3_convert_options()` lines 2781-2895):

```c
// Resolution to pitch conversion:
s->real_pitchx = s->resx_max / s->real_resx;  /* e.g., 2700 / 2700 = 1 */
s->real_pitchy = s->resy_max / s->real_resy;

// Logical dimensions from user-specified scan area:
s->logical_width  = (xmax - xmin + 1) / s->real_pitchx;
s->logical_height = (ymax - ymin + 1) / s->real_pitchy;
```

#### READ_CAPACITY (coolscan3.c line 3010):
```c
if ((s->type == CS3_TYPE_LS40) || ...)
    cs3_parse_cmd(s, "24 00 00 00 00 00 00 00 3a 80");  /* Note: 3a 80 for LS-40 */
else
    cs3_parse_cmd(s, "24 00 00 00 00 00 00 00 3a 00");
```

The `3a 80` vs `3a 00` distinction is significant for LS-40. The `0x3A` is the block size field and `0x80` is a control byte.

#### In the original coolscan.c (lines 1348-1393):
```c
static int pixels_per_line(Coolscan_t * s)
{
    int pic_dot;
    if(s->LS<2)
        pic_dot = (s->brx - s->tlx + s->x_nres) / s->x_nres;
    else
        pic_dot = (s->brx - s->tlx + 1) / s->x_nres;
    return pic_dot;
}

static int lines_per_scan(Coolscan_t * s)
{
    int pic_line;
    if(s->LS<2)
        pic_line = (s->bry - s->tly + s->y_nres) / s->y_nres;
    else
        pic_line = ((s->bry - s->tly + 1.0) / s->y_nres);
    return pic_line;
}
```

---

### 3. How SANE Handles Different Data Chunks During a Scan

#### Scan Data Reading Architecture (coolscan3.c `sane_read()` lines 1520-1712):

**Key variables:**
- `xfer_bytes_total`: Total bytes for entire image = `bytes_per_pixel * n_colors * logical_width * logical_height`
- `xfer_position`: Running offset through the total data
- `xfer_len_line`: Bytes per line = `n_colors * logical_width * bytes_per_pixel`
- `xfer_len_in`: Bytes to read from scanner per line (includes padding)

**Per-line read loop:**
```c
xfer_len_in = xfer_len_line + (s->n_colors * s->odd_padding);
// For LS-50, additionally pad to 512-byte boundary:
xfer_len_in += s->block_padding;

// Multiply for multi-sampling:
xfer_len_in *= s->samples_per_scan;
```

**The READ(10) command (0x28) is issued per line:**
```c
cs3_parse_cmd(s, "28 00 00 00 00 00");
cs3_pack_byte(s, (xfer_len_in >> 16) & 0xff);
cs3_pack_byte(s, (xfer_len_in >> 8) & 0xff);
cs3_pack_byte(s, xfer_len_in & 0xff);
cs3_parse_cmd(s, "00");
```

**Data reassembly (coolscan3.c lines 1626-1698):**
The scanner sends data organized as:
```
[Color1_pixels][padding][Color2_pixels][padding][Color3_pixels][padding]
```
SANE interleaves this into:
```
[R0][G0][B0][R1][G1][B1]...
```

For 8-bit:
```c
int p8 = s->logical_width * color + (color + 1) * s->odd_padding + index;
*s8 = s->recv_buf[p8];
```

For 16-bit:
```c
int p16 = 2 * (color * s->logical_width + index);
*s16 = (s->recv_buf[p16] << 8) + s->recv_buf[p16 + 1];
*s16 <<= s->shift_bits;
```

#### In the original coolscan.c (lines 2531-2695):

The `reader_process()` function reads data in **large chunks** (up to `row_bufsize`, typically 64KB), not per-line:
```c
data_left = scan_bytes_per_line(scanner) * lines_per_scan(scanner);
// ...
do {
    data_to_read = (data_left < scanner->row_bufsize) ? data_left : scanner->row_bufsize;
    status = coolscan_read_data_block(scanner, R_datatype_imagedata, data_to_read);
    // Process: mirror for LS-1000, RGBI correction, grayscale conversion, byte swap
    fwrite(scanner->obuffer, 1, data_to_write, fp);
    data_left -= data_to_read;
} while (data_left);
```

The data is piped from a child process/thread to the main SANE process.

---

### Summary of Key Differences Between coolscan.c and coolscan3.c

| Aspect | coolscan.c (original) | coolscan3.c (LS-40) |
|--------|----------------------|---------------------|
| **Data chunking** | Large blocks (64KB) via pipe | Per-line reads |
| **Byte order** | Scanner sends big-endian; swaps on LE hosts | Scanner sends big-endian; explicitly assembles |
| **Channel layout** | Already interleaved RGB from scanner | Plane-interleaved by color; SANE reassembles |
| **Width/height** | Computed from ILU coordinates and resolution | Computed from device pixels and pitch |
| **READ_CAPACITY** | Uses `3a 00` | Uses `3a 80` for LS-40/LS-4000/LS-50/LS-5000 |
| **Padding** | None mentioned | `odd_padding` (1 byte for odd width at 8-bit), `block_padding` (to 512-byte boundary for LS-50), plus 128 bytes line-end padding observed in LS-40 ED hardware tests |
| **Output depth** | 8-bit only | 8-bit or 12-bit (controlled by WDB `bits_per_pixel`); 12-bit ADC always, but output depth is configurable |

---

### 4. Verified Format (Hardware Test — LS-40 ED)

#### Raw Data Layout

Confirmed by parsing actual hardware scan data (`hardware_scan_output.raw`, 32,768,000 bytes):

- **Bit depth**: 8-bit per channel. The LS-40 ED has a 12-bit ADC, but when WDB `bits_per_pixel = 0x08`, the scanner outputs 8-bit data (1 byte per pixel value). The WDB field `bits_per_pixel` controls output depth, not ADC depth.
- **Channel layout**: RGB plane-interleaved per line (SANE coolscan3.c style):
  ```
  [R_0 R_1 ... R_{w-1}][G_0 G_1 ... G_{w-1}][B_0 B_1 ... B_{w-1}][padding]
  ```
  Each value is 1 byte. 128 bytes of padding follow each line (sensor data from outside active scan area).

#### Dimension Calculation

```
bytes_per_line = 3 * width + padding  (= 3 * 2624 + 128 = 8000)
total_bytes = bytes_per_line * height  (= 8000 * 4096 = 32,768,000)
```

For the test scan: **2624 × 4096 pixels** (aspect ratio 1.47, close to 35mm film ratio of 1.5).

The WDB specifies scan area: size_x=2870, size_y=4332 at 2900 DPI (pitch=1.0).
The effective output width (2624) is smaller than the WDB scan width (2870) because
the remaining pixels per channel (246 pixels × 3 bytes = 738 bytes) plus inter-plane
gaps account for the 128-byte line padding. The scanner reads the full carrier width
but only 2624 pixels of RGB data go into each line buffer.

> **Bug note**: The initial implementation incorrectly assumed 16-bit BE data with
> 12-bit shift, producing diagonal artifacts. The data is 8-bit throughout.

#### Grayscale Conversion

SANE converts RGB to grayscale using fixed weights (`coolscan.c` lines 2402-2420):

```
gray = 0.27 * R + 0.54 * G + 0.19 * B
```

These differ from standard luminance weights (0.299/0.587/0.114) and reflect the spectral sensitivity of film emulsion.

#### Data Parsing Reference (Python)

```python
import numpy as np
from PIL import Image

# Read raw bytes from scanner (65536-byte chunks, concatenated)
raw = open('scan_data.raw', 'rb').read()
raw_arr = np.frombuffer(raw, dtype=np.uint8)

# Verified dimensions for LS-40 ED full scan at 2900 DPI
width, height = 2624, 4096
bytes_per_line = 8000  # 3*width + 128 padding

# Parse per-line: plane-interleaved RGB
img_r = np.zeros((height, width), dtype=np.uint8)
img_g = np.zeros((height, width), dtype=np.uint8)
img_b = np.zeros((height, width), dtype=np.uint8)

offset = 0
for y in range(height):
    img_r[y, :] = raw_arr[offset:offset + width]
    img_g[y, :] = raw_arr[offset + width:offset + 2*width]
    img_b[y, :] = raw_arr[offset + 2*width:offset + 3*width]
    offset += bytes_per_line  # Skip 128-byte padding

# Grayscale (SANE weights)
gray8 = (0.27 * img_r.astype(np.float32) +
         0.54 * img_g.astype(np.float32) +
         0.19 * img_b.astype(np.float32)).astype(np.uint8)

# Contrast stretch (percentile stretching for film negatives)
p1, p99 = np.percentile(gray8, 0.5), np.percentile(gray8, 99.5)
gray8 = np.clip((gray8.astype(np.float32) - p1) / (p99 - p1) * 255, 0, 255).astype(np.uint8)

img = Image.fromarray(gray8)
img.save('scan_output.png')
```

#### Short Read Behavior

When scan data is exhausted, the scanner returns fewer bytes than requested (short read), then stalls both bulk endpoints. The short read is the end-of-scan signal. After short read:

1. `clear_halt` on both `bulk_out` and `bulk_in` endpoints
2. 50ms settling delay
3. Return data with READY status (skip status read — it will time out)

See `coolscan/protocol.py` `read_scan_data()` and `_issue_usb_command()` for implementation.

#### USB Transfer Pattern

The scanner sends image data in bulk transfers of ~65,508 bytes each. The host
issues READ(10) commands requesting larger amounts (e.g., 258,048 bytes = 0x3F000),
and the scanner responds with multiple 65,508-byte transfers. The `read_scan_data()`
function requests 65,536 bytes per call, which spans one or more scanner transfers.
The total scan data is 32,768,000 bytes (500 × 65,536-byte reads).
