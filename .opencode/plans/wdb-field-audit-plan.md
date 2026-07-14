# WDB Field Audit & Protocol Reference

Goal: Eliminate re-analyzing captures and tracing protocol.py from scratch for every protocol question.

---

## Deliverable 1: `docs/wdb-field-reference.md`

Pre-computed reference from `ls40-single-bw.pcapng` + `ls40-batch.pcapng`.

### Content

**Section A: WDB layout cheat sheet** — table of all 58 bytes with offset, width, name, and meaning. Already partially exists in `to_bytes_58()` docstring at `protocol.py:274-292`, but needs to be standalone.

**Section B: Mutable field values per scan type** — for each field that varies, a table like:

| Byte(s) | Field | prescan R | setup R | single_bw R | batch R | batch_between R |
|#|#|#|#|#|#|
|10-13 | resolution | 0x0060 | 0x0122 | 0x0b54 | 0x0122 | 0x0122 |
|18-21 | y_offset | 0 | 0x024e | 0x024e | 0x001e | 0x001e |
|34 | transfer_mode | 0x08 | 0x0C | 0x08 | 0x0C | 0x0C |
|49 | film_type | 0x81 | 0x80 | 0x00 | 0x80 | 0x80 |
|50 | sub_mode | 0x02 | 0x01 | 0x01 | 0x01 | 0x01 |
|54-57 | exposure | 0x0a381 | 0x0ea05 | 0x1a452 | 0x0d386 | 0x1b773 |

This table is derived from:
1. `_SCAN_WINDOW_WDB_TABLES` (our code defaults)
2. WDB from pcapng (Nikon's values)
3. `GET_WINDOW` / `READ_CAPACITY` read-back (scanner's internal values)

Where (1) ≠ (2), flag it. Where (1) = (2) but (3) differs, note the scanner's adjustment.

**Section C: Fields our code overrides** — from `_build_scan_window_wdb()`:
- Byte 8: window_id (always overridden to match)
- Bytes 10-13: resolution (from `_SCAN_WINDOW_RESOLUTIONS`)
- Bytes 18-21: y_offset (per-frame, batch mode)
- Bytes 26-29: height (per-frame, batch mode)
- Byte 34: depth (only for normal/single_bw non-IR)
- Bytes 54-57: exposure (auto-applied from `_calibrated_exposure`)

Document which overrides are deliberate (y_offset per frame) vs which are bugs (exposure from prescan applied to all types).

**Section D: CONTROL_FRAME field reference** — same treatment for the 8f payload:
- y_start, y_end, height per frame position
- How our code generates them vs what the scanner returns

### Implementation

One-shot script: `scripts/generate_wdb_reference.py`
- Reads `_SCAN_WINDOW_WDB_TABLES` from protocol.py (import or parse)
- Parses pcapng files via existing `analyze_capture.py --extract-wdbs`
- Parses `GET_WINDOW` / `READ_CAPACITY` read-backs from the same extractions
- Outputs markdown tables

Run once, commit the output to `docs/wdb-field-reference.md`. Regenerate when captures change.

---

## Deliverable 2: `analyze_capture.py --wdb-diff` + `--compare`

Extend the existing `--extract-wdbs` flag with comparison modes.

### `--wdb-diff` (builds on existing `--diff-wdbs`)

Current `--diff-wdbs` does structural diff by sequence position. Add field-level delta output:

```
python3 scripts/analyze_capture.py --diff-a hardware.txt --diff-b reference/golden_single_bw.txt --wdb-diff
```

Output:

```
Field          Frame1 hw     Frame1 ref   Delta
exposure(R)    0x00009f3b    0x0001a452   -13431 (-73%)
exposure(G)    0x00006cf4    0x000167d3   -34751 (-74%)
exposure(B)    0x000045b0    0x0000a4a7    -24047 (-74%)
y_offset       30            590          +560
```

### `--compare-captures` (new, cross-capture table)

Single command to produce the kind of summary table from the exposure analysis:

```
python3 scripts/analyze_capture.py \
  --compare-captures hardware.txt ls40-batch.pcapng logs/scan_20260712.txt \
  --fields exposure x_res y_res y_offset transfer_mode film_type
```

Output: unified table showing each capture's values per scan type/channel:

```
Source          Type       Ch  exposure    x_res  y_offset  transfer  film
hardware.txt    setup      R   0x00009f3b  290    30        0x0c      0x80
ls40-batch.pcap  setup      R   0x0000ea05  290    590       0x0c      0x80
logs/scan_...   setup      R   0x0001ea05  290    590       0x0c      0x80
```

### Implementation

Add to `scripts/analyze_capture.py`:

1. Extend `WdbRow` named tuple to include `transfer_mode`, `film_type`, `sub_mode`, `wdb_mode` (currently only extraction: exposure, x_res, y_res, offset_x, offset_y, size_x, size_y, scan_kind)
2. New `compare_wdbs(captures: List[WdbRows], fields: List[str]) -> str` function
3. New CLI args: `--compare-captures`, `--compare-fields`

Reuse existing WDB parsing from `extract_wdbs` — just add the extra bytes.

---

## Deliverable 3: `test_wdb_contracts.py`

Contract tests that verify `set_scan_window(scan_type=X, window_id=Y)` produces the correct WDB bytes.

### Structure

```python
# Parameterized over (scan_type, window_id) × field offsets
PARAMS = [
    ("prescan", 1, 10, b"\x00\x60"),  # x_res
    ("prescan", 1, 54, b"\x00\x00\xa3\x81"),  # exposure
    ("single_bw", 1, 54, b"\x00\x01\xa4\x52"),
    ("batch", 9, 54, b"\x00\x01\xd1\xae"),
    # ... for all mutable fields
]

@pytest.mark.parametrize("scan_type, window_id, offset, expected", PARAMS)
def test_wdb_field_value(scan_type, window_id, offset, expected):
    proto = FakeCoolscanProtocol()  # or direct _build_scan_window_wdb call
    wdb = proto._build_scan_window_wdb(window_id, scan_type, depth=8)
    assert wdb[offset:offset+len(expected)] == expected, \
        f"scan_type={scan_type} win={window_id} bytes {offset}-{offset+len(expected)}: " \
        f"got {wdb[offset:offset+len(expected)].hex()}, expected {expected.hex()}"
```

Run `FakeCoolscanProtocol` (test double, bypasses USB). These are fast, fixture-agnostic, and catch regressions like "oops, auto-applied calibrated exposure broke the default for scan type X."

### What to cover

Every field that `_build_scan_window_wdb` overrides:
- Byte 8 (window_id), bytes 10-13 (resolution), bytes 18-21 (y_offset), bytes 26-29 (height), byte 34 (depth), bytes 54-57 (exposure)

Every table entry in `_SCAN_WINDOW_WDB_TABLES` (6 types × 3-4 channels = ~20 combos).

### Integration

Add to `tests/` directory, included in `make test`. No hardware or fixtures needed.

---

## Deliverable 4: Protocol data flow diagram

Update `AGENTS.md` or create a protocol flow reference at `docs/protocol-flow.md`.

### Content

**Scan phase sequence** (single scan mode):

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ INIT                                                                         │
│  READ 0x06 → VERSION                                                         │
│  GET_WINDOW(0) → capacity                                                    │
│  READ 0xc1 → model info                                                      │
│  READ 0xe1 → firmware                                                        │
│  READ 0xf0 → serial                                                          │
│  GET_WINDOW(0-9) → initial scanner state                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│ PRESCAN (96 DPI)                                                             │
│  READ 0x8e → exposure calibration table                                      │
│  READ 0x8f → control frame state                                             │
│  TUR ×3                                                                      │
│  READ 0x8c ×3 → R/G/B calibrated exposure → _calibrated_exposure[1-3]        │
│  TUR ×3                                                                      │
│  SET_WINDOW(1-3, "prescan") → WDB with exposure from table defaults          │
│  LUT uploads ×3                                                              │
│  START_SCAN → poll until ready                                               │
│  READ image data → prescan image                                             │
│  GET_WINDOW(1-3) → read back scanner-computed WDBs                           │
│  (updates _calibrated_exposure from scanner values)                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ SETUP (290 DPI, IR preview)                                                  │
│  SET_BOUNDARY → control frame for full scan                                  │
│  AUTOFOCUS                                                                    │
│  TUR ×3, READ focus                                                          │
│  TUR, READ 0x8c(9) → IR calibrated exposure → _calibrated_exposure[9]        │
│  TUR ×2                                                                      │
│  SET_WINDOW(9,1,2,3, "setup") → WDB with table defaults                     │
│  LUT uploads ×4                                                              │
│  STOP_SCAN                                                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│ CAPTURE (2900 DPI)                                                           │
│  TUR ×2                                                                      │
│  SET_WINDOW(1-3, "single_bw") → WDB with table defaults                     │
│  TUR, LUT uploads ×3                                                         │
│  START_SCAN → poll until ready                                               │
│  GET_WINDOW(1-3) → read back final WDBs                                      │
│  READ image data ×145 → full-res image                                       │
└──────────────────────────────────────────────────────────────────────────────┘
```

**_calibrated_exposure dataflow:**

```
read_channel_state(ch)  ──┐
                          ├──→ _calibrated_exposure[ch]  ──┐
GET_WINDOW read-back     ──┘                               ├──→ set_scan_window()
perform_scan line 4916   ──────────────────────────────────┤     (auto-apply?)
prescan line 4338        ──────────────────────────────────┘
```

**Batch scan per-frame loop:**

```
FOR each frame:
  full_scan_setup_frame()   → SET_WINDOW("batch")    → GET_WINDOW read-back
  preview_capture_frame()   → SET_WINDOW("batch_between")
  set_scan_window ×3        → SET_WINDOW("normal")   → GET_WINDOW read-back
  start_scan + poll         → SCAN execution
  full_res_capture()        → GET_WINDOW + READ data
  autofocus (if not last)   → position for next frame
```

### Implementation

Short markdown file. Commit to `docs/protocol-flow.md`. Cross-reference from `AGENTS.md` under "Protocol implementation."

---

## Execution Order & Effort

1. **test_wdb_contracts.py** (~2h) — write first; discovering what to test forces clarity on current behavior and exposes bugs
2. **generate_wdb_reference.py** (~1h) — one-shot script to parse tables + pcapng, output markdown
3. **analyze_capture.py extensions** (~3h) — add compare mode and extra WDB fields to extraction
4. **docs/protocol-flow.md** (~1h) — document the flow, reference the reference doc
5. **Run generate script, commit docs/wdb-field-reference.md** (~15min)

Total: ~7h. Each item is independent and can be done in parallel.
