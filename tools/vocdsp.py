"""VOICE for DSP1 (v2.0, MFX lane): a voice chain (the EX Vocal Multi blocks the user picked: noise suppressor,
limiter + de-esser, enhancer, 3-band EQ = everything the EX "VO:Narrat." preset uses) feeding a vocoder. Written from
scratch after reading the EX 1.001 algorithms (fx22 Vocal Multi, fx24 Vocoder(10): 10 bands of cascaded 2-pole
band-passes, abs envelope, mc0 VCA); ours has more bands, 2-pole / 4-pole, formant shift and a level per band.

I/O (Roland's 58-word base program, like MFX slot 0): FX send L = i[12] = modulator (mic / LINE L, the send pan
routes it), FX send R = i[18] = carrier (pads / LINE R); out i[13] / i[19].

Vocoder = NHB half-bands. A half-band is one 2-pole state-variable band-pass per path (modulator, carrier), an
envelope of the modulator band and a VCA (mc0) on the carrier band. FILTER 2-POLE: every half-band is a band.
4-POLE: half-bands pair up, the odd one's inputs are the even one's band-pass outputs (coefficients ia / ib) and only
its VCA sounds = NHB / 2 bands of 4-pole. SVF (Chamberlin, no hp temp): lp' = lp + f bp; bp' = bp (1 - f q) + f in
- f lp', with the input term scaled by q (unity peak gain). Envelope: e += ka rect(|x| - e) + kr min(0, |x| - e) (attack / release), x = band * level.

build() returns the 768-word program and {name: ('coef', word)} (no ERAM). Ours from 0x3C, 0xF1-0xFF stay nop.
"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esp
from mfxdsp import Seq, op30, E, SH7, SH6, SH5, SH3, G0, END, FS

NHB = 14                                               # half-bands: 14 fit (20 words left), 15 does not
IO_ML, IO_CR, IO_OL, IO_OR = 0x12, 0x18, 0x13, 0x19
# IRAM (Roland's base program uses 0x05-0x1B; no ERAM here, so FC-FF are free): states read last sample's value at
# m + 1, so they take 2 addresses; same-sample temps take 1, in a region of their own at the top.
(NSE, NSG, LMG, DSH, DSE, EQ1L, EQ2L, EQ2B, EQ3L, HPM) = [0x1C + 2 * i for i in range(10)]
HB0 = 0x1C + 20
def hb_base(h): return HB0 + 10 * h                    # per half-band: MLP MBP CLP CBP ENV (x2)
MLP, MBP, CLP, CBP, ENV = 0, 2, 4, 6, 8
TEMPS = list(range(0xFF, 0xFF - 18, -1))
X0, LMY, ENX, MX, CX, SL, SR, D, U, ENH = TEMPS[:10]
TMP = TEMPS[10:18]                                      # rotating band temps
assert hb_base(NHB) <= min(TEMPS), 'IRAM layout'


def fine_hb(nhb): return (nhb // 2) & ~1                # half-bands below this use 15-bit filter coefficients


def svf(q, P, xin, xin2, lp, bp, pre, fine=True):
    """one SVF band-pass step. xin (, xin2 when given: the 4-pole input select) = same-sample input addresses.
    fine: 15-bit coefficients (pairs: hi word + dmac lo7); else 8-bit SH7 words (the upper half-bands)."""
    def term(acc, mem, n):
        op, dm = (0x00, 0xC6) if acc == 'A' else (0x10, 0xE6)
        if fine: q.pair(E(op, mem, SH7, 0), E(0x34, dm, SH7, 0), acc, P(pre + n), P(pre + n + 'l'))
        else: q.mac(E(op, mem, SH7, 0), acc, P(pre + n))
    q.mac(E(0x04, lp + 1, SH6, 64))                                                # A = lp
    term('A', bp + 1, 'f')                                                         # + f bp
    q.put(E(0x58, lp, SH7, 0), reads='A')                                          # lp'
    q.mac(E(0x14, bp + 1, SH6, 64), 'B')                                           # B = bp
    term('B', bp + 1, 'g')                                                         # - f q bp
    term('B', xin, 'a')                                                            # + f a in
    if xin2 is not None: term('B', xin2, 'b')                                      # + f b in2 (4-pole)
    term('B', lp, 'n')                                                             # - f lp'
    q.put(E(0x5C, bp, SH7, 0), reads='B')                                          # bp'


def onepole(q, name, x, y, acc='A'):
    """y += k (x - y), k 15-bit (pairs): y' = y + k x - k y."""
    c0, c1 = (0x04, 0x00) if acc == 'A' else (0x14, 0x10)
    dm = 0xC6 if acc == 'A' else 0xE6
    q.mac(E(c0, y + 1, SH6, 64), acc)
    q.pair(E(c1, x, SH7, 0), E(0x34, dm, SH7, 0), acc, name + 'k', name + 'kl')
    q.pair(E(c1, y + 1, SH7, 0), E(0x34, dm, SH7, 0), acc, name + 'n', name + 'nl')
    q.put(E(0x58 if acc == 'A' else 0x5C, y, SH7, 0), reads=acc)


def build(nhb=NHB):
    prog = [0] * 0x300
    params = {}
    q = Seq(prog, params)
    P = lambda n: 'v_' + n
    # ---- inputs: mic sens / synth in level ----
    q.mac(E(0x04, IO_ML, SH6, 64), 'A', P('msens')); q.mac(E(0x14, IO_CR, SH6, 64), 'B', P('cin'))
    q.put(E(0x58, X0, SH7, 0), reads='A'); q.put(E(0x5C, CX, SH7, 0), reads='B')
    # ---- NS: env of |x| (one-pole), gain = sat((env - thr) * K) smoothed -> mc1 ----
    q.mac(E(0x04, X0, SH6, 64))                                                    # env: fast attack, RELEASE
    q.put(E(0x7C, D, SH6, 1), reads='A', writes='A')                              # A = |x| / 64
    q.mac(E(0x00, NSE + 1, SH6, -1 & 0xFF))                                        # - e / 64
    q.put(E(0x58, D, SH7, 0), reads='A'); q.put(E(0x48, U, SH7, 0), reads='A')    # d, rect(d)
    q.mac(E(0x04, NSE + 1, SH6, 64))
    q.mac(E(0x00, D, SH7, 0), 'A', P('nsr'))                                       # + kr d
    q.mac(E(0x00, U, SH7, 0), 'A', P('nsa'))                                       # + (ka - kr) rect(d)
    q.put(E(0x58, NSE, SH7, 0), reads='A')
    q.mac(E(0x04, NSE, SH3, 0), 'A', P('nsk')); q.mac(E(0x00, 4, SH6, 0), 'A', P('nst'))   # (env K - thr)
    q.put(E(0x4C, U, SH7, 0), reads='A', writes='A')                              # i[U] = max(0, .); A = 0
    onepole(q, P('nsg'), U, NSG)                                                   # gate gain, smoothed (release)
    q.mac(E(0x04, NSG, SH6, 64), 'A', P('nsoff'))                                  # NS off: + 1 (coef via nsoff)
    q.mac(E(0x00, 4, SH6, 0), 'A', P('nson'))
    q.put(E(0x34, 0xA2, SH7, 0), reads='A')                                        # mc1 = gate
    q.pair(op30(1, mem=X0, sh=SH6), E(0x34, 0xC6, SH6, 0))                        # A = x * gate
    q.put(E(0x58, ENX, SH7, 0), reads='A')                                         # (reuse ENX as stage out)
    # ---- limiter (feedback AGC on y): g += ka (1 - g) - kr rect(|y| - thr); y = x g * level ----
    q.mac(E(0x04, LMG + 1, SH6, 64))                                               # A = g
    q.put(E(0x34, 0xA0, SH7, 0), reads='A')                                        # mc0 = g
    q.pair(op30(0, mem=ENX, sh=SH6), E(0x34, 0xC6, SH6, 0))                       # A = x g
    q.put(E(0x58, LMY, SH7, 0), reads='A')
    q.mac(E(0x04, LMY, SH6, 64))
    q.put(E(0x7C, D, SH6, 64), reads='A', writes='A')                             # A = |y|
    q.mac(E(0x00, 4, SH6, 0), 'A', P('lmt'))                                       # - thr
    q.put(E(0x4C, U, SH7, 0), reads='A', writes='A')                              # i[U] = rect(|y| - thr)
    q.mac(E(0x04, LMG + 1, SH6, 64))
    q.pair(E(0x00, LMG + 1, SH7, 0), E(0x34, 0xC6, SH7, 0), 'A', P('lma'), P('lmal'))   # - ka g (15-bit)
    q.pair(E(0x00, 4, SH7, 0), E(0x34, 0xC6, SH7, 0), 'A', P('lmb'), P('lmbl'))         # + ka 0x400000
    q.mac(E(0x00, U, SH6, 0), 'A', P('lmr'))                                       # - kr rect (attack)
    q.put(E(0x58, LMG, SH7, 0), reads='A')
    # ---- shared high band hf = y - lp1(y) (one-pole at FREQ): the de-esser and the enhancer both use it ----
    onepole(q, P('dsl'), LMY, DSH)
    q.mac(E(0x04, LMY, SH6, 64)); q.mac(E(0x00, DSH, SH6, -64 & 0xFF))
    q.put(E(0x58, ENH, SH7, 0), reads='A')                                         # hf
    q.mac(E(0x04, ENH, SH6, 64))
    q.put(E(0x7C, D, SH6, 64), reads='A', writes='A')                             # |hf|
    q.put(E(0x58, U, SH7, 0), reads='A')
    onepole(q, P('dse'), U, DSE)                                                   # de-esser envelope
    q.mac(E(0x04, DSE, SH3, 0), 'A', P('dsk')); q.mac(E(0x00, 4, SH6, 0), 'A', P('dst'))   # env SENS - thr
    q.put(E(0x4C, U, SH7, 0), reads='A', writes='A')                              # i[U] = amount (>= 0)
    q.mac(E(0x04, U, SH6, 0), 'A', P('dsoff'))                                     # (0 = de-esser off)
    q.put(E(0x34, 0xA2, SH7, 0), reads='A')                                        # mc1 = amount
    q.mac(E(0x04, ENH, SH6, 0), 'A', P('ens'))                                     # hf * enhancer sens
    q.put(E(0x7C, D, SH6, 64), reads='A', writes='A')                             # |hf s|
    q.put(E(0x34, 0xA0, SH7, 0), reads='A')                                        # mc0 = |hf s|
    q.mac(E(0x04, LMY, SH5, 0), 'A', P('lmv'))                                     # y * LMT level (<= +12 dB)
    q.pair(op30(1, clear=False, neg=True, mem=ENH, sh=SH6), E(0x34, 0xC6, SH6, 0)) # - hf amount (de-ess)
    q.pair(op30(0, clear=False, mem=ENH, sh=SH6), E(0x34, 0xC6, SH6, 0))          # + hf |hf s| (harmonics)
    q.mac(E(0x00, ENH, SH6, 0), 'A', P('enm'))                                     # + hf * enhancer mix
    q.put(E(0x58, MX, SH7, 0), reads='A')
    # ---- EQ: low shelf (one-pole lp), high shelf (x - one-pole lp), mid peak (SVF band-pass) ----
    onepole(q, P('e0'), MX, EQ1L)
    onepole(q, P('e2'), MX, EQ3L)
    svf(q, P, MX, None, EQ2L, EQ2B, 'e1')
    q.mac(E(0x04, MX, SH5, 32), 'A', P('eqx'))                                     # x (1 + gH - 1)
    q.mac(E(0x00, EQ1L, SH5, 0), 'A', P('eql'))                                    # + (gL - 1) lp_low
    q.mac(E(0x00, EQ3L, SH5, 0), 'A', P('eqh'))                                    # - (gH - 1) lp_high
    q.mac(E(0x00, EQ2B, SH5, 0), 'A', P('eqm'))                                    # + (gM - 1) q bp_mid
    q.put(E(0x58, ENX, SH7, 0), reads='A')                                         # = the modulator VM
    # ---- vocoder ----
    vout = []
    for h in range(nhb):
        b = hb_base(h); x = lambda m: b + m
        pv = hb_base(h - 1) if h % 2 else None
        Pp = lambda n, h=h: 'v_h%d_%s' % (h, n)
        fine = h < fine_hb(nhb)
        svf(q, Pp, ENX, (pv + MBP) if pv is not None else None, x(MLP), x(MBP), 'm', fine)
        svf(q, Pp, CX, (pv + CBP) if pv is not None else None, x(CLP), x(CBP), 'c', fine)
        t, t2 = TMP[(2 * h) % 8], TMP[(2 * h + 1) % 8]
        # envelope at 1/64 scale so 8-bit SH7 rates give k = c / 8192: d = |x lv| / 64 - e / 64
        q.mac(E(0x04, x(MBP), SH6, 0), 'A', Pp('lv'))
        q.put(E(0x7C, t, SH6, 1), reads='A', writes='A')                          # A = |x lv| / 64
        q.mac(E(0x00, x(ENV) + 1, SH6, -1 & 0xFF))                                 # - e / 64
        q.put(E(0x58, t, SH7, 0), reads='A')                                       # d
        q.put(E(0x48, t2, SH7, 0), reads='A')                                      # rect(d)
        q.mac(E(0x04, x(ENV) + 1, SH6, 64))
        q.mac(E(0x00, t, SH7, 0), 'A', Pp('kr'))                                   # + kr d
        q.mac(E(0x00, t2, SH7, 0), 'A', Pp('ka'))                                  # + (ka - kr) rect(d)
        q.put(E(0x58, x(ENV), SH7, 0), reads='A')
        q.put(E(0x34, 0xA0, SH7, 0), reads='A')                                    # mc0 = e
        side = SL if h % 4 in (0, 3) else SR                                       # L R R L ..: 4-pole (odd) alternates too
        q.pair(op30(0, mem=x(CBP), sh=SH5), E(0x34, 0xC6, SH5, 0))                # A = carrier band * e * 2
        if h >= 2: q.mac(E(0x00, side, SH6, 64))                                   # + running sum
        q.put(E(0x58, side, SH7, 0), reads='A')
    # ---- mic mix (hp of the processed mic) + outputs: L = SL a + SR b + mic, R = SL c + SR d + mic ----
    onepole(q, P('hpl'), ENX, HPM)
    q.mac(E(0x04, ENX, SH6, 0), 'A', P('mml')); q.mac(E(0x00, HPM, SH6, 0), 'A', P('mmln'))
    q.put(E(0x58, D, SH7, 0), reads='A')                                           # mic mix L share
    q.mac(E(0x04, SL, SH6, 64), 'A', P('oll')); q.mac(E(0x00, SR, SH6, 64), 'A', P('olr'))
    q.mac(E(0x00, D, SH6, 64), 'A', P('oml'))
    q.mac(E(0x14, SL, SH6, 64), 'B', P('orl')); q.mac(E(0x10, SR, SH6, 64), 'B', P('orr'))
    q.mac(E(0x10, D, SH6, 64), 'B', P('omr'))
    q.put(E(0x58, IO_OL, SH7, 0), reads='A'); q.put(E(0x5C, IO_OR, SH7, 0), reads='B')
    for il, ir, ol, orr in ((0xD1, 0xD3, 0x64, 0x6C), (0xD5, 0xD7, 0x66, 0x6E)):    # MFX slots 2 / 3 pass through
        q.mac(E(0x24, il, 1, 64)); q.mac(E(0x24, ir, 3, 64), 'B')                  #  (DSP0 may still insert them)
        q.put(E(0x38, ol, SH7, 0), reads='A'); q.put(E(0x3C, orr, SH7, 0), reads='B')
    T = q.finish()
    return prog, params


if __name__ == '__main__' and '--test' not in sys.argv:
    for n in (12, 13, 14, 15, 16):
        try:
            p, pa = build(n)
            used = [w for w in range(G0, END) if not 0xF1 <= w < 0x100]
            last = max(w for w in used if p[w])
            print('half-bands %2d: last word %03X, %d words free, nops inside %d' % (
                n, last, END - 1 - last, sum(1 for w in used if w <= last and not p[w])))
        except AssertionError as e:
            print('half-bands %2d: %s' % (n, e))


# ---------------------------------------------------------------- host side: UI params -> coefficients
# The firmware does exactly this: table lookups + a few integer ops (mulxu.w, shifts). values() is its model.
FMAX15 = 14746                                         # SVF f ceiling 0.9 (x 2^14)
def f15(hz): return min(FMAX15, int(round(2 * math.sin(math.pi * min(hz, FS * 0.24) / FS) * 16384)))
def kpole(hz): return 1 - math.exp(-2 * math.pi * hz / FS)
def ktime(ms): return 1 - math.exp(-1000.0 / (ms * FS))
def db(g): return 10 ** (g / 20.0)
def sat8(v): return max(-128, min(127, int(round(v))))
def hl15(t):                                           # 15-bit value (x 2^14) -> (hi, lo7) = SH7 coef + dmac
    t = max(-16384, min(16383, t)); return t >> 7, t & 0x7F
def c8(t):                                             # 15-bit value -> 8-bit SH7 coef (round half up on |t|)
    m = min(127, (abs(t) + 64) >> 7); return -m if t < 0 else m
def k4(k): return hl15(int(round(k * 16384))) + hl15(-int(round(k * 16384)))   # one-pole (k, kl, n, nl)

# ---- tables (the firmware's flash tables are these lists) ----
KG = 105                                               # semitone grid 30 Hz * 2^(i/12), i = 0..104
TAB_FG = [f15(30.0 * 2 ** (i / 12.0)) for i in range(KG)]
def band_idx(n):                                       # n bands -> semitone indices (120 Hz .. 6 kHz)
    if n == 1: return [61]
    return [int(round(24 + b * 68.0 / (n - 1))) for b in range(n)]
TAB_BIDX = [band_idx(n) + [0] * (NHB - n) for n in range(1, NHB + 1)]
def _qb(four, n):                                      # band damping for n bands at RESO 0 width 1 (x 2^14)
    r = (6000.0 / 120.0) ** (1.0 / max(1, n - 1)) if n > 1 else 4.0
    return min(65535, int(round((r ** 0.5 - r ** -0.5) * (1.55 if four else 1.0) * 16384)))
TAB_QB = [[_qb(fo, n) for n in range(1, NHB + 1)] for fo in (0, 1)]
TAB_QW = [int(round((1.6 - 1.2 * r / 100.0) * 16384)) for r in range(101)]   # RESO -> width (x 2^14)
QMAX = 31130                                           # q <= 1.9
def band_q(fo, n, reso): return min(QMAX, (TAB_QB[fo][n - 1] * TAB_QW[reso]) >> 14)
LVG = 127                                              # band level = BAND n * LVG >> 7 (bands have unity peak gain)
TAB_KA = [max(1, min(127, int(round(ktime(1 + 0.99 * v) * 8192)))) for v in range(101)]
TAB_KR = [max(1, min(127, int(round(ktime(5 + 1.75 * v) * 8192)))) for v in range(101)]
TAB_NSR = [max(1, min(127, int(round(ktime(10 + 1.7 * v) * 8192)))) for v in range(101)]
TAB_NST = [sat8(-0x800000 * db(-90 + 0.66 * v) * 15.9 / 65536) for v in range(101)]
NSG4 = k4(ktime(2.0)); DSE4 = k4(ktime(2.0))
TAB_LMT = [sat8(-0x800000 * db(v - 60) / 65536) for v in range(61)]            # lm_thr 0..60 = -60..0 dB
TAB_LMREL = [k4(ktime(10 * 200 ** (v / 100.0)))[:2] for v in range(101)]      # (hi, lo) of k: lma = -k, lmb = k
LMOFF = k4(ktime(10))[:2]
TAB_LMV = [sat8(32 * db(v - 60)) for v in range(73)]                          # lm_level 0..72 = -60..+12 dB
TAB_DSL = [k4(kpole(100.0 * v)) for v in range(101)]                          # ds_freq 10..100 (x 100 Hz)
TAB_DST = [sat8(-0x800000 * db(-6 - 0.4 * v) * 15.9 / 65536) for v in range(101)]
def lf_hz(v): return 10.0 * v                                                 # eq_lf 2..200 (x 10 Hz)
def mf_hz(v): return 200.0 * 40.0 ** (v / 127.0)                              # eq_mf 0..127 = 200 Hz .. 8 kHz
def hf_hz(v): return 100.0 * v                                                # eq_hf 14..200 (x 100 Hz)
TAB_E0 = [k4(kpole(lf_hz(max(2, v)))) for v in range(201)]
TAB_E2 = [k4(kpole(hf_hz(max(14, v)))) for v in range(201)]
TAB_MF = [f15(mf_hz(v)) for v in range(128)]
TAB_QM8 = [int(round(256 * 10.0 / max(3, v))) for v in range(161)]            # eq_mq 3..160 = Q 0.3..16
TAB_EQX = [[sat8(32 * db(o - 12) * db(h - 12)) for h in range(25)] for o in range(25)]
TAB_EQL = [[sat8(32 * db(o - 12) * (db(g - 12) - 1)) for g in range(25)] for o in range(25)]
TAB_EQH = [[sat8(-32 * db(o - 12) * (db(h - 12) - 1)) for h in range(25)] for o in range(25)]
TAB_EQM = [[int(round(32 * db(o - 12) * (db(g - 12) - 1) * 64)) for g in range(25)] for o in range(25)]   # signed Q6
TAB_HPL = [k4(kpole(20 + 30 * v)) for v in range(101)]
TAB_PAN = [(sat8(64 * math.cos(math.pi / 2 * p / 127.0) * 1.41), sat8(64 * math.sin(math.pi / 2 * p / 127.0) * 1.41))
           for p in range(128)]

# ---- UI (bytes as the firmware keeps them; signed rows are offsets) ----
UI_ROWS = [  # (key, lo, hi, default)
    ('ns_sw', 0, 1, 0), ('ns_thr', 0, 100, 30), ('ns_rel', 0, 100, 30),
    ('lm_sw', 0, 1, 0), ('lm_level', 0, 72, 60), ('lm_thr', 0, 60, 40), ('lm_rel', 0, 100, 50),
    ('ds_sens', 0, 100, 0), ('ds_freq', 10, 100, 50),
    ('en_sw', 0, 1, 0), ('en_sens', 0, 100, 10), ('en_mix', 0, 100, 30),
    ('eq_sw', 0, 1, 0), ('eq_lg', 0, 24, 12), ('eq_lf', 2, 200, 10), ('eq_mg', 0, 24, 12), ('eq_mf', 0, 127, 60),
    ('eq_mq', 3, 160, 10), ('eq_hg', 0, 24, 12), ('eq_hf', 14, 200, 50), ('eq_out', 0, 24, 12),
    ('preset', 0, 2, 0), ('filt', 0, 1, 0), ('bands', 1, NHB, NHB), ('formant', 0, 48, 24), ('reso', 0, 100, 50),
    ('attack', 0, 100, 10), ('release', 0, 100, 30), ('hold', 0, 1, 0), ('mic_sens', 0, 100, 80),
    ('synth_in', 0, 100, 80), ('mm_lev', 0, 100, 0), ('mm_pan', 0, 127, 64), ('mm_hpf', 0, 100, 40),
    ('out_mode', 0, 1, 0), ('level', 0, 127, 100)] + [('vchar%d' % i, 0, 100, 70) for i in range(NHB)]
UI_KEYS = [r[0] for r in UI_ROWS]
UI_DEFAULT = {k: d for k, lo, hi, d in UI_ROWS}
def mf_idx(roland):                                    # EX Mid Freq 20..800 (x 10 Hz) -> eq_mf 0..127
    return max(0, min(127, int(round(127 * math.log(10.0 * roland / 200.0) / math.log(40.0)))))
PRESET_NAMES = ['VC MONO', 'VC STEREO', 'NARRATOR']
PRESETS = {                                            # EX 1.001 values (VC:Mono / VC:Stereo, VO:Narrat.)
    'VC MONO': dict(mic_sens=80, synth_in=80, mm_lev=0, mm_pan=64, mm_hpf=40, out_mode=0, attack=5, release=20,
                    **{'vchar%d' % i: 70 for i in range(NHB)}),
    'VC STEREO': dict(mic_sens=80, synth_in=80, mm_lev=0, mm_pan=64, mm_hpf=40, out_mode=1, attack=20, release=60,
                      **{'vchar%d' % i: 70 for i in range(NHB)}),
    'NARRATOR': dict(ns_sw=0, lm_sw=1, lm_level=60 + 12, lm_thr=60 - 24, lm_rel=90, ds_sens=30, ds_freq=50, en_sw=0,
                     eq_sw=1, eq_lg=12 - 3, eq_lf=10, eq_mg=12 + 6, eq_mf=mf_idx(20), eq_mq=20, eq_hg=12 + 3,
                     eq_hf=50, eq_out=12, mic_sens=80, synth_in=80, out_mode=1, attack=20, release=60,
                     **{'vchar%d' % i: 70 for i in range(NHB)}),
}
def preset_ui(i):
    u = dict(UI_DEFAULT); u.update(PRESETS[PRESET_NAMES[i]]); u['preset'] = i; return u


def band_layout(u):
    """[(half-band, fm15, fc15, stage2, sounding)], n. 4-POLE: half-band h is stage 1 (even) / 2 (odd) of band h // 2
    (a stage-2 half-band takes the stage-1 outputs, by parity, active or not); sounding = active and not stage 1."""
    four = u['filt'] == 1
    n = max(1, min(u['bands'], NHB // 2 if four else NHB))
    idx = TAB_BIDX[n - 1]
    out = []
    for h in range(NHB):
        b = h // 2 if four else h
        active = b < n
        k = idx[b] if active else 61
        kc = max(0, min(KG - 1, k + u['formant'] - 24))
        out.append((h, TAB_FG[k], TAB_FG[kc], four and h % 2 == 1, active and (not four or h % 2 == 1)))
    return out, n


def values(ui=None):
    """{param name: coef byte} for the whole program (the firmware's result for these UI bytes)."""
    u = dict(UI_DEFAULT); u.update(ui or {})
    v = {}
    P = lambda n: 'v_' + n
    def put4(n, t): v[n + 'k'], v[n + 'kl'], v[n + 'n'], v[n + 'nl'] = t
    v[P('msens')], v[P('cin')] = min(127, u['mic_sens']), min(127, u['synth_in'])
    v[P('nsr')] = TAB_NSR[u['ns_rel']]; v[P('nsa')] = 127 - v[P('nsr')]
    v[P('nsk')] = 127; v[P('nst')] = TAB_NST[u['ns_thr']]; put4(P('nsg'), NSG4)
    v[P('nsoff')], v[P('nson')] = (32, 0) if u['ns_sw'] else (0, 64)
    v[P('lmr')] = -16
    if u['lm_sw']:
        v[P('lmt')] = TAB_LMT[u['lm_thr']]; hi, lo = TAB_LMREL[u['lm_rel']]; v[P('lmv')] = TAB_LMV[u['lm_level']]
        v[P('dsoff')] = 32 if u['ds_sens'] else 0
    else:
        v[P('lmt')] = -127; hi, lo = LMOFF; v[P('lmv')] = 32; v[P('dsoff')] = 0
    v[P('lmb')], v[P('lmbl')] = hi, lo
    v[P('lma')], v[P('lmal')] = hl15(-((hi << 7) | lo))
    put4(P('dsl'), TAB_DSL[u['ds_freq']]); put4(P('dse'), DSE4); v[P('dsk')] = 127; v[P('dst')] = TAB_DST[u['ds_sens']]
    v[P('ens')], v[P('enm')] = ((127 * u['en_sens']) // 100, (64 * u['en_mix']) // 100) if u['en_sw'] else (0, 0)
    put4(P('e0'), TAB_E0[u['eq_lf']]); put4(P('e2'), TAB_E2[u['eq_hf']])
    F = TAB_MF[u['eq_mf']]; q8 = TAB_QM8[u['eq_mq']]
    for nm, t in (('f', F), ('g', -min(16383, (F * q8) >> 8)), ('a', F), ('n', -F)):
        v[P('e1' + nm)], v[P('e1' + nm + 'l')] = hl15(t)
    if u['eq_sw']:
        o = u['eq_out']
        v[P('eqx')] = TAB_EQX[o][u['eq_hg']]; v[P('eql')] = TAB_EQL[o][u['eq_lg']]; v[P('eqh')] = TAB_EQH[o][u['eq_hg']]
        m = TAB_EQM[o][u['eq_mg']]; mm = min(127, (abs(m) * q8 + 8192) >> 14)
        v[P('eqm')] = -mm if m < 0 else mm
    else:
        v[P('eqx')], v[P('eql')], v[P('eqh')], v[P('eqm')] = 32, 0, 0, 0
    lay, n = band_layout(u)
    fo = u['filt']; q = band_q(fo, n, u['reso'])
    ka = 0 if u['hold'] else TAB_KA[u['attack']]; kr = 0 if u['hold'] else TAB_KR[u['release']]
    fb = fine_hb(NHB)
    for h, fm, fc, st2, snd in lay:
        Pp = lambda n_, h=h: 'v_h%d_%s' % (h, n_)
        for path, F_ in (('m', fm), ('c', fc)):
            fq = min(16383, (F_ * q) >> 14)                                # f q: damping and the input scale
            terms = [('f', F_), ('g', -fq), ('a', 0 if st2 else fq), ('n', -F_)]   # (input * q = unity peak)
            if h % 2: terms.append(('b', fq if st2 else 0))
            for nm, t in terms:
                if h < fb: v[Pp(path + nm)], v[Pp(path + nm + 'l')] = hl15(t)
                else: v[Pp(path + nm)] = c8(t)
        bi = h // 2 if fo == 1 else h
        v[Pp('lv')] = (LVG * u['vchar%d' % bi]) >> 7 if snd else 0
        v[Pp('kr')] = kr; v[Pp('ka')] = ka - kr
    put4(P('hpl'), TAB_HPL[u['mm_hpf']])
    mm = (64 * u['mm_lev']) // 100; v[P('mml')], v[P('mmln')] = mm, -mm
    v[P('oml')], v[P('omr')] = TAB_PAN[u['mm_pan']]
    lv = ((64 if u['out_mode'] else 32) * u['level']) // 100
    if u['filt']: lv = min(127, lv * 2)                                   # 4-POLE bands are narrower: x 2
    if u['out_mode']: v[P('oll')], v[P('olr')], v[P('orl')], v[P('orr')] = lv, 0, 0, lv
    else: v[P('oll')] = v[P('olr')] = v[P('orl')] = v[P('orr')] = lv
    return v


def apply(core, params, ui=None):
    import keysdsp
    for n, c in values(ui).items():
        keysdsp.set_coef(core.prog, params[n][1], c)


def selftest(verbose=True):
    prog, params = build()
    missing = [n for n in params if n not in values()]
    assert not missing, ('params without a value', missing[:6])
    import keysdsp
    core, _ = keysdsp.make_sim(prog)
    A = 0x200000
    def run(sig, n):
        out = []
        for i in range(n):
            l, r = sig(i); core.wg(0x71, int(l)); core.wg(0x75, int(r)); core.run_sample()
            out.append((core.rg(0x73), core.rg(0x77)))
        return out
    def gz(xs, f):                                     # Goertzel magnitude (normalised)
        w = 2 * math.pi * f / FS; c = 2 * math.cos(w); s1 = s2 = 0.0
        for x in xs: s0 = x + c * s1 - s2; s2, s1 = s1, s0
        return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / len(xs) / A
    saw = lambda i: ((i * 110.0 / FS) % 1.0) * 2 - 1                # 110 Hz saw carrier
    sine = lambda f: (lambda i: A * math.sin(2 * math.pi * f * i / FS))
    rep = []
    chain_only = '--chain' in sys.argv
    def spec(ui, fmod, fs_=(330, 2530)):
        apply(core, params, ui)
        res = run(lambda i: (sine(fmod)(i), A * saw(i)), 6000)[3000:]
        ys = [o[0] for o in res]
        return [(f, round(gz(ys, f), 4)) for f in fs_], max(abs(y) for y in ys) / A
    for fmod in (() if chain_only else (300, 2500)):
        e, pk = spec(preset_ui(0), fmod)
        rep.append(('mod sine %d Hz x 110 Hz saw: harmonics 330 / 2530 Hz, peak' % fmod, e, round(pk, 3)))
    if not chain_only: rep.append(('formant +12, mod 300 Hz: harmonics 330 / 660', spec(dict(preset_ui(0), formant=36), 300, (330, 660))[0]))
    if not chain_only: rep.append(('4-POLE, mod 300 Hz: harmonics 330 / 2530', spec(dict(preset_ui(0), filt=1), 300)[0]))
    if chain_only: return chain_tests(core, params, run, rep, verbose)
    apply(core, params, preset_ui(0))
    run(lambda i: (sine(500)(i), A * saw(i)), 3000)
    res = run(lambda i: (0, A * saw(i)), 3000)
    lv = [max(abs(o[0]) for o in res[k:k + 300]) / A for k in range(0, 3000, 300)]
    rep.append(('mod stops: output level per 6.8 ms (release)', [round(x, 3) for x in lv]))
    apply(core, params, preset_ui(0))
    res = run(lambda i: (sine(500)(i), A * saw(i)), 3000)
    before = max(abs(o[0]) for o in res[-300:]) / A
    apply(core, params, dict(preset_ui(0), hold=1))
    res = run(lambda i: (0, A * saw(i)), 1500)
    rep.append(('HOLD: level while mod plays / 34 ms after it stopped', round(before, 3),
                round(max(abs(o[0]) for o in res[-300:]) / A, 3)))
    return chain_tests(core, params, run, rep, verbose)


def chain_tests(core, params, run, rep, verbose):
    A = 0x200000
    # ---- voice chain, heard through the mic mix (vocoder bands silent, mic mix HPF at 20 Hz) ----
    chain = lambda **k: dict(dict({'vchar%d' % i: 0 for i in range(NHB)}, mm_lev=100, mm_hpf=0, mm_pan=64, out_mode=1), **k)
    def gain(ui, f, amp=A, n=3000):
        apply(core, params, ui)
        res = run(lambda i: (amp * math.sin(2 * math.pi * f * i / FS), 0), n)[n // 2:]
        return round(max(abs(o[0]) for o in res) / amp, 3)
    rep.append(('chain off: gain 1 kHz', gain(chain(), 1000)))
    nar = preset_ui(2); nar.update(lm_sw=0)
    rep.append(('NARRATOR EQ (low -3 @100, mid +6 @200, high +3 @5k): gain 60 / 200 / 1k / 6k Hz',
                [gain(chain(**{k: v for k, v in nar.items() if k.startswith('eq')}), f) for f in (60, 200, 1000, 6000)]))
    lim = dict(lm_sw=1, lm_level=60, lm_thr=60 - 24, lm_rel=50, ds_sens=0)
    gain(chain(), 500, A // 40, 4000)                                               # settle
    rep.append(('LIMITER thr -24 dB: gain for -40 dB in / -12 dB in', gain(chain(**lim), 500, A // 40, 6000),
                gain(chain(**lim), 500, A, 6000)))
    rep.append(('DE-ESSER sens 100 @5 kHz: gain 8 kHz / 1 kHz', gain(chain(lm_sw=1, lm_thr=60, ds_sens=100, ds_freq=50), 8000),
                gain(chain(lm_sw=1, lm_thr=60, ds_sens=100, ds_freq=50), 1000)))
    rep.append(('NS thr 50 rel 0: gain -12 dB in / -60 dB in', gain(chain(ns_sw=1, ns_thr=50, ns_rel=0), 500, A, 4000),
                gain(chain(ns_sw=1, ns_thr=50, ns_rel=0), 500, A // 256, 4000)))
    if verbose:
        for r in rep: print('  ', *r)
    return rep


if __name__ == '__main__' and '--test' in sys.argv:
    selftest()
