I now have comprehensive data from the repository. Let me compile this into a thorough Markdown document documenting the Coolscan protocol.

Nikon Coolscan SCSI/USB Protocol Specification
Source: Reverse-engineering project by kevihiiin — Nikon-Coolscan-RE Primary target: Nikon Coolscan V ED (LS-50), with cross-model verification for LS-40, LS-5000, LS-4000, LS-8000, LS-9000 Status: RE Phases 0–7 complete; protocol documented and cross-validated (host DLLs ↔ firmware) Confidence: Verified unless otherwise noted in per-section annotations

1. System Architecture
1.1 Scanner Models
Model	Marketing Name	Film Format	Interface	USB PID	MAID Module
LS-40	Coolscan IV ED	35 mm	USB only	0x4000	LS4000.md3
LS-50	Coolscan V ED	35 mm	USB only	0x4001	LS5000.md3
LS-5000	Super Coolscan 5000 ED	35 mm	USB only	0x4002	LS5000.md3
LS-4000	Super Coolscan 4000 ED	35 mm	IEEE 1394 only	—	LS4000.md3
LS-8000	Super Coolscan 8000 ED	35 mm + 120/220	IEEE 1394 only	—	LS8000.md3
LS-9000	Super Coolscan 9000 ED	35 mm + 120/220	IEEE 1394 only	—	LS9000.md3
Module sharing: LS4000.md3 serves LS-40 (USB) and LS-4000 (FireWire). LS5000.md3 serves LS-50 and LS-5000 (both USB). The SCSI command set is protocol-compatible across all models — differences are in parameter ranges and supported capabilities, not wire format.
1.2 Software Stack (Host Side)
The NikonScan 4.03 driver stack consists of four layers communicating through well-defined APIs:
┌──────────────────────────────────────────────────────┐
│ NikonScan 4.03 (User Application)                     │
└──────────────────────┬───────────────────────────────┘
                       │ TWAIN API (DS_Entry)
┌──────────────────────▼───────────────────────────────┐
│ NikonScan4.ds (2.2 MB)                                │
│ TWAIN Data Source                                     │
│  – Scan workflow orchestration                        │
│  – UI parameter mapping                               │
│  – Command queue management                           │
│  – 321 RTTI classes (MFC 7.0 based)                   │
│  – Image processing: DRAG / ICE integration           │
└──────────────────────┬───────────────────────────────┘
                       │ MAID API (MAIDEntryPoint)
┌──────────────────────▼───────────────────────────────┐
│ LS5000.md3 (~1 MB)                                     │
│ Model-specific MAID Module                            │
│  – SCSI CDB construction                              │
│  – Capability ID → SCSI command mapping               │
│  – Exports: MAIDEntryPoint, NkCtrlEntry, NkMDCtrlEntry│
└──────────────────────┬───────────────────────────────┘
                       │ NkDriverEntry API
          ┌────────────┴────────────┐
          │                         │
┌─────────▼──────────┐   ┌──────────▼──────────┐
│ NKDUSCAN.dll (88 KB)│   │ NKDSBP2.dll (84 KB) │
│ USB Transport       │   │ IEEE 1394 / SBP-2   │
│  – CUSB2Command     │   │  – CSBP2Command     │
│  – CUSBSession      │   │  – CSBP2Session     │
│ Export: NkDriverEntry│   │ Export: NkDriverEntry│
└─────────┬──────────┘   └──────────┬──────────┘
          │ DeviceIoControl         │ DeviceIoControl
┌─────────▼──────────┐   ┌──────────▼──────────┐
│ usbscan.sys        │   │ 1394 class driver   │
│ (Still Image driver)│   │ scsiscan.sys        │
└────────────────────┘   └─────────────────────┘
Side-loaded image processing DLLs: DRAGNKL1.dll, DRAGNKX2.dll, ICEDLL.dll, ICENKNL1.dll, ICENKNX2.dll.
1.3 NkDriverEntry Function Codes
Both transport DLLs (NKDUSCAN, NKDSBP2) export a single entry point NkDriverEntry accepting a function code:
FC	Symbol	Purpose
1	Initialize	Magic-check "1200", allocate handle, build command/session managers
2	OpenSession	Open or reopen a scanner session
3	CloseCommand	Cancel and free a specific command
4	ReleaseResource	Session-side cancel callback
5	ExecuteCommand	Build a SCSI command and enqueue for execution (hot path)
6	GetCommandStatus	Retrieve stored status code for a command
7	Shutdown	Release all resources, clear thread execution state
2. Transport Layers
2.1 USB Transport (NKDUSCAN.dll)
The Nikon Coolscan USB scanners use a custom vendor-specific USB protocol — this is not USB Mass Storage (UMS/BOT). The host communicates through the Windows usbscan.sys Still Image driver using USB bulk pipes.
USB Device Descriptors (from firmware):
Field	Value	Notes
bDeviceClass	0xFF	Vendor-specific
bDeviceSubClass	0xFF	Vendor-specific
bDeviceProtocol	0xFF	Vendor-specific
bMaxPacketSize0	64	Control endpoint max packet size
idVendor	0x04B0	Nikon Corporation
idProduct	0x4001	Coolscan V (LS-50)
bcdDevice	0x0102	Device version 1.02
bmAttributes	0xC0	Self-powered
bNumConfigurations	1	Single configuration
Device path: \\.\UsbscanN
USB-SCSI Command Exchange Sequence
A complete SCSI command exchange over USB follows this sequence:
Host (NKDUSCAN.dll)                    Scanner (firmware)
|                                      |
(1) |--- CDB (bulk-out) --------------->|  Raw SCSI CDB, 32 bytes
   |                                    |  Scanner parses & prepares response
(2) |--- 0xD0 (bulk-out) -------------->|  Phase query: "what's next?"
(3) |<-- phase byte (bulk-in) -----------|  Response: 0x01 / 0x02 / 0x03
   |                                    |
   |  [If phase == 0x03: data-in]        |
(4a)|<-- data (bulk-in) ----------------|  Scanner sends scan data
   |    (chunked reads, up to            |
   |     transfer_length bytes)         |
   |                                    |
   |  [If phase == 0x02: data-out]      |
(4b)|--- data (bulk-out) -------------->|  Host sends parameters/data
   |                                    |
   |  [If phase == 0x01: no data]       |
   |    (skip data transfer)            |
   |                                    |
(5) |--- 0x06 (bulk-out) -------------->|  Sense/status request
(6) |<-- sense data (bulk-in) -----------|  Error/status information
Phase Byte Values
Phase	Meaning	Host Action
0x01	Status only / busy	Skip data transfer, proceed to sense
0x02	Data-out (host → scanner)	Write data via bulk-out
0x03	Data-in (scanner → host)	Read data via bulk-in
The command parameter struct's direction field must match the scanner's phase byte:
Direction field	Expected phase	Operation
1	0x03	Data-in (read from scanner)
2	0x02	Data-out (write to scanner)
other	0x01	No data transfer
Extended CDB Path (64-byte CDBs)
For 64-byte CDBs, the driver uses DeviceIoControl with IOCTL_SEND_USB_REQUEST (0x80002008) instead of bulk pipe I/O. This sends the CDB as a USB vendor control transfer, then falls through to the same phase query / sense retrieval path.
Data Transfer Chunking
For data-in transfers (phase 0x03), the driver reads data in chunks of transfer_length bytes to handle USB transfer size limitations and allow the scanner to pace data delivery.
Command Parameter Structure (SCSISCAN_CMD)
Offset	Size	Field	Notes
0x00	4	Size	Constant 0x2C
0x04	1	CdbLength	6 / 10 / 12 / 16
0x05	1	SrbFlags	Typically 0
0x08	4	SrbDirection	0 = none, 0x40 = IN, 0x80 = OUT
0x0C	4	TransferLength	Bytes to read or write
0x10	16	Cdb	Standard SCSI CDB (memcpy)
0x20	4	TimeOutValue	Seconds; 0 = default (~30 s)
0x24	4	ActualTransferLength	Output: bytes actually transferred
0x28	4	SrbStatus	Output: I/O status
2.2 IEEE 1394 / SBP-2 Transport (NKDSBP2.dll)
For FireWire-equipped scanners (LS-4000, LS-8000, LS-9000), NKDSBP2.dll wraps SCSI commands in SBP-2 ORBs (Operation Request Blocks) over IEEE 1394.
SBP-2 ORB Structure:
ORB_POINTER → MANAGEMENT_AGENT → login → command_block_agent

Management Agent:
  +0x00  password (8 bytes; usually 0)
  +0x08  login_response_addr (8 bytes)
  +0x10  notify_excl_lun_funct (4 bytes)
  +0x14  reconnect_size_pwd (4 bytes)
  +0x18  status_FIFO_addr (8 bytes)

Command ORB:
  +0x00  next_ORB (8 bytes)
  +0x08  data_descriptor (8 bytes)
  +0x10  function_max_pyld (4 bytes; rq_fmt, dir, spd, max_pyld, etc.)
  +0x14  cdb[12 or 16 bytes]
Comparison: USB vs. FireWire transport:
Aspect	NKDUSCAN (USB)	NKDSBP2 (FireWire)
Hardware ID prefix	USB\VID_04B0&PID_4001	SBP2\NIKON___&LS-4000_ED...
Kernel driver	usbscan.sys	scsiscan.sys
Device open	\\.\UsbscanN	\\.\ScannerN
IOCTLs	3 (0x80002008, 0x80002014, 0x80002018)	1 (0x00190012)
CDB delivery ≤6 bytes	WriteFile(bulk_out_pipe, cdb)	IOCTL_SCSISCAN_CMD
CDB delivery ≥10 bytes	IOCTL_SEND_USB_REQUEST (vendor ctrl xfer)	IOCTL_SCSISCAN_CMD
Phase/status query	Custom opcode 0xD0 (1-byte response)	Implicit in IOCTL completion
3. SCSI Command Set
All Nikon Coolscan scanners implement the same 17+ SCSI opcodes. Every CDB byte is verified from LS5000.md3 CDB builder functions (host side) and firmware handler dispatch tables (device side).
3.1 Command Summary
Opcode	Command	CDB Size	Direction	Status
0x00	TEST UNIT READY	6	None	Verified
0x12	INQUIRY	6	Data-in	Verified
0x15	MODE SELECT(6)	6	Data-out	Verified
0x16	RESERVE	6	None	Verified
0x17	RELEASE	6	None	Verified
0x1A	MODE SENSE(6)	6	Data-in	Verified
0x1B	SCAN	6	Data-out	Verified
0x1C	RECEIVE DIAGNOSTIC RESULTS	6	Data-in	Verified
0x1D	SEND DIAGNOSTIC	6	Data-out	Verified
0x24	SET WINDOW	10	Data-out	Verified
0x25	GET WINDOW	10	Data-in	Verified
0x28	READ(10)	10	Data-in	Verified
0x2A	WRITE(10) / SEND(10)	10	Data-out	Verified
0x3B	WRITE BUFFER	10	Data-out	Verified
0x3C	READ BUFFER	10	Data-in	Verified
0xC0	Vendor Status Primitive	6	None	Verified
0xC1	Vendor Control Trigger	6	None	Verified
0xE0	Vendor Control Write	10	Data-out	Verified
0xE1	Vendor Sensor Read	10	Data-in	Verified
Vendor flag convention: Many commands set bit 7 of the control byte (last CDB byte) to 0x80 — a Nikon vendor extension. Standard SCSI uses 0x00. This flag signals the firmware to expect Nikon-extended fields.
3.2 TEST UNIT READY (0x00)
Checks scanner readiness. No data phase — only status is examined.
CDB: 00 00 00 00 00 00
Response interpretation:
Status	Meaning
Good (0x00)	Scanner ready to accept commands
Check Condition (0x02)	Not ready — issue REQUEST SENSE
Scanner state machine (RAM @0x40077C):
State	Meaning	Sense Code
0x00	Idle (ready)	Good
0x01	Active scan	Checks DMA/motor sub-states
0x20–0x2F	Setup phase	Returns status
0x80	Ejecting film	0x000D (Medium Removal Request)
0xF0	Sensor error	0x0008 (Communication Failure)
0xF1	Motor error	0x0009 (Track Following Error)
0xF3	Motor busy	0x0079
0xF4	Calibration busy	0x007A
Firmware handler: FW:0x0215C2, ~700 bytes. Validates CDB bytes 2–5 are zero (sense 0x0050 otherwise).
3.3 INQUIRY (0x12)
Returns device identification. Data-in, minimum 36 bytes.
CDB: 12 [EVPD] [PageCode] 00 [AllocLen] [Control]
Byte	Field	Value	Notes
0	Opcode	0x12	INQUIRY
1	EVPD	0x00 or 0x01	0=standard, 1=VPD page
2	Page Code	0x00	VPD page code (when EVPD=1)
4	Allocation Length	varies	Typically ≥36
5	Control	0x80 or 0x00	Bit 7 = Nikon vendor flag
Standard INQUIRY response (EVPD=0):
Offset	Length	Field	Expected Value
0	1	Peripheral Qualifier + Device Type	0x06 (Scanner)
1	1	RMB + Device Type Modifier	—
2	1	ISO/ECMA/ANSI Version	—
3	1	Response Data Format	0x02 (SPC)
4	1	Additional Length	N−4
8–15	8	Vendor Identification	"Nikon "
16–31	16	Product Identification	"LS-50 ED " or "LS-5000 ED "
32–35	4	Product Revision Level	Firmware version string
Known product strings: "Nikon LS-50 ED 1.02", "Nikon LS-5000 ED".
VPD page dispatch (two-level):
Page	Handler	Description
0x00	0x0260BA	Supported VPD page list
0x01	0x026178	Unit serial number
0x10	0x026178	Device identification
0x40–0x41	0x026178	Vendor-specific pages
0x50–0x52	0x026178	Vendor-specific pages
Adapter-specific VPD pages extend this with per-adapter tables at FW:0x49C74.
3.4 MODE SELECT (0x15)
Sends operating mode parameters to the scanner. Data-out.
CDB: 15 [PF|SP] 00 00 [ParamListLen] 00
Byte 1: 0x10 (PF=1, Page Format bit set). Supports mode page 0x03 (device-specific: resolution, max scan area).
Two builder variants in LS5000.md3:
* Variant 1 (Group A): Fixed-length 0x14 (20 bytes) — 4-byte header + 16-byte mode page data.
* Variant 2 (Group B): Variable length, depending on the mode page.
Firmware handler: FW:0x02194A, ~500 bytes. Mode page data stored at RAM @0x400DAA.
3.5 MODE SENSE (0x1A)
Reads current operating mode parameters. Data-in.
CDB: 1A 18 [PageCode] 00 [AllocLen] 00
Byte 1: 0x18 (DBD=1 + Nikon vendor flag bit 4; firmware ignores bit 4 via mask CDB & 0x07).
Response format:
Offset  Length  Field
0x00    1       Mode Data Length (N-1)
0x01    1       Medium Type (0x00 for scanners)
0x02    1       Device-Specific Parameter
0x03    1       Block Descriptor Length (0x00 when DBD=1)
0x04    N       Mode Page Data
Supported mode pages:
Page Code	Description	Data Source
0x03	Format/device-specific (resolution, max scan area)	RAM or Flash
0x3F	All pages (concatenated)	—
Page Control modes:
PC Value	Mode	Data Source
0	Current values	RAM @0x400D2A
1	Changeable values	RAM @0x400D32
2	Default values	Flash FW:0x0168AF
3	Saved values	Not supported → sense 0x0059
3.6 RESERVE (0x16) / RELEASE (0x17)
Standard SCSI reservation pair. RESERVE marks the scanner as in-use; RELEASE clears the reservation.
RESERVE CDB: 16 00 00 00 00 00 RELEASE CDB: 17 00 00 00 00 00
Both have no data phase. Firmware handlers are small (~100 bytes each), primarily setting/clearing an internal state flag.
3.7 SET WINDOW (0x24)
The most important command for configuring scans. Sends a Window Descriptor defining all scan parameters: resolution, bit depth, scan area coordinates, color mode, and Nikon vendor extensions. Every scan operation must be preceded by SET WINDOW.
CDB: 24 00 00 00 00 00 [TL_MSB] [TL] [TL_LSB] 80
Byte	Field	Value	Notes
0	Opcode	0x24	SET WINDOW
6–8	Transfer Length	varies (BE24)	Total payload length (header + descriptor)
9	Control	0x80	Nikon vendor flag
Maximum payload: 66 bytes (8-byte header + 54 bytes standard/Nikon fields + 4 bytes first vendor extension).
Window Parameter Header (8 bytes)
Offset	Length	Field
0–5	6	Reserved
6–7	2	Window Descriptor Length (big-endian)
Window Descriptor Layout
Standard SCSI fields (bytes 0–35):
Offset	Size	Field	MAID Param ID
0–1	2	Window ID	—
2–3	2	Reserved	—
4–7	4	Window Upper Left X (BE)	0x111
8–11	4	Window Upper Left Y (BE)	0x112
12–15	4	Window Width (BE)	0x113
16–19	4	Window Height (BE)	0x114
20	1	Scan Resolution X	0x115
21	1	Scan Resolution Y	0x116
22	1	Bits Per Sample	—
23–25	3	Magnification Factor	—
26–29	4	Compression Type	—
30	1	Brightness	0x100
31	1	Threshold	0x124
32	1	Contrast	0x101
33	1	Image Composition	0x125 (0=line-art, 1=halftone, 2=grayscale, 5=color)
34	1	Bits Per Pixel	0x126 (8, 14, or 16)
35	1	Halftone Pattern	0x127
Reserved gap (bytes 36–47): Zeroed.
Nikon vendor fields (bytes 48–53):
Offset	Size	Field	Source
48	1	Color/Composition Composite	(0x128 << 4) | (0x127 & 0xF)
49	1	Scan Flags (bitfield)	Multiple params OR'd
50	1	Multi-Sample Count	Scan type switch table
51	1	Compression Type	0x12d
52	1	Compression Argument	0x12e
53	1	Reserved	0x12f
First vendor extension (bytes 54–57): Per-channel CCD exposure time (MAID param 0x102, 4 bytes: R/G/B/IR stored at RAM 0x400FAE..0x400FB9).
Additional vendor extension parameters (0x103–0x10d, 0xf02, 0xf03, 0xa20) control features such as ICE/DRAG enable, film type, color balance — some with lower confidence ratings.
3.8 GET WINDOW (0x25)
Reads back current scan window parameters. Data-in. Response mirrors the SET WINDOW data structure.
CDB: 25 00 00 00 00 00 [TL_MSB] [TL] [TL_LSB] 00
3.9 SCAN (0x1B)
Initiates the physical scan. Data-out (1 byte window ID list, typically 0x00).
CDB: 1B 00 00 00 01 00
Byte	Field	Value	Notes
0	Opcode	0x1B	SCAN (not START STOP UNIT)
4	Transfer Length	0x01	1 byte of window ID data
Scan operation types (firmware handler FW:0x0220B8, ~1800 bytes):
Code	Operation	Description
0	Preview scan	Quick low-resolution preview
1	Fine scan (single pass)	Full-resolution single exposure
2	Fine scan (multi-pass)	Multi-sample averaging scan
3	Calibration scan	CCD/LED calibration
4	Move to position	Motor positioning only (no CCD)
9	Eject film	Film transport to eject position
After SCAN, the scanner begins physically scanning: moving the film carrier, activating the LED/lamp, and reading the CCD line-by-line into ASIC RAM at 0x800000.
3.10 READ (0x28)
Retrieves data from the scanner after a scan. Data-in. Uses Data Type Codes (DTC) to select the type of data.
CDB: 28 00 [DTC] 00 00 [Qualifier] [TL_MSB] [TL] [TL_LSB] 80
Byte	Field	Value	Notes
0	Opcode	0x28	READ(10)
2	Data Type Code	varies	What kind of data to read
5	Data Type Qualifier	varies	Sub-type or channel selector
6–8	Transfer Length	varies (BE24)	Number of bytes to read
9	Control	0x80	Nikon vendor control flag
Data Type Codes
DTC	Name	Max Size	Qualifier	Confidence
0x00	Image Data	Variable	0=8-bit, 1=16-bit	Verified
0x03	Gamma Function / LUT	32768	Per CDB	Verified
0x81	Scan Area / Film Frame Info	8	Single value	High
0x84	Calibration Data	6	Single value	Verified
0x87	Scan Parameters / Status	24	Ignored	Verified
0x88	Boundary / Per-Channel Cal	644	0–3 (R/G/B/all)	Verified
0x8A	Exposure / Gain Parameters	14	0–3 (R/G/B/all)	High
0x8C	Offset / Dark Current	Variable	0–3 (R/G/B/all), 0x09 (IR)	Verified
0x8D	(undocumented)	—	—	Low
0x8E	Focus Reading (latest)	Variable	0 or 1	High
0x8F	Focus Sweep Table	324	0, 1, or 3	High
0x90	(undocumented)	—	—	Low
0x92	Motor Control	—	—	Verified
0x93	Calibration Reference Constants	12	Ignored	Verified
0xE0	Extended Config	—	—	Low
Any unrecognized DTC returns sense 0x0050 (ILLEGAL REQUEST / Invalid Field in CDB).
DTC 0x87 — Scan Parameters (24 bytes)
Returned immediately after SCAN. Contains the computed scan geometry and total data byte count.
Response layout:
Offset	Size	Field	Notes
0	1	DTC echo	0x87
1	1	Sub-status / vendor flag	0x08
2–5	4	Data length (BE32)	Total bytes of image data that follow
6–23	18	Payload	Scan geometry from RAM 0x400D45
The first payload byte is the channel mode byte (interpreted by the host parser at LS5000.md3:0x1009F2D0).
Critical ordering: READ DTC 0x87 must be issued immediately after SCAN returns Good, before any TUR polling. The scanner's calibration phase gives a window of hundreds of milliseconds to complete this read.
DTC 0x8C — Per-Channel Dark Current / Offset
Returns raw per-channel ASIC RAM sample buffers. Each response has a 6-byte header followed by a DMA dump.
ASIC RAM bank mapping:
Qualifier	Channel	ASIC RAM Bank
0x01	R	0x800000
0x02	G	0x808000
0x03	B	0x810000
0x09	IR	0x818000
DTC 0x8E / 0x8F — Autofocus Sensor Data
DTC	Description	Qualifier Category	Max Size
0x8E	Latest focus reading	Two-mode (0 or 1)	Variable
0x8F	Full focus sweep table	Three-mode (0, 1, 3)	324 bytes
Used in the host's autofocus convergence loop: trigger focus step → wait → READ DTC 0x8E/0x8F → pick the motor position maximizing the measurement.
DTC 0x93 — Calibration Reference Constants
Returns 12 bytes of flash-resident calibration constants (design-time values intrinsic to the scanner's optical/CCD design).
Wire format: 93 00 00 00 00 06 03 F2 03 C8 02 D7 (fixed, read from flash 0x6042).
3.11 WRITE / SEND(10) (0x2A)
Sends data to the scanner — calibration data, LUTs, gamma curves, or configuration data. Data-out.
CDB: 2A 00 [DTC] 00 00 [Qualifier] [TL_MSB] [TL] [TL_LSB] 00
Note: Control byte is 0x00 (not 0x80 as in READ) — the vendor flag may only be needed for data-in transfers.
Supported DTCs for WRITE: 0x03 (gamma/LUT), 0x84 (calibration), 0x85 (extended calibration), 0x88 (boundary data), 0x8F (histogram/profile), 0x92 (motor control), 0xE0 (extended config).
3.12 SEND DIAGNOSTIC (0x1D) / RECEIVE DIAGNOSTIC (0x1C)
SEND DIAGNOSTIC: 1D 04 00 00 00 00 (SelfTest=1, no parameter data). State-dependent — appears in nearly every scan workflow phase with the same CDB but performs different operations based on internal state.
RECEIVE DIAGNOSTIC RESULTS: 1C 00 [PageCode] [AllocLen_MSB] [AllocLen_LSB] 00
Page Code	Purpose
0x05	Standard diagnostic results
0x06	Standard diagnostic page
0x38	Vendor-specific diagnostic
3.13 Vendor Commands
VENDOR 0xC0 — Status Primitive
Minimal status query. CDB: C0 00 00 00 00 00. No data phase, no parameters. Used in abort sequences. Emitted by the MAID opcode-14 abort handler.
VENDOR 0xC1 — Control Trigger
Fire-and-forget control primitive. CDB: C1 00 00 00 00 00. No data phase. Reads subcommand code from RAM @0x400D63 and dispatches to one of 23 firmware operations.
Subcommand dispatch:
Code	Group	Purpose
0x40–0x43	Scan/Cal	Execute scan operation variant
0x44	Motor	Move to position
0x45–0x47	Scan/Cal	Execute calibration variant
0x80	Control	Lamp on/off
0x81	Control	Motor initialization
0x91	Motor	Step motor (direction + count)
0xA0	Sensor	CCD/sensor setup
0xB0–0xB1	Control	State change
0xB3	Config	Write configuration
0xB4	Config	Write extended config
0xC0–0xC1	Calibration	Gain/offset calibration
0xD0–0xD2	Debug	Diagnostic operations
0xD5	Debug	Extended diagnostic
0xD6	Config	Write persistent settings
VENDOR 0xE0 — Control Write
Sends control parameters to the scanner (focus, exposure, etc.). Data-out. CDB: E0 00 [SubCmd] 00 00 [Qualifier] [TL_MSB] [TL] [TL_LSB] 00.
Sub-commands:
Code	Max Data	Purpose
0x40	11	Scan parameters
0x41	11	Calibration data
0x42	11	Gain values
0x43	11	Offset values
0x44	5	Motor position
0x45	11	Exposure time
0x46	11	Focus position
0x47	11	Lamp settings
0x80	0	Lamp on/off (trigger)
0x81	0	Motor init (trigger)
0x91	5	Motor step
0xA0	9	CCD setup
0xB0/0xB1	0	State change (trigger)
0xB3	13	Config write
0xB4	9	Extended config
0xC0/0xC1	5	Gain/offset calibration
0xD0/0xD1	0	Diagnostic (trigger)
0xD2	5	Diagnostic data
0xD5	5	Extended diagnostic
0xD6	5	Persistent settings
VENDOR 0xE1 — Sensor Read
Reads sensor data back from the scanner. Data-in. CDB: E1 00 [SubCmd] 00 00 [Qualifier] [TL_MSB] [TL] [TL_LSB] 00. Max response: 13 bytes (requesting more produces sense 0x50).
Sub-commands include: 0x40–0x47, 0x80 (lamp readback), 0x81/0x91 (adapter status), 0xA0, 0xB3, 0xC1, 0xD2, 0xD6.
The E0 → C1 → E1 Operational Cycle
These three commands form a round-trip control cycle:
1. E0 — Write control data to the scanner (set register values)
2. C1 — Trigger the operation (uses same sub-command code)
3. E1 — Read sensor data from the scanner (read results)
Both E0 and E1 use the same CDB structure with sub-command differentiation, and the same register table at FW:0x4A134. Example for focus auto-calibration:
E0 sub=0x42 → wire bytes 1..4 → obj+0x468 (focus write to scanner)
↓
C1 sub=0x42 (trigger)
↓
E1 sub=0x42 → wire bytes 1..4 → obj+0x468 (focus readback from scanner)
↓
TUR (settle)
3.14 READ BUFFER (0x3C) / WRITE BUFFER (0x3B)
READ BUFFER: Direct addressed access to scanner memory buffers. Primarily for service/diagnostic utilities — not used in normal NikonScan workflows.
Accepted modes: 0x02 (data-only) and 0x05 (alternate). Buffer IDs:
* 0x02: Flash log area at 0x00060000
* 0x03: Flash at 0x00008000
* 0x04: Flash at 0x00006010 (48 bytes)
WRITE BUFFER: Writes data to scanner buffers, including potential firmware updates (modes 0x04/0x05 — download microcode / download and save). Also not observed in normal scan workflows.

4. Sense Codes
The scanner returns sense data via the 0x06 USB protocol step. Sense data is stored at RAM 0x4007A0.
4.1 Standard Sense Codes
Index	ASC/ASCQ	Meaning	Typical Generator
0x4E	1A/00	Parameter list length error	MODE SELECT, SEND/RECV DIAG
0x4F	20/00	Invalid command operation code	Dispatch (unknown opcode)
0x50	24/00	Invalid field in CDB	All handlers (most common)
0x51	25/00	Logical unit not supported	Dispatch (LUN ≠ 0)
0x53	26/00	Invalid field in parameter list	MODE SELECT, SCAN, SET WINDOW
0x54	26/01	Parameter not supported	Shared module
0x55	26/02	Parameter value invalid	SCAN
0x56	2C/00	Command sequence error	Dispatch, READ, VENDOR C1
0x59	39/00	Saving parameters not supported	MODE SENSE (PC=3)
0x65	08/00	LU communication failure	Dispatch, READ, SEND DIAG
0x66	3E/00	LU has not self-configured yet	Dispatch
0x6F	4B/00	Data phase error	Dispatch, READ
4.2 State-Driven Sense Recipes
The firmware encodes state transitions as 4-byte recipes (b0 b1 b2 b3) mapped to sense fields:
State Code	Sense Key	ASC	ASCQ	FRU	Action
01 61 02 01	0x01	0x61	0x02	0x01	Init complete → advance to Phase B
02 05 00 00	0x02	0x05	0x00	0x00	Terminal "command applied"
02 04 02 00	0x02	0x04	0x02	0x00	Insert SEND DIAG step
02 04 03 00	0x02	0x04	0x03	0x00	Generic advance
06 28 00 01	0x06	0x28	0x00	0x01	Gated advance (FRU==1 required)
06 29 00 00	0x06	0x29	0x00	0x00	Init advance (primary 06-family)
5. Complete Scan Workflow
5.1 Initialization Sequence (Type A, Phase A)
Step  Command            CDB Bytes (hex)                        Dir   Notes
----  -----------------  --------------------------------------  ----  -------
1     TUR                00 00 00 00 00 00                       None  Scanner ready?
2     INQUIRY            12 00 00 00 24 80                       In    Get identity
3     RESERVE            16 00 00 00 00 00                       None  Exclusive access
4     MODE SELECT        15 10 00 00 14 00                       Out   Set mode page 0x03
5     SEND DIAGNOSTIC    1D 04 00 00 00 00                       None  Self-test/calibration
6     GET WINDOW         25 XX XX XX XX 00 LL LL LL 00           In    Read window params
7     READ (boundary)    28 00 88 00 00 03 LL LL LL 80           In    Read boundary data
5.2 Main Scan Setup (Type A, Phase B)
Step  Command            CDB Bytes (hex)                        Dir   Notes
----  -----------------  --------------------------------------  ----  -------
8     TUR                00 00 00 00 00 00                       None  Ready check
9     SEND DIAGNOSTIC    1D 04 00 00 00 00                       None  Pre-scan prep
10    SET WINDOW         24 00 00 00 00 00 LL LL LL 80           Out   Full scan descriptor
5.3 Scan Execution (Type B, Phase B)
Step  Command            CDB Bytes (hex)                        Dir   Notes
----  -----------------  --------------------------------------  ----  -------
11    TUR                00 00 00 00 00 00                       None  Ready check
12    WRITE (LUT)        2A 00 03 00 00 QQ 00 80 00 00           Out   Upload gamma LUT (32 KB)
13    SCAN               1B 00 00 00 01 00                       Out   Start final scan
14    TUR                00 00 00 00 00 00                       None  Poll until scan ready
15    READ (params)      28 00 87 00 00 00 00 00 18 80           In    Scan params (24 bytes)
16    READ (image)       28 00 00 00 00 QQ LL LL LL 80           In    Image data chunk
      [repeat step 16 until all lines transferred]
17    SEND DIAGNOSTIC    1D 04 00 00 00 00                       None  Post-scan cleanup
5.4 Correct Full Scan Ordering
The canonical full-scan protocol sequence with auto-exposure calibration:
1.  SET WINDOW (0x24)         — initial scan params (exposure bytes can be zero)
2.  E0/C1/E1 loop            — auto-exposure calibration
3.  SET WINDOW (0x24)         — re-send with calibrated exposure in bytes 54–57
4.  SCAN (0x1B)              — start scan pipeline (returns Good)
5.  READ DTC 0x87            — IMMEDIATELY! Parse bytes [2..5] = total_bytes
6.  Poll TUR (0x00)          — wait for data ready
7.  READ DTC 0x00 loop       — transfer exactly total_bytes
8.  SEND DIAGNOSTIC          — cleanup
Critical timing constraint: Step 5 (READ DTC 0x87) must come before step 6 (TUR polling). The E0/C1/E1 calibration loop in step 2 guarantees the pipeline enters calibration, providing hundreds of milliseconds to complete step 5 before any scan data reaches the USB endpoint.
5.5 Abort Sequence
18. VENDOR C0  [C0 00 00 00 00 00]  — signal abort to firmware
19. Poll TUR    [00 00 00 00 00 00]  — wait for Good (firmware cleanup)
20. usb_clear_halt(EP2_IN)           — clear host-side stale data
The usb_clear_halt() call is essential to flush the host-side USB buffer after an aborted scan.
5.6 Preview Scan Sequence
Step  Command            CDB Bytes (hex)                        Dir   Notes
----  -----------------  --------------------------------------  ----  -------
1     TUR                00 00 00 00 00 00                       None  Ready check
2     SCAN               1B 00 00 00 01 00                       Out   Start preview scan
3     SEND DIAGNOSTIC    1D 04 00 00 00 00                       None  Pre-scan calibration
4     SET WINDOW         24 00 00 00 00 00 LL LL LL 80           Out   Reconfigure if needed
5     GET WINDOW         25 00 00 00 00 00 LL LL LL 00           In    Verify parameters
6     READ (params)      28 00 87 00 00 00 00 00 18 80           In    Read scan params (24 B)
7     READ (image)       28 00 00 00 00 QQ LL LL LL 80           In    Transfer image data
      [repeat step 7 until all scan lines received]
8     WRITE (LUT)        2A 00 03 00 00 QQ LL LL LL 00           Out   Upload gamma LUT

6. Firmware Internals
6.1 CPU and Architecture
The scanner firmware runs on an H8/3003 (H8/300H core) microcontroller. The firmware is stored in flash (MBM29F400B).
6.2 Interrupt Vector Table
Vector	Address	Source	Purpose
0	0x000	Reset	Startup code
7	0x01C	NMI	Tight loop
8	0x020	TRAP #0	Context switch (cooperative yield)
13	0x034	IRQ1	ISP1581 USB interrupt
15	0x03C	IRQ3	Motor encoder pulses
32	0x080	IMIA2 (ITU2)	Motor mode dispatcher
36	0x090	IMIA3 (ITU3)	Timer 3 compare match
40	0x0A0	IMIA4 (ITU4)	System tick timer
45	0x0B4	DEND0B	DMA ch0B transfer end
6.3 Key I/O Ports
Port	Address	Refs	Primary Function	Confidence
Port A DR	0xD3	44	Stepper motor phase output (primary motor port)	High
Port 1 DDR	0x80	32	Data direction configuration for Port 1	High
Port 1 DR	0x82	17	Multi-purpose I/O (bus status, motor feedback)	Medium
Port 7 DR	0x8E	16	Adapter/sensor status input (read during SCAN)	High
Port 9 DR	0xC8	12	Motor encoder input + stepper phase output	High
Port 8 DR	0xC9	3	Lamp state readback	High
6.4 ASIC RAM Banks
The scanner's ASIC has multiple RAM banks for per-channel CCD data:
Address	Channel	Used By
0x800000	R (Red)	DTC 0x8C qualifier 0x01, DTC 0x00
0x808000	G (Green)	DTC 0x8C qualifier 0x02
0x810000	B (Blue)	DTC 0x8C qualifier 0x03
0x818000	IR (Infrared)	DTC 0x8C qualifier 0x09
6.5 Scanner State Byte (RAM @0x40077C)
The scanner state byte drives the TUR response and determines which commands are permitted. Permission flags (stored in the firmware dispatch table per-handler) use a 16-bit bitmask restricting command execution to certain states.

7. Cross-Model Compatibility
All four MAID modules implement the same 17 SCSI opcodes with byte-wise identical CDB builders. Verification performed by byte-level diff:
Comparison	Result
LS-40 vs LS-50 host CDB builders	All 17 opcodes byte-wise identical; minor buffer offset differences in MODE SELECT v1, no wire-format changes
LS-40 vs LS-50 firmware dispatch tables	21/21 entries identical permission and exec-mode bytes; only handler addresses differ
LS-4000/8000/9000 vs LS-40 host CDB builders	All 18 builders byte-wise identical
Conclusion: A driver written against LS-50 documentation works on all models at the SCSI level. Differences are in parameter ranges and supported capabilities (e.g., 120/220 film on LS-8000/9000), not wire format.

8. Key Design Patterns
8.1 CDB Builder Vtable System
Each SCSI command has a CDB builder function in the MAID module (LS5000.md3), constructed via a factory pattern:
1. Factory function creates a command object with direction (data-in/data-out/none) and CDB length.
2. Builder function fills CDB bytes from MAID capability parameters.
3. ExecuteCommand (FC5) hands the built CDB to the transport DLL.
8.2 State-Dependent Command Semantics
SEND DIAGNOSTIC (0x1D) exemplifies Nikon's state-driven design: the same CDB is sent at every workflow phase, but the firmware performs different operations based on internal state. The host advances through states by interpreting sense codes (the "state recipe" table) rather than explicit state commands.
8.3 Chunked Data Transfer
Image data is transferred in chunks via repeated READ DTC 0x00 commands. The host calculates transfer_length = min(chunk_size, total_bytes - bytes_read) for each iteration, stopping when bytes_read == total_bytes. The total byte count comes from READ DTC 0x87 response bytes [2..5].
8.4 Underflow Handling
When the host's allocation length exceeds the firmware's response size (common with DTC 0x87), the firmware sets sense key 0x6F and reports the residue via the SCSI DATA UNDERFLOW mechanism, then truncates the transfer.

Document compiled from the docs/kb/ knowledge base of the Nikon-Coolscan-RE repository. All factual claims are sourced from reverse-engineered host DLLs (LS5000.md3, NKDUSCAN.dll, NKDSBP2.dll), firmware decompilation (H8/3003), and live USB captures (Cynthion/Packetry). Per-field confidence levels are documented in the original repository files.
