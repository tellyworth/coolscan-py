# Additional Coolscan Protocol Information

This document contains additional protocol information discovered in other Coolscan files from the SANE backend.

## Additional Scanner Models

### From coolscan.desc
- **LS-20**: SCSI interface (replaced by LS-30)
- **LS-30**: SCSI interface, 24/30 bit RGB + 32/40 bit RGBI
- **LS-2000**: SCSI interface, 24/36 bit + RGB 32/48 bit RGBI
- **LS-1000**: SCSI interface, doesn't support gamma correction

### From coolscan2.desc
- **LS 30**: SCSI interface, working
- **LS 2000**: SCSI interface, good status
- **LS 40 ED**: USB interface (0x04b0:0x4000), complete status
- **LS 4000 ED**: IEEE-1394 interface, good status
- **LS 50 ED**: USB interface (0x04b0:0x4001), minimal status
- **Coolscan V ED**: USB interface (0x04b0:0x4001), minimal status
- **Super Coolscan LS-5000 ED**: USB interface (0x04b0:0x4002), untested
- **LS 8000 ED**: IEEE-1394 interface, good status

### From coolscan3.desc
- **LS 30**: SCSI interface, complete status
- **Coolscan III**: SCSI interface, complete status (rebadged LS 30?)
- **LS 40 ED**: USB interface (0x04b0:0x4000), complete status
- **Coolspan IV**: USB interface (0x04b0:0x4000), complete status (rebadged LS 40?)
- **LS 50 ED**: USB interface (0x04b0:0x4001), minimal status
- **Coolscan V ED**: USB interface (0x04b0:0x4001), minimal status (rebadged LS 50?)
- **LS 2000**: SCSI interface, good status
- **LS 4000 ED**: IEEE-1394 interface, good status
- **Super Coolscan LS-5000 ED**: USB interface (0x04b0:0x4002), untested
- **LS 8000 ED**: IEEE-1394 interface, good status

## SCSI Command Definitions (from coolscan-scsidef.h)

### Standard SCSI Commands
```c
#define TEST_UNIT_READY         0x00
#define REQUEST_SENSE           0x03
#define INQUIRY                 0x12
#define MODE_SELECT		0x15
#define RESERVE_UNIT            0x16
#define RELEASE_UNIT            0x17
#define MODE_SENSE		0x1a
#define SCAN                    0x1b
#define SEND_DIAGNOSTIC		0x1d
#define SET_WINDOW              0x24
#define GET_WINDOW              0x25
#define READ                    0x28
#define SEND                    0x2a
#define OBJECT_POSITION         0x31
#define WRITE_BUFFER            0x3b
#define READ_BUFFER	        0x3c
```

### Vendor-Specific Commands
```c
#define SABORT			0xc0
#define COMMAND_C1		0xc1
#define AUTO_FOCUS		0xc2
#define UNIT_MOVE		0xe0
```

## Window Descriptor Block Structure

The Window Descriptor Block (WDB) is a critical data structure for configuring scan parameters:

### Standard WDB Structure (117 bytes)
```c
typedef struct {
    unsigned char window_id;           // 0x00: Window Identifier
    unsigned char auto_flag;           // 0x01: Reserved, AUTO
    unsigned char x_resolution[2];     // 0x02-0x03: X Resolution in dpi
    unsigned char y_resolution[2];     // 0x04-0x05: Y Resolution in dpi
    unsigned char ulx[4];              // 0x06-0x09: Upper Left X (1200|2700pt/inch)
    unsigned char uly[4];              // 0x0a-0x0d: Upper Left Y (1200|2700pt/inch)
    unsigned char width[4];            // 0x0e-0x11: Width (1200pt/inch)
    unsigned char length[4];           // 0x12-0x15: Length (1200pt/inch)
    unsigned char brightness;          // 0x16: Brightness
    unsigned char reserved1;           // 0x17: Reserved
    unsigned char contrast;            // 0x18: Contrast
    unsigned char composition;         // 0x19: Image Mode
    unsigned char bits_per_pixel;      // 0x1a: Bits/Pixel
    unsigned char reserved2[13];       // 0x1b-0x27: Reserved
    unsigned char x_pixels[4];         // 0x28-0x2b: X-axis pixel count (1-2592)
    unsigned char y_pixels[4];         // 0x2c-0x2f: Y-axis pixel count (1-3888)
    unsigned char negative_dropout;    // 0x30: Negative/positive, drop-out color
    unsigned char scan_mode;           // 0x31: Scan mode
    unsigned char transfer_mode;       // 0x32: Data transfer mode
    unsigned char gamma_selection;     // 0x33: Gamma selection
    unsigned char reserved3;           // 0x34: Reserved
    unsigned char shading_analog;      // 0x35: Reserved, shading, analog gamma, averaging
    unsigned char reserved4;           // 0x36: Reserved
    unsigned char brightness_r;        // 0x37: R brightness
    unsigned char brightness_g;        // 0x38: G brightness
    unsigned char brightness_b;        // 0x39: B brightness
    unsigned char contrast_r;          // 0x3a: R contrast
    unsigned char contrast_g;          // 0x3b: G contrast
    unsigned char contrast_b;          // 0x3c: B contrast
    unsigned char reserved5[12];       // 0x3d-0x48: Reserved
    unsigned char exposure_r;          // 0x49: R exposure time adjustment [0, 12-200]
    unsigned char exposure_g;          // 0x4a: G exposure time adjustment [0, 12-200]
    unsigned char exposure_b;          // 0x4b: B exposure time adjustment [0, 12-200]
    unsigned char reserved6[6];        // 0x4c-0x51: Reserved
    unsigned char shift_r;             // 0x52: Amount of R shift [0, 128+-15]
    unsigned char shift_g;             // 0x53: Amount of G shift [0, 128+-15]
    unsigned char shift_b;             // 0x54: Amount of B shift [0, 128+-15]
    unsigned char offset_r;            // 0x55: Amount of R offset [0-255]
    unsigned char offset_g;            // 0x56: Amount of G offset [0-255]
    unsigned char offset_b;            // 0x57: Amount of B offset [0-255]
    unsigned char max_resolution[2];   // 0x58-0x59: Maximum resolution (for GET WINDOW: [2700])
    unsigned char reserved7[2];        // 0x5a-0x5b: Reserved
    unsigned char lut_r_g;             // 0x5c: LUT-R, LUT-G
    unsigned char lut_b;               // 0x5d: LUT-B, reserved
    unsigned char bw_ref_r;            // 0x5e: LS-1000: reserved. LS-20: R B/W reference point
    unsigned char bw_ref_g;            // 0x5f: LS-1000: reserved. LS-20: G B/W reference point
    unsigned char bw_ref_b;            // 0x60: LS-1000: reserved. LS-20: B B/W reference point
    unsigned char exposure_unit_r;     // 0x61: R exposure time unit [0-7] (LS-1000); [0, 2-1] (LS-20)
    unsigned char exposure_unit_g;     // 0x62: G exposure time unit [0-7] (LS-1000); [0, 2-1] (LS-20)
    unsigned char exposure_unit_b;     // 0x63: B exposure time unit [0-7] (LS-1000); [0, 2-1] (LS-20)
    unsigned char reserved8;           // 0x64: Reserved
    unsigned char stop_flag;           // 0x65: Reserved, stop
    unsigned char gain_r;              // 0x66: R gain [0-4] (LS-1000), [0-255] (LS-20)
    unsigned char gain_g;              // 0x67: G gain [0-4] (LS-1000), [0-255] (LS-20)
    unsigned char gain_b;              // 0x68: B gain [0-4] (LS-1000), [0-255] (LS-20)
    unsigned char exposure_var_r[4];   // 0x69-0x6c: R exposure time variable [0, 64-65535]
    unsigned char exposure_var_g[4];   // 0x6d-0x70: G exposure time variable [0, 64-65535]
    unsigned char exposure_var_b[4];   // 0x71-0x74: B exposure time variable [0, 64-65535]
} WindowDescriptorBlock;
```

### LS-30 WDB Structure (50 bytes)
```c
typedef struct {
    unsigned char window_id;           // 0x00: Window Identifier
    unsigned char auto_flag;           // 0x01: Reserved, AUTO
    unsigned char x_resolution[2];     // 0x02-0x03: X Resolution in dpi
    unsigned char y_resolution[2];     // 0x04-0x05: Y Resolution in dpi
    unsigned char ulx[4];              // 0x06-0x09: Upper Left X (2700pt/inch)
    unsigned char uly[4];              // 0x0a-0x0d: Upper Left Y (2700pt/inch)
    unsigned char width[4];            // 0x0e-0x11: Width (1200pt/inch)
    unsigned char length[4];           // 0x12-0x15: Length (1200pt/inch)
    unsigned char brightness;          // 0x16: Brightness
    unsigned char reserved1;           // 0x17: Reserved
    unsigned char contrast;            // 0x18: Contrast
    unsigned char composition;         // 0x19: Image Mode
    unsigned char bits_per_pixel;      // 0x1a: Bits/Pixel (0x0a for 10-bit)
    unsigned char reserved2[15];       // 0x1b-0x29: Reserved
    unsigned char negative_scanmode;   // 0x2a: Negative/positive, scan mode
    unsigned char reserved3[4];        // 0x2b-0x2e: Reserved
    unsigned char gain[4];             // 0x2e-0x31: Gain
} WindowDescriptorBlock_LS30;
```

## Command Structures

### INQUIRY Command
```c
static unsigned char inquiryC[] = {
    INQUIRY, 0x00, 0x00, 0x00, 0x1f, 0x00
};
```

### TEST UNIT READY Command
```c
static unsigned char test_unit_readyC[] = {
    TEST_UNIT_READY, 0x00, 0x00, 0x00, 0x00, 0x00
};
```

### SET WINDOW Command
```c
static unsigned char set_windowC[] = {
    SET_WINDOW, 0x00,        // opcode, lun
    0x00, 0x00, 0x00, 0x00,  // reserved
    0x00, 0x00, 0x00,        // transfer length; needs to be set
    0x00,                    // control byte
};
```

### GET WINDOW Command
```c
static unsigned char get_windowC[] = {
    GET_WINDOW, 0x01,        // opcode, lun, misc (should be 0x01?)
    0x00, 0x00, 0x00,        // reserved
    0x00,                    // Window identifier
    0x00, 0x00, 0x00,        // transfer length; needs to be get
    0x00,                    // control byte
};
```

### SCAN Command
```c
static unsigned char scanC[] = {
    SCAN, 0x00, 0x00, 0x00, 0x00, 0x00
};
```

### READ Command
```c
static unsigned char sreadC[] = {
    READ, 0x00,
    0x00,                    // Data Type Code
    0x00,                    // reserved
    0x00, 0x00,              // data type qualifier
    0x00, 0x00, 0x00,        // transfer length
    0x00                     // control
};
```

### SEND Command
```c
static unsigned char sendC[] = {
    SEND, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};
```

### OBJECT POSITION Command
```c
static unsigned char object_positionC[] = {
    OBJECT_POSITION,
    0x00,                    // Auto feeder function
    0x00, 0x00, 0x00,        // Count
    0x00, 0x00, 0x00, 0x00,  // Reserved
    0x00                     // Control byte
};
```

### AUTO FOCUS Command
```c
static unsigned char autofocusC[] = {
    AUTO_FOCUS, 0x00, 0x00, 0x00,
    0x00,                    // transfer length (0|8)
    0x00                     // Control byte
};
```

### COMMAND C1
```c
static unsigned char command_c1_C[] = {
    0xc1, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,  // 
    0x00, 0x00               // transfer length
};
```

### COMMAND E1
```c
static unsigned char commande1C[] = {
    0xe1, 0x00, 0xc1, 0x00,
    0x00, 0x00, 0x00, 0x00,  // 
    0x0d, 0x00               // transfer length
};
```

## Data Type Codes

### READ Command Data Types
```c
#define R_datatype_imagedata		0x00
#define R_EX_datatype_LUT		0x01	// Experiment code
#define R_image_positions		0x88
#define R_EX_datatype_shading_data	0xa0	// Experiment code
#define R_user_reg_gamma		0xc0
#define R_device_internal_info		0xe0
```

### SEND Command Data Types
```c
#define S_datatype_imagedatai		0x00
#define S_EX_datatype_LUT			0x01	// Experiment code
#define S_EX_datatype_shading_data	0xa0	// Experiment code
#define S_user_reg_gamma			0xc0
#define S_device_internal_info		0x03
```

## Data Type Qualifiers

### READ Command Qualifiers
```c
#define R_DQ_none	0x00
#define R_DQ_Rcomp	0x06
#define R_DQ_Gcomp	0x07
#define R_DQ_Bcomp	0x08
#define R_DQ_Reg1	0x01
#define R_DQ_Reg2	0x02
#define R_DQ_Reg3	0x03
```

### SEND Command Qualifiers
```c
#define S_DQ_none	0x00
#define S_DQ_Rcomp	0x06
#define S_DQ_Gcomp	0x07
#define S_DQ_Bcomp	0x08
#define S_DQ_Reg1	0x01
#define S_DQ_Reg2	0x02
#define S_DQ_Reg3	0x03
#define S_DQ_Reg9	0x09
```

## Window Descriptor Block Constants

### Image Composition
```c
#define WD_comp_grey          0x02
#define WD_comp_gray          0x02
#define WD_comp_rgb_full      0x05
```

### Bits Per Pixel
```c
#define WD_bits_8    0x08
#define WD_bits_10   0x0a
```

### Negative/Positive
```c
#define WD_Negative 0x01
#define WD_Positive 0x00
```

### Drop-out Colors
```c
#define WD_Dropout_Red 0x00
#define WD_Dropout_Green 0x01
#define WD_Dropout_Blue 0x02
```

### Scan Modes
```c
#define WD_Scan 0x00
#define WD_Prescan 0x01
```

### Transfer Modes
```c
#define WD_LineSequence	0x2
#define WD_DotSequence	0x1
```

### Gamma Selection
```c
#define WD_Linear	0x2
#define WD_Monitor	0x3
```

### Shading
```c
#define WD_Shading_ON	0x0
#define WD_Shading_OFF	0x1
```

### Analog Gamma
```c
#define WD_Analog_Gamma_ON	0x0
#define WD_Analog_Gamma_OFF	0x1
```

### Averaging
```c
#define WD_Averaging_ON	0x0
#define WD_Averaging_OFF	0x1
```

## Object Position Commands

### Auto Feeder Functions
```c
#define OP_Discharge		0x00
#define OP_Feed			0x01
#define OP_Absolute		0x02	// For development only
```

## Internal Device Information Structure

The device internal information structure (256 bytes) contains detailed scanner state:

### Key Fields
```c
#define get_DI_ADbits(b)	   getnbyte(b + 0x00, 1)        // Number of A/D bits
#define get_DI_Outputbits(b)	   getnbyte(b + 0x01, 1)        // Number of output bits
#define get_DI_MaxResolution(b)	   getnbyte(b + 0x02, 2)        // Maximum resolution
#define get_DI_Xmax(b)		   getnbyte(b + 0x04, 2)        // X-axis maximum
#define get_DI_Ymax(b)		   getnbyte(b + 0x06, 2)        // Y-axis maximum
#define get_DI_Xmaxpixel(b)	   getnbyte(b + 0x08, 2)        // X-axis pixel maximum
#define get_DI_Ymaxpixel(b)	   getnbyte(b + 0x0a, 2)        // Y-axis pixel maximum
#define get_DI_currentY(b)	   getnbyte(b + 0x10, 2)        // Current Y position
#define get_DI_currentFocus(b)	   getnbyte(b + 0x12, 2)        // Current focus position
#define get_DI_currentscanpitch(b) getnbyte(b + 0x14, 1)        // Current scan pitch
#define get_DI_autofeeder(b)	   getnbyte(b + 0x1e, 1)        // Auto feeder available
#define get_DI_analoggamma(b)	   getnbyte(b + 0x1f, 1)        // Analog gamma support
```

### Error Information
```c
#define get_DI_deviceerror0(b)	   getnbyte(b + 0x40, 1)        // Latest error
#define get_DI_deviceerror1(b)	   getnbyte(b + 0x41, 1)        // Second latest error
// ... up to error7
```

### Exposure Information
```c
#define get_DI_WBETR_R(b)	   getnbyte(b + 0x80, 2)        // White balance exposure time R
#define get_DI_WBETR_G(b)	    getnbyte(b + 0x82, 2)        // White balance exposure time G
#define get_DI_WBETR_B(b)	    getnbyte(b + 0x84, 2)        // White balance exposure time B
#define get_DI_PRETV_R(b)	    getnbyte(b + 0x88, 2)        // Prescan exposure time R
#define get_DI_PRETV_G(b)	    getnbyte(b + 0x8a, 2)        // Prescan exposure time G
#define get_DI_PRETV_B(b)	    getnbyte(b + 0x8c, 2)        // Prescan exposure time B
#define get_DI_CETV_R(b)	    getnbyte(b + 0x90, 2)        // Current exposure time R
#define get_DI_CETV_G(b)	    getnbyte(b + 0x92, 2)        // Current exposure time G
#define get_DI_CETV_B(b)	    getnbyte(b + 0x94, 2)        // Current exposure time B
#define get_DI_IETU_R(b)	    getnbyte(b + 0x98, 1)        // Internal exposure unit R
#define get_DI_IETU_G(b)	    getnbyte(b + 0x99, 1)        // Internal exposure unit G
#define get_DI_IETU_B(b)	    getnbyte(b + 0x9a, 1)        // Internal exposure unit B
```

### Additional Information
```c
#define get_DI_limitcondition(b)    getnbyte(b + 0xa0, 1)        // Limit condition
#define get_DI_offsetdata_R(b)	    getnbyte(b + 0xa1, 1)        // Offset data R
#define get_DI_offsetdata_G(b)	    getnbyte(b + 0xa2, 1)        // Offset data G
#define get_DI_offsetdata_B(b)	    getnbyte(b + 0xa3, 1)        // Offset data B
#define get_DI_poweron_errors(b,to) memcpy(to, (b + 0xa8), 8)    // Power-on errors
```

## Request Sense Information

The request sense return block (18 bytes) provides detailed error information:

```c
#define get_RS_information_valid(b)       getbitfield(b + 0x00, 1, 7)
#define get_RS_error_code(b)              getbitfield(b + 0x00, 0x7f, 0)
#define get_RS_filemark(b)                getbitfield(b + 0x02, 1, 7)
#define get_RS_EOM(b)                     getbitfield(b + 0x02, 1, 6)
#define get_RS_ILI(b)                     getbitfield(b + 0x02, 1, 5)
#define get_RS_sense_key(b)               getbitfield(b + 0x02, 0x0f, 0)
#define get_RS_information(b)             getnbyte(b+0x03, 4)    // normally 0
#define get_RS_additional_length(b)       b[0x07]                // always 10
#define get_RS_ASC(b)                     b[0x0c]                // Additional Sense Code
#define get_RS_ASCQ(b)                    b[0x0d]                // Additional Sense Code Qualifier
#define get_RS_SKSV(b)                    getbitfield(b+0x0f,1,7) // valid, always 0
```

## Scanner-Specific Information

### LS-1000 Characteristics
- Doesn't support gamma correction
- Uses different exposure time units [0-7]
- Different gain range [0-4]

### LS-20 Characteristics
- Different exposure time units [0, 2-1]
- Different gain range [0-255]
- B/W reference points at offsets 0x5e-0x60

### LS-30 Characteristics
- 10-bit support (WD_bits_10 = 0x0a)
- Different WDB structure (50 bytes vs 117 bytes)
- Different negative/positive handling

## Implementation Notes

### Bit Field Operations
The code uses helper functions for bit field manipulation:

```c
static inline void setbitfield(unsigned char *pageaddr, int mask, int shift, int val) {
    *pageaddr = (*pageaddr & ~(mask << shift)) | ((val & mask) << shift);
}

static inline int getbitfield(unsigned char *pageaddr, int mask, int shift) {
    return ((*pageaddr >> shift) & mask);
}
```

### Multi-byte Operations
Helper functions for multi-byte values:

```c
static inline int getnbyte(unsigned char *pnt, int nbytes) {
    unsigned int result = 0;
    int i;
    for (i = 0; i < nbytes; i++)
        result = (result << 8) | (pnt[i] & 0xff);
    return result;
}

static inline void putnbyte(unsigned char *pnt, unsigned int value, unsigned int nbytes) {
    int i;
    for (i = nbytes - 1; i >= 0; i--) {
        pnt[i] = value & 0xff;
        value = value >> 8;
    }
}
```

### WDB Length Constants
```c
#define STD_WDB_LEN 0x28
#define max_WDB_size 0xff
#define used_WDB_size 0x75
#define used_WDB_size_LS30 0x32
```

This additional information provides a much more complete picture of the Coolscan protocol, including detailed command structures, data formats, and scanner-specific variations.
