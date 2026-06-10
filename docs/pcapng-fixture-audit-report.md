# PCAPNG vs Fixture Audit Report

**Date:** 2026-06-09
**Scope:** `ls40-single-bw.pcapng` (2544 USB events) vs `test_basic_scan_capture.txt` (308 events)
**Method:** Automated byte-by-byte comparison using `audit_fixture.py`

---

## Executive Summary

**The fixture is NOT a faithful extraction from the pcapng capture.** It is a hand-crafted reconstruction that was manually edited to fix known bugs (G1, G2, P0-2). The replay tests validate **fixture self-consistency**, not hardware correctness. There are **166 discrepancies in the first 200 events alone**, and the fixture covers only **12%** of the capture's events.

**Recommendation:** Replace the current replay approach with a **pcapng-derived golden fixture** generated programmatically, augmented with **property tests** for non-deterministic behavior and **periodic hardware smoke tests** for final validation.

---

## 1. Quantitative Overview

| Metric | Capture (pcapng) | Fixture (.txt) | Gap |
|--------|-----------------|----------------|-----|
| Total events | 2,544 | 308 | 2,236 missing |
| OUT commands | 1,186 | 155 | 1,031 missing |
| IN responses | 1,358 | 153 | 1,205 missing |
| TUR+PC polling cycles | 200 | 14 | 186 missing |
| PHASE_CHECK commands | 572 | 65 | 507 missing |
| READ(10) commands | 172 | 12 | 160 missing |
| SET_WINDOW commands | 18 | 6 | 12 missing |
| START_SCAN commands | 7 | 3 | 4 missing |

---

## 2. Structural Discrepancies

### 2.1 Missing initial TUR retries (Critical)

**Capture:** 4 complete TEST_UNIT_READY + PHASE_CHECK cycles before the first INQUIRY page reads. The first TUR returns BUSY status (`02 06 28 00 01 00 00 00`), then 3 retries succeed.

**Fixture:** Only 1 TUR cycle, with OK status (`00 00 00 00 00 00 00 00`).

**Impact:** The fixture elides the scanner's warm-up/busy behavior. The replay tests never exercise the TUR retry logic in `scanner_ready()`.

### 2.2 INQUIRY page sequence differs

**Capture:** INQUIRY sequence starts with `120100000480` (page 0x00, length 4), then `120100001580` (page 0x00, length 21).

**Fixture:** Starts with `120101000480` (page 0x01, length 4), then `120101000c80` (page 0x01, length 12).

**Impact:** The fixture's INQUIRY page IDs don't match the capture. The code's `initialize_scanner()` sends page 0x01, which suggests the fixture was corrected to match the *code*, not the *capture*. This confirms the fixture is a reconstruction of intended behavior, not a raw extraction.

### 2.3 Missing vendor commands (0xe0, 0xe1, 0xc1, 0x04, 0x09, 0x0f)

**Capture:** Contains VENDOR_E1 (3×), VENDOR_E0 (4×), VENDOR_C1 (4×), and unknown 0x04 (1×), 0x09 (2×), 0x0f (3×) commands between SET_WINDOW and prescan START_SCAN.

**Fixture:** Zero vendor commands. These are entirely absent.

**Impact:** The fixture skips the scanner configuration phase that includes exposure calibration, focus setup, and other vendor-specific operations. The replay tests never validate whether the code handles these commands.

### 2.4 Massive polling discrepancy

**Capture:** 200 polling cycles (TUR+PHASE_CHECK pairs) across the session. Long polling sequences of 30-60 cycles between scan phases.

**Fixture:** 14 polling cycles total. Polling is represented as 2-3 cycles per phase.

**Impact:** The fixture cannot validate that `poll_until_ready()` handles extended BUSY/PROCESSING periods correctly.

### 2.5 SENSE data fabrication

**Capture:** First TUR returns `02 06 28 00 01 00 00 00` (status=BUSY, sense_key=0x06).

**Fixture:** Same position shows `00 00 00 00 00 00 00 00` (status=OK).

**Impact:** The fixture normalizes error/busy responses to success. Replay tests never exercise error handling paths.

### 2.6 Timestamps are fabricated

**Capture:** Timestamps are real capture times (e.g., `35.733292` for first command).

**Fixture:** Timestamps from line 111 onward are round numbers (`0.343600000`, `0.343700000`, etc.), clearly fabricated.

**Impact:** No timing validation is possible against the fixture.

### 2.7 READ_CAPACITY response count

**Capture:** 16 READ_CAPACITY commands (windows 0x00, 0x01-0x04, 0x09).

**Fixture:** 5 READ_CAPACITY commands (windows 0x00, 0x01-0x03).

**Impact:** The fixture doesn't cover windows 0x04 and 0x09, which are used in the capture for additional scan area configuration.

---

## 3. What The Replay Tests Actually Validate

The 157 passing tests fall into three categories:

### Category A: CDB construction tests (~30 tests)
Tests like `test_inquiry_standard_36_bytes`, `test_read_capacity`, etc. These verify that `struct.pack()` produces the expected byte sequences. **These are unit tests, not replay tests.** They validate CDB construction, not protocol flow.

### Category B: Replay tests against fixture (~20 tests)
Tests like `test_init_sequence_matches_capture`, `test_prescan_sequence_matches_capture`, etc. These run `CoolscanProtocol` methods against the fixture and assert byte-exact match. **These validate that the code produces what the fixture expects, not what the hardware does.**

### Category C: Mocked sequence tests (~100 tests)
Tests like `test_prescan_sequence_exact_order`, `test_scan_read_integration`, etc. These mock protocol methods and verify call order. **These validate control flow, not wire format.**

**Bottom line:** No test currently validates that the code's wire output matches the actual hardware's wire input.

---

## 4. Root Cause Analysis

The fixture was created through a multi-step process:

1. **Initial extraction** from pcapng (lines 1-82 roughly match capture)
2. **Manual normalization** to skip busy retries and error responses
3. **Bug fixes** (G1: SET_WINDOW replaces MODE_SELECT; G2: REISSUE handling; P0-2: set_boundary added, later corrected to use 0x92 BORDER_POSITION for prescan and 0x8f CONTROL_FRAME for full scan, matching golden fixture — SANE's 0x88 IMAGE_POSITIONS is rejected by LS-40 ED)
4. **Synthetic extension** for phases not in the original capture slice
5. **Timestamp fabrication** for post-line-111 content

Each step moved the fixture further from the raw capture. The result is a document that represents **what the developer believes the protocol should look like**, not what the hardware actually does.

---

## 5. Recommendations

### 5.1 Immediate: Create a pcapng-derived golden fixture

**Action:** Write `scripts/generate_fixture_from_pcapng.py` that:
1. Extracts all OUT/IN events from `ls40-single-bw.pcapng` using tshark
2. Normalizes known non-determinism (TUR retry counts, timestamps)
3. Outputs a text fixture in the same format as `test_basic_scan_capture.txt`
4. Computes a checksum of the pcapng and embeds it in the fixture header

**Benefit:** The fixture becomes a deterministic, reproducible artifact derived from the ground truth.

### 5.2 Medium-term: Augment with property tests

**Action:** Add tests that verify protocol invariants, not byte-exact sequences:
- "After START_SCAN returns REISSUE, code re-issues the command"
- "poll_until_ready() returns after receiving READY status"
- "LUT upload sends 8192 bytes per channel"
- "SET_WINDOW is called for channels 1, 2, 3 before scan"

**Benefit:** Property tests are resilient to non-determinism while still catching regressions.

### 5.3 Long-term: Periodic hardware smoke tests

**Action:** Set up a weekly (or monthly) CI job that:
1. Connects to a real LS-40 ED scanner
2. Runs a basic scan
3. Captures the USB traffic
4. Diffs the capture against the golden fixture

**Benefit:** Catches drift between the code and actual hardware behavior.

### 5.4 Keep replay tests, but reframe their purpose

The replay tests have value as **integration tests** that verify the code's internal consistency. They should be reframed as:

> "Given a simulated scanner that responds exactly as defined in the fixture, does our protocol stack complete the scan sequence without errors?"

This is still valuable, but it's not the same as "does our code match the hardware."

### 5.5 Add fixture validation to CI

**Action:** `scripts/validate_fixtures.py` already exists. Ensure it runs on every PR and validates:
- Column count consistency
- Endpoint values (0x01 OUT, 0x82 IN)
- Length vs hex payload match
- `@path` resolution and file size match
- Timestamp ordering
- Pcapng checksum match (new)

---

## 6. Discrepancy Summary (First 200 Events)

The automated comparison found 166 discrepancies. The most significant categories:

| Category | Count | Example |
|----------|-------|---------|
| Direction mismatch | ~50 | Fixture expects OUT where capture has IN (or vice versa) |
| Payload mismatch | ~60 | Same command, different bytes |
| Length mismatch | ~40 | Same command, different payload length |
| Missing in fixture | ~16 | Events in capture with no fixture counterpart |

These discrepancies are not random noise — they reflect systematic differences in how the fixture was constructed vs. how the capture was recorded.

---

## 7. Conclusion

The current replay test strategy is **not validating hardware correctness**. It's validating that the code is consistent with a hand-crafted fixture that diverges significantly from the actual capture. The 157 passing tests provide confidence in internal consistency, but not in wire-format correctness.

To close this gap, the project needs:
1. **A golden fixture derived programmatically from the pcapng** (eliminates manual drift)
2. **Property tests for non-deterministic behavior** (handles retries, timing)
3. **Periodic hardware validation** (catches real-world drift)

The replay tests should be retained but reframed as integration tests for internal consistency, not as oracle tests for hardware correctness.
