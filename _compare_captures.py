#!/usr/bin/env python3
"""Parse OUT commands from both capture files and compare command sequences."""

import re
from collections import defaultdict

# Command type names
CMD_NAMES = {
    0x00: 'TUR',
    0x12: 'INQUIRY',
    0x15: 'MODE_SELECT',
    0x16: 'RESERVE',
    0x17: 'RELEASE',
    0x1b: 'SCAN',
    0x24: 'SET_WINDOW',
    0x25: 'GET_WINDOW',
    0x28: 'READ',
    0x2a: 'SEND',
    0xc1: 'COMMAND_C1',
    0xe0: 'UNIT_MOVE',
    0xe1: 'UNIT_MOVE_READ',
}

# 0x2a sub-types (byte 2 of payload)
SEND_SUB = {
    0x03: 'LUT',
    0x88: 'boundary',
    0x92: 'border_position',
}

# 0x28 sub-types (byte 2 of payload)
READ_SUB = {
    0x00: 'image',
    0x8c: 'channel_state',
    0x8e: 'exposure_cal',
    0x8f: 'control_frame',
}

# 0xe0 sub-types (byte 2 of payload)
E0_SUB = {
    0xb4: 'e0_b4',
    0xc1: 'e0_c1',
    0xd0: 'e0_d0',
    0xb0: 'e0_b0',
    0xb2: 'e0_b2',
    0xb6: 'e0_b6',
    0xb8: 'e0_b8',
    0xbc: 'e0_bc',
    0xbe: 'e0_be',
    0xc0: 'e0_c0',
    0xc2: 'e0_c2',
    0xc4: 'e0_c4',
    0xc6: 'e0_c6',
    0xc8: 'e0_c8',
    0xca: 'e0_ca',
    0xcc: 'e0_cc',
    0xce: 'e0_ce',
    0xd2: 'e0_d2',
    0xd4: 'e0_d4',
    0xd6: 'e0_d6',
    0xd8: 'e0_d8',
    0xda: 'e0_da',
    0xdc: 'e0_dc',
    0xde: 'e0_de',
    0xe0: 'e0_e0',
    0xe2: 'e0_e2',
    0xe4: 'e0_e4',
    0xe6: 'e0_e6',
    0xe8: 'e0_e8',
    0xea: 'e0_ea',
    0xec: 'e0_ec',
    0xee: 'e0_ee',
    0xf0: 'e0_f0',
    0xf2: 'e0_f2',
    0xf4: 'e0_f4',
    0xf6: 'e0_f6',
    0xf8: 'e0_f8',
    0xfa: 'e0_fa',
    0xfc: 'e0_fc',
    0xfe: 'e0_fe',
}

def parse_file(path):
    """Parse a capture file and return list of OUT command dicts."""
    commands = []
    with open(path) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            ts = float(parts[0])
            endpoint = int(parts[1], 16)
            length = int(parts[2])
            hexdata = parts[3]

            if endpoint != 0x01:
                continue

            # Parse command: first byte of data is command code
            if length == 0 or len(hexdata) < 2:
                continue
            cmd_code = int(hexdata[0:2], 16)

            # For 0x2a, get sub-type from byte 2
            sub_info = ''
            if cmd_code == 0x2a and len(hexdata) >= 6:
                sub_byte = int(hexdata[4:6], 16)
                sub_info = f" [{SEND_SUB.get(sub_byte, hex(sub_byte))}]"

            # For 0x28, get sub-type from byte 2
            if cmd_code == 0x28 and len(hexdata) >= 6:
                sub_byte = int(hexdata[4:6], 16)
                sub_info = f" [{READ_SUB.get(sub_byte, hex(sub_byte))}]"

            # For 0xe0, get sub-type from byte 2
            if cmd_code == 0xe0 and len(hexdata) >= 6:
                sub_byte = int(hexdata[4:6], 16)
                sub_info = f" [{E0_SUB.get(sub_byte, hex(sub_byte))}]"

            cmd_name = CMD_NAMES.get(cmd_code, f'UNK_{hex(cmd_code)}')
            commands.append({
                'ts': ts,
                'cmd': cmd_code,
                'name': cmd_name,
                'sub': sub_info,
                'length': length,
                'hexdata': hexdata,
                'line': line_no,
            })
    return commands

def label_phase(cmd, prev_cmd=None):
    """Label the scan phase for a command."""
    c = cmd['cmd']
    if c == 0x00:
        return 'init'
    if c == 0x12:
        return 'inquiry'
    if c in (0x25, 0x24):
        return 'prescan/window'
    if c == 0x1b:
        return 'scan'
    if c == 0x28:
        return 'read'
    if c == 0x2a:
        return 'send'
    if c == 0xe0:
        return 'unit_move'
    if c == 0xe1:
        return 'unit_move_read'
    if c == 0x15:
        return 'mode_select'
    if c == 0x16:
        return 'reserve'
    if c == 0x17:
        return 'release'
    if c == 0xc1:
        return 'c1'
    return 'other'

def print_timeline(commands, title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"  Total OUT commands: {len(commands)}")
    print(f"{'='*80}")
    for i, cmd in enumerate(commands):
        print(f"  {i+1:4d}  t={cmd['ts']:.6f}s  0x{cmd['cmd']:02x} {cmd['name']:15s}{cmd['sub']}  len={cmd['length']:3d}  line={cmd['line']}")

def compare_sequences(golden, test):
    """Compare two command sequences and find differences."""
    print(f"\n{'#'*80}")
    print(f"  COMPARISON: Golden ({len(golden)} cmds) vs Test ({len(test)} cmds)")
    print(f"{'#'*80}")

    # Build command type counts
    g_counts = defaultdict(int)
    t_counts = defaultdict(int)
    for c in golden:
        g_counts[c['name']] += 1
    for c in test:
        t_counts[c['name']] += 1

    all_names = sorted(set(list(g_counts.keys()) + list(t_counts.keys())))
    print(f"\n  Command type counts:")
    print(f"  {'Command':<18s} {'Golden':>8s} {'Test':>8s} {'Delta':>8s}")
    print(f"  {'-'*50}")
    for name in all_names:
        gc = g_counts.get(name, 0)
        tc = t_counts.get(name, 0)
        delta = tc - gc
        marker = ' <<<' if delta != 0 else ''
        print(f"  {name:<18s} {gc:>8d} {tc:>8d} {delta:>+8d}{marker}")

    # Compare sub-types for 0x2a, 0x28, 0xe0
    print(f"\n  0x2a SEND sub-type counts:")
    g_2a = defaultdict(int)
    t_2a = defaultdict(int)
    for c in golden:
        if c['cmd'] == 0x2a:
            g_2a[c['sub']] += 1
    for c in test:
        if c['cmd'] == 0x2a:
            t_2a[c['sub']] += 1
    for k in sorted(set(list(g_2a.keys()) + list(t_2a.keys()))):
        print(f"    {k:>20s}  G={g_2a.get(k,0)}  T={t_2a.get(k,0)}")

    print(f"\n  0x28 READ sub-type counts:")
    g_28 = defaultdict(int)
    t_28 = defaultdict(int)
    for c in golden:
        if c['cmd'] == 0x28:
            g_28[c['sub']] += 1
    for c in test:
        if c['cmd'] == 0x28:
            t_28[c['sub']] += 1
    for k in sorted(set(list(g_28.keys()) + list(t_28.keys()))):
        print(f"    {k:>20s}  G={g_28.get(k,0)}  T={t_28.get(k,0)}")

    print(f"\n  0xe0 UNIT_MOVE sub-type counts:")
    g_e0 = defaultdict(int)
    t_e0 = defaultdict(int)
    for c in golden:
        if c['cmd'] == 0xe0:
            g_e0[c['sub']] += 1
    for c in test:
        if c['cmd'] == 0xe0:
            t_e0[c['sub']] += 1
    for k in sorted(set(list(g_e0.keys()) + list(t_e0.keys()))):
        print(f"    {k:>20s}  G={g_e0.get(k,0)}  T={t_e0.get(k,0)}")

    # Sequence alignment: walk both and find mismatches
    print(f"\n  Sequence alignment (first 80 commands):")
    print(f"  {'#':>4s}  {'Time(G)':>10s} {'Time(T)':>10s}  {'Golden':>20s}  {'Test':>20s}  {'Match':>5s}")
    print(f"  {'-'*80}")

    max_cmp = min(80, len(golden), len(test))
    mismatches = []
    for i in range(max_cmp):
        g = golden[i]
        t = test[i]
        glabel = f"0x{g['cmd']:02x} {g['name']}{g['sub']}"
        tlabel = f"0x{t['cmd']:02x} {t['name']}{t['sub']}"
        match = 'OK' if g['cmd'] == t['cmd'] and g['length'] == t['length'] else 'DIFF'
        if match == 'DIFF':
            mismatches.append((i, g, t))
        print(f"  {i+1:4d}  {g['ts']:10.3f} {t['ts']:10.3f}  {glabel:>20s}  {tlabel:>20s}  {match:>5s}")

    if mismatches:
        print(f"\n  MISMATCHES in first 80 commands:")
        for idx, g, t in mismatches:
            print(f"    Pos {idx+1}: G=0x{g['cmd']:02x} {g['name']}{g['sub']} (len={g['length']}) "
                  f"vs T=0x{t['cmd']:02x} {t['name']}{t['sub']} (len={t['length']})")

    # Check for commands in golden but not in test (and vice versa)
    # Build a simplified signature: (cmd_code, sub_info)
    g_sigs = [(c['cmd'], c['sub']) for c in golden]
    t_sigs = [(c['cmd'], c['sub']) for c in test]

    from collections import Counter
    g_counter = Counter(g_sigs)
    t_counter = Counter(t_sigs)

    print(f"\n  Signatures (cmd+sub) in golden but NOT in test:")
    for sig, count in sorted(g_counter.items()):
        tc = t_counter.get(sig, 0)
        if tc == 0:
            print(f"    0x{sig[0]:02x}{sig[1]} x{count}")

    print(f"\n  Signatures (cmd+sub) in test but NOT in golden:")
    for sig, count in sorted(t_counter.items()):
        gc = g_counter.get(sig, 0)
        if gc == 0:
            print(f"    0x{sig[0]:02x}{sig[1]} x{count}")

    # Check for count differences
    print(f"\n  Signatures with COUNT differences:")
    all_sigs = set(list(g_counter.keys()) + list(t_counter.keys()))
    for sig in sorted(all_sigs):
        gc = g_counter.get(sig, 0)
        tc = t_counter.get(sig, 0)
        if gc != tc:
            print(f"    0x{sig[0]:02x}{sig[1]}: G={gc} T={tc} (delta={tc-gc:+d})")

    # Focus areas
    print(f"\n{'@'*80}")
    print(f"  FOCUS: Exposure-related commands (0x28/0x8e, 0x25)")
    print(f"{'@'*80}")
    print("  Golden:")
    for c in golden:
        if c['cmd'] == 0x28 and '0x8e' in c['sub']:
            print(f"    t={c['ts']:.3f}s  0x28 [exposure_cal] len={c['length']} data={c['hexdata'][:40]}...")
        if c['cmd'] == 0x25:
            print(f"    t={c['ts']:.3f}s  0x25 [GET_WINDOW] len={c['length']} data={c['hexdata'][:40]}...")
    print("  Test:")
    for c in test:
        if c['cmd'] == 0x28 and '0x8e' in c['sub']:
            print(f"    t={c['ts']:.3f}s  0x28 [exposure_cal] len={c['length']} data={c['hexdata'][:40]}...")
        if c['cmd'] == 0x25:
            print(f"    t={c['ts']:.3f}s  0x25 [GET_WINDOW] len={c['length']} data={c['hexdata'][:40]}...")

    print(f"\n{'@'*80}")
    print(f"  FOCUS: Focus-related commands (0xe0/0xc1, 0xe1, 0xe0/0xb4, 0xc2)")
    print(f"{'@'*80}")
    print("  Golden:")
    for c in golden:
        if (c['cmd'] == 0xe0 and ('0xc1' in c['sub'] or '0xb4' in c['sub'] or '0xc2' in c['sub'])) or c['cmd'] == 0xe1:
            print(f"    t={c['ts']:.3f}s  0x{c['cmd']:02x}{c['sub']} len={c['length']} data={c['hexdata'][:40]}...")
    print("  Test:")
    for c in test:
        if (c['cmd'] == 0xe0 and ('0xc1' in c['sub'] or '0xb4' in c['sub'] or '0xc2' in c['sub'])) or c['cmd'] == 0xe1:
            print(f"    t={c['ts']:.3f}s  0x{c['cmd']:02x}{c['sub']} len={c['length']} data={c['hexdata'][:40]}...")

    print(f"\n{'@'*80}")
    print(f"  FOCUS: Frame/boundary commands (0x2a/0x88, 0x2a/0x92)")
    print(f"{'@'*80}")
    print("  Golden:")
    for c in golden:
        if c['cmd'] == 0x2a and ('0x88' in c['sub'] or '0x92' in c['sub']):
            print(f"    t={c['ts']:.3f}s  0x2a{c['sub']} len={c['length']} data={c['hexdata'][:60]}...")
    print("  Test:")
    for c in test:
        if c['cmd'] == 0x2a and ('0x88' in c['sub'] or '0x92' in c['sub']):
            print(f"    t={c['ts']:.3f}s  0x2a{c['sub']} len={c['length']} data={c['hexdata'][:60]}...")

    print(f"\n{'@'*80}")
    print(f"  FOCUS: Prescan-related (SCAN 0x1b, SET_WINDOW 0x24, early GET_WINDOW 0x25)")
    print(f"{'@'*80}")
    print("  Golden:")
    for c in golden:
        if c['cmd'] in (0x1b, 0x24, 0x25):
            print(f"    t={c['ts']:.3f}s  0x{c['cmd']:02x} {c['name']}{c['sub']} len={c['length']}")
    print("  Test:")
    for c in test:
        if c['cmd'] in (0x1b, 0x24, 0x25):
            print(f"    t={c['ts']:.3f}s  0x{c['cmd']:02x} {c['name']}{c['sub']} len={c['length']}")

    print(f"\n{'@'*80}")
    print(f"  FOCUS: Device cleanup/release at end (last 30 commands)")
    print(f"{'@'*80}")
    print("  Golden (last 30):")
    for c in golden[-30:]:
        print(f"    t={c['ts']:.3f}s  0x{c['cmd']:02x} {c['name']}{c['sub']} len={c['length']}")
    print("  Test (last 30):")
    for c in test[-30:]:
        print(f"    t={c['ts']:.3f}s  0x{c['cmd']:02x} {c['name']}{c['sub']} len={c['length']}")

    # Payload comparison for matching command types
    print(f"\n{'%'*80}")
    print(f"  PAYLOAD DIFFERENCES: Same cmd+sub but different data")
    print(f"{'%'*80}")
    # Compare payloads for commands at same position with same cmd code
    payload_diffs = []
    for i in range(min(len(golden), len(test))):
        g = golden[i]
        t = test[i]
        if g['cmd'] == t['cmd'] and g['sub'] == t['sub'] and g['hexdata'] != t['hexdata']:
            payload_diffs.append((i, g, t))
            if len(payload_diffs) <= 20:
                print(f"    Pos {i+1}: 0x{g['cmd']:02x}{g['sub']}")
                print(f"      G: {g['hexdata'][:80]}")
                print(f"      T: {t['hexdata'][:80]}")
    if not payload_diffs:
        print("    No payload differences found for aligned commands.")
    if len(payload_diffs) > 20:
        print(f"    ... and {len(payload_diffs) - 20} more")

if __name__ == '__main__':
    golden = parse_file('/Users/alex/dev/coolscan-py/reference/golden_single_bw.txt')
    test = parse_file('/Users/alex/dev/coolscan-py/test_hardware_scan_capture.txt')
    print_timeline(golden, 'GOLDEN FIXTURE OUT Commands')
    print_timeline(test, 'TEST HARDWARE CAPTURE OUT Commands')
    compare_sequences(golden, test)
