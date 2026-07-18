# Remaining Capture-Test Integration Work

Follow-up to PR #17 (capture-driven test infrastructure).

## D: Generate Fixtures from Remaining pcapng Captures

Three pcapng files exist at repo root with no derived fixtures:

| Capture | What it tests |
|---------|--------------|
| `ls40-single-negs.pcapng` | Negative film handling -- different exposure, WDB negative flag, scan mode params |
| `ls40-batch-neg.pcapng` | Batch + negatives combined -- frame structure with negative mode |
| `ls40-batch-session.pcapng` | Full session lifecycle -- init through multiple frames through teardown |

### Steps

1. Generate text fixtures:
   ```bash
   make generate-fixture-from-pcapng PCA=ls40-single-negs.pcapng OUT=reference/golden_single_negs.txt
   make generate-fixture-from-pcapng PCA=ls40-batch-neg.pcapng OUT=reference/golden_batch_neg.txt
   make generate-fixture-from-pcapng PCA=ls40-batch-session.pcapng OUT=reference/golden_batch_session.txt
   ```
   (This requires adding a parameterized `generate-fixture-from-pcapng` target to the Makefile.)

2. Run `make validate-fixtures` on each new fixture (expect errors from missing `@path` bin files -- extract them from pcapng via `scripts/refresh_*_image_fixtures.py` or normalize in the fixture).

3. Generate analysis snapshots:
   ```bash
   make generate-fixture-snapshot
   ```
   (Update the Makefile target to include all four fixtures.)

4. Add cross-capture property tests:
   - **Negative film invariants**: does negative-mode WDB have different byte 49 (film_flag), byte 44 (averaging), and byte 50 (scan_mode) from positive-mode?
   - **Batch negative structure**: does `golden_batch_neg.txt` have the same frame count and similar inter-frame auto-focus pattern as `golden_batch.txt`?
   - **Session lifecycle**: does `golden_batch_session.txt` contain INQUIRY → RESERVE_UNIT at the start and RELEASE_UNIT at the end (unlike the current batch fixture, which starts mid-session)?
   - **Command code coverage**: does every command code present in any fixture appear in the `@sends` registry?

5. Add `conftest.py` fixtures for each new fixture (session-scoped, parallel loading).

6. Run full test suite against all fixtures.

## E: Property Tests Cross-Validate Against Capture Bytes

`tests/test_protocol_properties.py` constructs synthetic USB events by hand. These sequences are plausible but not verified against actual capture data. A validation layer would:

### Steps

1. **Replay golden fixture through `CoolscanProtocol`** -- create a test that loads `golden_single_bw.txt` into `UsbCaptureReplay`, wraps it with `CoolscanProtocol(..., usb_capture_replay=replay)`, and runs the full session. Count mismatches. Fix any discrepancies found in protocol code.

2. **Sense-key extraction test** -- extract every 8-byte status response from `golden_single_bw.txt`, run each through `_parse_status()`, and assert the resulting `StatusType` matches expected behavior (READY, REISSUE, PROCESSING, etc.). This would catch missed sense-key combinations.

3. **Synthetic event equivalence** -- for each hand-crafted event sequence in `test_protocol_properties.py`, find the structurally equivalent subsequence in the golden fixture (same CDB prefix, same phase pattern, same sense-key sequence). Assert they produce the same `StatusType` transitions.

4. **CDB byte-level validation** -- extract every OUT command from the golden fixture, compare byte 5 (control byte) against the expected value (0x80 for most, 0x00 for TUR/RESERVE/RELEASE). Flag any commands with unexpected control bytes.

5. **Phase ordering** -- assert that every PHASE_CHECK → phase response sequence in the fixture follows the expected pattern (DATA_OUT after 0x02, STATUS after 0x01, etc.).

## Verification

After both D and E:
```bash
make check-all        # full pipeline
make validate-fixtures # all fixtures pass validation
```

## Estimated Effort

- **D**: 2-3 hours (mostly fixture generation + structural validation tests)
- **E**: 3-4 hours (replay validation + sense-key extraction + equivalence checks)
