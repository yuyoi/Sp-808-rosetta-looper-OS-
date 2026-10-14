"""KEYS sampler for DSP1 (the SP-808's effects core): N pitched voices playing one sample held in the FX delay RAM.

Layout of the DSP1 program: Roland's 58-word base stays (I/O, wet ramp), our algorithm sits at 0x3C.. (globals)
and 0x100.. (voices, mixer); 0xF1-0xFF stay nop because the OS's end-of-program JMP 0x2F2 -> 0xF1 may re-run them.

Model (phases are 16.8 fixed point in 24-bit IRAM words, 44.1 kHz):
  AGE   += 256 per sample            (host resets it when the recording's sound starts: coef 'age_g' = 0 for one pass)
  record: the FX input (L+R)/2 is written to ERAM at offsets 0 and 0x10000 every sample (two copies, so the 16-bit
          wrap of AGE and the phases stays consistent); the host enables/disables the two write groups.
  detect: a leaky peak of |input| goes to the host readback register, saturated (all ones = sound present).
  voice v: PHI_v += DELTA_v (= 256 * pitch ratio, from 3 coefficient fields), reset by 'g' = 0 for one pass;
           X = AGE - PHI_v -> read ERAM at pos + X (two reads, +0/+1) interpolated with the fraction;
           LVL_v one-pole smoothed from coefficient 't' (target = t * 2^15); OUT_v = sample * LVL_v.
  mixer:  i[0x13] = i[0x19] = sum OUT_v + input * thru (pass-through while picking / sampling).
build() returns the 768-word program (DSP view) and {name: ('coef'|'eram', word)}.  Coef fields are written with
the OS routine 0x108936 (r0 = 0x1000 | word << 2, e0 = coef << 8 | shift selector); ERAM groups with 0x108B64.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esp

NVOICES = 8
G0, V0, VSTRIDE = 0x3C, 0x100, 44
# IRAM slots (relative addresses; a state value written at m is read next sample at m + 1 -> pairs)
AGE, REC, PK, T1 = 0x20, 0x22, 0x24, 0x26
def vslot(v, k): return 0x30 + 12 * v + 2 * k          # per voice: PHI, LVL, NX, SMP, OUT (+1 spare pair)
PHI, LVL, NX, SMP, OUT = 0, 1, 2, 3, 4

E = esp.encode
SH7, SH6, SH5, SH3 = 0, 1, 2, 3                        # shift selector values


def op30(mck, acc_b=False, clear=True, flip=False, neg=False, mem=0):
    """op 0x30: acc = i[mem] * mulcoeff[mck] (>>7); mck 6 = the ERAM variable-offset fraction. flip: (1 - mc)."""
    assert mck in (0, 1, 2, 6), 'DSP1 (FX core) has mulcoeff mc0-mc2 (+ mc6 = ERAM fraction) only: mc%d' % mck
    coef = (mck << 5) | (0x10 if flip else 0) | (0x08 if neg else 0) | (0x02 if acc_b else 0) | (0 if clear else 1)
    return E(0x30, mem, SH7, coef)


def dmac(acc_b=False, clear=False):
    return E(0x34, 0xC6 | (0x20 if acc_b else 0) | (0x10 if clear else 0), SH7, 0)


def build(nvoices=NVOICES):
    prog = [0] * 0x300
    params = {}
    def put(w, word, name=None, kind='coef'):
        assert prog[w] == 0, 'word %03X used twice' % w
        prog[w] = word
        if name: params[name] = (kind, w)
    # ---- globals @ G0: age counter, the recording write (two copies), the signal detector ----
    g = G0
    put(g + 0, E(0x04, AGE + 1, SH6, 64), 'age_g')            # A = age_old * 1      (0 = reset)
    put(g + 1, E(0x00, 2, SH7, 32))                            # A += 0x400 * 32 >> 7 = 256
    put(g + 2, E(0x04, 0x12, SH6, 32), 'rec_l')                # A = inL * 0.5
    put(g + 3, E(0x00, 0x18, SH6, 32), 'rec_r')                # A += inR * 0.5          -> rec
    put(g + 4, E(0x40, AGE, SH7, 0))                           # i[AGE] = raw(A(+1)) = age_new
    put(g + 6, E(0x58, REC, SH7, 0) | (0x10 << 23), 'rec_w0', 'eram')   # i[REC] = sat(rec); ERAM WRITE start (imm 0)
    put(g + 7, E(0x34, 0xCB, SH7, 0))                          # eramwr = sat(A(+4)) = rec
    put(g + 8, E(0x7C, T1, SH6, 32))                           # i[T1] = sat(rec); A = |rec| * 0.5
    put(g + 9, E(0x00, PK + 1, SH7, 126))                      # A += pk_old * 126/128
    put(g + 12, E(0x58, PK, SH7, 0) | (0x10 << 23), 'rec_w1', 'eram')   # i[PK] = sat(A(+9)); WRITE start #2
    put(g + 13, E(0x04, PK, SH3, 127))                         # A = pk * 15.9
    put(g + 16, E(0x08, T1, SH3, 127) | (0x02 << 23))          # i[T1] = sat(A(+13)); A = sat * 15.9; imm word 4 = 2
    put(g + 19, E(0x34, 0xCA, SH7, 0))                         # hostreg = sat(A(+16))   (all ones when sound)
    # ---- voices ----
    outs = []
    for v in range(nvoices):
        b = V0 + VSTRIDE * v
        phi, lvl, nx, smp, out = (vslot(v, k) for k in (PHI, LVL, NX, SMP, OUT))
        mck = 2                                                # level mulcoeff: mc2 for every voice. The FX core (DSP1)
                                                               # has no general mc3: Roland's 20 FX programs only write
                                                               # mc0-mc2; odd voices on mc3 played at random levels on hw
        put(b + 0, E(0x04, lvl + 1, SH6, 63), 'v%d_lvlk' % v)   # A = L_old * 63/64
        put(b + 1, E(0x00, 3, SH7, 0), 'v%d_t' % v)             # A += 0x10000 * t >> 7 = t * 512 (target / 64)
        put(b + 2, E(0x14, phi + 1, SH6, 64), 'v%d_g' % v)      # B = PHI_old * 1    (0 = reset)
        put(b + 3, E(0x10, 3, SH7, 0), 'v%d_d2' % v)            # B += c2 * 512
        put(b + 4, E(0x08, lvl, SH6, 64))                       # i[LVL] = sat(A(+1)) = L_new; A = L_new
        put(b + 5, E(0x10, 2, SH7, 0), 'v%d_d1' % v)            # B += c1 * 8
        put(b + 6, E(0x10, 1, SH7, 0), 'v%d_d0' % v)            # B += c0 / 8 (c0 multiple of 8)  -> PHI_new
        put(b + 7, E(0x34, 0xA0 | (mck << 1), SH7, 0))          # mc[k] = sat(A(+4)) = L_new
        put(b + 9, E(0x0C, phi, SH6, 64))                       # i[PHI] = sat(B(+6)) = PHI_new; A = PHI_new
        put(b + 10, E(0x00, AGE, SH6, -64 & 0xFF))              # A += age_new * -1  -> A = PHI - AGE = -X
        put(b + 13, E(0x44, nx, SH3, -128 & 0xFF))              # i[NX] = raw(A(+10)) = -X; A = -X * -16 = 16 X
        put(b + 16, E(0x34, 0xC7, SH7, 0) | (0x18 << 23), 'v%d_rdA' % v, 'eram')   # eramvar = A(+13); READvar (+0)
        put(b + 22, 0x18 << 23, 'v%d_rdB' % v, 'eram')          # READvar start #2, imm 2 (+1 sample)
        put(b + 23, 0x02 << 23)
        put(b + 26, E(0x34, 0xCC, SH7, 0))                      # i[FC] = eramrd  (read A, start + 10)
        put(b + 27, op30(6, flip=True, clear=True, mem=0xFC))   # A = i[FC] * (1 - frac)
        put(b + 28, dmac())
        put(b + 32, E(0x34, 0xCD, SH7, 0))                      # i[FD] = eramrd  (read B, start + 10)
        put(b + 33, op30(6, clear=False, mem=0xFD))             # A += i[FD] * frac
        put(b + 34, dmac())                                     # -> A = interpolated sample
        put(b + 37, E(0x58, smp, SH7, 0))                       # i[SMP] = sat(A(+34))
        put(b + 38, op30(mck, acc_b=True, clear=True, mem=smp)) # B = sample * L
        put(b + 39, dmac(acc_b=True))
        put(b + 42, E(0x1C, out, SH7, 0))                       # i[OUT] = sat(B(+39)); B cleared
        outs.append(out)
    # ---- mixer: voices + pass-through -> i[13] (L) and i[19] (R) ----
    m = V0 + VSTRIDE * nvoices
    for k, out in enumerate(outs):
        put(m + k, E(0x04 if k == 0 else 0x00, out, SH6, 64))
    n = len(outs)
    put(m + n, E(0x00, 0x12, SH6, 0), 'thru_l')                 # A += inL * thru
    put(m + n + 1, E(0x00, 0x18, SH6, 0), 'thru_r')             # A += inR * thru
    put(m + n + 4, E(0x58, 0x13, SH7, 0))                       # i[13] = sat(A(+n+1))
    put(m + n + 5, E(0x58, 0x19, SH7, 0))                       # i[19] = same (A unchanged, coef 0)
    end = m + n + 6
    assert end <= 0x2F2 and all(w == 0 for w in prog[0xF1:0x100]), 'program layout'
    return prog, params


def shsel(prog, params, name): return (prog[params[name][1]] >> 8) & 3


def coef_value(prog, params, name, c):
    """The 16-bit value for the OS coefficient writer: coef byte + the word's own shift selector."""
    return ((c & 0xFF) << 8) | shsel(prog, params, name)


def set_coef(prog, w, coef, shsel_=None):
    prog[w] = (prog[w] & ~0xFF) | (coef & 0xFF)
    if shsel_ is not None: prog[w] = (prog[w] & ~0x300) | (shsel_ << 8)


def set_eram(prog, w, mode, imm=0):
    """Like the host's ERAM-group write (0x56 mode): mode 0 = off, 0x10 write, 0x08 read, 0x18 read @var."""
    fields = (mode, imm & 0x1F, (imm >> 5) & 0x1F, (imm >> 10) & 0x1F, (imm >> 15) & 0x1F)
    for k, f in enumerate(fields): prog[w + k] = (prog[w + k] & 0x7FFFFF) | (f << 23)


def delta_fields(ratio):
    """DELTA = round(ratio * 256) -> (c2, c1, c0, delta) with DELTA = 512 c2 + 8 c1 + c0 / 8, c0 a multiple of 8."""
    d = int(round(ratio * 256))
    c2, r = divmod(d, 512); c1, r = divmod(r, 8)
    return c2, c1, r * 8, d


def host_image_eram(mode, imm):
    """32-bit long for the OS routine 0x108B64 (what 0x109696 / 0x10965A produce for write / read)."""
    return ((mode << 3) << 24) | ((imm & 0xFF) << 16) | (((imm >> 8) & 0xFF) << 8) | ((imm >> 16) & 0xF)


def rom_table(prog, start=0x3C, end=0x300):
    """Words start..end as the OS loader wants them: 3 bytes per word, coefficient byte first."""
    out = bytearray()
    for w in prog[start:end]: out += esp.dsp_to_rom(w & 0x7FFFFF).to_bytes(3, 'big')
    return bytes(out)


# ---------------------------------------------------------------- simulation
def make_sim(prog):
    import json
    P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'dsp', 'programs.json')))
    base = [esp.rom_to_dsp(w) for w in P['dsp1_base']['words']]
    full = (base + [0, 0] + prog[0x3C:])[:0x300]
    gram = [0] * 256; eram = esp.Eram(17)
    return esp.Core(full, gram, eram, name='dsp1'), eram


def simulate(nvoices=4, seconds_rec=0.25, f_in=1000.0, ratios=(1.0, 2 ** (7 / 12), 0.5, 1.5)):
    import math
    prog, params = build(nvoices)
    core, eram = make_sim(prog)
    fs = 44100
    def host_coef(name, c): set_coef(core.prog, params[name][1], c)
    def host_eram(name, mode, imm=0): set_eram(core.prog, params[name][1], mode, imm)
    def tick(s=0):                                             # the input slots are refreshed every sample (as the
        core.wg(0x71, s); core.wg(0x75, s); core.run_sample(); eram.tick_sample()   # hardware does)
    for v in range(nvoices): host_coef('v%d_t' % v, 0)
    for _ in range(400): tick()
    # record: enable the two writes, feed silence then a sine; the detector must fire at the sine
    host_eram('rec_w0', 0x10, 0); host_eram('rec_w1', 0x10, 0x10000)
    n_rec = int(seconds_rec * fs)
    fired = None
    for n in range(300 + n_rec):
        s = 0 if n < 300 else int(0.4 * 0x7FFFFF * math.sin(2 * math.pi * f_in * (n - 300) / fs))
        tick(s)
        if fired is None and core.hostreg >= 0x7FFF00: fired = n; host_coef('age_g', 0)
        if fired is not None and n == fired + 1: host_coef('age_g', 64)
    print('detector fired at sample %s (sine starts at 300), hostreg now %06X' % (fired, core.hostreg & 0xFFFFFF))
    host_eram('rec_w0', 0); host_eram('rec_w1', 0)
    for _ in range(200): tick()
    results = []
    for v, r in enumerate(ratios[:nvoices]):
        c2, c1, c0, d = delta_fields(r)
        host_coef('v%d_d2' % v, c2); host_coef('v%d_d1' % v, c1); host_coef('v%d_d0' % v, c0)
        host_coef('v%d_g' % v, 0); host_eram('v%d_rdA' % v, 0x18, 0); host_eram('v%d_rdB' % v, 0x18, 2)
        for _ in range(40): tick()
        host_coef('v%d_g' % v, 64); host_coef('v%d_t' % v, 100)
        ys = []
        for n in range(int(min(0.9 * seconds_rec / r, 0.2) * fs)):
            tick(); ys.append(core.rg(0x73))                  # g[72] written this pass; the pointer moved by 1
        host_coef('v%d_t' % v, 0)
        for _ in range(600): tick()
        ys = ys[2000:]
        zc = sum(1 for a, b in zip(ys, ys[1:]) if a < 0 <= b)
        f = zc * fs / len(ys); peak = max(abs(y) for y in ys) / 0x7FFFFF
        results.append((v, r, d, f, f_in * r, peak))
        print('voice %d ratio %.4f delta %d: measured %.1f Hz, expected %.1f Hz, peak %.3f' % results[-1])
    return results


if __name__ == '__main__':
    simulate()
