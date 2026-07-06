# Capture Comparison Findings

## Executive Summary

Hardware test captures (`full_scan_single.log.txt`, `full_scan_batch.log.txt`)
were compared against Nikon Scan reference captures (`ls40-single-bw.pcapng`,
`ls40-batch.pcapng`) using `scripts/analyze_capture.py` with diff, annotation,
and phase-analysis modes.

**Bottom line:** Our protocol implementation produces working scans on hardware,
but diverges from Nikon in 12 areas. 8 ILLEGAL_REQ errors (single) and 9
(batch) indicate protocol violations. Exposure calibration reads ~45% less data
than Nikon. We poll with 3× more TUR commands. Several Nikon-specific commands
are undocumented in our codebase.

## Methodology

- Converted human-readable test logs to tab-separated fixture format (1729 /
  8083 events respectively)
- Ran `analyze_capture.py` on all four captures: summary, annotation, diff
- Extracted unique command sets, phase boundaries, and TUR counts
- Cross-referenced against `protocol.py` and `scanner.py`

## Findings Catalog

Each item lists: severity, what Nikon does, what we do, code location, and
proposed fix.  Priority 1 items are errors that may produce incorrect results.
Priority 2 are protocol misalignments. Priority 3 are inefficiencies.

### P1-1: ILLEGAL_REQ errors (8 single / 9 batch)

**Severity:** High — protocol violations

Nikon produces zero ILLEGAL_REQ (sense key 0x05, ASC 0x2c) responses.  Our
captures contain 8 (single) and 9 (batch).  These indicate we are sending
commands the scanner rejects in the current state.

**Root causes (suspected):**
- Phase ordering: we send calibration reads (exposure, channel state) in what
  Nikon considers the config phase, before the scanner expects them
- Missing 4th channel (0x09) in prescan setup
- Incorrect exposure calibration READ length

**Proposed fix:**
- [ ] Move calibration reads (exposure, channel state, control frame) from
  config phase into scan prescan, matching Nikon's sequencing
- [ ] Add channel 0x09 to prescan window setup
- [ ] Correct exposure calibration READ length (see P1-2)
- [ ] Re-run hardware test and verify ILLEGAL_REQ count drops to zero

**Code locations:** `protocol.py` — `prescan_frame()`, `full_scan_setup_frame()`,
`initialize_scanner()`

---

### P1-2: Exposure calibration READ length mismatch

**Severity:** High — incomplete calibration data

Nikon reads exposure calibration (datatype 0x8e) with length 0x0D7C (3452
bytes).  We read with length 0x0770 (1904 bytes) — about 45% of Nikon's.

**Evidence:** `golden_single_bw.txt` line with `28008e000000000d7c80` vs. our
log `28008e00000000077080`

**Proposed fix:**
- [ ] Derive exposure table length from the 6-byte header (first READ 0x8e
  returns header; byte offset encodes actual table length)
- [ ] Verify `read_exposure_data()` in `protocol.py` uses header-derived length
  rather than hardcoded value
- [ ] Confirm on hardware that the full 3452-byte read succeeds

**Code location:** `protocol.py:2963` — `read_exposure_data()`

---

### P1-3: Missing channel 0x09 in prescan

**Severity:** High — missing IR/density channel

Nikon sends SET_WINDOW for channel 0x09 (IR/density) in both prescan and full
scan phases.  Our prescan only sets up channels 1, 2, 3 (R, G, B).  The batch
capture consistently includes channel 9.

**Evidence:** Nikon prescan: `24...000000320900...` (channel 9).  Our prescan
only has channels 1, 2, 3.

**Proposed fix:**
- [ ] Add channel 9 to `prescan_frame()` window setup (after channels 1/2/3)
- [ ] Add channel 9 to `upload_identity_luts()` when `include_ir=True` in
  prescan context
- [ ] Verify WDB table exists for channel 9 in prescan resolution (96 DPI)

**Code location:** `protocol.py:3875` — prescan window loop, `_SCAN_WINDOW_WDB_TABLES`

---

### P1-4: Batch scan READ chunk size inconsistency

**Severity:** Medium — may affect image reconstruction

Nikon uses a single consistent READ size of 0x3F480 (258,368 bytes) throughout
the scan phase.  Our batch scan varies between 0x3F000, 0x36900, 0x381C0, and
0x3F480.

**Evidence:** Diff shows hundreds of mismatches between our READ commands and
Nikon's, all centered on varying length fields.

**Status:** Images look good on recent runs.  May be an artifact of how chunk
sizes are computed (e.g., remaining bytes vs. fixed allocation).  Not blocking
but should be investigated.

**Proposed fix:**
- [ ] Audit `batch_full_res_capture_frame()` and `batch_full_scan_capture_frame()`
  for chunk size computation
- [ ] Standardize on a single chunk size derived from control frame or capacity
  data, matching Nikon's 0x3F480
- [ ] Re-run batch scan and capture to confirm alignment

**Code location:** `protocol.py:2534` — batch capture frame methods

---

### P2-1: Phase ordering — calibration in wrong phase

**Severity:** Medium — protocol sequence mismatch

Nikon's config phase is minimal: MODE_SELECT + 2 INQUIRYs + 1 TUR.  All
calibration operations (focus read, exposure calibration, channel state reads,
border position write) happen in the scan prescan phase.

Our code does all of these in the config phase, before any SCAN command.  This
may explain some ILLEGAL_REQ errors — the scanner may not be in the right state
to accept these commands.

**Proposed fix:**
- [ ] Move `read_focus()`, `read_exposure_data()`, `read_control_frame()`,
  `read_channel_state()`, and `set_boundary_for_prescan()` from config/init
  phase into the scan prescan sequence
- [ ] Keep config phase minimal: MODE_SELECT, INQUIRY pages, RESERVE_UNIT,
  READ_CAPACITY
- [ ] Update `initialize_scanner()` to not perform calibration reads

**Code location:** `protocol.py:4356` — `initialize_scanner()`, `prescan_frame()`

---

### P2-2: Missing INQUIRY pages in config

**Severity:** Medium — missing capability discovery

Nikon queries INQUIRY page 0xe2 (extended capabilities) and page 0x01 (sense
code formats) in the config phase, after MODE_SELECT.  We skip these entirely.

**Evidence:** Nikon sends `1201e2000480` + `1201e2001e80` and
`120101000480` + `120101000c80` — two-step length probe + full read.

**Proposed fix:**
- [ ] Add INQUIRY page 0xe2 read to `initialize_scanner()` after MODE_SELECT
- [ ] Add INQUIRY page 0x01 read
- [ ] Parse page 0xe2 response for any scanner-specific capability flags

**Code location:** `protocol.py:4394` — INQUIRY pages loop

---

### P2-3: Autofocus payload differences

**Severity:** Medium — different parameters for same operation

Nikon's VENDOR_E0(0xb4) autofocus sequence uses different 9-byte payloads
depending on context:
- Prescan: `0000000e1000000001`
- Eject/reset: `000000025800000001`

We use `000000000c0000000a` consistently in all contexts.

**Evidence:** `golden_single_bw.txt` — line 186 shows `0000000e1000000001`
after e0/b4 in prescan; line 1441 shows `000000025800000001` after e0/b4
in eject.

**Proposed fix:**
- [ ] Parameterize the 9-byte data payload for `e0/b4` based on operation
  context (prescan autofocus vs. post-scan reset)
- [ ] Update `reset_params()` to use `000000025800000001`
- [ ] Update autofocus helpers to use `0000000e1000000001`

**Code location:** `protocol.py:3649` — `reset_params()`, `protocol.py:3511`
— `_auto_focus_command()`

---

### P2-4: Extended TUR commands

**Severity:** Medium — undocumented protocol feature

Nikon sends 10-byte TUR variants with non-zero fields in specific contexts:
- `000000025800000001` — after eject + autofocus
- `000000059b00000ac4` — during batch init (focus coordinates?)
- `0000000e1000000001` — during autofocus setup
- `000000000c0000000a` — after eject (this is the one we happen to use)

We only send the standard 6-byte `000000000000`.

**Proposed fix:**
- [ ] Document extended TUR format in `docs/protocol.md`
- [ ] Add `send_tur_with_params(data_bytes)` helper
- [ ] Use extended TURs where Nikon does (after eject, batch init)
- [ ] Verify whether standard TUR works as fallback (may be optional)

**Code location:** `protocol.py:1351` — `_test_unit_ready_once()`

---

### P2-5: VENDOR_E1 subcode 0x91

**Severity:** Low — undocumented but present in both captures

Nikon sends `e1 00 91 00 00 00 00 00 09 00` in the scan prescan phase,
between the focus read and the autofocus command.  We do send this command
but it's not documented in our subcode name tables.

**Proposed fix:**
- [ ] Add subcode 0x91 to `E1_SUBCODE_NAMES` in `analyze_capture.py`
- [ ] Document purpose in `docs/commands.md` (suspected: focus calibration
  or channel state query)
- [ ] Verify our implementation sends the correct payload

**Code location:** `scripts/analyze_capture.py:123`, `protocol.py` — VENDOR_E1 calls

---

### P3-1: Excessive TUR polling

**Severity:** Low — performance impact only

We send ~3× more TUR commands than Nikon:

| Phase | Nikon | Ours | Ratio |
|-------|-------|------|-------|
| Config | 1 | 11 | 11× |
| Scan | 39 | 128 | 3.3× |
| Eject | 4 | 12 | 3× |

On hardware, each TUR adds ~100ms latency.  Excessive polling in scan phase
adds ~13 seconds; in config adds ~1 second.

**Proposed fix:**
- [ ] Replace `poll_until_ready()` with fixed-count TUR in fixture-aligned
  paths (use `_wait_ready_or_replay_once()` pattern)
- [ ] Reduce TUR count in config phase from 11 to 1
- [ ] Reduce TUR count in eject phase from 12 to 4
- [ ] Keep `poll_until_ready()` for hardware-only paths where timing varies

**Code location:** `protocol.py:2378` — `poll_until_ready()`, `scan_teardown()`

---

### P3-2: Eject phase inefficiencies

**Severity:** Low — redundant operations

Our eject phase:
- Sends EJECT twice (duplicate `e0/d0`)
- Sends RELEASE_UNIT after eject (Nikon doesn't)
- Polls with 12 TURs (Nikon uses 4)
- Skips the post-eject SCAN setup that Nikon does

Nikon's eject: EJECT once → TUR → autofocus(e0/b4) + execute → TUR →
SCAN(1/2/3/9) → done.

**Proposed fix:**
- [ ] Remove duplicate EJECT from `scan_teardown()`
- [ ] Remove RELEASE_UNIT from eject path (it's already sent in disconnect)
- [ ] Add post-eject autofocus + SCAN setup to match Nikon
- [ ] Reduce TUR count to 4

**Code location:** `protocol.py:3721` — `scan_teardown()`

---

### P3-3: READ_CAPACITY overuse in batch

**Severity:** Low — minor performance

Nikon: 63 READ_CAPACITY calls in batch init.  We: 70 calls.  ~10% excess.

**Proposed fix:**
- [ ] Audit `initialize_scanner()` READ_CAPACITY loop — we query window 0 +
  [1,2,3,4,9] = 7 calls. Nikon queries window 0 + [1,2,3,9] = 6 calls,
  but repeats them across frames.
- [ ] Eliminate window 4 query if not used (Nikon doesn't query it)

**Code location:** `protocol.py:4440` — READ_CAPACITY loop

---

## Unknown Nikon Commands

Commands present in the Nikon captures that lack documentation or handlers in
our codebase:

| Command | Subcode | Context | Suspected Purpose |
|---------|---------|---------|-------------------|
| `e0 00 b4` | 0xb4 | After eject, prescan | Autofocus trigger / parameter reset |
| `e1 00 91` | 0x91 | Scan prescan | Focus calibration query |
| Extended TUR | — | Various | Parameterized TUR with data payload |
| Channel 0x09 SCAN | — | Prescan, full scan | IR/density channel setup |

**Proposed documentation:**
- [ ] Add all subcodes to `analyze_capture.py` lookup tables
- [ ] Document in `docs/commands.md` with capture line references
- [ ] Cross-reference with SANE `coolscan3.c` for any matching behavior

---

## Testing Plan

After each fix:

- [ ] Run `make check-all` (lint + tests)
- [ ] Run `test_hardware_full_scan.py` with USB capture logging
- [ ] Convert log to fixture format and run `analyze_capture.py --diff`
      against corresponding Nikon capture
- [ ] Verify ILLEGAL_REQ count decreases
- [ ] Verify saved image quality (visual inspection + checksum if baseline exists)

Regression verification (after all fixes):
- [ ] Capture fresh single-scan log, diff against `ls40-single-bw.pcapng`
- [ ] Capture fresh batch-scan log, diff against `ls40-batch.pcapng`
- [ ] Target: zero ILLEGAL_REQ errors, TUR count within 20% of Nikon,
  matching command sequence (allowing for timing differences)

---

## Risks

- **Phase reordering (P2-1):** Moving calibration reads from config to scan
  phase changes the initialization contract.  Any caller that expects calibration
  data to be available after `initialize_scanner()` will need updating.
- **Channel 9 prescan (P1-3):** Adding IR channel to prescan changes LUT upload
  count and may affect downstream image dimensions.
- **Exposure calibration length (P1-2):** Reading more data than expected may
  cause issues if downstream code assumes fixed-size exposure tables.
- **Autofocus payload changes (P2-3):** Different payloads may produce different
  focus behavior.  Verify with hardware test.
