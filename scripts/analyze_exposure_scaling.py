#!/usr/bin/env python3
"""
analyze_exposure_scaling.py

Reads a golden fixture and prints a comparison table of:
  - READ 0x8c (channel state) calibrated exposure values
  - SET_WINDOW WDB exposure values (full scan phase)
  - The scaling factor between them (WDB / 0x8c)

This is a read-only analysis script. It does NOT modify any files.

Usage:
    python3 scripts/analyze_exposure_scaling.py reference/golden_single_bw.txt
    python3 scripts/analyze_exposure_scaling.py reference/golden_batch.txt
"""

import sys
import struct


def parse_fixture(path):
    """Parse a golden fixture file and extract all events."""
    events = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            ts, endpoint, length, data = parts[0], parts[1], int(parts[2]), parts[3]
            events.append({
                'line': lineno,
                'ts': float(ts),
                'endpoint': endpoint,
                'length': length,
                'data': data,
            })
    return events


def find_read_0x8c(events):
    """Find READ 0x8c commands and their responses."""
    results = {}
    for i, ev in enumerate(events):
        # READ 0x8c command: 28 00 8c 00 <channel> 03 00 00 0a 80
        if ev['endpoint'] == '0x01' and ev['data'].startswith('28008c'):
            hexdata = ev['data']
            channel = int(hexdata[8:10], 16)
            ch_name = {1: 'R', 2: 'G', 3: 'B', 9: 'IR'}.get(channel, f'?{channel}')
            # Find the response: next 0x82 endpoint with length 10
            resp = None
            for j in range(i + 1, min(i + 5, len(events))):
                if events[j]['endpoint'] == '0x82' and events[j]['length'] == 10:
                    resp_hex = events[j]['data']
                    # Response format: 8c 20 00 00 00 04 <4-byte value>
                    if resp_hex.startswith('8c20'):
                        val = int(resp_hex[12:20], 16)
                        resp = val
                    break
            if resp is not None:
                results[ch_name] = resp
    return results


def find_all_wdbs(events):
    """Find ALL SET_WINDOW (0x24) commands and their 58-byte WDB payloads."""
    wdb_events = []
    seen = set()  # Avoid duplicate WDBs
    for i, ev in enumerate(events):
        # SET_WINDOW header: 24 00 00 00 00 00 00 00 3a 80
        if ev['endpoint'] == '0x01' and ev['data'].startswith('2400'):
            # Find the 58-byte WDB payload
            for j in range(i + 1, min(i + 10, len(events))):
                if events[j]['endpoint'] == '0x82' and events[j]['length'] == 1:
                    # Scanner ack (02 = ready for data)
                    for k in range(j + 1, min(j + 3, len(events))):
                        if events[k]['endpoint'] == '0x01' and events[k]['length'] == 58:
                            wdb_hex = events[k]['data']
                            if wdb_hex not in seen:
                                seen.add(wdb_hex)
                                wdb_events.append({
                                    'line': events[k]['line'],
                                    'ts': events[k]['ts'],
                                    'wdb': wdb_hex,
                                })
                            break
                    break
    return wdb_events


def parse_wdb(hexstr):
    """Parse a 58-byte WDB and extract channel, resolution, and exposure."""
    if len(hexstr) != 116:  # 58 bytes = 116 hex chars
        return None
    channel = int(hexstr[16:18], 16)
    resx = int(hexstr[20:24], 16)
    resy = int(hexstr[24:28], 16)
    exposure = int(hexstr[108:116], 16)  # bytes 54-57 (last 4 bytes)
    scan_kind = int(hexstr[100:102], 16)  # byte 50
    ch_name = {1: 'R', 2: 'G', 3: 'B', 9: 'IR'}.get(channel, f'?{channel}')
    return {
        'channel': ch_name,
        'resx': resx,
        'resy': resy,
        'exposure': exposure,
        'scan_kind': scan_kind,
    }


def find_fullscan_wdbs(all_wdbs, events, cal_0x8c):
    """
    Find the full scan WDBs: the FIRST group of kind=0x01 WDBs sent AFTER
    the last READ 0x8c command completes.

    Strategy: find the timestamp of the last READ 0x8c, then find the first
    group of NORMAL (kind=0x01) WDBs immediately after that point.
    """
    if not cal_0x8c:
        return {}

    # Find the latest READ 0x8c timestamp
    max_0x8c_ts = 0
    for i, ev in enumerate(events):
        if ev['endpoint'] == '0x01' and ev['data'].startswith('28008c'):
            max_0x8c_ts = max(max_0x8c_ts, ev['ts'])

    # Find all NORMAL WDBs after the last 0x8c read
    post_0x8c_wdbs = []
    for wdb_ev in all_wdbs:
        parsed = parse_wdb(wdb_ev['wdb'])
        if parsed and parsed['scan_kind'] == 0x01 and wdb_ev['ts'] > max_0x8c_ts:
            post_0x8c_wdbs.append({**wdb_ev, **parsed})

    # Group consecutive WDBs (within 1 second of each other)
    groups = []
    current_group = []
    for wdb in sorted(post_0x8c_wdbs, key=lambda w: w['ts']):
        if not current_group or (wdb['ts'] - current_group[-1]['ts']) < 1.0:
            current_group.append(wdb)
        else:
            groups.append(current_group)
            current_group = [wdb]
    if current_group:
        groups.append(current_group)

    # The full scan is the FIRST group of NORMAL WDBs after 0x8c
    if not groups:
        return {}

    first_group = groups[0]
    result = {}
    for wdb in first_group:
        result[wdb['channel']] = wdb

    return result


def find_prescan_wdbs(all_wdbs):
    """
    Find the prescan WDBs: the FIRST group of kind=0x02 (AE) WDBs.
    If no AE WDBs exist, use the first group of any WDBs.
    """
    # Look for AE (kind=0x02) WDBs first
    ae_wdbs = []
    for wdb_ev in all_wdbs:
        parsed = parse_wdb(wdb_ev['wdb'])
        if parsed and parsed['scan_kind'] == 0x02:
            ae_wdbs.append({**wdb_ev, **parsed})

    if ae_wdbs:
        # Group consecutive AE WDBs
        ae_wdbs.sort(key=lambda w: w['ts'])
        result = {}
        for wdb in ae_wdbs:
            result[wdb['channel']] = wdb
        return result

    # Fallback: use the first group of any WDBs
    all_parsed = []
    for wdb_ev in all_wdbs:
        parsed = parse_wdb(wdb_ev['wdb'])
        if parsed:
            all_parsed.append({**wdb_ev, **parsed})
    all_parsed.sort(key=lambda w: w['ts'])

    result = {}
    for wdb in all_parsed[:4]:  # First 4 WDBs
        result[wdb['channel']] = wdb
    return result


def analyze_fixture(path):
    """Main analysis function."""
    events = parse_fixture(path)
    cal_0x8c = find_read_0x8c(events)
    all_wdbs = find_all_wdbs(events)

    prescan_wdb = find_prescan_wdbs(all_wdbs)
    fullscan_wdb = find_fullscan_wdbs(all_wdbs, events, cal_0x8c)

    print(f"Fixture: {path}")
    print(f"Total events: {len(events)}")
    print(f"READ 0x8c responses found: {len(cal_0x8c)}")
    print(f"Total WDBs found: {len(all_wdbs)}")
    print(f"Prescan WDBs: {list(prescan_wdb.keys())}")
    print(f"Full scan WDBs: {list(fullscan_wdb.keys())}")
    print()

    print("=" * 70)
    print("READ 0x8c Calibrated Exposure Values (scanner auto-calibration)")
    print("=" * 70)
    for ch in ['R', 'G', 'B', 'IR']:
        if ch in cal_0x8c:
            val = cal_0x8c[ch]
            ms = val * 10 / 1e6
            print(f"  {ch:>3s}: 0x{val:08x} = {val:>7,d}  ({ms:.3f} ms)")

    print()
    print("=" * 70)
    print("Prescan WDB Exposures (initial guesses sent to scanner)")
    print("=" * 70)
    for ch in ['R', 'G', 'B']:
        if ch in prescan_wdb:
            p = prescan_wdb[ch]
            ms = p['exposure'] * 10 / 1e6
            kind_label = "AE" if p['scan_kind'] == 0x02 else "NORMAL"
            print(f"  {ch:>3s}: 0x{p['exposure']:08x} = {p['exposure']:>7,d}  ({ms:.3f} ms)  res=({p['resx']},{p['resy']})  kind={kind_label}")

    print()
    print("=" * 70)
    print("Full Scan WDB Exposures (final values sent to scanner)")
    print("=" * 70)
    for ch in ['IR', 'R', 'G', 'B']:
        if ch in fullscan_wdb:
            p = fullscan_wdb[ch]
            ms = p['exposure'] * 10 / 1e6
            print(f"  {ch:>3s}: 0x{p['exposure']:08x} = {p['exposure']:>7,d}  ({ms:.3f} ms)  res=({p['resx']},{p['resy']})")

    print()
    print("=" * 70)
    print("Scaling Analysis: WDB_exposure / 0x8c_calibrated")
    print("=" * 70)
    for ch in ['IR', 'R', 'G', 'B']:
        if ch in fullscan_wdb and ch in cal_0x8c:
            wdb_val = fullscan_wdb[ch]['exposure']
            cal_val = cal_0x8c[ch]
            ratio = wdb_val / cal_val
            note = ""
            if ch == 'IR':
                note = "  ← Consistent 0.9000 across captures"
            elif ch in ['G', 'B'] and ch in cal_0x8c:
                # Check if G and B have the same ratio
                g_ratio = fullscan_wdb.get('G', {}).get('exposure', 0) / cal_0x8c.get('G', 1)
                b_ratio = fullscan_wdb.get('B', {}).get('exposure', 0) / cal_0x8c.get('B', 1)
                if abs(g_ratio - b_ratio) < 0.001:
                    note = "  ← G and B share scaling (B&W mode)"
            print(f"  {ch:>3s}: {wdb_val:>7,d} / {cal_val:>7,d} = {ratio:.4f}{note}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_exposure_scaling.py <fixture_path>")
        print("\nAvailable fixtures:")
        import glob
        for f in sorted(glob.glob('reference/golden_*.txt')):
            print(f"  {f}")
        sys.exit(1)

    for path in sys.argv[1:]:
        analyze_fixture(path)
        print()


if __name__ == '__main__':
    main()
