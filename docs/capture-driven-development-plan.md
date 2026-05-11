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
| Human/machine-friendly trace | `test_basic_scan_capture.txt` (columns: time, endpoint, length, hex payload). **Currently a slice** of the session (extend from `ls40-single-bw.pcapng` / `parse_pcapng.py` as milestones need more lines). As of the plan write-up, lines **84–133** cover TUR → reserve → three `SET_WINDOW` → TUR → three LUT `WRITE`s → `START_SCAN` + WDB; lines **134+** begin post-`START_SCAN` traffic. |
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

**Fallback** (if injection is too invasive for a given area): Keep **targeted mocks** on specific methods but assert **exact bytes** passed in/out, still derived from `test_basic_scan_capture.txt`.

## Handling non-determinism (retries, extra polls)

Captures may include **retries, NAKs, or repeated** `TEST_UNIT_READY` / phase checks. Tests should **not** require one monolithic global byte stream. Prefer:

- **Phase fixtures** — Slices of the trace: e.g. “boot through first INQUIRY,” “prescan through START_SCAN,” “first image bulk block.”
- **Loose matchers** where needed — e.g. allow up to *N* extra known noop commands before a milestone, or “next semantically relevant IN after this OUT.”

Normalize once per slice when building the fixture, document the rule in the test docstring.

## Milestones (vertical slices)

Work in **order along the real single-bw session**, extending only as far as needed for a working scan:

1. **Init / inquiry / mode** — Match capture through stable “ready for scan setup” point; update docs when locked.
2. **Prescan setup** — SET_WINDOW ×3, LUT upload, START_SCAN; match capture sequence and payloads.
3. **Post-START_SCAN** — Status reads, polling pattern, first meaningful **image-related READ** per capture.
4. **Full prescan image path** — Complete bulk reads for prescan dimensions from capture.
5. **Full scan path** (still single-bw) — Extend to final image completion as in capture.

After each milestone: **`pytest` green**, **docs updated** (what is now guaranteed vs capture), **git commit** (see below).

## Documentation and commits

- After each **passing milestone**, update **`docs/unified-protocol-spec.md`** and/or **`docs/usb-capture-findings.md`** with a short note: what sequence is now test-locked and any caveats (normalization, optional retries).
- **Commit discipline:** One commit per **logical chunk** (e.g. one milestone or one fixture+test+fix cluster). Message should state which capture slice is now enforced.

*(Agents: commit only when the user explicitly authorizes commits for that session.)*

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

## Out of scope for this plan

- **Batch / ADF** capture (`ls40-batch.pcapng`) until single-bw path is done.
- **CI setup** (optional later).
- **Bit-identical timing** to the pcap unless a specific bug is proven to be timing-related; then add **tolerant** timing or ordering checks only for that phase.

---

*Last updated: aligned with discussion to use `ls40-single-bw` + `test_basic_scan_capture.txt` as the single narrative source, fake transport where possible, and phased vertical milestones.*
