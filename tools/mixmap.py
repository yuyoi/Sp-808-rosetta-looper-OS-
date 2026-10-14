"""Map Roland's mixer API onto DSP words: run the stock OS's 0x11F2AE(group, index, value) in the H8S emulator for
every group / index with a few values and log which DSP0 / DSP1 coefficient words it writes.

usage: python -I tools/mixmap.py sp808_v1050_raw.bin [out.txt]
0x11F2AE: r0 = group (0-4 = channels, table 0x422018 + 0x2A * group, 21 params each; 5 = 0x4220EA, 6 = 0x4220F0,
7 = 0x422108 FX insert point, 0xFF = apply all), e0 = index, r1 = value.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h8emu, esp

MIXER_PARAM, DSP_COEF, DSP_ERAM, DSP_LOAD = 0x11F2AE, 0x108936, 0x108B64, 0x1096D2
GROUPS = [(g, 21) for g in range(5)] + [(5, 3), (6, 12), (7, 12)]
VALUES = (0, 1, 64, 100, 127)


def make_emu(image):
    e = h8emu.Emu(image[:0xC0000])
    e.code_lo, e.code_hi = 0x000000, 0x800000                # run the stock code itself (boot ROM, flash, RAM)
    dump = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dump')
    e.boot = open(os.path.join(dump, 'BOOTROM.BIN'), 'rb').read()   # math library (float / double helpers)
    rl = lambda a: int.from_bytes(image[a - 0x100000:a - 0x100000 + 4], 'big')
    src, end, dst = rl(0x12670E), rl(0x126716), rl(0x12671A)   # C startup: .data copy (RAM-resident routines)
    for i in range(end - src): e.wb(dst + i, image[src - 0x100000 + i])
    e.ram[:0x3000] = open(os.path.join(dump, 'BOOTRAM.BIN'), 'rb').read()[:0x3000]   # 0x400000-0x402FFF as the boot ROM leaves it
    a = 0x1266BC                                             # then the RAM vector table: JMP to each address
    while rl(a) != 0xFFFFFFFF:
        e.wl(rl(a), rl(a + 4) | 0x5A000000); a += 8
    e.log = []
    def coef(e): e.log.append(('coef', e.g16(0), e.g16(8)))
    def eram(e): e.log.append(('eram', e.g16(0), e.g32(1)))
    def load(e): e.log.append(('load', e.g16(0), e.g16(8), e.g16(1)))
    e.stubs[DSP_COEF] = coef; e.stubs[DSP_ERAM] = eram; e.stubs[DSP_LOAD] = load
    return e


def run(e, group, index, value):
    e.log = []
    before = bytes(e.ram[:0x40000])                          # 0x400000-0x43FFFF (stack at 0x43F000 excluded below)
    hw0 = bytes(e.hw)
    e.s16(0, group); e.er[0] = (e.er[0] & 0xFFFF) | (index << 16); e.s16(1, value)
    e.steps = 0
    try:
        e.call(MIXER_PARAM, limit=200_000)
    except RuntimeError as x:
        return None, str(x)
    after = e.ram[:0x40000]
    ch = [a for a in range(0x3E000) if before[a] != after[a]]
    if ch: e.log.append(('ram', ch))
    hch = [a for a in range(len(hw0)) if hw0[a] != e.hw[a]]
    if hch: e.log.append(('hw', [(0xC00000 + a, e.hw[a]) for a in hch]))
    return list(e.log), None


def fmt(w):
    kind = w[0]
    if kind == 'coef':
        addr, val = w[1], w[2]
        chip = 'DSP1' if addr & 0x1000 else 'DSP0'
        return '%s w%03X=%04X' % (chip, (addr & 0xFFC) >> 2, val)
    if kind == 'eram':
        return '%s eram w%03X %08X' % ('DSP1' if w[1] & 0x1000 else 'DSP0', (w[1] & 0xFFC) >> 2, w[2])
    if kind == 'ram':
        runs, a0 = [], None
        for a in w[1]:
            if a0 is not None and a == prev + 1: prev = a; continue
            if a0 is not None: runs.append((a0, prev))
            a0 = prev = a
        runs.append((a0, prev))
        return 'ram ' + ','.join('%06X' % (0x400000 + x) if x == y else '%06X-%X' % (0x400000 + x, 0x400000 + y)
                                 for x, y in runs)
    if kind == 'hw':
        return 'hw ' + ' '.join('%06X=%02X' % x for x in w[1][:24])
    return 'load chip %d start %X n %d' % w[1:]


SHADOW = {0: 0x410362, 1: 0x410F62}                          # RAM copies of DSP0 / DSP1 program words


def shadow(e, chip):
    b = SHADOW[chip] - 0x400000
    r = e.ram                                                # bytes 0-2 = ROM order (coef first), byte 3 = ERAM bits
    return [esp.rom_to_dsp((r[b + 4 * w] << 16) | (r[b + 4 * w + 1] << 8) | r[b + 4 * w + 2]) | (r[b + 4 * w + 3] << 24)
            for w in range(0x300)]


def main(path, out=None, dis=None):
    image = open(path, 'rb').read()
    e = make_emu(image)
    for chip, src, n in ((0, 0x151FE2, 757), (1, 0x1528C1, 58)):   # the shadows hold the loaded programs
        for w in range(n):
            for k in range(3): e.wb(SHADOW[chip] + 4 * w + k, image[src - 0x100000 + 3 * w + k])
    run(e, 0xFF, 0, 0)                                       # "apply all" once so every word has its idle value
    names = {}
    if dis:                                                  # optional disassembly: show what each word does
        for ln in open(dis, encoding='utf-8-sig'):
            if len(ln) > 4 and ln[3] == ':':
                try: names[int(ln[:3], 16)] = ln[4:].strip()
                except ValueError: pass
    vals = (0, 1, 16, 32, 64, 96, 127)
    lines = []
    for group, n in GROUPS:
        for index in range(n):
            snaps, other = [], set()
            vals = tuple(range(16)) if group == 7 or (group, index) == (6, 11) else (0, 1, 16, 32, 64, 96, 127)
            for v in vals:
                log, err = run(e, group, index, v)
                if err: other.add(err); snaps.append(None); continue
                snaps.append((shadow(e, 0), shadow(e, 1)))
                for w in log:
                    if w[0] == 'ram':
                        other.update('%06X' % (0x400000 + a) for a in w[1] if not 0x10362 <= a < 0x11B62)
            good = [x for x in snaps if x]
            diff = [(c, w) for c in (0, 1) for w in range(0x300) if len({x[c][w] for x in good}) > 1]
            lines.append('g%d i%02d: %s values %s  other RAM %s' % (group, index, 'words %d' % len(diff) if diff else '-',
                                                          ','.join(map(str, vals)),
                                                          ' '.join(sorted(other))[:120]))
            for c, w in diff:
                vs = ' '.join('%07X' % x[c][w] if x else '-------' for x in snaps)
                last = [x for x in snaps if x][-1][c][w]
                lines.append('    DSP%d %03X: %s  | %s' % (c, w, vs, esp.disasm_word(last & 0x7FFFFFF, w, core=c)))
    text = chr(10).join(lines)
    print(text)
    if out: open(out, 'w').write(text + chr(10))


if __name__ == '__main__':
    main(*sys.argv[1:])
