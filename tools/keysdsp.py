"""KEYS sampler for DSP1 (the SP-808's effects core): N pitched voices playing one sample held in the FX delay RAM.

Layout of the DSP1 program: Roland's 58-word base stays (I/O, wet ramp), our algorithm sits at 0x3C.. (globals)
0x50.. (AGE_E/REF/SOFF, voice sum, filter, output mix) and 0x100.. (voices); 0xF1-0xFF stay nop because the OS's end-of-program JMP 0x2F2 -> 0xF1 may re-run them.

Model (phases are 16.8 fixed point in 24-bit IRAM words, 44.1 kHz):
  AGE   += 256 per sample            (host resets it when the recording's sound starts: coef 'age_g' = 0 for one pass)
  record: the FX input (L+R)/2 is written to ERAM at offsets 0 and 0x10000 every sample (two copies, so the 16-bit
          wrap of AGE and the phases stays consistent); the host enables/disables the two write groups.
  detect: a leaky peak of |input| goes to the host readback register, saturated (all ones = sound present).
  voice v: PHI_v += DELTA_v (= 256 * pitch ratio, from 3 coefficient fields), reset by 'g' = 0 for one pass;
           X = AGE - PHI_v -> read ERAM at pos + X (two reads, +0/+1) interpolated with the fraction;
           LVL_v one-pole smoothed from coefficient 't' (target = t * 2^15); OUT_v = sample * LVL_v.
  mixer:  (start of the sample, last sample's OUT_v) VS = sum OUT_v -> filter -> F = lp * wet + VS * dry;
          i[0x13] = F + inL * thru, i[0x19] = F + inR * thru (per channel: Roland's base subtracts each side's
          own input from the return, so a summed L+R pass-through leaked the other side at unity).
build() returns the 768-word program (DSP view) and {name: ('coef'|'eram', word)}.  Coef fields are written with
the OS routine 0x108936 (r0 = 0x1000 | word << 2, e0 = coef << 8 | shift selector); ERAM groups with 0x108B64.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esp

NVOICES = 8
G0, V0, VSTRIDE = 0x3C, 0x100, 57
# IRAM slots (relative addresses; a state value written at m is read next sample at m + 1 -> pairs)
AGE, REC, PK, T1 = 0x20, 0x22, 0x24, 0x26
AGE_E, REF = 0x28, 0x2A                                 # age since the take's END (reverse); the voices' read reference
VS, LP, BP, HP = 0x90, 0x92, 0x94, 0x96                 # voice sum (filter input), state-variable filter lp / bp / hp
MIXF = 0x98                                             # the voices' output (filtered or dry), for the R channel
OSC0 = 0xA0                                             # per voice: OPH1 (osc 1 phase) at OSC0 + 4v, OPH2 (unison) + 2
TRI, PUL, JUNK = 0xC0, 0xC2, 0xC4                       # shared temps: osc 1 triangle / pulse, write-only side stores
SOFF = 0x2C                                             # loop start offset (16.8, raw): a voice with sel on starts there
G1 = 0x50                                               # second global block: AGE_E, REF, the filter (before the voices)
def vslot(v, k): return 0x30 + 12 * v + 2 * k          # per voice: PHI, LVL, NX, SMP, OUT, S1/S2 (head temps)
PHI, LVL, NX, SMP, OUT, SH = 0, 1, 2, 3, 4, 5

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
    # ---- AGE_E: age since the end of the take (host resets it there); REF = AGE (forward) or AGE_E (reverse) ----
    g = G1
    put(g + 0, E(0x04, AGE_E + 1, SH6, 64), 'age_e_g')        # A = age_e_old * 1   (0 = reset)
    put(g + 1, E(0x00, 2, SH7, 32))                            # A += 256
    put(g + 4, E(0x40, AGE_E, SH7, 0))                         # i[AGE_E] = raw(A(+1))
    put(g + 5, E(0x04, AGE, SH6, 64), 'ref_f')                 # A = AGE * f
    put(g + 6, E(0x00, AGE_E, SH6, 0), 'ref_r')                # A += AGE_E * r
    put(g + 9, E(0x40, REF, SH7, 0))                           # i[REF] = raw(A(+6))
    # SOFF = loop start (16.8) = a * 2048 + b * 32 + c / 2 samples, three host-written fields (raw store: wraps)
    put(g + 10, E(0x04, 4, SH3, 0), 'soff_a')                  # A = 0x400000 * a >> 3 = a * 0x80000
    put(g + 11, E(0x00, 3, SH3, 0), 'soff_b')                  # A += 0x10000 * b >> 3 = b * 0x2000
    put(g + 12, E(0x00, 2, SH3, 0), 'soff_c')                  # A += 0x400 * c >> 3 = c * 0x80
    put(g + 15, E(0x40, SOFF, SH7, 0))                         # i[SOFF] = raw(A(+12))
    # ---- voice sum: the voices' outputs of the last sample (OUT is read at out + 1): one sample of latency ----
    sm = g + 16
    for k in range(nvoices):
        put(sm + k, E(0x04 if k == 0 else 0x00, vslot(k, OUT) + 1, SH6, 64))
    put(sm + nvoices + 2, E(0x58, VS, SH7, 0))                 # i[VS] = sat(A(+n-1)) = the voices
    # ---- state-variable low-pass on the voice sum (Chamberlin), 15-bit coefficients ----
    #   lp' = lp + f*bp ; hp = x - lp' - q*bp ; bp' = bp + f*hp      (f: SH7 + lo7, q: SH6 + lo7, q_hi negative)
    f = sm + nvoices + 3
    put(f + 0, E(0x04, LP + 1, SH6, 64))                       # A = lp
    put(f + 1, E(0x00, BP + 1, SH7, 0), 'flt_f1')              # A += bp * f_hi
    put(f + 2, E(0x34, 0xC6, SH7, 0), 'flt_f1l')               # A += bp * f_lo / 128           -> lp'
    put(f + 3, E(0x14, VS, SH6, 64))                           # B = x (VS, stored 4 words ago)
    put(f + 4, E(0x10, BP + 1, SH6, 0), 'flt_q')               # B += bp * q_hi   (q_hi <= 0)
    put(f + 5, E(0x34, 0xE6, SH6, 0), 'flt_ql')                # B += bp * q_lo / 128
    put(f + 6, E(0x58, LP, SH7, 0))                            # i[LP] = sat(A(+3)) = lp'
    put(f + 7, E(0x10, LP, SH6, -64 & 0xFF))                   # B -= lp'                        -> hp
    put(f + 10, E(0x5C, HP, SH7, 0))                           # i[HP] = sat(B(+7))
    put(f + 11, E(0x04, BP + 1, SH6, 64))                      # A = bp
    put(f + 12, E(0x00, HP, SH7, 0), 'flt_f2')                 # A += hp * f_hi
    put(f + 13, E(0x34, 0xC6, SH7, 0), 'flt_f2l')              # A += hp * f_lo / 128           -> bp'
    put(f + 16, E(0x58, BP, SH7, 0))                           # i[BP] = sat(A(+13))
    # ---- output, per channel: F = lp' * wet + voices * dry; L = F + inL * thru, R = F + inR * thru ----
    o = f + 17
    put(o + 0, E(0x04, LP, SH6, 0), 'flt_wet')                 # A = lp' * wet       (filter on: 64)
    put(o + 1, E(0x00, VS, SH6, 64), 'flt_dry')                # A += voices * dry   (filter off: 64)
    put(o + 2, E(0x00, 0x12, SH6, 0), 'thru_l')                # A += inL * thru
    put(o + 3, E(0x14, 0x18, SH6, 0), 'thru_r')                # B = inR * thru
    put(o + 4, E(0x58, MIXF, SH7, 0))                          # i[MIXF] = sat(A(+1)) = F
    put(o + 5, E(0x58, 0x13, SH7, 0))                          # i[13] = sat(A(+2)) = F + inL
    put(o + 6, E(0x10, MIXF, SH6, 64))                         # B += F
    put(o + 9, E(0x1C, 0x19, SH7, 0))                          # i[19] = sat(B(+6)) = F + inR; B cleared
    assert o + 9 < 0xF1
    # ---- voices ----
    outs = []
    for v in range(nvoices):
        b = V0 + VSTRIDE * v
        phi, lvl, nx, smp, out = (vslot(v, k) for k in (PHI, LVL, NX, SMP, OUT))
        o1, o2 = OSC0 + 4 * v, OSC0 + 4 * v + 2
        mck = 2                                                # level mulcoeff: mc2 for every voice. The FX core (DSP1)
                                                               # has no general mc3: Roland's 20 FX programs only write
                                                               # mc0-mc2; odd voices on mc3 played at random levels on hw
        # level in B (saturating), phase in A: stored RAW so it wraps like AGE (a saturating store froze every note
        # after 32767 source samples = 0.74 s; the wrap keeps X = REF - PHI right for the whole 1.48 s take)
        put(b + 0, E(0x14, lvl + 1, SH6, 63), 'v%d_lvlk' % v)   # B = L_old * 63/64      (idle voice: 0 = hard mute)
        put(b + 1, E(0x10, 3, SH7, 0), 'v%d_t' % v)             # B += 0x10000 * t >> 7 = t * 512 (target / 64)
        put(b + 2, E(0x04, phi + 1, SH6, 64), 'v%d_g' % v)      # A = PHI_old * 1    (0 = reset)
        put(b + 3, E(0x00, 3, SH7, 0), 'v%d_d2' % v)            # A += c2 * 512
        put(b + 4, E(0x5C, lvl, SH7, 0))                        # i[LVL] = sat(B(+1)) = L_new
        put(b + 5, E(0x00, 2, SH7, 0), 'v%d_d1' % v)            # A += c1 * 8
        put(b + 6, E(0x00, 1, SH7, 0), 'v%d_d0' % v)            # A += c0 / 8 (c0 multiple of 8)  -> PHI_new
        put(b + 7, E(0x34, 0xA1 | (mck << 1), SH7, 0))          # mc[k] = sat(B(+4)) = L_new
        put(b + 9, E(0x44, phi, SH6, 64), 'v%d_dir' % v)        # i[PHI] = raw(A(+6)); A = +PHI (fwd) / -PHI (rev)
        put(b + 10, E(0x00, REF, SH6, -64 & 0xFF))              # A -= REF
        put(b + 11, E(0x00, SOFF, SH6, 0), 'v%d_sel' % v)       # A += SOFF * sel (loop continuation: +64 fwd / -64 rev)
        put(b + 14, E(0x44, nx, SH3, -128 & 0xFF))              # i[NX] = raw(A(+11)) = -X; A = -X * -16 = 16 X
        # ---- DDS oscillator 1: a raw 24-bit phase = the saw; pulse = saw + pw driven into saturation twice (x252);
        #      triangle = 2|saw| - 1. A is free once the ERAM start at +17 has taken A(+14).
        put(b + 15, E(0x04, o1 + 1, SH6, 64), 'v%d_og' % v)     # A = OPH1_old * 1
        put(b + 16, E(0x00, 4, SH7, 0), 'v%d_o2a' % v)          # A += o2 * 32768
        put(b + 17, E(0x34, 0xC7, SH7, 0) | (0x18 << 23), 'v%d_rdA' % v, 'eram')   # eramvar = A(+14); READvar (+0)
        put(b + 18, E(0x00, 3, SH7, 0), 'v%d_o1a' % v)          # A += o1 * 512
        put(b + 19, E(0x00, 2, SH7, 0), 'v%d_o0a' % v)          # A += o0 * 8
        put(b + 20, E(0x00, o2 + 1, SH6, 0), 'v%d_fm' % v)      # A += unison saw (last sample) * fm (phase mod, later)
        put(b + 23, E(0x44, o1, SH6, 64) | (0x18 << 23), 'v%d_rdB' % v, 'eram')   # i[OPH1] = raw(A(+20)); A = saw;
                                                                # READvar start #2 (imm 2 = +1 sample)
        put(b + 24, E(0x00, 4, SH6, 0) | (0x02 << 23), 'v%d_pw' % v)   # A += pw * 65536 (pulse width)
        put(b + 26, E(0x7C, JUNK, SH6, 127))                    # A = |saw (A(+23))| * 127/64
        put(b + 27, E(0x18, JUNK, SH3, 127))                    # B = sat(saw + pw (A(+24))) * 15.9
        put(b + 29, E(0x00, 4, SH6, -128 & 0xFF))               # A -= 0x800000                    -> triangle
        put(b + 30, E(0x1C, JUNK, SH3, 127))                    # B = sat(B(+27)) * 15.9
        put(b + 31, E(0x34, 0xCC, SH7, 0))                      # i[FC] = eramrd (read A, committed at +27)
        put(b + 32, E(0x58, TRI, SH7, 0))                       # i[TRI] = sat(A(+29))
        put(b + 33, E(0x1C, PUL, SH7, 0))                       # i[PUL] = sat(B(+30)) = pulse; B = 0
        # ---- the sample, interpolated, now in B ----
        put(b + 34, op30(6, acc_b=True, flip=True, clear=True, mem=0xFC))   # B = i[FC] * (1 - frac)
        put(b + 35, dmac(acc_b=True))
        put(b + 36, E(0x34, 0xCD, SH7, 0))                      # i[FD] = eramrd (read B, committed at +33)
        put(b + 37, op30(6, acc_b=True, clear=False, mem=0xFD)) # B += i[FD] * frac
        put(b + 38, dmac(acc_b=True))                           # -> B = interpolated sample
        # ---- DDS oscillator 2 (unison saw, detuned by the host) in A; the mix in B ----
        put(b + 39, E(0x04, o2 + 1, SH6, 64), 'v%d_og2' % v)    # A = OPH2_old * 1
        put(b + 40, E(0x00, 4, SH7, 0), 'v%d_o2b' % v)
        put(b + 41, E(0x1C, JUNK, SH6, 64), 'v%d_mxs' % v)      # B = sat(sample (B(+38))) * sample level
        put(b + 42, E(0x00, 3, SH7, 0), 'v%d_o1b' % v)
        put(b + 43, E(0x00, 2, SH7, 0), 'v%d_o0b' % v)
        put(b + 44, E(0x10, o1, SH6, 0), 'v%d_mxsaw' % v)       # B += saw * level
        put(b + 45, E(0x10, PUL, SH6, 0), 'v%d_mxpul' % v)      # B += pulse * level
        put(b + 46, E(0x40, o2, SH7, 0))                        # i[OPH2] = raw(A(+43))
        put(b + 47, E(0x10, TRI, SH6, 0), 'v%d_mxtri' % v)      # B += triangle * level
        put(b + 48, E(0x10, o2, SH6, 0), 'v%d_mxuni' % v)       # B += unison saw * level
        put(b + 51, E(0x1C, smp, SH7, 0))                       # i[SMP] = sat(B(+48)); B = 0
        put(b + 52, op30(mck, acc_b=True, clear=True, mem=smp)) # B = SMP * L
        put(b + 53, dmac(acc_b=True))
        put(b + 56, E(0x1C, out, SH7, 0))                       # i[OUT] = sat(B(+53)); B cleared
        outs.append(out)
    end = V0 + VSTRIDE * nvoices
    assert end <= 0x2F2 and all(w == 0 for w in prog[0xF1:0x100]), 'program layout'
    return prog, params


def shsel(prog, params, name): return (prog[params[name][1]] >> 8) & 3


FS = 44100
CUT_LO, CUT_HI = 30.0, 7000.0                             # knob 0..126 -> cutoff (exponential); 127 = filter off
def cutoff_hz(k): return CUT_LO * (CUT_HI / CUT_LO) ** (k / 126.0)
def filt_f(k):
    import math
    f = 2 * math.sin(math.pi * cutoff_hz(k) / FS)          # Chamberlin f, SH7: value = (hi + lo/128) / 128
    v = max(1, min(127 * 128 + 127, round(f * 128 * 128)))
    return v >> 7, v & 0x7F
def osc_fields(f):
    """oscillator frequency (Hz) -> (o2, o1, o0): phase increment per sample = o2 * 32768 + o1 * 512 + o0 * 8 of 2^24."""
    inc = int(round(f / FS * (1 << 24)))
    o2, r = divmod(inc, 32768); o1, r = divmod(r, 512)
    assert o2 <= 127, f
    return o2, o1, r // 8
def osc_freq(o2, o1, o0): return (o2 * 32768 + o1 * 512 + o0 * 8) * FS / (1 << 24)
def soff_fields(samples):
    """loop start in samples (0..65535.5) -> (a, b, c) with a * 2048 + b * 32 + c / 2 = samples; all in 0..127."""
    h = int(round(samples * 2))
    a, r = divmod(h, 4096); b, c = divmod(r, 64)
    return a, b, c
def filt_q(k):
    q = 1.4 - (1.4 - 0.07) * (k / 127.0)                   # knob 0 = no resonance (q 1.4), 127 = screaming (q 0.07)
    v = round(-q * 64 * 128)                               # SH6: value = (hi + lo/128) / 64, negative
    hi = -((-v + 127) >> 7); lo = v - hi * 128             # hi <= 0, 0 <= lo < 128
    return hi & 0xFF, lo


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
