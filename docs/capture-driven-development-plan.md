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
| Human/machine-friendly trace | `test_basic_scan_capture.txt` (columns: time, endpoint, length, hex or `@path` for large IN). **260 lines** today (including footer comments). **1–83:** init through MODE_SELECT (replay-locked). **84–87:** extra `TEST_UNIT_READY` before the prescan-aligned window. **88–208:** full `prescan()` USB replay slice (includes post-`START_SCAN` status, poll, image READs, exposure, `GET_WINDOW`). **210–252:** full-scan setup + polling for `perform_scan_sequence()` (TUR, reserve, object_position, MODE_SELECT, send_lut, start_scan, PROCESSING→READY polling, release_unit). |
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

**Full scan setup replay:** `tests/test_usb_replay_full_scan_sequence.py` — **`perform_scan_sequence()`** bulk I/O matches **lines 210–252** (scanner_ready TUR, reserve_unit, object_position, set_window via MODE_SELECT, send_lut, start_scan, polling PROCESSING→READY, release_unit). Command bytes match `CoolscanProtocol` output, not raw capture (full scan uses SET_WINDOW 0x24 vs MODE_SELECT 0x15, and 3× 8192-byte LUT uploads vs single 768-byte LUT).

**Full scan image data strategy:** Rather than replaying ~25 MiB of byte-for-byte image data, validate at three levels: (A) CDB construction test proves `read_scan_data(259200)` emits correct READ(10) CDB against minimal fixture with synthetic IN; (B) post-READY GET_WINDOW fixture validates WDB responses; (C) integration test covers control flow from setup → scan → data read with synthetic IN data.

**Fallback** (if injection is too invasive for a given area): Keep **targeted mocks** on specific methods but assert **exact bytes** passed in/out, still derived from `test_basic_scan_capture.txt`.

## Handling non-determinism (retries, extra polls)

Captures may include **retries, NAKs, or repeated** `TEST_UNIT_READY` / phase checks. Tests should **not** require one monolithic global byte stream. Prefer:

- **Phase fixtures** — Slices of the trace: e.g. “boot through first INQUIRY,” “prescan through START_SCAN,” “first image bulk block.”
- **Loose matchers** where needed — e.g. allow up to *N* extra known noop commands before a milestone, or “next semantically relevant IN after this OUT.”

Normalize once per slice when building the fixture, document the rule in the test docstring.

## Pcap vs text fixture (maintenance)

- **`*.pcapng` is gitignored** but should exist beside the repo for offline regeneration (`parse_pcapng.py`, `scripts/export_usb_capture_text.py`, `scripts/refresh_prescan_image_fixtures.py`); **`tshark`** must be on `PATH`.
- The checked-in text file is **not** a contiguous bulk prefix of the pcap from the first frame: the first transactions match, then an early **8-byte status IN** is **normalized to zeros** (fixture elision), after which the stream **re-aligns** with the pcap around the READ CAPACITY–style sequence beginning with host OUT `120101000480`.
- **`CoolscanProtocol._issue_usb_command`** performs **one** bulk IN read for the full `data_in_length` (e.g. 130752 for a prescan image block). **`tshark`** often records that as **multiple IN rows** (e.g. ~65508-byte chunks plus 8-byte status) and may show **repeated identical READ(10) OUT CDBs** per chunk. Strict replay therefore uses **one IN event per logical read**; large payloads use **`@tests/fixtures/prescan_image_block*.bin`**, rebuilt from wire-order bulk INs via **`scripts/refresh_prescan_image_fixtures.py`** (concatenate large INs after the first `28000000000001fec080` OUT through the 11520-byte tail IN, then slice **130752|130752|11520**).
- Post-**READY** prescan tail in the text file follows **`prescan()` call order** (image → exposure → `GET_WINDOW`), which can differ from **chronological bus order** in an unedited export.

## Milestones (vertical slices)

Work in **order along the real single-bw session**, extending only as far as needed for a working scan:

1. **Init / inquiry / mode** — **Done (replay).** `tests/test_usb_replay_init_sequence.py` locks **`test_basic_scan_capture.txt` lines 1–83** through MODE_SELECT (line 84 is the next host transaction). Fixture remains an **edited** slice of `ls40-single-bw.pcapng`, not a raw prefix (see **Pcap vs text fixture** above).
2. **Prescan setup** — **Done (fixture + mocks).** SET_WINDOW ×3, LUT upload, START_SCAN and earlier path are in the text capture; `tests/test_prescan_sequence_verification.py` still uses mocks for inner calls.
3. **Post-START_SCAN** — **Done (replay slice).** Status reads (`0x87`), `poll_until_ready()` pattern, READY transition through line **168** of the text file; covered by `tests/test_usb_replay_prescan_sequence.py` from line **88**.
4. **Full prescan image path** — **Done (replay harness).** `tests/test_usb_replay_prescan_sequence.py` matches **lines 88–208** including three image `READ`s (`@` fixture blobs), exposure `0x8e`, three `GET_WINDOW`s. Image fixture binaries are regenerated from **`ls40-single-bw.pcapng`** using **`scripts/refresh_prescan_image_fixtures.py`** (see **Pcap vs text fixture**).
5. **Full scan setup + polling** — **Done (replay).** `tests/test_usb_replay_full_scan_sequence.py` locks **lines 210–252** against `perform_scan_sequence()` (scanner_ready TUR, reserve_unit, object_position, set_window via MODE_SELECT, send_lut, start_scan with ERROR/ASCQ=6, post-scan polling PROCESSING→READY, release_unit). Command bytes match `CoolscanProtocol` output, not raw capture (full scan uses SET_WINDOW 0x24 vs MODE_SELECT 0x15, and 3× 8192-byte LUT uploads vs single 768-byte LUT).
6. **Full scan image data** — **Done (three-level validation).** Rather than replaying ~25 MiB of byte-for-byte image data (which requires consolidating ~65508-byte wire chunks into single bulk reads), we validate correctness at three levels:
   - **Piece A: CDB construction** — `tests/test_read_scan_data_cdb.py` proves `read_scan_data()` emits correct READ(10) CDBs for all stripe sizes (258048, 223488, 259200, 103680) plus status/exposure datatypes.
   - **Piece B: Post-READY GET_WINDOW** — `tests/test_get_window_cdb.py` validates GET_WINDOW CDBs for windows 1/2/3/9 and WDB exposure extraction (SANE formula, bytes 54-57).
   - **Piece C: Integration** — `tests/test_scan_read_integration.py` covers full control flow (scanner_ready → reserve_unit → object_position → set_window → send_lut → start_scan → poll_until_ready → read_scan_data(64) → release_unit) with synthetic IN data.

After each milestone: **`pytest` green**, **docs updated** (what is now guaranteed vs capture), **git commit** (see below).

## Documentation and commits

- After each **passing milestone**, update **`docs/unified-protocol-spec.md`** and/or **`docs/usb-capture-findings.md`** with a short note: what sequence is now test-locked and any caveats (normalization, optional retries).
- **Commit discipline:** One commit per **logical chunk** (e.g. one milestone or one fixture+test+fix cluster). Message should state which capture slice is now enforced.

*(Agents: commit when the user has authorized commits for the session.)*

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

- **Batch / ADF** capture (`ls40-batch.pcapng`) until single-bw path is done.
- **CI setup** (optional later).
- **Bit-identical timing** to the pcap unless a specific bug is proven to be timing-related; then add **tolerant** timing or ordering checks only for that phase.

---

*Last updated (2026-05): milestone 6 complete — full scan image data validated via CDB construction (7 tests), GET_WINDOW/WDB parsing (8 tests), and integration test with synthetic IN data (1 test). Total: 141 tests.*Last updated (2026-05): milestone status, full scan setup replay (lines 210-252), revised image data strategy (CDB + GET_WINDOW + integration instead of byte-for-byte replay).*Last updated (2026-05): milestone status and “Pcap vs text fixture” maintenance notes; prescan replay through line 208.*
