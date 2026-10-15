"""MFX for DSP1: three insert slots (DSP0 mixer group 7 index 0 / 1 / 2, NOTES "DSP0 mixer map"), each a chain
FILTER -> DRIVE (+ CRUSH) -> MOD -> DELAY. A slot's TYPE switches one block on; the others are set transparent by
their coefficients (v1.97; v1.91-1.96 had a plain LEVEL block per slot).

Slot I/O (DSP0 writes / reads GRAM, DSP1 sees it one sample later at address + 1, writes one below what DSP0 reads):
  slot 0: Roland's 58-word base program reads g[71]/g[75] into i[12]/i[18] and sends i[13]/i[19] back (g[72]/g[76])
  slot 1: in g[D1]/g[D3]  -> out g[64]/g[6C]   (DSP0 reads g[65]/g[6D])
  slot 2: in g[D5]/g[D7]  -> out g[66]/g[6E]   (DSP0 reads g[67]/g[6F])

Blocks (per slot s, channels l / r; every coefficient is a host-written field, see coefs() for the values):
  FILTER  Chamberlin state-variable filter per channel, 15-bit f and q (like S-EDIT's), out = lp*wl + bp*wb + hp*wh
          + x*dry. Off: dry 64, the rest 0.
  DRIVE   two gain stages into saturation (x1 .. x252), one-pole TONE, then CRUSH: the signal is written to delay
          RAM every sample and read back at offset (n mod N) = sample & hold for N = 2^k samples (READvar offset from a
          raw phase that wraps every N samples). out = in*dry + crushed*wet. Off: dry 64, wet 0.
  MOD     a triangle LFO (raw phase, |p| trick); gains gL = l0 + l1*tri, gR = r0 + r1*tri (half scale, through
          mulcoeff mc0 / mc1, 15-bit) = tremolo / auto-pan / ring. Off: l0 = r0 = 64, l1 = r1 = 0 (exactly x1).
  DELAY   one mono line per slot: (L+R)/2 + fb * last read -> delay RAM; read back with READvar at the smoothed
          offset V (host target = region base + D), two reads interpolated with the offset's fraction (mc6).
          out = y*dry + read*wet; the slot LEVEL is folded into dry / wet. Off: dry = level, wet 0, fb 0.

Delay RAM (128K words): READvar offsets are kept below 65536 (the range KEYS proved on the unit). Crush regions at
offsets 8 + 80 * (2s + ch) (N <= 64), delay lines above 512, split by the host between the slots whose TYPE is DELAY.
ERAM fields are not part of the program image (the loader can't write them): eram_groups() lists what the host
writes with 0x108B64 after a load (mode, offset), clear_groups() what another program must clear.

build() returns the 768-word program (DSP view) and {name: ('coef'|'eram', word)}; ours from 0x3C, 0xF1-0xFF stay nop.
"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esp

E = esp.encode
SH7, SH6, SH5, SH3 = 0, 1, 2, 3
G0, END = 0x3C, 0x2F1                                  # ours: 0x3C .. 0x2F0 (the OS puts JMP 0xF1 at 0x2F2)
SLOT_IO = [None, (0xD1, 0xD3, 0x64, 0x6C), (0xD5, 0xD7, 0x66, 0x6E)]   # GRAM in L, in R, out L, out R (slots 1, 2)
NSLOTS = 3
FS = 44100
TYPES = ['OFF', 'FILTER', 'DRIVE', 'DELAY', 'MOD']
T_OFF, T_FILTER, T_DRIVE, T_DELAY, T_MOD = range(5)
CRUSH_BASE = [[8 + 80 * (2 * s + ch) for ch in (0, 1)] for s in range(NSLOTS)]   # multiples of 8, < 512
DELAY_LO, DELAY_HI = 512, 65520                        # READvar offsets the delay lines may use
FC, FD = 0xFC, 0xFD                                    # where eramrd lands (i[F0 | p])
# IRAM per slot (even addresses; a state written at m is read next sample at m + 1)
XL, XR, LPL, BPL, HPL, LPR, BPR, HPR, FL, FR = 0, 2, 4, 6, 8, 10, 12, 14, 16, 18
D1L, D1R, TL, TR, PK, QK, DL, DR, PM, TRI, JUNK, YL, YR, V, RD = 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48
def ib(s): return 0x20 + 0x40 * s                     # slot s: i[0x20..0x5F], [0x60..0x9F], [0xA0..0xDF]


def op30(mck, acc_b=False, clear=True, flip=False, neg=False, mem=0, sh=SH7):
    assert mck in (0, 1, 2, 6), 'DSP1 has mulcoeff mc0-mc2 (+ mc6 = ERAM fraction) only'
    coef = (mck << 5) | (0x10 if flip else 0) | (0x08 if neg else 0) | (0x02 if acc_b else 0) | (0 if clear else 1)
    return E(0x30, mem, sh, coef)


class Seq:
    """Places words one after another and pads with nops for the ESP's rules: an accumulator read (store / sat /
    mulcoeff / eramvar) sees the value from 3 words before; ERAM transactions start >= 6 words apart and stay out of
    0xF1-0xFF; eramrd only between its commit (start + 10) and the next transaction's commit."""
    def __init__(self, prog, params, w=G0):
        self.prog, self.params, self.w = prog, params, w
        self.last = {'A': -99, 'B': -99}; self.estart = -99; self.pending = []   # pending reads: start words
    def _slot(self, need=0):
        self.w = max(self.w, need)
        if 0xF1 <= self.w < 0x100: self.w = 0x100
        assert self.w < END, 'program too long (%03X)' % self.w
        return self.w
    def put(self, word, name=None, kind='coef', reads=None, writes=None, eram=None, need=0):
        for acc in (reads or ''): need = max(need, self.last[acc] + 3)
        if eram:
            need = max(need, self.estart + 6)
            w = self._slot(need)
            if 0xE6 <= w < 0x100: w = self._slot(0x100)
            self.estart = w
            if eram != 0x10: self.pending.append(w)
            word |= eram << 23
        w = self._slot(need)
        assert self.prog[w] == 0, 'word %03X used twice' % w
        self.prog[w] = word
        if name: self.params[name] = (kind if not eram else 'eram', w)
        for acc in (writes or ''): self.last[acc] = w
        self.w = w + 1
        return w
    def mac(self, word, acc='A', name=None):           # acc (=|+=) input * coef: writes acc (acc may be the name)
        if acc not in ('A', 'B'): acc, name = 'A', acc
        return self.put(word, name, writes=acc)
    def pair(self, w1, w2, acc='A', n1=None, n2=None):  # a multiply and its dmac (lo7 / mulcoeff precision): adjacent
        if self.w == 0xF0: self.w = 0x100
        self.mac(w1, acc, n1); w = self.mac(w2, acc, n2)
        return w
    def rd(self, start, word, name=None, acc='A'):      # eramrd of the read started at `start` (+= into acc)
        nxt = [p for p in self.pending if p > start]
        w = self._slot(start + 11)
        if nxt: assert w < nxt[0] + 10, 'eramrd at %03X too late for the read at %03X' % (w, start)
        return self.put(word, name, writes=acc, need=w)


def big_const(seq, value, acc='A', first=False):
    """A (=|+=) value, built from the constant inputs (0x400000 / 0x10000 / 0x400 / 0x10, SH3 = x c / 8)."""
    terms = []
    for mem, unit in ((4, 0x400000 >> 3), (3, 0x10000 >> 3), (2, 0x400 >> 3), (1, 0x10 >> 3)):
        while abs(value) >= unit:
            c = max(-128, min(127, value // unit if value > 0 else -((-value) // unit)))
            terms.append((mem, c)); value -= c * unit
    assert value == 0, value
    for i, (mem, c) in enumerate(terms):
        clr = first and i == 0
        op = (0x04 if clr else 0x00) if acc == 'A' else (0x14 if clr else 0x10)
        seq.mac(E(op, mem, SH3, c & 0xFF), acc)


def build():
    prog = [0] * 0x300
    params = {}
    q = Seq(prog, params)
    for s in range(NSLOTS):
        b = ib(s)
        x = lambda m: b + m
        P = lambda n: 'm%d_%s' % (s, n)
        # ---- input -> XL / XR ----
        if s == 0:
            q.mac(E(0x04, 0x12, SH6, 64)); q.mac(E(0x14, 0x18, SH6, 64), 'B')
        else:
            il, ir, _, _ = SLOT_IO[s]
            q.mac(E(0x24, il, 1, 64)); q.mac(E(0x24, ir, 3, 64), 'B')          # GRAM: shift field bit 0 = >>6, bit 1 = B
        q.put(E(0x58, x(XL), SH7, 0), reads='A'); q.put(E(0x5C, x(XR), SH7, 0), reads='B')
        # ---- FILTER (per channel) ----
        for c, X, LP, BP, HP, F in (('l', XL, LPL, BPL, HPL, FL), ('r', XR, LPR, BPR, HPR, FR)):
            q.mac(E(0x04, x(LP) + 1, SH6, 64))
            q.pair(E(0x00, x(BP) + 1, SH7, 0), E(0x34, 0xC6, SH7, 0), 'A', P('f1' + c), P('f1l' + c))   # bp * f
            q.mac(E(0x14, x(X), SH6, 64), 'B')
            q.pair(E(0x10, x(BP) + 1, SH6, 0), E(0x34, 0xE6, SH6, 0), 'B', P('q' + c), P('ql' + c))   # bp * q (<= 0)
            q.put(E(0x58, x(LP), SH7, 0), reads='A')                           # lp'
            q.mac(E(0x10, x(LP), SH6, -64 & 0xFF), 'B')                        # hp = x - q bp - lp'
            q.put(E(0x5C, x(HP), SH7, 0), reads='B')
            q.mac(E(0x04, x(BP) + 1, SH6, 64))
            q.pair(E(0x00, x(HP), SH7, 0), E(0x34, 0xC6, SH7, 0), 'A', P('f2' + c), P('f2l' + c))
            q.put(E(0x58, x(BP), SH7, 0), reads='A')                           # bp'
            q.mac(E(0x04, x(LP), SH6, 0), 'A', P('wl' + c))
            q.mac(E(0x00, x(BP), SH6, 0), 'A', P('wb' + c))
            q.mac(E(0x00, x(HP), SH6, 0), 'A', P('wh' + c))
            q.mac(E(0x00, x(X), SH6, 64), 'A', P('fdry' + c))
            q.put(E(0x58, x(F), SH7, 0), reads='A')
        # ---- DRIVE: two gain stages, tone, then the crush write ----
        wr = {}
        for c, F, D1, T in (('l', FL, D1L, TL), ('r', FR, D1R, TR)):
            q.mac(E(0x04, x(F), SH6, 64), 'A', P('g1' + c))
            q.put(E(0x08, x(D1), SH6, 64), P('g2' + c), reads='A', writes='A')   # i[D1] = sat; A = sat * g2
            q.put(E(0x58, x(D1), SH7, 0), reads='A')
            q.mac(E(0x04, x(T) + 1, SH6, 64))
            q.mac(E(0x00, x(D1), SH7, 127), 'A', P('t' + c))                   # tone: T += t (in - T)
            q.mac(E(0x00, x(T) + 1, SH7, -127 & 0xFF), 'A', P('tn' + c))
            q.put(E(0x58, x(T), SH7, 0), reads='A')
            wr[c] = q.put(E(0x34, 0xCB, SH7, 0), P('kw' + c), reads='A', eram=0x10)   # eramwr = T; WRITE (crush)
        # crush phase: PK += inc (wraps every N samples); QK = PK / 128; var = (QK + 0x10000) * 2^(k-5) + base * 4096
        q.mac(E(0x04, x(PK) + 1, SH6, 64))
        q.mac(E(0x00, 4, SH6, 0), 'A', P('kinc'))                              # += 0x400000 * c >> 6
        q.put(E(0x44, x(PK), SH7, 1), reads='A', writes='A')                   # i[PK] = raw; A = raw / 128
        q.put(E(0x40, x(QK), SH7, 0), reads='A')
        rdk = {}
        for c, ch in (('l', 0), ('r', 1)):
            q.mac(E(0x04, x(QK), SH7, 0), 'A', P('kq' + c))
            q.mac(E(0x00, 3, SH7, 0), 'A', P('kk' + c))
            q.mac(E(0x00, 4, SH7, CRUSH_BASE[s][ch] // 8), 'A')                # + base * 4096 (= 0x400000 * base/8 >> 7)
            rdk[c] = q.put(E(0x34, 0xC7, SH7, 0), P('kr' + c), reads='A', eram=0x18)   # eramvar = A; READvar
        for c, F, DD in (('l', FL, DL), ('r', FR, DR)):
            q.mac(E(0x04, x(F), SH6, 64), 'A', P('ddry' + c))
            q.rd(rdk[c], E(0x34, 0xCC if c == 'l' else 0xCD, SH6, 0), P('dwet' + c))
            q.put(E(0x58, x(DD), SH7, 0), reads='A')
        # ---- MOD: triangle LFO, gains through mc0 / mc1 ----
        q.mac(E(0x04, x(PM) + 1, SH6, 64))
        q.mac(E(0x00, 4, SH7, 0), 'A', P('mra'))
        q.mac(E(0x00, 3, SH7, 0), 'A', P('mrb'))
        q.mac(E(0x00, 2, SH7, 0), 'A', P('mrc'))
        q.put(E(0x44, x(PM), SH6, 64), reads='A', writes='A')                  # i[PM] = raw; A = phase
        q.put(E(0x7C, x(JUNK), SH6, 127), reads='A', writes='A')               # A = |phase| * 127/64
        q.mac(E(0x00, 4, SH6, -128 & 0xFF))                                    # -= 0x800000 -> triangle
        q.put(E(0x58, x(TRI), SH7, 0), reads='A')
        q.mac(E(0x04, 4, SH6, 64), 'A', P('ml0')); q.mac(E(0x00, x(TRI), SH7, 0), 'A', P('ml1'))
        q.mac(E(0x14, 4, SH6, 64), 'B', P('mr0')); q.mac(E(0x10, x(TRI), SH7, 0), 'B', P('mr1'))
        q.put(E(0x34, 0xA0, SH7, 0), reads='A')                                # mc0 = gL (half scale)
        q.put(E(0x34, 0xA3, SH7, 0), reads='B')                                # mc1 = gR
        q.pair(op30(0, mem=x(DL), sh=SH6), E(0x34, 0xC6, SH6, 0))              # A = DL * mc0 (15 bits)
        q.pair(op30(1, acc_b=True, mem=x(DR), sh=SH6), E(0x34, 0xE6, SH6, 0), 'B')
        q.put(E(0x58, x(YL), SH7, 0), reads='A')
        q.put(E(0x5C, x(YR), SH7, 0), reads='B')
        # ---- DELAY: mono line ----
        q.mac(E(0x04, x(YL), SH6, 32)); q.mac(E(0x00, x(YR), SH6, 32))
        q.mac(E(0x00, x(RD) + 1, SH7, 0), 'A', P('efb'))
        q.put(E(0x34, 0xCB, SH7, 0), P('ew'), reads='A', eram=0x10)             # eramwr = in; WRITE at the line's base
        q.mac(E(0x04, x(V) + 1, SH6, 64))                                      # NV += (-target - NV) / 128
        q.mac(E(0x00, x(V) + 1, SH7, -1 & 0xFF))                               # (NV = -offset * 64, kept negative:
        q.mac(E(0x00, 3, SH7, 0), 'A', P('etb'))                               #  -target / 128 = -b * 512 - c * 8)
        q.mac(E(0x00, 2, SH7, 0), 'A', P('etc'))
        q.put(E(0x58, x(V), SH7, 0), reads='A')
        for k in range(4): q.mac(E(0x04 if k == 0 else 0x00, x(V), SH3, -128 & 0xFF))   # A = -16 NV x 4 = var
        e0 = q.put(E(0x34, 0xC7, SH7, 0), P('er0'), reads='A', eram=0x18)      # eramvar = var; READvar +0
        e1 = q.put(E(0x00, 0, SH7, 0), P('er1'), eram=0x18)                    # READvar +1 (imm 2)
        q.rd(e0, E(0x34, 0xCC, SH7, 0))                                        # i[FC] = sample at +0
        q.rd(e1, E(0x34, 0xCD, SH7, 0))                                        # i[FD] = sample at +1
        q.pair(op30(6, flip=True, mem=FC), E(0x34, 0xC6, SH7, 0))              # A = FC * (1 - frac)
        q.pair(op30(6, clear=False, mem=FD), E(0x34, 0xC6, SH7, 0))            # A += FD * frac
        q.put(E(0x58, x(RD), SH7, 0), reads='A')
        # ---- out: y * dry + read * wet (the slot level folded in) ----
        q.mac(E(0x04, x(YL), SH6, 64), 'A', P('odl')); q.mac(E(0x00, x(RD), SH6, 0), 'A', P('owl'))
        q.mac(E(0x14, x(YR), SH6, 64), 'B', P('odr')); q.mac(E(0x10, x(RD), SH6, 0), 'B', P('owr'))
        if s == 0:
            q.put(E(0x58, 0x13, SH7, 0), reads='A'); q.put(E(0x5C, 0x19, SH7, 0), reads='B')
        else:
            _, _, ol, orr = SLOT_IO[s]
            q.put(E(0x38, ol, SH7, 0), reads='A'); q.put(E(0x3C, orr, SH7, 0), reads='B')
    q.end = q.w
    return prog, params


# ---------------------------------------------------------------- host side: parameters -> coefficients
def osc_fields(f):
    inc = int(round(f / FS * (1 << 24)))
    o2, r = divmod(inc, 32768); o1, r = divmod(r, 512)
    assert o2 <= 127, f
    return o2, o1, r // 8


def cs(g):
    """gain g (0 .. 15.9) -> (coef, shift selector) with the best precision."""
    for shsel, sh in ((SH7, 128), (SH6, 64), (SH5, 32), (SH3, 8)):
        if g * sh <= 127.4: return max(0, min(127, int(round(g * sh)))), shsel
    return 127, SH3


def filter_f(hz):
    f = 2 * math.sin(math.pi * hz / FS)
    hi = int(f * 128); lo = int(round((f * 128 - hi) * 128))
    if lo == 128: hi, lo = hi + 1, 0
    return hi, lo


def filter_q(qv):
    """damping q (0.1 .. 2) -> (q_hi, q_lo): B += bp * q_hi >> 6 + bp * q_lo >> 13, q_hi negative."""
    t = -qv * 64
    hi = math.floor(t); lo = int(round((t - hi) * 128))
    if lo == 128: hi, lo = hi + 1, 0
    return hi, lo


FLT_MODES = ['LP', 'BP', 'HP']
MOD_MODES = ['TREMOLO', 'AUTO-PAN', 'RING']
CRUSH_NAMES = ['OFF', '22K', '11K', '5.5K', '2.8K', '1.4K', '690']
def cutoff_hz(v): return 40.0 * (6500.0 / 40.0) ** (v / 127.0)          # CUTOFF 0..127: 40 Hz .. 6.5 kHz
def reso_q(v): return 1.4 - 1.3 * (v / 127.0) ** 0.7                     # RESONANCE 0..127: q 1.4 .. 0.1
def gain_db(v): return 48.0 * v / 127.0                                  # GAIN 0..127: 0 .. 48 dB
def tone_hz(v): return 400.0 * (16000.0 / 400.0) ** (v / 127.0)          # TONE 0..127: 400 Hz .. 16 kHz
def lfo_hz(v, ring): return (30.0 * 100.0 ** (v / 127.0)) if ring else (0.1 * 200.0 ** (v / 127.0))
def delay_ms(v): return 20.0 * (1480.0 / 20.0) ** (v / 127.0)            # TIME 0..127: 20 .. 1480 ms


# ---- host tables: the firmware does exactly this (tables + a little integer math), coefs() is its model ----
def _gain(v):
    g = 10 ** (gain_db(v) / 20.0); g1 = min(g, 15.8)
    return cs(g1) + cs(g / g1) + (int(round(64 * min(1.0, 2.0 / math.sqrt(g)))),)
TAB_CUT = [filter_f(cutoff_hz(v)) for v in range(128)]                   # (f_hi, f_lo)
TAB_Q = [filter_q(reso_q(v)) for v in range(128)]                        # (q_hi, q_lo)
TAB_WB = [int(round(64 * min(1.0, reso_q(v) * 1.4))) for v in range(128)]   # BP level
TAB_GAIN = [_gain(v) for v in range(128)]                                 # (g1 coef, g1 shift, g2 coef, g2 shift, wet)
TAB_TONE = [min(127, int(round((1 - math.exp(-2 * math.pi * tone_hz(v) / FS)) * 128))) for v in range(128)]
TAB_CRUSH = [(0, 0, SH7)] + [(-128 if k == 1 else 1 << (8 - k),) + {1: (8, SH7), 2: (16, SH7), 3: (32, SH7),
             4: (64, SH7), 5: (64, SH6), 6: (64, SH5)}[k] for k in range(1, 7)]   # (inc, var coef, var shift)
TAB_LFO = [osc_fields(lfo_hz(v, False)) for v in range(128)]
TAB_RING = [osc_fields(lfo_hz(v, True)) for v in range(128)]
TAB_DQ = [int(round(32 * v / 127.0)) for v in range(128)]                # depth: 32 = full
TAB_DTIME = [int(round(delay_ms(v) * FS / 1000.0)) for v in range(128)]  # samples
TAB_FB = [int(round(v * 120 / 127.0)) for v in range(128)]
TAB_MIX = [(64 if v <= 64 else int(round(64 * (127 - v) / 63.0)), min(64, v)) for v in range(128)]   # (dry, wet)
P_MAX = {T_OFF: (127, 127, 127), T_FILTER: (2, 127, 127), T_DRIVE: (127, 127, 6), T_DELAY: (127, 127, 127),
         T_MOD: (2, 127, 127)}
P_DEFAULT = {T_OFF: (0, 0, 0), T_FILTER: (0, 64, 30), T_DRIVE: (60, 100, 0), T_DELAY: (80, 40, 40), T_MOD: (0, 80, 100)}
VIDS = ['FH', 'FL', 'QH', 'QL', 'WL', 'WB', 'WH', 'FDRY', 'G1C', 'G1S', 'G2C', 'G2S', 'T', 'TN', 'DDRY', 'DWET',
        'KINC', 'KC', 'KS', 'MRA', 'MRB', 'MRC', 'ML0', 'ML1', 'MR0', 'MR1', 'ETB', 'ETC', 'EFB', 'OD', 'OW']
VI = {n: i for i, n in enumerate(VIDS)}
VDEF = dict(FH=0, FL=0, QH=-90, QL=0, WL=0, WB=0, WH=0, FDRY=64, G1C=64, G1S=SH6, G2C=64, G2S=SH6, T=127, TN=-127,
            DDRY=64, DWET=0, KINC=0, KC=0, KS=SH7, MRA=0, MRB=0, MRC=0, ML0=64, ML1=0, MR0=64, MR1=0, ETB=0, ETC=0,
            EFB=0, OD=64, OW=0)
# (param suffix, value id, shift value id or None = the word's own shift)
ENTRIES = []
for _c in 'lr':
    ENTRIES += [('f1' + _c, 'FH', None), ('f1l' + _c, 'FL', None), ('f2' + _c, 'FH', None), ('f2l' + _c, 'FL', None),
                ('q' + _c, 'QH', None), ('ql' + _c, 'QL', None), ('wl' + _c, 'WL', None), ('wb' + _c, 'WB', None),
                ('wh' + _c, 'WH', None), ('fdry' + _c, 'FDRY', None),
                ('g1' + _c, 'G1C', 'G1S'), ('g2' + _c, 'G2C', 'G2S'), ('t' + _c, 'T', None), ('tn' + _c, 'TN', None),
                ('ddry' + _c, 'DDRY', None), ('dwet' + _c, 'DWET', None), ('kq' + _c, 'KC', 'KS'), ('kk' + _c, 'KC', 'KS'),
                ('od' + _c, 'OD', None), ('ow' + _c, 'OW', None)]
ENTRIES += [('kinc', 'KINC', None), ('mra', 'MRA', None), ('mrb', 'MRB', None), ('mrc', 'MRC', None),
            ('ml0', 'ML0', None), ('ml1', 'ML1', None), ('mr0', 'MR0', None), ('mr1', 'MR1', None),
            ('etb', 'ETB', None), ('etc', 'ETC', None), ('efb', 'EFB', None)]


def values(typ, p1, p2, p3, level=64, region=(DELAY_LO, DELAY_HI)):
    """the value vector (VIDS order) as the firmware computes it."""
    v = dict(VDEF)
    if typ == T_FILTER:
        v['FH'], v['FL'] = TAB_CUT[p2]; v['QH'], v['QL'] = TAB_Q[p3]; v['FDRY'] = 0
        if p1 == 0: v['WL'] = 64
        elif p1 == 1: v['WB'] = TAB_WB[p3]
        else: v['WH'] = 64
    elif typ == T_DRIVE:
        v['G1C'], v['G1S'], v['G2C'], v['G2S'], v['DWET'] = TAB_GAIN[p1]
        v['T'] = TAB_TONE[p2]; v['TN'] = -TAB_TONE[p2]; v['DDRY'] = 0
        v['KINC'], v['KC'], v['KS'] = TAB_CRUSH[p3]
    elif typ == T_MOD:
        v['MRA'], v['MRB'], v['MRC'] = (TAB_RING if p1 == 2 else TAB_LFO)[p2]
        dq = TAB_DQ[p3]
        if p1 == 2: v['ML0'] = v['MR0'] = 64 - 2 * dq; v['ML1'] = v['MR1'] = 2 * dq
        else: v['ML0'] = v['MR0'] = 64 - dq; v['ML1'] = -dq; v['MR1'] = dq if p1 == 1 else -dq
    base, end = region
    d, dry, wet = 2, 64, 0
    if typ == T_DELAY:
        d = max(2, min(TAB_DTIME[p1], end - base - 2)); v['EFB'] = TAB_FB[p2]; dry, wet = TAB_MIX[p3]
    half = (base + d) >> 1
    v['ETB'] = -(half >> 9); v['ETC'] = -((half & 0x1FF) >> 3)
    v['OD'] = min(127, (dry * level) >> 6); v['OW'] = min(127, (wet * level) >> 6)
    return [v[n] for n in VIDS]


def coefs(s, typ, p1, p2, p3, level=64, region=(DELAY_LO, DELAY_HI)):
    """{param name: (coef byte, shift selector or None)} for slot s (the firmware's result)."""
    vals = values(typ, p1, p2, p3, level, region)
    return {'m%d_%s' % (s, n): (vals[VI[vid]] & 0xFF, None if sid is None else vals[VI[sid]])
            for n, vid, sid in ENTRIES}


def eram_groups(s, region=(DELAY_LO, DELAY_HI)):
    """[(param name, mode, offset)] the host writes after a load (and the delay WRITE when the region changes)."""
    P = lambda n: 'm%d_%s' % (s, n)
    return [(P('kwl'), 0x10, CRUSH_BASE[s][0]), (P('kwr'), 0x10, CRUSH_BASE[s][1]),
            (P('krl'), 0x18, 0), (P('krr'), 0x18, 0),
            (P('ew'), 0x10, region[0]), (P('er0'), 0x18, 0), (P('er1'), 0x18, 2)]


def regions(types):
    """delay RAM for the slots whose TYPE is DELAY: [(base, end)] per slot (others get a dummy line)."""
    users = [s for s in range(NSLOTS) if types[s] == T_DELAY]
    out = [(480 + 8 * s, 486 + 8 * s) for s in range(NSLOTS)]                 # not DELAY: a private dummy line
    if users:
        size = (DELAY_HI - DELAY_LO) // len(users)
        for i, s in enumerate(users): out[s] = (DELAY_LO + i * size, DELAY_LO + (i + 1) * size)
    return out


def coef_value(prog, params, name, c):
    """e0 for 0x108936: coef << 8 | the word's shift selector."""
    return ((c & 0xFF) << 8) | ((prog[params[name][1]] >> 8) & 3)


def make_sim(prog):
    import keysdsp
    return keysdsp.make_sim(prog)


# ---------------------------------------------------------------- model test
def apply(core, prog, params, s, typ, p1=0, p2=0, p3=0, level=64, region=None):
    if region is None: region = regions([typ if t == s else T_OFF for t in range(NSLOTS)])[s]
    import keysdsp
    for n, (c, sh) in coefs(s, typ, p1, p2, p3, level, region).items():
        keysdsp.set_coef(core.prog, params[n][1], c, sh)
    for n, mode, off in eram_groups(s, region): keysdsp.set_eram(core.prog, params[n][1], mode, off)


def run(core, eram, s, sig, n, start=0):
    """feed sig(i) -> (l, r) into slot s for n samples, return the outputs [(l, r)]."""
    ins = {0: (0x71, 0x75), 1: (0xD1, 0xD3), 2: (0xD5, 0xD7)}[s]
    outs = {0: (0x73, 0x77), 1: (0x65, 0x6D), 2: (0x67, 0x6F)}[s]
    res = []
    for i in range(start, start + n):
        l, r = sig(i); core.wg(ins[0], int(l)); core.wg(ins[1], int(r))
        core.run_sample(); eram.tick_sample()
        res.append((core.rg(outs[0]), core.rg(outs[1])))
    return res


def selftest(verbose=True):
    prog, params = build()
    core, eram = make_sim(prog)
    A = 0x200000                                                        # -12 dB
    sine = lambda f: (lambda i: (A * math.sin(2 * math.pi * f * i / FS),) * 2)
    def pk(res, ch=0, skip=0): return round(max(abs(o[ch]) for o in res[skip:]) / A, 3)
    rep = []
    for s in range(NSLOTS):
        for t in range(NSLOTS): apply(core, prog, params, t, T_OFF)
        rep.append(('slot %d OFF (x1)' % s, pk(run(core, eram, s, sine(440), 1500), 0, 500)))
        apply(core, prog, params, s, T_OFF, level=0)
        rep.append(('slot %d level 0' % s, pk(run(core, eram, s, sine(440), 800), 0, 400)))
    s = 0
    for mode, f, want in ((0, 200, 'pass'), (0, 4000, 'cut'), (2, 200, 'cut'), (2, 4000, 'pass'), (1, 1000, 'peak')):
        apply(core, prog, params, s, T_FILTER, mode, 64, 0)            # cutoff ~ 510 Hz... (64 -> 40*162^0.5)
        rep.append(('FILTER %s cut %d Hz, %d Hz tone (%s)' % (FLT_MODES[mode], cutoff_hz(64), f, want),
                    pk(run(core, eram, s, sine(f), 3000), 0, 1500)))
    apply(core, prog, params, s, T_FILTER, 0, 64, 110)
    rep.append(('FILTER LP reso 110 at the cutoff', pk(run(core, eram, s, sine(cutoff_hz(64)), 4000), 0, 2000)))
    for g in (0, 64, 127):
        apply(core, prog, params, s, T_DRIVE, g, 127, 0)
        res = run(core, eram, s, sine(220), 2000)
        rep.append(('DRIVE gain %d (%.0f dB) peak / clip share' % (g, gain_db(g)), pk(res, 0, 1000),
                    round(sum(1 for o in res[1000:] if abs(o[0]) > 0.95 * max(abs(p[0]) for p in res[1000:])) / 1000.0, 2)))
    for k in (1, 3, 6):
        apply(core, prog, params, s, T_DRIVE, 0, 127, k)
        res = run(core, eram, s, sine(150), 1200)
        runs, last, cur = [], None, 0
        for o in res[600:]:
            if o[0] == last: cur += 1
            else:
                if last is not None: runs.append(cur)
                cur, last = 1, o[0]
        rep.append(('CRUSH %s: hold lengths' % CRUSH_NAMES[k], sorted(set(runs))[:4]))
    apply(core, prog, params, s, T_MOD, 0, 90, 127)
    res = run(core, eram, s, lambda i: (A, A), int(FS / lfo_hz(90, False) * 1.2) + 2000)[2000:]
    rep.append(('MOD TREMOLO %.1f Hz depth 127: gain min / max' % lfo_hz(90, False),
                round(min(o[0] for o in res) / A, 2), round(max(o[0] for o in res) / A, 2)))
    apply(core, prog, params, s, T_MOD, 1, 90, 127)
    res = run(core, eram, s, lambda i: (A, A), int(FS / lfo_hz(90, False) * 1.2) + 2000)[2000:]
    rep.append(('MOD AUTO-PAN L+R (constant?) min / max', round(min(o[0] + o[1] for o in res) / A, 2),
                round(max(o[0] + o[1] for o in res) / A, 2)))
    apply(core, prog, params, s, T_DELAY, 30, 0, 127)
    d = int(round(delay_ms(30) * FS / 1000))
    run(core, eram, s, lambda i: (0, 0), 3000)                         # the offset glides to its target
    imp = lambda i: (A, A) if i == 0 else (0, 0)
    res = run(core, eram, s, imp, d + 200)
    hits = [i for i, o in enumerate(res) if abs(o[0]) > A * 0.3]
    rep.append(('DELAY time %d (%.1f ms = %d samples), mix 127: echo at' % (30, delay_ms(30), d), hits[:3]))
    apply(core, prog, params, s, T_DELAY, 30, 100, 64)
    run(core, eram, s, lambda i: (0, 0), d + 500)
    res = run(core, eram, s, imp, 3 * d + 300, start=0)
    hits = [(i, round(o[0] / A, 2)) for i, o in enumerate(res) if abs(o[0]) > A * 0.05 and i > 0]
    rep.append(('DELAY feedback 100, mix 64: repeats (sample, level)', [h for h in hits if h[0] > 10][:6]))
    if verbose:
        print('program end %03X (limit %03X)' % (max(w for k, (kind, w) in params.items()) + 1, END))
        for r in rep: print('  ', *r)
    return rep


if __name__ == '__main__':
    selftest()
