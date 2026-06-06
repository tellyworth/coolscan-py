# Capture-driven development plan

This project implements a Python scanner stack for Nikon Coolscan hardware using SANE-derived knowledge and **USB captures as the ground truth**. Hardware runs are slow and noisy; development should **iterate against captured traffic** first, then confirm on a real scanner.

## Goals

- **Primary:** A **working scan path** (init → prescan → image read), not a complete or perfect protocol implementation.
- **Oracle:** **`ls40-single-bw.pcapng`** (single scan, monochrome). **`ls40-batch.pcapng`** is out of scope until the single path is stable.
- **Lightweight:** No CI requirement; tests run **locally** with **stdlib + pytest** and **checked-in text fixtures**. Optional tools (`tshark`, `parse_pcapng.py`) regenerate fixtures **offline**, not as a hard test dependency.

## Canonical artifacts

| Role | Artifact |
|------|----------|
| Raw reference | `ls40-single-bw.pcapng` |
| Human/machine-friendly trace | `test_basic_scan_capture.txt` (columns: time, endpoint, length, hex or `@path` for large IN). **303 lines** today. **1–83:** init through MODE_SELECT (replay-locked). **84–87:** extra `TEST_UNIT_READY` before the prescan-aligned window. **88–208:** full `prescan()` USB replay slice (includes post-`START_SCAN` status, poll, image READs, exposure, `GET_WINDOW`). **210–259:** full-scan setup + polling for `perform_scan_sequence()` (TUR, reserve, read_capacity, set_window via MODE_SELECT, 3× LUT upload, start_scan, PROCESSING→READY polling). **273–303:** full-scan image READs (64-byte synthetic + 4× 65508-byte capture-derived chunks) with `@tests/fixtures/scan_image_block*.bin`. |
| Deeper analysis | `docs/usb-capture-findings.md`, `docs/unified-protocol-spec.md` |
| Second opinion | SANE backend source (intent, naming, edge cases); **wire format defers to capture** when they disagree |

**Convention:** New tests and comments should cite **`test_basic_scan_capture.txt`** (line ranges or phase labels), not ad hoc secondary extracts, unless those extracts are regenerated from the same pcap and checked in (e.g. under `tests/fixtures/`).

## Existing tests (baseline)

- **`tests/test_protocol_commands.py`** — Golden **hex** for many CDBs and patterns; already references `ls40-single-bw.pcapng`. Often validates `struct.pack`-level construction; does not always prove **`CoolscanProtocol`** emits the same bytes.
- **`tests/test_prescan_sequence_verification.py`** — **`prescan()`** with mocked protocol methods; asserts **call order and counts**. Should be **aligned** with the same segments of `test_basic_scan_capture.txt` as the single-bw reference (replace or supplement references to `usb_capture_timing.txt` where they drift).
- **`tests/test_scanner.py`** — Scanner API with protocol mocked; good for wiring, not USB fidelity.
- **`tests/test_protocol_module.py`** — Module-level behavior as applicable.

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

**Tests:** `tests/test_usb_replay_transport.py` (first INQUIRY, parser edge cases); `tests/test_usb_replay_init_sequence.py` — **`initialize_scanner()` through MODE_SELECT** matches **`test_basic_scan_capture.txt` lines 1–83** (line 84 is the next host transaction, start of the prescan-era segment).

**Prescan replay:** `tests/test_usb_replay_prescan_sequence.py` — **`prescan()`** bulk I/O matches **lines 88–208** (replay starts at 88 so the first capture TUR before that does not duplicate `prescan`’s opening `test_unit_ready`). The post-**READY** tail is **synthetic** where needed: it follows **`CoolscanProtocol.prescan()` order** (three image `READ`s via `read_prescan_image_data`, then exposure `0x8e`, then three `GET_WINDOW`s), not necessarily the chronological bus order in a raw export. Large IN payloads use **`@tests/fixtures/...` binary files** resolved from the capture file’s directory (see `coolscan/usb_replay.py`). **LUT OUT rows** must be **full-length** hex (parser checks the length column). **Tooling:** `scripts/export_usb_capture_text.py` writes more text lines from `ls40-single-bw.pcapng` when `tshark` is available. **`scripts/refresh_prescan_image_fixtures.py`** rebuilds `tests/fixtures/prescan_image_block{1,2,3}.bin` from the same pcap. **`scripts/audit_capture_read_batches.py`** prints image `READ` allocation vs single-transfer IN sums for pcap QA before extending full-scan replay. **`scripts/validate_fixtures.py`** (`make validate-fixtures`) checks fixture consistency: column count, endpoint values, length-vs-hex match, `@path` resolution, file-size match, and timestamp ordering (warnings for splice points). Runs as part of `make check-all`.

**Full scan setup replay:** `tests/test_usb_replay_full_scan_sequence.py` — **`perform_scan_sequence()`** bulk I/O matches **lines 210–254** (scanner_ready TUR, reserve_unit, set_window via MODE_SELECT, 3× 8192-byte LUT uploads, start_scan, polling PROCESSING→READY). `object_position` removed (LS-40 ED rejects with ILLEGAL REQUEST). `release_unit` moved to `scanner._perform_scan`. Command bytes match `CoolscanProtocol` output, not raw capture (full scan uses SET_WINDOW 0x24 vs MODE_SELECT 0x15, and 3× 8192-byte LUT uploads vs single 768-byte LUT).

**Full scan image replay:** `tests/test_usb_replay_full_scan_sequence.py::test_full_scan_image_reads_match_capture` — **`perform_scan_sequence()`** + synthetic 64-byte read + 4× `read_scan_data()` calls match **lines 210–303**. The four image READs correspond to the first stripe from the capture (frames 2399-2438): 3× READ(10) with allocation 258048 plus 1× READ(10) with allocation 223488. The scanner returns 65508 bytes per chunk, so each IN payload is 65508 bytes. Large INs use **`@tests/fixtures/scan_image_block{1,2,3,4}.bin`** rebuilt from `ls40-single-bw.pcapng` via **`scripts/refresh_scan_image_fixtures.py`**.

**Batch scan replay:** `tests/test_usb_replay_batch_scan.py` — 4 tests against `tests/fixtures/test_batch_scan_protocol.txt` (lines 256-290 from `ls40-batch.pcapng`): reserve_unit, 3× READ_CAPACITY (windows 1/2/3), START_SCAN, post-scan polling, 4× READ_SCAN_DATA (64, 258048, 259200, 103680 bytes), RELEASE_UNIT teardown.

**Full scan image data strategy:** First-stripe replay validates the full scan image READ path with capture-derived data (4× 65508-byte chunks from frames 2399-2438). Remaining validation: (A) CDB construction test proves `read_scan_data(N)` emits correct READ(10) CDB for all stripe sizes; (B) post-READY GET_WINDOW fixture validates WDB responses; (C) integration test covers control flow from setup → scan → data read with synthetic IN data.

**Fallback** (if injection is too invasive for a given area): Keep **targeted mocks** on specific methods but assert **exact bytes** passed in/out, still derived from `test_basic_scan_capture.txt`.

## Handling non-determinism (retries, extra polls)

Captures may include **retries, NAKs, or repeated** `TEST_UNIT_READY` / phase checks. Tests should **not** require one monolithic global byte stream. Prefer:

- **Phase fixtures** — Slices of the trace: e.g. “boot through first INQUIRY,” “prescan through START_SCAN,” “first image bulk block.”
- **Loose matchers** where needed — e.g. allow up to *N* extra known noop commands before a milestone, or “next semantically relevant IN after this OUT.”

Normalize once per slice when building the fixture, document the rule in the test docstring.

## Pcap vs text fixture (maintenance)

- **`*.pcapng` is gitignored** but should exist beside the repo for offline regeneration (`parse_pcapng.py`, `scripts/export_usb_capture_text.py`, `scripts/refresh_prescan_image_fixtures.py`, `scripts/refresh_scan_image_fixtures.py`); **`tshark`** must be on `PATH`.
- The checked-in text file is **not** a contiguous bulk prefix of the pcap from the first frame: the first transactions match, then an early **8-byte status IN** is **normalized to zeros** (fixture elision), after which the stream **re-aligns** with the pcap around the READ CAPACITY–style sequence beginning with host OUT `120101000480`.
- **`CoolscanProtocol._issue_usb_command`** performs **one** bulk IN read for the full `data_in_length` (e.g. 130752 for a prescan image block). **`tshark`** often records that as **multiple IN rows** (e.g. ~65508-byte chunks plus 8-byte status) and may show **repeated identical READ(10) OUT CDBs** per chunk. Strict replay therefore uses **one IN event per logical read**; large payloads use **`@tests/fixtures/prescan_image_block*.bin`**, rebuilt from wire-order bulk INs via **`scripts/refresh_prescan_image_fixtures.py`** (concatenate large INs after the first `28000000000001fec080` OUT through the 11520-byte tail IN, then slice **130752|130752|11520**).
- **Full scan image chunks:** The scanner returns 65508 bytes per READ(10) CDB issue, even when the CDB allocation length is larger (258048, 223488, etc.). The fixture encodes **one IN event per CDB issue** with 65508-byte payloads from **`@tests/fixtures/scan_image_block{1,2,3,4}.bin`**, rebuilt via **`scripts/refresh_scan_image_fixtures.py`** (extract first 4 IN transfers from frames 2399-2438).
- Post-**READY** prescan tail in the text file follows **`prescan()` call order** (image → exposure → `GET_WINDOW`), which can differ from **chronological bus order** in an unedited export.

## Milestones (vertical slices)

Work in **order along the real single-bw session**, extending only as far as needed for a working scan:

1. **Init / inquiry / mode** — **Done (replay).** `tests/test_usb_replay_init_sequence.py` locks **`test_basic_scan_capture.txt` lines 1–83** through MODE_SELECT (line 84 is the next host transaction). Fixture remains an **edited** slice of `ls40-single-bw.pcapng`, not a raw prefix (see **Pcap vs text fixture** above).
2. **Prescan setup** — **Done (fixture + mocks).** SET_WINDOW ×3, LUT upload, START_SCAN and earlier path are in the text capture; `tests/test_prescan_sequence_verification.py` still uses mocks for inner calls.
3. **Post-START_SCAN** — **Done (replay slice).** Status reads (`0x87`), `poll_until_ready()` pattern, READY transition through line **168** of the text file; covered by `tests/test_usb_replay_prescan_sequence.py` from line **88**.
4. **Full prescan image path** — **Done (replay harness).** `tests/test_usb_replay_prescan_sequence.py` matches **lines 88–208** including three image `READ`s (`@` fixture blobs), exposure `0x8e`, three `GET_WINDOW`s. Image fixture binaries are regenerated from **`ls40-single-bw.pcapng`** using **`scripts/refresh_prescan_image_fixtures.py`** (see **Pcap vs text fixture**).
5. **Full scan setup + polling** — **Done (replay).** `tests/test_usb_replay_full_scan_sequence.py::test_perform_scan_sequence_matches_capture` locks **lines 210–259** against `perform_scan_sequence()` (scanner_ready TUR, reserve_unit, read_capacity, set_window via MODE_SELECT, 3× 8192-byte LUT uploads, start_scan with ERROR/ASCQ=6, post-scan polling PROCESSING→READY). Command bytes match `CoolscanProtocol` output, not raw capture (full scan uses SET_WINDOW 0x24 vs MODE_SELECT 0x15, and 3× 8192-byte LUT uploads vs single 768-byte LUT). `object_position` removed (LS-40 ED rejects). `release_unit` moved to `scanner._perform_scan`.
6. **Full scan image data** — **Done (first-stripe replay + three-level validation).** `tests/test_usb_replay_full_scan_sequence.py::test_full_scan_image_reads_match_capture` replays the first stripe from the capture (lines 210-303): `perform_scan_sequence()` + synthetic 64-byte read + 4× `read_scan_data()` with capture-derived 65508-byte IN payloads. Remaining validation:
   - **Piece A: CDB construction** — `tests/test_read_scan_data_cdb.py` proves `read_scan_data()` emits correct READ(10) CDBs for all stripe sizes (258048, 223488, 259200, 103680) plus status/exposure datatypes.
   - **Piece B: Post-READY GET_WINDOW** — `tests/test_get_window_cdb.py` validates GET_WINDOW CDBs for windows 1/2/3/9 and WDB exposure extraction (SANE formula, bytes 54-57).
   - **Piece C: Integration** — `tests/test_scan_read_integration.py` covers full control flow (scanner_ready → reserve_unit → set_window → send_lut → start_scan → poll_until_ready → read_scan_data(64) → release_unit) with synthetic IN data.

After each milestone: **`pytest` green**, **docs updated** (what is now guaranteed vs capture), **git commit** (see below).

## SANE backend audit findings

A full comparison of `coolscan/protocol.py` against the SANE `coolscan3` backend (`sane-comparison.md`) identified the following discrepancies. **Wire format still defers to USB capture** when SANE and capture disagree.

### P0 (blocker): Must fix before reliable hardware scan

| ID | Issue | SANE source | Our source |
|----|-------|------------|------------|
| P0-2 | Missing `set_boundary()` before scan | `coolscan3.c:3106` / `:2898-2936` | Nowhere |

`set_boundary()` sends SEND(0x2a) with datatype 0x88 (IMAGE_POSITIONS), frame count, and boundary coordinates. Without it, the scanner may not know the scan area or frame count. **Must be added to `perform_scan_sequence()` between `set_window()` and `start_scan()`.** Verify against capture: check if `ls40-single-bw.pcapng` shows a 0x88 SEND before START_SCAN.

### P1 (bug): Incorrect behavior on some hardware

| ID | Issue | SANE source | Our source |
|----|-------|------------|------------|
| P1-1 | Missing REISSUE status after START_SCAN | `coolscan3.c:3147-3151` | `protocol.py:1535-1631` |
| P1-2 | LUT size hardcoded 8192, should use maxbits from page 0xc1 | `coolscan3.c:2972-2980` / `:2443` | `protocol.py:1375` |
| P1-3 | Missing `get_exposure()` after `set_window()` | `coolscan3.c:3121-3123` | `protocol.py:2316-2361` |
| P1-4 | WDB `negative_dropout` writes full byte, should use bit 4 | `coolscan-scsidef.h:349-358` | `protocol.py:135-136` |
| P1-5 | WDB `scan_mode` writes to bits 0-1, should be bits 4-5 | `coolscan-scsidef.h:362-367` | `protocol.py:136-137` |

**P1-4 / P1-5 are WDB construction bugs** that affect negative film handling and prescan mode. Verify against capture WDB bytes to confirm our hardcoded WDBs are correct (they may have been captured from working traffic, so the bytes could be right despite wrong construction logic).

### P2 (gap): Missing features

12 items including: `set_focus()` before scan, resolution pitch calculation, exposure clamping, multi-frame support, LOAD/EJECT/RESET commands, `cs3_execute()`, data reassembly (interleaved→planar→RGB), independent X/Y resolution. **None block a basic scan** but will be needed for full feature parity.

### P3 (cosmetic): Different but both work

8 items including: timeout values, polling intervals, INQUIRY page order, WDB construction approach, LUT upload timing, chunk sizes. **No action needed.**

### Resolution order

1. **P0-2:** Audit capture for 0x88 SEND before START_SCAN. If present, add `set_boundary()` and extend fixture. If absent on LS-40 ED, note model-specific behavior.
2. **P1-4 / P1-5:** Verify WDB bytes against capture. If our hardcoded WDBs match capture, the construction logic bug is latent but not active.
3. **P1-1:** Add REISSUE mapping to `_parse_status()` and handle in `start_scan()`.
4. **P1-2:** Read maxbits from page 0xc1, parameterize LUT size.
5. **P1-3:** Add `get_exposure()` call after `set_window()` in scan sequence.

## Documentation and commits

- After each **passing milestone**, update **`docs/unified-protocol-spec.md`** and/or **`docs/usb-capture-findings.md`** with a short note: what sequence is now test-locked and any caveats (normalization, optional retries).
- **Commit discipline:** One commit per **logical chunk** (e.g. one milestone or one fixture+test+fix cluster). Message should state which capture slice is now enforced.

*(Agents: commit when the user has authorized commits for the session.)*

**Last updated (2026-06):** Milestone 5 extended — full scan image replay via `test_usb_replay_full_scan_sequence.py` (lines 210-303, first-stripe capture replay with 4× 65508-byte IN chunks from frames 2399-2438). `scripts/refresh_scan_image_fixtures.py` rebuilds `scan_image_block{1,2,3,4}.bin` from pcap. Milestone 6 extended — batch scan replay via `test_usb_replay_batch_scan.py`. `read_capacity()` accepts `window_id` parameter. `object_position` removed (LS-40 ED rejects). Total: **157 tests**.
## Subagent roles

Use separate agents to keep context clean; hand off **artifacts** (fixture snippets, failing test output) explicitly.

| Agent | Responsibility |
|-------|----------------|
| **Fixture** | Extend or split `test_basic_scan_capture.txt`; add `tests/fixtures/*.txt` slices; optional small **stdlib** parser emitting `(direction, payload)` or OUT/IN pairs. |
| **Test** | Write or adjust tests against fixtures or fake transport; document normalization rules in docstrings. |
| **Implementation** | Minimal `coolscan/` changes until the active slice passes. |
| **Verify** | Run `python -m pytest tests/ -v` (or targeted paths); confirm green before claiming done. |

## Verification command

```bash
python -m pytest tests/ -v
```

Use a narrower path while iterating (e.g. `tests/test_prescan_sequence_verification.py`) when appropriate.

**Fixture validation:** Run `make validate-fixtures` (or `python scripts/validate_fixtures.py`) before committing fixture changes. Included in `make check-all`.

## Out of scope for this plan

- **Batch / ADF** capture (`ls40-batch.pcapng`) — partially done via `test_usb_replay_batch_scan.py`. Full multi-image ADF workflow is next after P0/P1 fixes land.
- **CI setup** (optional later).
- **Bit-identical timing** to the pcap unless a specific bug is proven to be timing-related; then add **tolerant** timing or ordering checks only for that phase.
- **SANE feature parity** — We implement the minimal scan path. SANE-specific features (multi-frame, LOAD/EJECT, 16-bit depth, independent X/Y resolution) are P2 gaps, tracked in SANE audit section above.

---

*Last updated (2026-06): SANE backend audit complete (sane-comparison.md). 1 P0 (set_boundary), 5 P1 (REISSUE, LUT size, get_exposure, WDB bits), 12 P2, 8 P3. Milestone 5/6 extended — full scan image replay (lines 210-303), batch scan replay (4 tests), hardware scan script. Total: 157 tests.*
