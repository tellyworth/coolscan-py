# Roadmap / ideas

## Protocol fixes and completion
 - [x] Basic exposure and LUT
 - [ ] 12 bit full scan
 - [ ] Batch scan (as per pcapng with separate segments)
 - [x] Review output log for issues

## Proper scan script
 - [ ] New CLI script with args for bit depth, batch mode etc
 - [ ] TIFF output for 12 bit scans with IR channel layer, compression, EXIF
 - [ ] TIFF + jpeg output option (raw 12 bit data in TIFF, inverted and cropped and adjusted in jpeg)
 - [ ] File naming sequence numbers etc
 - [ ] check_orientation package for auto rotate

## Improvements to investigate and try
 - [ ] Full strip scanning (instead of separate segments)
 - [ ] Auto detect film type
 - [ ] Detect border between frames
 - [ ] White balance
 - [ ] Auto exposure / LUT (auto black/white points etc)
 - [ ] Heal dust spots using IR data

## Repo and test cleanup
 - [ ] Refactor unit tests to replace golden fixture with derived tests
 - [ ] Clean up docs
 - [ ] Mermaid diagram of protocol
 - [ ] Fix mypy errors
 - [ ] Simplify code generally
 - [ ] Move to a clean repo


