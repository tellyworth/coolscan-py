# Capture-driven development plan

> **Note (current):** The active sequence-refactor plan has moved to
> `.opencode/plans/golden-fixture-sequence-alignment.md`. This document
> describes the overall capture-driven philosophy and historical milestones.
> The legacy full-sequence replay tests against `test_basic_scan_capture.txt`
> were removed; current coverage uses focused golden-fixture slice tests and
> cross-capture property tests.

This project implements a Python scanner stack for Nikon Coolscan hardware using SANE-derived knowledge and **USB captures as the ground truth**. Hardware runs are slow and noisy; development should **iterate against captured traffic** first, then confirm on a real scanner.

## Goals

- **Primary:** A **working scan path** (init → prescan → image read), not a complete or perfect protocol implementation.
- **Oracle:** **`ls40-single-bw.pcapng`** (single scan, monochrome). The **golden fixture** (`tests/fixtures/golden_single_bw.txt`, 1472 events) derived from this pcapng is now the **primary test oracle**. **`ls40-batch.pcapng`** is out of scope until the single path is hardware-verified.
- **Lightweight:** No CI requirement; tests run **locally** with **stdlib + pytest**. Optional tools (`tshark`, `scripts/generate_fixture_from_pcapng.py`) regenerate fixtures **offline**, not as a hard test dependency.

## Canonical artifacts

| Role | Artifact |
|------|----------|
| Raw reference | `ls40-single-bw.pcapng` |
| **Primary oracle** | **`tests/fixtures/golden_single_bw.txt`** — 1472-event fixture auto-derived from pcapng via `scripts/generate_fixture_from_pcapng.py`. SHA-256 of source pcapng pinned in header. Validated by `make validate-fixtures`. |
| Secondary / legacy | `tests/fixtures/test_basic_scan_capture.txt` was a hand-edited slice; it is now legacy and no replay tests depend on it. |
| Deeper analysis | `docs/usb-capture-findings.md`, `docs/unified-protocol-spec.md` |
| Active refactor plan | `.opencode/plans/golden-fixture-sequence-alignment.md` |
| Second opinion | SANE backend source (intent, naming, edge cases); **wire format defers to capture** when they disagree |

**Convention:** New tests and comments should cite **`tests/fixtures/golden_single_bw.txt`** as the primary reference. `ls40-batch.pcapng` is the secondary oracle for batch/multi-frame behavior.

## Three-tier test strategy

The test suite is organized into three tiers, each with a different role:

| Tier | Scope | Marker | Purpose |
|------|-------|--------|---------|
| **Contract** | `test_protocol_contracts.py` | (none) | **Method call patterns** — each scenario method calls the right low-level methods in the right order with the right arguments. Uses `FakeCoolscanProtocol` (test double). |
| **Property** | `test_protocol_properties.py`, `test_command_properties.py` | `@pytest.mark.property_test` | **Fixture-agnostic invariants** — REISSUE handling, polling loops, LUT sizes, status parsing, TUR retries, timeout budgeting. |
| **State-machine** | `test_batch_state_machine.py` | (none) | **Batch frame transitions** — validates batch scan frame transitions are valid. Parameterized over frame counts. |
| **Scanner** | `test_scanner.py` | (none) | **Scanner API** — `CoolscanScanner` uses real `CoolscanProtocol` API via `FakeCoolscanProtocol`. |
| **Behavior** | `test_protocol_behavior.py` | (none) | **CDB-level contracts** — validated with mocked `_issue_command`. |
| **Smoke** | `test_hardware_smoke.py` | `@pytest.mark.hardware` | **Hardware correctness** — connects to real scanner, validates protocol works on actual device. Skips gracefully when no scanner attached. |

Markers are registered in `tests/conftest.py`. Replay tests are auto-marked when they lack an explicit marker.

## Existing tests (baseline)

- **`tests/test_protocol_commands.py`** — Golden **hex** for many CDBs and patterns; already references `ls40-single-bw.pcapng`. Often validates `struct.pack`-level construction; does not always prove **`CoolscanProtocol`** emits the same bytes.
- **`tests/test_prescan_sequence_verification.py`** — **`prescan()`** with mocked protocol methods; asserts **call order and counts**.
- **`tests/test_scanner.py`** — Scanner API with protocol mocked; good for wiring, not USB fidelity.
- **`tests/test_protocol_module.py`** — Module-level behavior as applicable.
- **`tests/test_protocol_properties.py`** — 14 fixture-agnostic property tests covering protocol invariants.
- **`tests/test_hardware_smoke.py`** — 3 hardware smoke tests (enumerate, TUR, full prescan) + 4 golden fixture structural tests.

## Strategy: run the real protocol against fixtures

**Preferred approach:** Introduce or extend a **fake USB transport** at the boundary where the stack already logs traffic (`CoolscanProtocol` bulk/control read-write path, alongside `enable_usb_capture`):

1. For each **host → device** write, compare payload to the **next expected OUT** from the fixture (or a **normalized** form: 6-byte command + tagged bulk payload).
2. For each **device → host** read, return the **next fixture IN** bytes from the capture-derived list.

That runs **real `CoolscanProtocol` logic** without hardware and without simulating all of libusb.

### Implemented harness

| Piece | Location |
|-------|----------|
| Parser + strict replay cursor | `coolscan/usb_replay.py` — `UsbCaptureReplay`, `ReplayUsbDevice`, `ReplayError` subclasses |
| Wire protocol to replay | `CoolscanProtocol(..., usb_capture_replay=replay)` (keyword-only). Uses bulk endpoints **0x01** / **0x82** only; no libusb device. |
| Fail-fast | When `usb_capture_replay` is set, **`ReplayError`** is re-raised from `_usb_read_bulk` / `_usb_write_bulk`, `_issue_usb_command`, `wait_scanner`, `_check_phase` / `_check_phase_with_retry`, and `initialize_scanner` paths instead of being turned into generic `StatusType.ERROR` / swallowed retries. |
| `close()` | Skips `usb.util` teardown when replay is active. |

**Tests:** The replay harness is tested through `UsbCaptureReplay` unit tests in `tests/test_protocol_properties.py` and contract tests in `tests/test_protocol_contracts.py`. These exercise the `usb_capture_replay` keyword argument on `CoolscanProtocol` and verify dispatches produce the expected byte sequences against golden fixture slices.

**Focused golden fixture coverage (current strategy):** Rather than replaying entire sequences against a single capture, the suite now uses small, focused golden fixture references and cross-capture property assertions:

- `tests/test_protocol_properties.py` — `test_reissue_causes_resend` exercises the real 3-attempt `REISSUE → ERROR → READY` pattern (golden fixture lines 297-331) via hand-constructed `UsbCaptureReplay` events.
- `tests/test_protocol_contracts.py` — Individual helper contracts: `set_boundary_for_prescan`, `set_boundary` (CONTROL_FRAME), `read_exposure_data`, `read_control_frame`, `read_channel_state`, `upload_identity_luts`, `read_focus`, `stop_scan`, `start_scan` retry behavior, and full-scan setup.
- `tests/test_protocol_behavior.py` — CDB-level contracts for `set_window`, `read_scan_data`, `get_window`, and related methods.
- `tests/test_batch_state_machine.py` — Batch frame transition validation with ASCII state machine diagram.
- `tests/test_command_properties.py` — Parameterized CDB structure, WDB layout, and status parsing properties.

The legacy full-sequence replay tests (`tests/test_usb_replay_prescan_sequence.py`
and `tests/test_usb_replay_full_scan_sequence.py`) were removed because they
locked the code to a hand-edited fixture and to a per-operation reservation model
that does not match the pcapng.

**Tooling:** `scripts/export_usb_capture_text.py` writes text lines from
`ls40-single-bw.pcapng` when `tshark` is available. `scripts/refresh_prescan_image_fixtures.py`
and `scripts/refresh_scan_image_fixtures.py` rebuild binary payloads from the pcap.
`scripts/validate_fixtures.py` (`make validate-fixtures`) checks fixture consistency
and cross-validates `golden_single_bw.txt` against `ls40-single-bw.pcapng` (SHA match,
event count bounds, command code coverage). Runs as part of `make check-all`.

**Replay tests are fixture self-consistency checks**, not hardware correctness proofs. They verify that protocol code reproduces the fixture's byte sequence, but the fixture itself may contain errors relative to actual hardware behavior. Hardware smoke tests (`make smoke-test-hardware`) are needed to close this gap.

**Fallback** (if injection is too invasive for a given area): Keep **targeted mocks** on specific methods but assert **exact bytes** passed in/out, still derived from the golden fixture.

## Handling non-determinism (retries, extra polls)

Captures may include **retries, NAKs, or repeated** `TEST_UNIT_READY` / phase checks. Tests should **not** require one monolithic global byte stream. Prefer:

- **Phase fixtures** — Slices of the trace: e.g. "boot through first INQUIRY," "prescan through START_SCAN," "first image bulk block."
- **Loose matchers** where needed — e.g. allow up to *N* extra known noop commands before a milestone, or "next semantically relevant IN after this OUT."

Normalize once per slice when building the fixture, document the rule in the test docstring.

## Pcap vs text fixture (maintenance)

- **`*.pcapng` is gitignored** but should exist beside the repo for offline regeneration (`parse_pcapng.py`, `scripts/export_usb_capture_text.py`, `scripts/refresh_prescan_image_fixtures.py`, `scripts/refresh_scan_image_fixtures.py`, `scripts/generate_fixture_from_pcapng.py`); **`tshark`** must be on `PATH`.
- The checked-in legacy text file is **not** a contiguous bulk prefix of the pcap from the first frame: the first transactions match, then an early **8-byte status IN** is **normalized to zeros** (fixture elision), after which the stream **re-aligns** with the pcap around the READ CAPACITY-style sequence beginning with host OUT `120100000480`.
- The **golden fixture** (`tests/fixtures/golden_single_bw.txt`) is a **raw, unedited** extraction from the pcapng. It is 1472 events covering the full single-bw scan session. Its SHA-256 of the source pcapng is pinned in the header. `make validate-fixtures` cross-checks the golden fixture against the raw pcapng.
- **`CoolscanProtocol._issue_usb_command`** performs **one** bulk IN read for the full `data_in_length` (e.g. 130752 for a prescan image block). **`tshark`** often records that as **multiple IN rows** (e.g. ~65508-byte chunks plus 8-byte status) and may show **repeated identical READ(10) OUT CDBs** per chunk. Strict replay therefore uses **one IN event per logical read**; large payloads use **`@tests/fixtures/prescan_image_block*.bin`**, rebuilt from wire-order bulk INs via **`scripts/refresh_prescan_image_fixtures.py`** (concatenate large INs after the first `28000000000001fec080` OUT through the 11520-byte tail IN, then slice **130752|130752|11520**).
- **Full scan image chunks:** The scanner returns 65508 bytes per READ(10) CDB issue, even when the CDB allocation length is larger (258048, 223488, etc.). The fixture encodes **one IN event per CDB issue** with 65508-byte payloads from **`@tests/fixtures/scan_image_block{1,2,3,4}.bin`**, rebuilt via **`scripts/refresh_scan_image_fixtures.py`** (extract first 4 IN transfers from frames 2399-2438).
- Post-**READY** prescan tail in the text file follows **`prescan()` call order** (image → exposure → `GET_WINDOW`), which can differ from **chronological bus order** in an unedited export.

## Milestones (vertical slices)

Work in **order along the real single-bw session**, extending only as far as needed for a working scan:

1. **Init / inquiry / mode** — **Done.** `initialize_scanner()` matches golden fixture lines 1–123 through MODE_SELECT. Covered by contract tests in `tests/test_protocol_contracts.py`.
2. **Prescan setup** — **Partially done.** Individual prescan helpers now match the golden fixture (`set_boundary_for_prescan`, `read_exposure_data`, `read_control_frame`, `read_channel_state`, `upload_identity_luts`). `prescan()` itself still needs restructuring to drop redundant `SET_WINDOW` calls and add the missing `CONTROL_FRAME` / channel-state reads.
3. **Post-START_SCAN** — **Done.** Status reads (`0x87`), `poll_until_ready()` pattern, and the 3-attempt retry behavior are covered by `test_reissue_causes_resend` in `tests/test_protocol_properties.py` and `test_start_scan` contracts in `tests/test_protocol_contracts.py`.
4. **Full prescan image path** — **Historical.** Was covered by the now-removed legacy full-sequence replay test. Coverage will be restored as part of composing `prescan_frame()` in Phase 3.
5. **Full scan setup + polling** — **Partially done.** Individual full-scan helpers now match the golden fixture (`set_boundary`, `read_focus`, `read_channel_state(9)`, `upload_identity_luts(include_ir=True)`, `stop_scan`). `perform_scan_sequence()` still needs restructuring to follow the real full-scan slice (lines ~427-660+) and to remove the obsolete `reserve_unit` / `read_capacity` preamble.
6. **Full scan image data** — **Historical.** Was covered by the now-removed legacy full-sequence replay test. Coverage will be restored as part of composing `full_scan_frame()` in Phase 3. Remaining validation still applies:
   - **Piece A: CDB construction** — `tests/test_read_scan_data_cdb.py` proves `read_scan_data()` emits correct READ(10) CDBs for all stripe sizes (258048, 223488, 259200, 103680) plus status/exposure datatypes.
   - **Piece B: Post-READY GET_WINDOW** — `tests/test_get_window_cdb.py` validates GET_WINDOW CDBs for windows 1/2/3/9 and WDB exposure extraction (SANE formula, bytes 54-57).
   - **Piece C: Integration** — `tests/test_scan_read_integration.py` covers full control flow with synthetic IN data.

7. **Golden fixture infrastructure** — **Done.** `tests/fixtures/golden_single_bw.txt` (1472 events) derived from `ls40-single-bw.pcapng` via `scripts/generate_fixture_from_pcapng.py`. SHA-256 of source pcapng pinned in header. `make validate-fixtures` cross-checks golden fixture against raw capture. `ls40-batch.pcapng` is available as the secondary oracle but a text fixture has not yet been generated from it.

8. **Property tests** — **Done.** `tests/test_protocol_properties.py` adds fixture-agnostic invariant tests: REISSUE handling, polling loops, LUT sizes, SET_WINDOW CDB construction, TUR retries, CDB format, status parsing, focus/readback sequences. Run via `make test-properties`.

9. **Hardware smoke tests** — **Done (infrastructure).** `tests/test_hardware_smoke.py` provides 3 hardware tests (enumerate, TUR, full prescan) that skip gracefully when no scanner is attached, plus 4 golden fixture structural tests. Run via `make smoke-test-hardware`.

**Note:** The remaining work is tracked in `.opencode/plans/golden-fixture-sequence-alignment.md` (Phases 3-7). The protocol code reproduces individual helper slices, but the high-level `prescan()` / `perform_scan_sequence()` methods still need to be composed from those helpers before full-sequence hardware validation makes sense.

### Protocol fixes landed (Fixes 1-5)

| Fix | Description | Status |
|-----|-------------|--------|
| Fix 1 | `set_boundary()` added to prescan path; corrected to use 0x92 BORDER_POSITION (prescan) and 0x8f CONTROL_FRAME (full scan) per golden fixture — SANE's 0x88 IMAGE_POSITIONS rejected by LS-40 ED | Landed |
| Fix 2 | `prescan()` returns False on image read failure | Landed |
| Fix 3 | REISSUE byte positions corrected (buf4 in 0/1, not ASCQ low bits) | Landed |
| Fix 4 | Session-level `_scanner_alive` fail-fast after 3 consecutive USB errors | Landed |
| Fix 5 | Timeout budgeting — `prescan(timeout=120)` and `perform_scan_sequence(timeout=300)` track deadline, pass remaining budget to `poll_until_ready` | Landed |
| Fix 6 | Session reservation model — reserve once in `initialize_scanner()`, release in `disconnect()` / teardown; remove per-operation reserve/release from `prescan()`, `auto_focus()`, `perform_scan_sequence()`, `_perform_scan()` | Landed |
| Fix 7 | `read_exposure_data()` derives table length from the 6-byte header instead of a hardcoded value | Landed |
| Fix 8 | `read_focus()` requests 9 bytes to match the golden fixture | Landed |
| Fix 9 | `stop_scan()` retries on `REISSUE` with status/progress reads, matching the golden fixture | Landed |

After each milestone: **`pytest` green**, **docs updated** (what is now guaranteed vs capture), **git commit** (see below).

## SANE backend audit findings

A full comparison of `coolscan/protocol.py` against the SANE `coolscan3` backend (`sane-comparison.md`) identified the following discrepancies. **Wire format still defers to USB capture** when SANE and capture disagree.

### P0 (blocker): Must fix before reliable hardware scan

| ID | Issue | Status |
|----|-------|--------|
| P0-2 | Missing `set_boundary()` before scan | **Resolved** — uses 0x92 BORDER_POSITION (prescan) and 0x8f CONTROL_FRAME (full scan) per golden fixture; SANE's 0x88 IMAGE_POSITIONS rejected by LS-40 ED |

### P1 (bug): Incorrect behavior on some hardware

| ID | Issue | Status |
|----|-------|--------|
| P1-1 | Missing REISSUE status after START_SCAN | **Resolved** — Fix 3 corrected REISSUE byte positions |
| P1-2 | LUT size hardcoded 8192, should use maxbits from page 0xc1 | Open |
| P1-3 | Missing `get_exposure()` after `set_window()` | Open |
| P1-4 | WDB `negative_dropout` writes full byte, should use bit 4 | Open |
| P1-5 | WDB `scan_mode` writes to bits 0-1, should be bits 4-5 | Open |

**P1-4 / P1-5 are WDB construction bugs** that affect negative film handling and prescan mode. Verify against capture WDB bytes to confirm our hardcoded WDBs are correct (they may have been captured from working traffic, so the bytes could be right despite wrong construction logic).

### P2 (gap): Missing features

12 items including: `set_focus()` before scan, resolution pitch calculation, exposure clamping, multi-frame support, LOAD/EJECT/RESET commands, `cs3_execute()`, data reassembly (interleaved→planar→RGB), independent X/Y resolution. **None block a basic scan** but will be needed for full feature parity.

### P3 (cosmetic): Different but both work

8 items including: timeout values, polling intervals, INQUIRY page order, WDB construction approach, LUT upload timing, chunk sizes. **No action needed.**

### Resolution order

1. **P1-4 / P1-5:** Verify WDB bytes against capture. If our hardcoded WDBs match capture, the construction logic bug is latent but not active.
2. **P1-2:** Read maxbits from page 0xc1, parameterize LUT size.
3. **P1-3:** Add `get_exposure()` call after `set_window()` in scan sequence.

## Documentation and commits

- After each **passing milestone**, update **`docs/unified-protocol-spec.md`** and/or **`docs/usb-capture-findings.md`** with a short note: what sequence is now test-locked and any caveats (normalization, optional retries).
- **Commit discipline:** One commit per **logical chunk** (e.g. one milestone or one fixture+test+fix cluster). Message should state which capture slice is now enforced.

*(Agents: commit when the user has authorized commits for the session.)*

## Subagent roles

Use separate agents to keep context clean; hand off **artifacts** (fixture snippets, failing test output) explicitly.

| Agent | Responsibility |
|-------|----------------|
| **Fixture** | Extend or split fixtures; add `tests/fixtures/*.txt` slices; optional small **stdlib** parser emitting `(direction, payload)` or OUT/IN pairs. |
| **Test** | Write or adjust tests against fixtures or fake transport; document normalization rules in docstrings. |
| **Implementation** | Minimal `coolscan/` changes until the active slice passes. |
| **Verify** | Run verification commands below; confirm green before claiming done. |

## Verification commands

```bash
# Full test suite
make test

# Property tests only (fixture-agnostic invariants)
make test-properties

# Validate fixture consistency (including golden fixture cross-check)
make validate-fixtures

# Hardware smoke tests (skip gracefully if no scanner)
make smoke-test-hardware

# All checks (lint + validate + test)
make check-all
```

Use a narrower path while iterating (e.g. `pytest tests/test_prescan_sequence_verification.py -v`) when appropriate.

## Out of scope for this plan

- **Batch / ADF** capture (`ls40-batch.pcapng`) — partially covered by state-machine tests in `tests/test_batch_state_machine.py` and batch helper contracts in `tests/test_protocol_contracts.py`. Full multi-image ADF workflow is next after P0/P1 fixes land.
- **CI setup** (optional later).
- **Bit-identical timing** to the pcap unless a specific bug is proven to be timing-related; then add **tolerant** timing or ordering checks only for that phase.
- **SANE feature parity** — We implement the minimal scan path. SANE-specific features (multi-frame, LOAD/EJECT, 16-bit depth, independent X/Y resolution) are P2 gaps, tracked in SANE audit section above.

---

*Last updated (2026-06-10): Hardware smoke test revealed set_boundary used wrong datatype (0x88 IMAGE_POSITIONS from SANE, rejected by LS-40 ED with ILLEGAL REQUEST). Corrected to 0x92 BORDER_POSITION (prescan) and 0x8f CONTROL_FRAME (full scan) per golden fixture. Legacy fixture and replay tests updated to match. Total: **178 tests** (175 passing, 3 hardware-skipped).*