# External Protocol Reference: kevihiiin/Nikon-Coolscan-RE Knowledge Base

**Source**: [https://github.com/kevihiiin/Nikon-Coolscan-RE](https://github.com/kevihiiin/Nikon-Coolscan-RE)
**Author**: [@kevihiiin](https://github.com/kevihiiin)
**Last analysed**: 2026-07-25
**Original commit**: `371f86b` (session 41), 214 commits total
**LS-40 verification**: Run against 5 pcapng captures (see §12). Key results inline below.

> This document captures the protocol understanding from the Nikon-Coolscan-RE project
> for cross-reference with our pcapng-verified LS-40 ED knowledge. Their primary target is
> the **LS-50 (Coolscan V ED, PID 4001)** using firmware disassembly + Windows driver RE.
> Our primary target is the **LS-40 ED (Coolscan IV ED, PID 4000)** using USB pcapng captures.
> Differences may reflect genuine LS-40 vs LS-50 hardware variation, not errors in either
> project. Where the projects disagree, our pcapng captures are the authority for LS-40.

---

## 1. Fundamental Approach Differences

| | coolscan-py (us) | Nikon-Coolscan-RE (them) |
|---|---|---|
| Target | LS-40 ED (PID 4000) | LS-50 (PID 4001) |
| Method | USB hardware captures (pcapng) | Firmware disassembly (Ghidra/radare2) + driver RE |
| Ground truth | `ls40-single-bw.pcapng` (1472 events) | LS-50 firmware binary + LS-50 USB captures (001-006 via Cynthion/Packetry) |
| SCSI dispatch | Inferred from wire + SANE backend audit | Traced from firmware handler table at FW:0x49834 |
| DTC dispatch | Inferred from wire | Traced from firmware tables at FW:0x49AD8 (READ) and FW:0x49B98 (WRITE) |
| VENDOR_E0 sub-commands | ~8 observed in captures | 23 from firmware register table at FW:0x4A134 |
| Emulator | No | Full H8/3003 emulator, 99.6% replay parity |
| Firmware knowledge | None | Full firmware binary RE: handlers, data tables, state machines |
| Driver knowledge | SANE coolscan3.c only | NKDUSCAN.dll + LS5000.md3 + NikonScan4.ds full decompilation |

**Where they agree**: USB transport protocol (0xD0 phase query, 0x06 sense), core opcodes, phase byte values, CDB padding, data chunking, sense data format -- all consistent between projects. This is strong evidence that the wire protocol is the same at the transport layer.

### 1.1 Cross-Model Protocol Compatibility

Their LS-40 firmware analysis (`binaries/firmware/PT17035.bin`, v1.20, H8/3003) and
host-side `LS4000.md3` decompilation verify that the SCSI command set is
**protocol-compatible across all Coolscan models** at the wire level:

| Side | What | Result | Source |
|---|---|---|---|
| Host | LS4000.md3 vs LS5000.md3 CDB builders | All 17 opcodes byte-identical; minor internal buffer offset differences in MODE SELECT v1, no wire-format changes | `ls-4000-protocol-deltas.md` §1-2 |
| Device | LS-40 vs LS-50 firmware dispatch tables | **21/21 entries identical `perm16` AND identical `exec`** — only handler addresses differ (different RAM layout: early-RAM block shifted by Δ ≈ -0x378) | `ls-4000-protocol-deltas.md` §3 |
| Device | Representative handler bodies (TUR, INQUIRY, MODE SELECT, READ, SET WINDOW, VENDOR\_E0, VENDOR\_C1) | Same algorithmic structure, same magic numbers, same sense codes — differ only in relocated RAM addresses | `ls-4000-protocol-deltas.md` §4 |

The LS-40 uses the `LS4000.md3` module (shared with FireWire LS-4000), NOT
`LS5000.md3`.  Despite this, the CDB bytes sent over the wire are bytewise
identical between the two host modules for every SCSI command.

**Implication for driver writers** (paraphrased from `coolscan-iv-ls40.md`):

> Use the LS-50 protocol documentation as your starting point — every SCSI
> command, every CDB layout, every sense code, every state-machine value
> documented in the LS-50 KB applies bit-for-bit to the LS-40.

**Caveat**: Vendor sub-codes for `0xE0`/`0xE1`/`0xC1` and READ DTC qualifiers
are *probably* the same across models but **not yet exhaustively verified**
at the sub-command level (per `ls-4000-protocol-deltas.md` §7).  The 23-entry
VENDOR\_E0 table in §5 is from LS-50 firmware; most sub-commands likely work on
LS-40, but only sub-codes `0xA0`, `0xB4`, `0xD0` (E0) and `0x91`, `0xC1` (E1)
have been confirmed on LS-40 wire captures.

The **dispatcher gate algorithm** (state-bin → perm16 bit lookup, sense codes,
eject/uninit pre-gate) is byte-identical on LS-40 firmware.  TUR state byte at
`@0x40077C` (LS-50) has a relocated equivalent in LS-40's RAM map.

**INQUIRY response** identifies the model: `"Nikon LS-40 ED 1.XX"` vs LS-50's
`"Nikon LS-50 ED"`.  Drivers should match on the first 12 bytes (`"Nikon LS-`)
and branch on the next 5 bytes if model-specific behavior is needed.

**Model differences** that do not affect wire protocol:
- LS-40: 2,900 DPI optical, 12-bit per channel, single-pass, basic ICE only
- LS-50: 4,000 DPI optical, 16-bit per channel, multi-sample, full ROC/GEM/Fine ICE
- Module: LS4000.md3 (824KB, MAID v1 MD3.01) vs LS5000.md3 (1028KB, MAID v5 MD3.50)
- LS-8000/9000: host-side builders verified byte-identical; device-side blocked on missing firmware dumps

---

## 2. USB Transport Layer

Both projects agree on the USB transport:

| Detail | Both Agree |
|---|---|
| VID/PID | 0x04B0 / varies by model (LS-40: 4000, LS-50: 4001, LS-5000: 4002) |
| Device class | 0xFF/0xFF/0xFF (vendor-specific) -- NOT USB Mass Storage |
| Endpoints | EP1 OUT (0x01) Bulk, EP2 IN (0x82) Bulk |
| CDB padding | Sent as 32 bytes on bulk-out, zero-padded |
| Command sequence | CDB → 0xD0 phase query → phase byte → data transfer (if needed) → 0x06 sense |
| Phase byte 0x01 | No data transfer, skip to sense |
| Phase byte 0x02 | Data-out (host → scanner) |
| Phase byte 0x03 | Data-in (scanner → host) |
| Sense data | 18 bytes, fixed format |
| Control byte | 0x80 = Nikon vendor flag, 0x00 = standard |

**Their additional detail** (from NKDUSCAN.dll decompilation):
- CDB direction field in host parameter struct: 1=data-in, 2=data-out, other=no-data
- 64-byte CDBs use `DeviceIoControl(IOCTL_SEND_USB_REQUEST = 0x80002008)` instead of bulk pipe I/O
- Data chunking: first read attempts full transfer_length; if fewer bytes received, use actual as new chunk size
- `ReadFile()` may return in chunks; NKDUSCAN retry-loops at `0x10002c46`

---

## 3. Opcode Inventory — Side-by-Side

### Standard / Scanner SCSI Commands

| Opcode | Name | Their KB | Our Code | Agreement? |
|---|---|---|---|---|
| `0x00` | TEST UNIT READY | Verified (FW:0x0215C2) | Verified (pcapng) | **Yes** |
| `0x03` | REQUEST SENSE | — | Not used (0x06 instead) | — |
| `0x06` | (Sense request byte, not CDB) | Same | Same | **Yes** |
| `0x12` | INQUIRY | Verified (FW:0x023544, std + VPD pages) | Verified (pcapng) | **Yes** |
| `0x15` | MODE SELECT | Verified (FW:0x02194A, page 0x03, 20B payload) | Verified (pcapng) | **Yes** |
| `0x16` | RESERVE UNIT | Verified (FW handler) | Verified (pcapng) | **Yes** |
| `0x17` | RELEASE UNIT | They note: "never sent by NikonScan" | Used in our teardown | **Investigate** |
| `0x1a` | MODE SENSE | Verified | Partial (pcapng) | Consistent |
| `0x1b` | SCAN / START STOP | Verified (FW:0x0220B8, op codes 1-4) | Verified (pcapng) | **Yes** |
| `0x1c` | RECEIVE DIAGNOSTIC | Limited | Limited | Consistent |
| `0x1d` | SEND DIAGNOSTIC | Verified (FW handler, state-dependent) | Mostly not used | **Gap** |
| `0x24` | SET WINDOW | Verified (FW:0x026E38, 10B CDB + WDB) | Verified (pcapng) | **Yes** (see §6 for WDB comparison) |
| `0x25` | GET WINDOW / READ CAPACITY | Verified (FW:0x0272F6, SI=0/1) | Verified (pcapng) | **Yes** |
| `0x28` | READ(10) | Verified (FW:0x023F10, 15 DTCs) | Verified (pcapng, 6 DTCs) | **Yes**, see §4 |
| `0x2a` | WRITE(10) | Verified (FW:0x025506, 7 DTCs) | Verified (pcapng, 4 DTCs) | **Yes**, see §4 |
| `0x31` | OBJECT POSITION | Not in their KB | Used (SANE `object_feed` equiv) | **LS-40 specific?** |
| `0x3c` | READ BUFFER | Verified (FW handler, log records) | Not used | **Their discovery** |
| `0x3d` | WRITE BUFFER | Documented | Not used | **Their discovery** |
| `0xc0` | VENDOR_C0 (abort) | Verified (FW:0x028AB4, cooperative flag) | Used (CANCEL_SCAN) | **Yes** |
| `0xc1` | VENDOR_C1 (execute) | Verified (FW:0x028B08, dispatches to motor/cal) | Used (EXECUTE) | **Yes** |
| `0xd0` | (Phase query byte, not CDB) | Same | Same | **Yes** |
| `0xe0` | VENDOR_E0 (control write) | Verified (FW:0x028E16, 23 sub-cmds) | Used (~8 sub-cmds) | **Yes**, see §5 |
| `0xe1` | VENDOR_E1 (sensor read) | Verified (FW:0x0295EA, 23 sub-cmds) | Used (~2 sub-cmds) | **Yes**, see §7 |

### Their Additional Opcodes (not in our codebase)

| Opcode | Name | Their Source | Notes |
|---|---|---|---|
| `0x3c` | READ BUFFER | FW:0x023544 dispatch | Reads firmware log records; verified High confidence (session 41) |
| `0x3d` | WRITE BUFFER | FW dispatch | Write to scanner buffers |
| `0x1c` | RECEIVE DIAGNOSTIC RESULTS | FW dispatch | Limited implementation |
| `0x1d` | SEND DIAGNOSTIC | FW: dispatch, self-test/cal trigger | NikonScan sends with byte\[1\]=0x04; firmware action depends on scanner state |

---

## 4. READ / WRITE Data Type Code (DTC) Dispatch Tables

### READ DTCs (opcode 0x28, FW:0x023F10, dispatch table at FW:0x49AD8)

Their full list of 15 DTCs (12-byte entries, 0xFF terminated):

| DTC | Name | Max Size | Qualifier | Confidence | In Our Code? |
|---|---|---|---|---|---|
| `0x00` | Image Data | Variable | 0=8-bit, 1=16-bit | Verified | **Yes** |
| `0x03` | Gamma Function / LUT | 32768 | Per CDB\[5\] | Verified | **Yes** |
| `0x81` | Scan Area / Film Frame Info | 8 | Single value | High | No |
| `0x84` | Calibration Data | 6 | Single value | Verified | No |
| `0x87` | Scan Parameters / Status | 24 | None (ignored) | Verified | **Yes** |
| `0x88` | Boundary / Per-Channel Cal | 644 | 0-3 (R/G/B/all) | Verified | No (but see note) |
| `0x8A` | Exposure / Gain Parameters | 14 | 0-3 (R/G/B/all) | High | No |
| `0x8C` | Offset / Dark Current | 10 | 0-3 (R/G/B/all), 0x09 (IR) | High | **Yes** (channel state) |
| `0x8D` | Extended Scan Line Data | Variable | 0/1/3 (modes) | High | No |
| `0x8E` | Focus / Measurement Data | Variable | 0 or 1 | High | **Yes** (exposure cal) |
| `0x8F` | Histogram / Profile | 324 | 0/1/3 (R/G/B) | High | **Yes** (control frame read) |
| `0x90` | CCD Characterization | 54 | 0-3 (R/G/B/all) | High | No |
| `0x92` | Motor / Positioning Status | 10 | 0-3 (sub-type) | High | **Yes** (WDB readback) |
| `0x93` | Calibration Reference Triplet | 12 | Single value (must=1) | High | **NEW — not in our code** |
| `0xE0` | Extended Configuration | 1030 | 0/1/3 (modes) | High | No |

Qualifier category byte from DTC table:
- `0x00` — qualifier ignored
- `0x01` — must match the table's qualifier value exactly
- `0x03` — 0=composite/all, 1=R, 2=G, 3=B (channel select)
- `0x10` — 0 or 1 (two-mode select)
- `0x30` — 0, 1, or 3 (three-mode select, skips 2)

**DTC 0x88 note**: They report DTC 0x88 appears in 0 out of 2058 READ exchanges across all 6 real LS-50 captures. The only factory that emits it (Type D PhaseB) is gated behind MAID cap 0x4129 ("Start Scan") which NikonScan never reaches in the current HIL setup. This suggests DTC 0x88 may exist but is rarely/never used in practice on LS-50.

**DTC 0x93 note** (NEW): Returns a fixed 12-byte response: 6-byte header + 6-byte payload from firmware flash at 0x6042. The payload is three 16-bit big-endian values: `0x03F2` (1010), `0x03C8` (968), `0x02D7` (727) — interpreted as R/G/B calibration-reference levels. The host reads this at each cal-pass boundary during full scans. Appears in LS-50 captures 003/004/005 but NOT in preview (002). The firmware handler at FW:0x024FC4 has a scan-state gate (`@0x40077C & 0xFF == 1` = scan active).

**DTC 0x8C qualifier → ASIC RAM bank mapping** (from `read-dtc-8c.md` firmware RE):

| CDB qual | Channel | ASIC Bank | Handler source address |
|---|---|---|---|
| `0x00` | G (composite) | `0x808000` | `*(0x40107C) + *(0x40108C)` |
| `0x01` | R | `0x800000` | `*(0x401078) + *(0x401088)` |
| `0x02` | G | `0x808000` | `*(0x40107C) + *(0x40108C)` |
| `0x03` | B | `0x810000` | `*(0x401080) + *(0x401090)` |
| `0x04` | R (special) | `0x800000` | `*(0x401078) + *(0x401088)` |
| `0x09` | IR | `0x818000` | `*(0x401084) + *(0x401094)` |

**Note**: The firmware response builder at FW:0x025060 DMAs from the **ASIC bank
base** address, not from the handler's computed per-channel pointer (which is
stored but possibly unused — this is an open question in their KB).  On LS-50,
NikonScan reads DTC 0x8C with large transfer lengths (hundreds of bytes per
channel); on LS-40, only 10-byte reads have been observed.  The source also
notes an unresolved "2688-byte mystery" where NikonScan sends a length that
violates the firmware's `(len-6)%4==0` alignment rule.  **This DTC's behavior
differs between LS-40 and LS-50 at the sub-handler level.**

### WRITE DTCs (opcode 0x2A, FW:0x025506, dispatch table at FW:0x49B98)

Their full list of 7 DTCs (10-byte entries, 0xFF terminated):

| DTC | Name | Max Size | Qualifier | Confidence | In Our Code? |
|---|---|---|---|---|---|
| `0x03` | Gamma Function / LUT | 32768 | Per CDB\[5\] (LUT select) | Verified | **Yes** |
| `0x84` | Calibration Data Upload | 6 | Single value | Verified | No |
| `0x85` | Extended Calibration | Variable | Single value | High | No (WRITE-only, no READ counterpart) |
| `0x88` | Boundary / Per-Channel Cal | 644 | 0-3 (R/G/B/all) | Verified | No |
| `0x8F` | Histogram / Profile | 324 | 0/1/3 (R/G/B) | High | **Yes** (control frame write) |
| `0x92` | Motor / Positioning Control | 4 | 0-3 (sub-type) | High | **Yes** (border position) |
| `0xE0` | Extended Configuration | 1024 | 0/1/3 (modes) | High (handler undecoded) | **Yes** (internal data) |

**Key difference from READ**: WRITE has only 7 DTCs vs READ's 15. Image data (0x00) is never written. DTC 0x85 is WRITE-only with no READ counterpart. DTCs 0x81/0x87/0x8A/0x8C/0x8D/0x8E/0x90/0x93 are READ-only.

**DTC 0x92 divergence**: They document DTC 0x92 WRITE as "motor/positioning control" with a 4-byte payload (motor selector, operation mode, direction/flags, step count). We use WRITE DTC 0x92 as BORDER_POSITION (4 bytes for prescan boundary offset). The firmware handler at FW:0x25908 validates transfer size == 4, qualifier range, and writes to `0x400790` (motor_state). **This likely IS the same DTC** — the LS-40 prescan boundary offset may be mapped to the same DTC, just with different payload semantics across models. **Verify with pcapng** — does our LS-40 WRITE DTC 0x92 payload match the motor control format described below?

Firmware motor control payload format (from their FW:0x25908 decompile):
```
Byte 0: Motor selector (0x01=scan motor, 0x02=focus motor)
Byte 1: Operation mode (step count multiplier)
Byte 2: Direction/flags (bit 0=direction, bits 4-7=speed profile)
Byte 3: Step count parameter
```

**DTC 0x8F divergence**: They document WRITE DTC 0x8F as "histogram/profile" with max 324 bytes. We use it as CONTROL_FRAME with 52-byte payload. The same DTC but different payload semantics across models.

---

## 5. VENDOR_E0 Sub-Command Register Table (23 entries from FW:0x4A134)

Firmware register table format: `[reg_id:8, max_data_len:8]` at FW:0x4A134.

| Sub-cmd | Max Data Len | Their Purpose | In Our Code? | Notes |
|---|---|---|---|---|
| `0x40` | 11 | Scan parameters | No | |
| `0x41` | 11 | Calibration data | No | |
| `0x42` | 11 | Gain values | No | Host-side parser consumes this (stored at obj+0x468) |
| `0x43` | 11 | Offset values | No | |
| `0x44` | 5 | Motor position | Implied (via e0/c1) | Our `auto_focus()` and `focus_setup()` may use this |
| `0x45` | 11 | Exposure time | Implied (via e0/c1) | Key to auto-exposure calibration loop |
| `0x46` | 11 | Focus position | Implied | |
| `0x47` | 11 | Lamp settings | No | |
| `0x80` | **0** | Lamp on/off (trigger only) | **Yes** (our `reset_scanner()`) | We send 13-byte data; they say 0 bytes |
| `0x81` | **0** | Motor init (trigger only) | No | |
| `0x91` | 5 | Motor step (direction + count) | **Yes** (our `load_medium()` / `eject_medium()`) | Our `e1/91` always returned `000000000100000000` |
| `0xA0` | 9 | CCD setup / load preheat | **Yes** (our `auto_focus()`) | LS-50 captures show 9-byte payload with motor target + session counter |
| `0xB0` | **0** | State change (trigger only) | **Yes** (our `calibrate()`) | We send 9-byte payload; they say 0 bytes |
| `0xB1` | **0** | State change (trigger only) | No | |
| `0xB3` | 13 | Config write | No | |
| `0xB4` | 9 | Extended config | **Yes** (our ICE/densitometry/reset params) | Firmware validates: scanner state + param range [60,3600] |
| `0xC0` | 5 | Gain calibration | Implied | Host-side parser consumes this (stored at obj+0x460) |
| `0xC1` | 5 | Offset calibration | **Yes** (our `frame_select()`) | |
| `0xD0` | **0** (table) / 9 (wire) | Diagnostic / **eject motor** | **Yes** (our `eject_medium()`) | **Conflict**: table says 0-byte trigger, but LS-50 capture 006 shows 9-byte payload |
| `0xD1` | **0** | Diagnostic (trigger only) | No | |
| `0xD2` | 5 | Diagnostic data | No | |
| `0xD5` | 5 | Extended diagnostic | No | |
| `0xD6` | 5 | Persistent settings | No | |

**Key observations**:
- Sub-cmds marked with max_data_len=0 are "trigger only" in the firmware table, but real LS-50 captures show NikonScan sometimes sends data anyway (e.g., 0xD0 with 9 bytes). The firmware may silently accept and discard the extra data.
- Our code sends 13-byte data for 0x80, 9-byte data for 0xB0 — both listed as "trigger only" in their table. This may be LS-40 vs LS-50 difference or our code may be over-sending.

**The E0 → C1 → E1 cycle** (their description):
1. **E0** = write control data TO scanner (sets register values)
2. **C1** = commit/trigger the operation (firmware reads sub-command from `@0x400D63`, set by E0)
3. **E1** = read sensor data FROM scanner (reads results)

This cycle is used for: autofocus, auto-exposure, motor positioning, gain/offset calibration.

---

## 6. SET WINDOW Descriptor (WDB) Layout

Their WDB layout is traced from `LS5000.md3:0x100B2B30` (host-side SET WINDOW builder function, 1268 bytes). Their host-side builder constructs a **variable-length** descriptor based on scanner-reported vendor extensions. The firmware accepts up to 0x42 (66 bytes) total.

### Their Standard Fields (offsets within the descriptor, after 8-byte header)

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | Window ID | |
| 1 | 1 | Reserved | |
| 2-3 | 2 | X Resolution (DPI, BE) | |
| 4-5 | 2 | Y Resolution (DPI, BE) | |
| 6-9 | 4 | Upper Left X (BE) | |
| 10-13 | 4 | Upper Left Y (BE) | |
| 14-17 | 4 | Width (BE) | |
| 18-21 | 4 | Height (BE) | |
| 22 | 1 | Brightness | Default 128 (0x80) |
| 23 | 1 | Threshold | |
| 24 | 1 | Contrast | |
| 25 | 1 | Image Composition | 0=BW, 2=grayscale, 5=RGB |
| 26 | 1 | Bits Per Pixel | 8, 14, 16 |
| 27 | 1 | Halftone Pattern | |
| 28-33 | 6 | Padding / Reserved | |
| 34 | 1 | Color/Composition Composite | `(param_0x128 << 4) \| (param_0x127 & 0xF)` |
| 35 | 1 | Scan Flags (bitfield) | See below |
| 36 | 1 | Multi-Sample Count | From scan type code (see encoding table) |
| 37 | 1 | Compression Type | |
| 38 | 1 | Compression Argument | |
| 39 | 1 | Reserved | |
| 40-43 | 4 | Vendor ext 0x102 | **Per-channel exposure time** (4 bytes, big-endian) |
| 44+ | var | Additional vendor extensions | Dynamic, see below |

### Byte 35 — Scan Flags Bitfield

| Bit | MAID Param | Meaning |
|---|---|---|
| 0 | 0x129 | Padding type |
| 1 | 0x131 | Bit ordering (0=MSB, 1=LSB) |
| 2-4 | — | Reserved |
| 5 | 0x12a | RIF (Reverse Image Format) |
| 6 | 0x12b | Auto background detection |
| 7 | 0x12c | Reserved flag |

### Byte 36 — Multi-Sample Count Encoding

| Scan Type (param_4) | Multi-Sample | Byte Value |
|---|---|---|
| 0x20 | 1× (single) | 0x01 |
| 0x21 | 2× | 0x02 |
| 0x22 | 4× | 0x04 |
| 0x31 | 8× | 0x08 |
| 0x23 | 16× | 0x10 |
| 0x24 | 32× | 0x20 |
| 0x25 | 64× | 0x40 |

### Vendor Extension Parameters (dynamic, self-describing)

12 vendor extension param IDs (0x102-0x10d), registered conditionally based on feature flags from GET WINDOW response. Only **0x102 (per-channel exposure time, 4 bytes)** is Verified end-to-end.

| Param ID | Group | Feature Flag | Data Size | Confidence | Notes |
|---|---|---|---|---|---|
| 0x102 | 1 | flags_1 bit 2 | 4 bytes (BE) | **Verified** | Per-channel CCD integration time, stored at RAM 0x400FAE |
| 0x103 | 1 | flags_1 bit 3 | dynamic (1/2/4) | **Low** | Unverified |
| 0x104 | 1 | flags_1 bit 4 | dynamic | **Low** | Unverified |
| 0x105 | 1 | flags_1 bit 5 | dynamic | **Low** | Unverified |
| 0x106 | 1 | flags_1 bit 6 | dynamic | **Low** | Unverified |
| 0x107 | 2 | flags_2 bit 0 | dynamic | **Low** | Unverified |
| 0x108 | 2 | flags_2 bit 1 | dynamic | **Low** | Unverified |
| 0x109 | 2 | flags_2 bit 2 | dynamic | **Low** | Unverified |
| 0x10a | 2 | flags_2 bit 3 | dynamic | **Low** | Unverified |
| 0x10b | 2 | flags_2 bit 4 | dynamic | **Low** | Unverified |
| 0x10c | 2 | flags_2 bit 5 | dynamic | **Low** | Unverified |
| 0x10d | 2 | flags_2 bit 6 | dynamic | **Medium** | Triggers reading of 0xf02 or 0xf03 |

The data size for each vendor extension (1, 2, or 4 bytes) is determined **by the scanner**, not the host. The host discovers this during init via GET WINDOW.

### Comparison with Our 58-Byte WDB

Our 58-byte hardcoded WDB format from pcapng captures matches the first 40 bytes of their standard layout, plus the 4-byte vendor ext 0x102, plus 14 more bytes that likely correspond to additional vendor extensions. The key structural difference is:
- **Theirs**: Variable-length, self-describing via GET WINDOW discovery
- **Ours**: Fixed 58-byte tables (`_SCAN_WINDOW_WDB_TABLES`) from pcapng

---

## 7. VENDOR_E1 Host-Side Response Parser

Their KB decodes `FUN_100AEB80` at `LS5000.md3:0x100AEB80` (108 bytes), the single function that interprets 9-byte E1 data-in payloads.

**Critical finding**: NikonScan's host-side parser only processes **two** sub-commands:
- **Sub=0x42 (focus)**: packs `buf[1..4]` into 32-bit value, stores at `scan_op + 0x468`
- **Sub=0xC0 (gain/exposure)**: packs `buf[1..4]` into 32-bit value, stores at `scan_op + 0x460`
- **All other sub-commands** (0x44, 0x45, 0x46, 0x47, 0x80, 0x81, 0x91, 0xA0, 0xB0, etc.): data is **IGNORED** — received transiently but never read

This explains our observation that `e1/91` always returns `000000000100000000` — the host never reads the bytes anyway. The E1→E0→C1 round-trip for 0x42/0xC0 is used for the **auto-exposure / auto-focus convergence loop** (read current value → write adjusted value → trigger).

### Response-Length Policy (from FW:0x029668)

The firmware has a hard cap of **13 bytes** for E1 responses. The actual length sent is `min(host_requested, 13)`. If host requests >13 bytes, firmware returns sense 0x50. Each sub-command fills specific bytes of the 13-byte buffer; unwritten positions are zero.

---

## 8. Scan Flow State Machine (LS-50 Firmware Perspective)

### Full-Scan Pipeline Stages (task codes)

From their firmware RE of the 20KB scan state machine region (0x40000-0x45300):

```
SCAN Good → INIT (0x0110-0x0121) → MOTOR (0x0300) → FOCUS (0x0400)
         → CALIBRATION (0x0501) → EXPOSURE (0x0930-0x0940) → SCAN EXEC (0x08xx)
                                                                    ↓
                                                              First scan line → Buffer RAM
                                                                    ↓
                                                              push_to_usb → EP2 FIFO
```

### Scan Task Codes by Operation

| Condition | Task Group | Task Codes |
|---|---|---|
| Preview / low-res | Group 2 | 0x0800-0x0820 |
| 8-bit, no ICE | Group 3 | 0x0830-0x0834 |
| 8-bit, with ICE | Group 4 | 0x0840-0x0844 |
| 14-bit, no ICE | Group 5 | 0x0850-0x0854 |
| 14-bit, with ICE | Group 6 | 0x0860-0x0864 |
| Multi-pass, no ICE | Group 7 | 0x0870-0x0874 |
| Multi-pass, with ICE | Group 8 | 0x0880-0x0884 |
| Extended multi-sample A-C | Groups 9-B | 0x0891-0x08B4 |

The low nibble (0-4) selects the adapter variant.

### Calibration Trigger Conditions

Their firmware RE shows the scan orchestrator F2 at FW:0x40660 decides whether to calibrate:

| Condition | Triggers Recalibration? | Why |
|---|---|---|
| E0/C1/E1 exposure loop ran | **Always** | Updates 0x400FAE, firmware detects parameter change |
| Resolution changed | Yes | Different CCD binning mode |
| Bit depth changed | Yes | Different analog gain/offset config |
| Scan area changed | Sometimes | Only if crosses CCD readout boundary |
| Same params, repeat scan | **No** — calibration skipped | Firmware reuses cached calibration data |
| First scan of session | Yes | No cached calibration exists |

### Data Buffer Pipeline (3-stage)

```
CCD Sensor (tri-linear R/G/B + IR)
    ↓  ASIC internal DMA (triggered per line: write 0x02 to 0x200001)
    ↓  Poll 0x200002 bit 3 for completion
ASIC RAM (224KB @ 0x800000-0x837FFF)
    ↓  16 DMA banks: 4×32KB + 12×8KB
    ↓  CPU pixel extraction at FW:0x36C90
Buffer RAM (64KB @ 0xC00000-0xC0FFFF)
    ↓  Ping-pong: Bank A (0xC00000, 32KB) + Bank B (0xC08000, 32KB)
    ↓  ITU4 system tick (FW:0x10A8C) polls buffer_status==3
ISP1581 USB Controller (0x600000)
    ↓  DMA direction 0x8000 = host-read, mode 5 = bulk
USB Bulk-In (EP2) → Host
```

Buffer status variable at `0x4052EE`: 0=empty, 1=initializing, 3=full/ready, 6=DMA active, 7=scan complete.

### Stall Behavior

When host stops reading: buffer fills → EP2 FIFO fills → `buffer_status` stays at 3 → no new CCD DMA triggered → task code transitions to **0x0330** ("scan buffer stall") → motor pauses (single-step cooperative model, ITU2 stops naturally). When host resumes: USB drains → `buffer_status` clears → scan resumes from paused position. No data loss occurs.

---

## 9. Key Protocol Mechanics (Driver-Critical Details)

### 9.1 DTC 0x87 Timing Criticality

**This is the most impactful finding for driver correctness.**

After SCAN returns Good, the firmware's `push_to_usb` function (FW:0x10B3E) runs autonomously on the ITU4 system tick. Once the scan pipeline produces its first complete scan line into Buffer RAM, the system tick pushes that data to EP2's FIFO — **without waiting for a READ DTC 0x00 CDB from the host**.

Once scan data is in EP2's FIFO, all subsequent bulk-in reads return that data instead of command responses (D0 phase bytes, sense data, or DTC responses).

Their analysis of approaches and failures:

| Approach | Failure Mechanism |
|---|---|
| DTC 0x87 after TUR OK | TUR OK means scanner exited active scan state → READ permission 0x0054 rejects → sense 0x66 |
| DTC 0x87 after no calibration | Pipeline goes straight to SCAN EXEC (0x08xx) → data in EP2 FIFO before host completes READ 0x87 |
| Read until timeout | No end-of-data signal on USB; firmware just stops producing, last read hangs |
| GET WINDOW instead | Wrong data, unreliable permissions at high DPI |

**The solution**: Run the E0/C1/E1 auto-exposure calibration loop before SCAN. This forces the firmware to recalibrate during SCAN, creating a guaranteed window of 500ms+ where:
- Scanner is in active scan state (permission 0x0054 passes for READ DTC 0x87)
- Pipeline is in CALIBRATION phase (no scan data has reached EP2)
- DTC 0x87 buffer at 0x400D45 is already populated from SET WINDOW processing

**Correct sequence**:
```
1. SET WINDOW — initial scan params (exposure bytes can be zero)
2. E0/C1/E1 loop — auto-exposure calibration (FORCES recalibration window)
3. SET WINDOW — re-send with calibrated exposure in bytes 54-57
4. SCAN — start scan pipeline (returns Good)
5. READ DTC 0x87 — IMMEDIATELY! Parse bytes [2..5] = total_bytes
6. Poll TUR — wait for data ready
7. READ DTC 0x00 loop — transfer exactly total_bytes
8. SEND DIAGNOSTIC — cleanup
```

Step 5 MUST come before step 6. This is **not a hack — it is the correct protocol**.

### 9.2 DTC 0x87 Response Layout (24 bytes)

| Offset | Size | Field |
|---|---|---|
| 0-1 | 2 | Status/flags |
| **2-5** | **4** | **Total image byte count (BE32)** |
| 6 | 1 | Channel count/mode (1=mono, 2=dual, 6=RGB, 7=RGBI) |
| 7-18 | 12 | Per-channel line geometry (bytes_per_line, line_count) |
| 19-23 | 5 | Additional params |

The total image byte count is the key field. The host uses this to read
exactly the right number of bytes, avoiding buffer corruption from
over-reading.

The DTC 0x87 sub-handler at FW:0x244D2 is a direct RAM copy from
``0x400D45`` — it is the **only** DTC whose handler does not compose its
response dynamically.  The firmware populates this buffer during SET
WINDOW processing and scan initialization, and the values reflect the
actual scan geometry after any CCD alignment rounding.

### 9.3 MODE SELECT Page Layout (20 bytes)

From their host-side CDB builder:

| Offset | Size | Field |
|---|---|---|
| 0-3 | 4 | Mode parameter header |
| 4-5 | 2 | Page code (0x03) + page length (6) |
| 6-7 | 2 | Base resolution (big-endian) |
| 8-9 | 2 | Max X dimension (big-endian) |
| 10-11 | 2 | Max Y dimension (big-endian) |
| 12-19 | 8 | Reserved/padding |

### 9.4 SCAN Command Details

The SCAN handler at FW:0x0220B8 uses operation code in the data-out payload:
- Operation 0 = Preview scan
- Operation 1 = (not detailed)
- Operation 4 = Full-scan / move to position

Data-out payload: window ID list. For full scan with IR+RGB: `09 01 02 03`. For RGB-only: `01 02 03`. For preview: single byte typically `0x00`.

### 9.5 VENDOR_C0 Abort Mechanism

Cooperative flag mechanism (not immediate kill):

1. Host sends `C0 00 00 00 00 00`
2. Firmware handler at FW:0x028AB4 checks bit 6 of `@0x400776` (operation active)
3. If active, sets bit 7 (abort requested) and clears transfer count
4. Inner scan loop at FW:0x40252 periodically checks bit 7 → exits cleanly
5. Recovery task 0x0F10 runs cleanup
6. Host polls TUR until Good

After abort, host must call `usb_clear_halt()` on EP2 IN to clear stale data from host USB controller buffer.

---

## 10. New-To-Us Information (Previously Unknown or Unconfirmed)

### 10.1 DTC 0x93 — Calibration Reference Triplet

**Status**: Not in our codebase at all. Present in LS-50 captures 003/004/005.

- CDB: `28 00 93 00 00 01 00 00 0c 80` (qualifier must = 1, transfer_length = 12)
- Response: 12 bytes: `93 00 00 00 00 06 03 f2 03 c8 02 d7`
- Payload: Three 16-bit BE values from firmware flash 0x6042: 0x03F2 (1010), 0x03C8 (968), 0x02D7 (727)
- Interpretation: R/G/B nominal target/white-balance reference levels
- The value is a compile-time constant, never changes at runtime
- Read once per cal-pass boundary during full scans
- Firmware handler has scan-state gate: must be in active scan state

**Action**: Check our LS-40 pcapng for this DTC.

### 10.2 DTC 0x85 — Extended Calibration (WRITE-only)

**Status**: Not in our codebase. Has no READ counterpart.

Firmware dispatch at FW:0x025830. WRITE DTC 0x85 uploads extended calibration values. Unique among WRITE DTCs for having no READ counterpart — scanner accepts calibration uploads it does not expose for readback.

### 10.3 WRITE BUFFER (0x3D) / READ BUFFER (0x3C)

**Status**: Not in our codebase. Their KB notes READ BUFFER 0x3C reads firmware log records (verified in session 41 against FW:0x60000-0x7FFFF flash dump).

### 10.4 SEND DIAGNOSTIC (0x1D) State-Dependent Behavior

**Status**: We don't use this. NikonScan always sends `1D 04 00 00 00 00` (SelfTest=1), but the firmware's action depends on scanner state:
- Just initialized: Hardware self-test (lamp, motor, CCD)
- Pre-scan: Pre-scan calibration
- Post-scan: Cleanup, lamp-off
- Ejecting: Motor control for film transport

### 10.5 E0 sub=0xB4 Host-Data Validation Gate

The sub=0xB4 handler at FW:0x029510 enforces:
1. Scanner state `@0x400773` ∈ {1, 2, 4, 5} (active-scan family)
2. First 32-bit parameter ∈ [60, 3600] (consistent with µs exposure range)
3. Second 32-bit parameter ∈ {0, 1}

If any check fails → sense 0x53 ("Invalid Field in Parameter List").

### 10.6 Per-Channel Exposure Storage (RAM 0x400FAE)

Vendor extension param 0x102 values are stored per-channel at `0x400FAE + (channel_id * 4)`:
- Window 1 (Red): `0x400FAE`
- Window 2 (Green): `0x400FB2`
- Window 3 (Blue): `0x400FB6`
- Window 9 (IR): special path

Values are in hardware clock cycles (20 MHz CPU = 50 ns/cycle). Updated by E0/C1/E1 auto-exposure loop.

### 10.7 READ DTC 0x8E / 0x8F Sub-Handler Details

Their firmware RE fully decodes the 0x8E (focus/measurement) and 0x8F (histogram/profile) sub-handlers:

- **DTC 0x8E** (FW:0x24CDE): Reads focus measurement data from `0x405282`. qual=0 returns 9-byte head; qual=1 returns variable-length record sized as `step_idx*4 + 10`.
- **DTC 0x8F** (FW:0x248BC): Reads autofocus per-channel sensor measurements indexed by focus iteration count (1..40). qual=0 returns header only (6 bytes); qual=1/3 returns N×8 + 8 bytes of per-step R/G/B/IR measurements.

---

## 11. LS-50 Full-Scan Wire Trace Summary

From their capture 003 (4000 DPI, 8-bit, no ICE, ~800 SCSI exchanges):

### Phase 1 — Warm-up (~12s)
- 5× TUR idle poll
- E0 sub=0xA0 + 9B payload + C1 trigger (load + cal preheat)
- ~95× TUR busy-poll while lamp warms / film positions

### Phase 2 — Pre-scan Probes
- E1 sub=0xC1 read (9B response, state-counter sanity check)
- READ DTC 0x93 qual=1 (calibration triplet)
- READ DTC 0x8C qual=9 (IR channel motor position)

### Phase 3 — Cal-Pass Cycle (repeated per pass)
- 4× SET WINDOW (channels 09/01/02/03 for cal pass, or 01/02/03 for RGB-only passes)
- 4× WRITE DTC 0x03 (32KB cal LUT each)
- 1× SCAN (data-out: `09 01 02 03` or `01 02 03`)
- 2× READ DTC 0x87 (status snapshot: 6B busy + 33B extended)
- 4× GET WINDOW (readback)
- READ DTC 0x00 burst (chunked image data, ~261KB-262KB per chunk)
- READ DTC 0x93 (pass-boundary marker)

### Per-Pass Statistics
- Cal pass: 261,120 B chunks (with 6-byte IR header in first chunk)
- RGB-only passes: 262,144 B chunks
- Total passes: 1 cal-pass + 3 RGB passes = 4 passes
- 003 ends mid-scan at exchange #800 (no explicit eject)

### 8-bit vs 14-bit Delta (003 vs 004)
Only **3 bytes** differ per SET WINDOW:
- Byte 21: 0xC6 (8-bit no-ICE) vs 0xE2 (14-bit no-ICE)
- Bytes 56-57: CRC trailer (different seed when byte 21 changes)

### ICE Delta (003 vs 005)
- Pass count: 4 passes all with channel 09 (vs 1 cal-pass + 3 RGB-only)
- Byte 21: 0xC6 (003) → 0xF0 (005)
- SCAN payload: always `09 01 02 03` (vs cal-only IR in 003)

---

## 12. LS-40 ED Capture Verification Results

All verification was run against 5 pcapng captures:
- `ls40-single-bw.pcapng` (1472 events, single B&W scan)
- `ls40-batch.pcapng` (6863 events, 6-frame batch)
- `ls40-single-negs.pcapng` (single negative scan)
- `ls40-batch-neg.pcapng` (batch negatives)
- `ls40-batch-session.pcapng` (batch session variant)

### 12.1 DTC Coverage in LS-40 Captures

| DTC | single-bw | batch | single-negs | batch-neg | batch-sess | LS-50? |
|---|---|---|---|---|---|---|
| `0x00` (IMAGE_DATA) | 155 | 918 | 618 | 1232 | 653 | Yes |
| `0x03` (LUT write) | 10 | 63 | ? | ? | ? | Yes |
| `0x87` (STATUS) | 8 | 40 | ? | ? | ? | Yes |
| `0x8c` (CH_STATE) | 4 | 4 | ? | ? | ? | Yes |
| `0x8e` (EXPOSURE_CAL) | 4 | 3 | ? | ? | ? | Yes |
| `0x8f` (CONTROL_FRAME) | 2 | 3 | ? | ? | ? | Yes |
| `0x92` (BORDER_POS) | 1 | 0 | ? | ? | ? | **LS-40 only**? |
| `0x93` | **0** | **0** | **0** | **0** | **0** | Yes (LS-50) |
| `0x88` | **0** | **0** | — | — | — | 0 (LS-50 too) |

Key findings:
- **DTC 0x93 is LS-50 specific** — absent from all 5 LS-40 captures.
- **DTC 0x88 is absent from both LS-40 and LS-50** captures (they also reported 0/2058).
- LS-40 DTC set: `{0x00, 0x03, 0x87, 0x8c, 0x8e, 0x8f, 0x92}` — 7 DTCs total.
- LS-50 DTC set (from their RE): 15 READ + 7 WRITE DTCs defined in firmware; only `{0x00, 0x03, 0x87, 0x8c, 0x8e, 0x8f, 0x93}` observed in actual captures.

### 12.2 Opcode Inventory (all 5 LS-40 captures)

Opcode | Purpose | Present? | Notes
---|---|---|---
`0x00` | TEST UNIT READY | Yes | Heavy use (51-1048 per capture)
`0x12` | INQUIRY | Yes | 4-19 per capture, std+VPD pages
`0x15` | MODE SELECT | Yes | 1 per session (MUD=2900)
`0x16` | RESERVE UNIT | Yes | 1 per session
`0x17` | RELEASE UNIT | **No** | **Never sent by SANE/LS-40 driver — matches NikonScan behavior**
`0x1b` | START STOP / SCAN | Yes | 7-39 per capture
`0x24` | SET WINDOW | Yes | Via DATA_OUT(WDB58)
`0x25` | READ CAPACITY / GET WINDOW | Yes | 16-63 per capture
`0x28` | READ(10) | Yes | 172-1232 per capture
`0x2a` | WRITE(10) | Yes | 12-65 per capture
`0x31` | OBJECT POSITION | **No** | **Not sent by SANE/LS-40 driver — LS-50 doesn't use it either**
`0x3c` | READ BUFFER | **No** | Only in firmware, not on wire
`0xc0` | VENDOR_C0 (abort) | Yes (SHORT_OUT) | Cancel scan
`0xc1` | VENDOR_C1 (execute) | Yes (EXECUTE) | 4-13 per capture
`0xe0` | VENDOR_E0 | Yes | 4-13 per capture, sub-cmds: 0xA0, 0xB4, 0xD0
`0xe1` | VENDOR_E1 | Yes | 3-8 per capture, sub-cmds: 0x91, 0xC1

### 12.3 Control Byte Asymmetry — CONFIRMED

Verified in `reference/golden_single_bw.txt`:
- **Data-IN commands** (READ 0x28, INQUIRY 0x12, SET_WINDOW 0x24): control = **0x80**
- **Data-OUT / no-data commands** (WRITE 0x2A, VENDOR_E0 0xE0, MODE_SELECT 0x15): control = **0x00**
- **6-byte CDBs** (TUR 0x00, SCAN 0x1B, RESERVE 0x16): control = **0x00**

This matches their finding. The `0x80` vendor flag is used for data-in transfers only.

### 12.4 DTC 0x87 Timing — CONFIRMED (LS-40 follows same pattern)

In the LS-40 single-BW capture, DTC 0x87 is read **immediately after SCAN, before TUR polling**:

```
ts=81.453s  START_STOP (1B, num_colors=4)
ts=81.460s  READ DTC 0x87 (6B status snapshot)      ← 7ms after SCAN
ts=81.463s  READ DTC 0x87 (33B extended status)    ← 10ms after SCAN
ts=81.467s  START_STOP (1B, reissue)
ts=81.591s  TUR polling begins                       ← 138ms after first SCAN
```

The pattern `SCAN → DTC 0x87 → (SCAN reissue) → TUR polling → READ_IMAGE` is consistent across all scan passes in the LS-40 capture.

**Implication**: Our protocol.py already implements this correctly — the `_scan_and_retry` helper reads status blocks during the REISSUE retry loop. However, the DTC 0x87 is read on the **first** SCAN attempt (which may return BUSY/REISSUE), not only on the successful one.

### 12.5 VENDOR_E0/E1 Sub-Commands Used — LS-40 Subset

**E0 sub-commands observed (from 5 captures)**:
| Sub | Purpose | Frequency |
|---|---|---|
| `0xA0` | Autofocus / CCD setup | Every scan (1+ per capture) |
| `0xB4` | Extended config (ICE/reset) | Once per session |
| `0xD0` | Eject motor | Once per session |

**E1 sub-commands observed**:
| Sub | Purpose | Frequency |
|---|---|---|
| `0xC1` | Get focus position | Every scan (1+ per frame) |
| `0x91` | Densitometry gate | Single capture (single-bw only) |

The LS-40 uses only **3 of 23** E0 sub-commands and **2 of 23** E1 sub-commands from the firmware register table. The other 18 sub-commands exist in firmware but are unused in practice.

### 12.6 MODE SELECT Payload — VERIFIED

LS-40 MODE SELECT payload (20 bytes from golden fixture line 122):
```
00 00 00 08  00 00 00 00  00 00 00 01  03 06 00 00  0b 54 00 00
```

Key value: `0b 54` = 2900 (MUD / max DPI). Matches the SCSI-2 mode page format with 8-byte block descriptor. The SANE backend uses this correctly.

### 12.7 RELEASE UNIT (0x17) — SHOULD BE REMOVED FROM OUR CODE

Neither LS-40 nor LS-50 captures ever send RELEASE UNIT. Our protocol.py includes it in teardown. It's harmless but unnecessary — the scanner implicitly clears reservation on USB disconnect. We should consider removing it to match observed behavior.

### 12.8 OBJECT POSITION (0x31) — SHOULD BE REMOVED FROM OUR CODE

Neither LS-40 nor LS-50 captures ever send this opcode. It comes from SANE's `object_feed` abstraction layer. It is not used by either real scanner driver. We should remove it from protocol.py.

### 12.9 WRITE DTC 0x92 — LS-40 Usage (single occurrence)

In single-bw only: `2a 00 92 00 00 03 00 00 00 04 00` (4-byte payload, qualifier=3).
Not present in any batch capture. The payload semantics (motor control vs border position) cannot be resolved from the fixture alone — we'd need to decode the 4-byte data-out payload.

### 12.10 SCAN Firmware Operation Types

From `scan.md` (FW:0x0220B8, ~1800 bytes): the firmware's SCAN handler supports
6 operation types encoded in a scan descriptor at `er6[0]`:

| Code | Operation | Description |
|---|---|---|
| 0 | Preview scan | Quick low-resolution preview |
| 1 | Fine scan (single pass) | Full-resolution single exposure |
| 2 | Fine scan (multi-pass) | Multi-sample averaging scan |
| 3 | Calibration scan | CCD/LED calibration |
| 4 | Move to position | Motor positioning only (no CCD); dispatches motor task `0x0440` |
| 9 | Eject film | Film transport to eject position; dispatches motor task `0x0430` |

These are **firmware-internal task codes**, NOT fields in the wire-level SCAN
CDB.  On the wire, SCAN (0x1B) uses byte 4 for transfer length (allocating
space for the window ID list) and the data-out payload carries the window ID
list (`01 02 03` for RGB, `09 01 02 03` for IR+RGB).  The firmware determines
the operation type from the scan descriptor built during SET WINDOW processing,
not from the SCAN CDB itself.

The SCAN handler also interfaces with the motor subsystem:
- Operation 4 (move) dispatches motor task 0x0440 (relative move)
- Operation 9 (eject) dispatches motor task 0x0430 (home)
- Scan operations configure motor speed based on resolution (ramp tables at
  `FW:0x16C38`)

Scan state variables set by the handler:
- `0x400D43`: scan operation active flag
- `0x400E7A`: scan operation state
- `0x400D3C`: max operations for current adapter

### 12.11 Per-Resolution-Band Line Count Limits

The LS-40 firmware enforces a **maximum line count per SET_WINDOW that  
depends on the resolution band**.  Empirically verified via hardware testing:

| Resolution | Max line_count | Used for | Prescan |
|---|---|---|---|
| 96 DPI | ≥ 34656 (0x8760) | Whole-strip prescan | Yes |
| 290 DPI | Unknown | IR preview pass | No |
| 2900 DPI | ≤ 4332 (0x10EC) | Per-frame full-res scan | No |

At 2900 DPI, values of 7776 (2×) and 23328 (6×) are rejected with sense 5 /
ASC 0x26 ("Invalid field in parameter list").  The 96 DPI band accepts 34656
(the full strip length used by the prescan across all 5 captures).

The rejection originates inside `parse_window_descriptor` at FW:0x0279BE,
the firmware function that validates individual WDB fields.  This function's
body was **not decompiled** by their Ghidra run, so the exact validation
formula is unknown.  No constant matching 0x10EC (4332) appears in the
decompiled SET_WINDOW handler code, suggesting the limit is computed
dynamically from resolution and adapter parameters rather than hardcoded.

**Practical implication**: Full-strip scanning at 2900 DPI is not possible
on the LS-40.  Use batch mode (`--batch --frames 6`) for multi-frame
scanning — it scans frame-by-frame with effectively zero gap between
consecutive frames.

**Best available approach for full-strip output**: batch scan with
consecutive-frame positioning.  The scanner returns to READY naturally
after each frame's exact byte count — no STOP_SCAN between frames.
Set each frame's WDB ``frame_offset`` = previous offset + frame_height,
producing zero-gap output (offsets differ by ~4330–4360, within ±30 of
the nominal 4332 frame height).  The motor runs continuously across frames
and the ∼20–30 unit shift per frame is the prescan edge detection
adjustment; omit the edge-detection pass for fully-uniform spacing.

### 12.12 CONTROL_FRAME Defines Tri-Linear CCD Color Rows

The 3 entries in every CONTROL_FRAME payload define **per-color-channel
CCD line regions**, not per-frame scan areas:

- **Entry 0**: R (red) channel region — y_start, y_end, x1, x2
- **Entry 1**: G (green) channel region — offset by ∼8680 CCD lines from R
- **Entry 2**: B (blue) channel region — offset by ∼8660 CCD lines from G

The ∼8680-line offset between entries is the **physical tri-linear CCD
sensor row spacing** — each color sensor row is positioned at a different
location in the linear CCD array, so the same physical film line passes
through R, then G (8680 CCD lines later), then B (another 8660 lines
later).  The entry y_start shifts per capture because the film is loaded
at a slightly different position each time.

This means the CONTROL_FRAME does NOT define per-frame boundaries for
batch scanning — batch scans use the same 3-entry structure with entries
covering frame *pairs* (entry 0 covers frames 0-1, entry 1 covers frames
2-3, entry 2 covers frames 4-5).  Per-frame precision comes from the
WDB `frame_offset` field (bytes 18-21), which positions each frame's scan
window within the coarse region defined by its CONTROL_FRAME entry.

The x1/x2 fields remain **not fully reverse-engineered** — even their
firmware RE project labels the semantics as "not known."  Our heuristic
(`[i*0x10 << 16] | [0x06 + i*0x08]` for x1) matches all observed captures.

---

## 13. Key Discrepancies / Conflicts Between Projects

### 13.1 WRITE DTC 0x92: Motor Control vs Border Position — INCONCLUSIVE

| | Their KB | Our Code |
|---|---|---|
| DTC | 0x92 | 0x92 |
| Name | Motor / Positioning Control | BORDER_POSITION |
| Payload | 4 bytes: motor_sel, mode, direction, step_count | 4 bytes: unknown (pcapng) |
| FW handler | FW:0x25908 (motor command dispatch) | N/A |
| LS-40 occurrence | N/A | 1× in single-bw, **0× in batch** |

**Status**: The 4-byte data-out payload needs to be decoded from the pcapng to determine semantics. Only one occurrence in single-bw (not in batch captures). Low priority — this DTC is infrequently used on LS-40.

### 13.2 DTC 0x8F: Histogram vs Control Frame — CONFIRMED OUR INTERPRETATION

Our `--extract-control-frames` analyzer correctly parses the 0x8F payloads as
frame boundary data (y_start, y_end, height per entry). The "histogram" label
in their KB is for READ DTC 0x8F in autofocus context — a different lifecycle
phase. The WRITE DTC 0x8F in LS-40 captures IS control frame data (52-byte
boundary positions).

Further confirmed by the **tri-linear CCD color-row interpretation**:
the 3 entries define per-color-channel CCD line regions with ∼8680-line
offsets between R/G/B sensor rows (see §12.12).  The entries cover frame
pairs for batch scanning, with per-frame precision from WDB `frame_offset`.

### 13.3 VENDOR_E0 Payload Lengths — OPEN (their table is likely wrong for D0)

| Sub-cmd | FW table says | LS-50 capture | Our LS-40 captures | Our code |
|---|---|---|---|---|
| 0x80 | 0 (trigger) | — | Not used | 13 bytes |
| 0xA0 | 9 bytes | 9 bytes | **9 bytes** | 9 bytes |
| 0xB0 | 0 (trigger) | — | Not used | 9 bytes |
| 0xB4 | 9 bytes | — | **9 bytes** | 9 bytes |
| 0xD0 | 0 (trigger) | **9 bytes** | **9 bytes** | 9 bytes |

Both NikonScan (LS-50) and SANE (LS-40) send 9-byte payloads for sub=0xD0. Their firmware table says max_data_len=0. This is almost certainly a firmware table error — the firmware accepts the data silently.

### 13.4 RELEASE UNIT (0x17) — CONFIRMED UNNECESSARY

**Never sent in any LS-40 capture (all 5 pcapngs).** Their finding that NikonScan never sends it is confirmed on LS-40 too. Our code should remove it to match observed behavior.

The RELEASE handler **exists** in both LS-40 firmware (`FW:0x0221F2`) and LS-50 firmware (`FW:0x021EA0`) with identical `perm16` flags (`0x07FC`) and execution mode — it is part of the standard SCSI-2 reservation pair that both scanners implement at the firmware level. Neither host driver (NikonScan for LS-50, SANE coolscan3 for LS-40) ever emits it on the wire; reservation is implicitly cleared on USB disconnect. (See `ls-4000-protocol-deltas.md` §1, §3 for dispatch table verification including opcode 0x17.)

### 13.5 OBJECT POSITION (0x31) — CONFIRMED UNNECESSARY

**Never sent in any LS-40 capture (all 5 pcapngs).** Not present in their firmware dispatch tables either. This is a SANE artifact that neither real driver uses. Our code should remove it.

### 13.6 MODE SELECT Ordering — GENUINE DIFFERENCE (benign)

SANE does INQUIRY VPD pages before MODE SELECT; NikonScan does MODE SELECT earlier. Both work. Not a discrepancy to fix.

---

## 14. Verification Tasks (Prioritized)

### P1 — Verify against our pcapng ✅ DONE

1. ✅ **DTC 0x93**: NOT present in any LS-40 capture. LS-50 specific.
2. ✅ **WRITE DTC 0x92**: 1 occurrence in single-bw only. Payload semantics unresolved.
3. ✅ **DTC 0x8F**: Confirmed as control frame (not histogram) in LS-40 context.
4. ✅ **DTC 0x88**: Absent from both LS-40 and LS-50 real captures.
5. ✅ **Control byte asymmetry**: Confirmed — 0x80 for data-IN, 0x00 for data-OUT/6B CDBs.
6. ✅ **DTC 0x87 timing**: Confirmed — LS-40 reads DTC 0x87 immediately after SCAN, before TUR polling. Our protocol.py already implements this correctly.
7. ✅ **VENDOR_E0/E1 subset**: LS-40 uses only 3 E0 sub-commands (0xA0, 0xB4, 0xD0) and 2 E1 sub-commands (0x91, 0xC1) from the 23-entry table.
8. ✅ **MODE SELECT payload**: 20-byte SCSI-2 mode page with 8-byte block descriptor, MUD=2900.
9. ✅ **RELEASE (0x17) and OBJECT_POSITION (0x31)**: Never sent in any LS-40 capture. Should be removed from protocol.py.

### P2 — Protocol improvements to adopt

1. **E0/C1/E1 auto-exposure calibration loop** (future enhancement): The
   kevihiiin repo documents an auto-exposure calibration loop (E0 sub=0x45
   write → C1 trigger → E1 read → repeat until converged) that NikonScan
   runs before every SCAN.  Two benefits: (a) computes optimal per-channel
   exposure for WDB bytes 54-57, and (b) forces firmware recalibration
   creating a ~500ms safe window for DTC 0x87 reads.  Our code uses
   ``read_channel_state`` (DTC 0x8C) to read existing calibrated values
   which is sufficient for LS-40.  Implementing the full loop would improve
   exposure accuracy and provide LS-50 compatibility.

2. **``_auto_focus_command`` payload format** (fixed): Was sending ``00
   [focus_x:4B] [focus_y:4B]`` instead of the pcapng-verified format
   ``00 00 00 05 9b 00 00 [position:2B]`` (motor step target at bytes 3-4,
   position at bytes 7-8).  Scanner tolerated the wrong format.  Fixed in
   protocol.py.

3. **E0 sub=0xB4 validation gate** (documented): The LS-50 firmware at
   FW:0x029510 validates bytes 1-4 of the payload must be in [60, 3600].
   Our ``set_focus_param`` payload places the focus value at bytes 0-3,
   which would fail the LS-50 gate if it applied to LS-40.  The LS-40
   accepts the payload regardless.  Flagged as a potential LS-50
   compatibility issue.

---

## 14. References

- Their repo: [https://github.com/kevihiiin/Nikon-Coolscan-RE](https://github.com/kevihiiin/Nikon-Coolscan-RE)
- Our key docs: `docs/unified-protocol-spec.md`, `docs/commands.md`, `docs/protocol.md`
- Their key docs:
  - `docs/kb/scsi-commands/` — per-command reference (22 files)
  - `docs/kb/driver-guide/scan-data-transfer.md` — scan data protocol Q&A
  - `docs/kb/deep-dive/scsi-command-sequences.md` — complete sequence reference
  - `docs/kb/deep-dive/full-scan-wire-trace.md` — LS-50 003 full-scan annotated trace
  - `docs/kb/scsi-commands/set-window-descriptor.md` — WDB byte-level mapping
  - `docs/kb/scsi-commands/vendor-e0.md` — 23-entry sub-command table
  - `docs/kb/scsi-commands/vendor-e1.md` — host-side parser decode
  - `docs/kb/scsi-commands/read-dtc-93.md` — DTC 0x93 full decode
  - `docs/kb/architecture/usb-protocol.md` — USB transport details
  - `docs/kb/scsi-commands/scan.md` — SCAN command (6 firmware operation types)
  - `docs/kb/scsi-commands/read-dtc-8c.md` — DTC 0x8C qualifier→ASIC bank mapping
  - `docs/kb/scsi-commands/mode-sense.md` — MODE SENSE PC values + page sources
  - `docs/kb/scanners/coolscan-iv-ls40.md` — LS-40 model entry with firmware sample info
  - `docs/kb/scanners/ls-4000-protocol-deltas.md` — byte-level LS-40 vs LS-50 diff
  - `docs/kb/scanners/model-comparison.md` — all 6 scanner models cross-reference

---

## 15. Firmware Internals Quick Reference

Internal details from LS-50 firmware RE (H8/3003, `docs/kb/` source verified).
These are firmware addresses, not wire-level fields. Included for context when
interpreting scanner behavior.

### 15.1 NkDriverEntry Function Codes

| FC | Symbol | Purpose |
|---|---|---|
| 1 | Initialize | Magic-check "1200", allocate handle, build command/session managers |
| 2 | OpenSession | Open or reopen a scanner session |
| 3 | CloseCommand | Cancel and free a specific command |
| 4 | ReleaseResource | Session-side cancel callback |
| 5 | ExecuteCommand | Build a SCSI command and enqueue for execution (hot path) |
| 6 | GetCommandStatus | Retrieve stored status code for a command |
| 7 | Shutdown | Release all resources, clear thread execution state |

### 15.2 ASIC RAM Banks

| Address | Channel | Used By |
|---|---|---|
| `0x800000` | R (Red) | DTC 0x8C qual 0x01/0x04, DTC 0x00 image data |
| `0x808000` | G (Green) | DTC 0x8C qual 0x00/0x02 |
| `0x810000` | B (Blue) | DTC 0x8C qual 0x03 |
| `0x818000` | IR (Infrared) | DTC 0x8C qual 0x09 |

Source: ASIC RAM Bank Descriptor Table at `FW:0x49A94..0x49AAC`.

### 15.3 MODE SENSE Page Control Sources

| PC Value | Mode | Data Source |
|---|---|---|
| 0 | Current values | RAM `@0x400D2A` (8 bytes per page) |
| 1 | Changeable values | RAM `@0x400D32` (8 bytes) |
| 2 | Default values | Flash `FW:0x0168AF` (8 bytes): base resolution=1200 DPI, max X/Y=4000 |
| 3 | Saved values | Not supported → sense 0x0059 |

Supported pages: 0x03 (device-specific: resolution, max scan area) and 0x3F (all pages).

### 15.4 Interrupt Vector Table

| Vector | Address | Source | Purpose |
|---|---|---|---|
| 0 | 0x000 | Reset | Startup code |
| 7 | 0x01C | NMI | Tight loop |
| 8 | 0x020 | TRAP #0 | Context switch (cooperative yield) |
| 13 | 0x034 | IRQ1 | ISP1581 USB interrupt |
| 15 | 0x03C | IRQ3 | Motor encoder pulses |
| 32 | 0x080 | IMIA2 (ITU2) | Motor mode dispatcher |
| 36 | 0x090 | IMIA3 (ITU3) | Timer 3 compare match |
| 40 | 0x0A0 | IMIA4 (ITU4) | System tick timer (`push_to_usb` runs here) |
| 45 | 0x0B4 | DEND0B | DMA ch0B transfer end |

### 15.5 Key I/O Port Registers

| Port | Address | Primary Function |
|---|---|---|
| Port A DR | `0xD3` | Stepper motor phase output (primary motor port) |
| Port 1 DR | `0x82` | Multi-purpose I/O (bus status, motor feedback) |
| Port 7 DR | `0x8E` | Adapter/sensor status input (read during SCAN) |
| Port 9 DR | `0xC8` | Motor encoder input + stepper phase output |
| Port 8 DR | `0xC9` | Lamp state readback |

### 15.6 Scanner State Byte (`@0x40077C` in LS-50)

| State | Meaning | TUR Response |
|---|---|---|
| `0x00` | Idle (ready) | Good |
| `0x01` | Active scan | Checks DMA/motor sub-states |
| `0x20`–`0x2F` | Setup phase | Returns status |
| `0xF0` | Sensor error | Sense 0x0008 (Communication Failure) |
| `0xF1` | Motor error | Sense 0x0009 (Track Following Error) |
| `0xF3` | Motor busy (positioning) | Sense 0x0079 |
| `0xF4` | Calibration busy | Sense 0x007A |

LS-40 equivalent register at relocated address (Δ ≈ -0x378 from LS-50 addresses).
