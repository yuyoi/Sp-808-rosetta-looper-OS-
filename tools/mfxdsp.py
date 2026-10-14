"""MFX for DSP1: three insert slots (DSP0 mixer group 7 index 0 / 1 / 2, NOTES "DSP0 mixer map"), one block each.

v1.91 = the skeleton the sound work drops into later: every slot is a stereo LEVEL block (pass-through x level), so the
routing / controls / host hooks can be tested on the unit by ear (a slot at level 0 silences its insert point).

Slot I/O (DSP0 writes / reads GRAM, DSP1 sees it one sample later at address + 1, writes one below what DSP0 reads):
  slot 0: Roland's 58-word base program reads g[71]/g[75] into i[12]/i[18] and sends i[13]/i[19] back (g[72]/g[76])
  slot 1: in g[D1]/g[D3]  -> out g[64]/g[6C]   (DSP0 reads g[65]/g[6D])
  slot 2: in g[D5]/g[D7]  -> out g[66]/g[6E]   (DSP0 reads g[67]/g[6F])
Level coefficients (SH6): 64 = x1, 127 = x2 (+6 dB), 0 = silent. Host writes them with 0x108936 (own_coef).
build() returns the 768-word program (DSP view) and {name: ('coef', word)}; layout like keysdsp (ours from 0x3C,
0xF1-0xFF stay nop).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esp

E = esp.encode
SH7, SH6, SH5, SH3 = 0, 1, 2, 3
G0 = 0x3C
SLOT_IO = [None, (0xD1, 0xD3, 0x64, 0x6C), (0xD5, 0xD7, 0x66, 0x6E)]   # GRAM in L, in R, out L, out R (slots 1, 2)
NSLOTS = 3


def build():
    prog = [0] * 0x300
    params = {}
    def put(w, word, name=None):
        assert prog[w] == 0, 'word %03X used twice' % w
        prog[w] = word
        if name: params[name] = ('coef', w)
    w = G0
    # slot 0 through Roland's base: i[13] = inL * level, i[19] = inR * level (stores take A/B from 3 words before)
    put(w + 0, E(0x04, 0x12, SH6, 64), 'm0_l')                 # A = inL * lvl
    put(w + 1, E(0x14, 0x18, SH6, 64), 'm0_r')                 # B = inR * lvl
    put(w + 3, E(0x58, 0x13, SH7, 0))                          # i[13] = sat(A(+0))
    put(w + 4, E(0x5C, 0x19, SH7, 0))                          # i[19] = sat(B(+1))
    w += 6
    # slots 1 / 2: GRAM in -> level -> GRAM out, the same word spacing as DSP0's own slot code (0x238-0x23E)
    for s in (1, 2):
        il, ir, ol, orr = SLOT_IO[s]
        put(w + 0, E(0x24, il, 1, 64), 'm%d_l' % s)            # A = g[in L] * lvl >> 6    (GRAM op: shift field 1 = >>6)
        put(w + 2, E(0x24, ir, 1, 64), 'm%d_r' % s)            # A = g[in R] * lvl >> 6
        put(w + 3, E(0x38, ol, SH7, 0))                        # g[out L] = sat(A(+0))
        put(w + 6, E(0x38, orr, SH7, 0))                       # g[out R] = sat(A(+2))
        w += 8
    assert w < 0xF1
    return prog, params


def coef_value(prog, params, name, c):
    """e0 for 0x108936: coef << 8 | the word's shift selector."""
    return ((c & 0xFF) << 8) | ((prog[params[name][1]] >> 8) & 3)


def make_sim(prog):
    import keysdsp
    return keysdsp.make_sim(prog)


def selftest():
    """Every slot passes its input at the level, L and R kept apart; level 0 silences it."""
    import math
    prog, params = build()
    core, eram = make_sim(prog)
    def setc(name, c): w = params[name][1]; core.prog[w] = (core.prog[w] & ~0xFF) | (c & 0xFF)
    ins = {0: (0x71, 0x75), 1: (0xD1, 0xD3), 2: (0xD5, 0xD7)}
    outs = {0: (0x73, 0x77), 1: (0x65, 0x6D), 2: (0x67, 0x6F)}    # where DSP0 reads them
    res = []
    for lv in (64, 127, 32, 0):
        for s in range(NSLOTS): setc('m%d_l' % s, lv); setc('m%d_r' % s, lv)
        peak = {(s, ch): 0 for s in range(NSLOTS) for ch in (0, 1)}
        for n in range(2000):
            for s in range(NSLOTS):
                for ch in (0, 1):                               # a different tone per slot and side
                    f = 300 + 200 * s + 50 * ch
                    core.wg(ins[s][ch], int(0x200000 * math.sin(2 * math.pi * f * n / 44100)))
            core.run_sample(); eram.tick_sample()
            if n > 200:
                for s in range(NSLOTS):
                    for ch in (0, 1): peak[(s, ch)] = max(peak[(s, ch)], abs(core.rg(outs[s][ch])))
        res.append((lv, {k: round(v / 0x200000, 3) for k, v in peak.items()}))
    return res


if __name__ == '__main__':
    prog, params = build()
    esp.disasm(prog[G0:G0 + 24], core=1, start=G0)
    for lv, pk in selftest(): print('level %3d -> peak / input per (slot, side): %s' % (lv, pk))
