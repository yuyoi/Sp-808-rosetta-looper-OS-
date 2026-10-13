"""Derive the R-DAC frame format from the boot ROM decoder (rdac_emu oracle) and validate a generic decoder.

Frame = 12 bytes = big-endian words W0..W5. Dispatch: W0[15:13], W1[15:13], W1[12]; W0[12] = error in some modes.
Half 1 = (W0, W2, W4) -> samples 0-7, half 2 = (W1, W3, W5) -> samples 8-15; both halves use the mode of the header.
For the A0-A5 families the handlers are shared pairwise, so W0/W1 bits 12-13 are payload there (anchor sign/MSB).
Per half, sample k = field_k + const_k [+ (left >> 1) + (right >> 1) if interpolated], neighbours
s3: (prev, s7), s1: (prev, s3), s5: (s3, s7), s0: (prev, s1), s2: (s1, s3), s4: (s3, s5), s6: (s5, s7), in the order
7,3,1,5,0,2,4,6; prev = the previous half's s7 (the running state). A payload bit may feed several fields.

usage: python -I tools/rdac_probe.py work/rdac_modes.json
"""
import json, os, random, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdac_emu

M16 = 0xFFFF
PARENTS = {7: (), 3: ('p', 7), 1: ('p', 3), 5: (3, 7), 0: ('p', 1), 2: (1, 3), 4: (3, 5), 6: (5, 7)}
ORDER = (7, 3, 1, 5, 0, 2, 4, 6)
PATTERNS = ('11111110', '11101110', '10101010', '00000000', '10101110', '11111010')


def sgn(x): x &= M16; return x - 0x10000 if x & 0x8000 else x
def shar(x): return (sgn(x) >> 1) & M16


def residuals(samples, interp, prev):
    """field_k + const_k for each k, given the decoded samples of a half (removes the interpolation terms)."""
    out = [0] * 8
    for k in ORDER:
        r = samples[k]
        if interp[k]:
            for par in PARENTS[k]: r -= shar(prev if par == 'p' else samples[par])
        out[k] = r & M16
    return out


def decode_half(words, bits, consts, interp, prev):
    s = [0] * 8
    for k in ORDER:
        f = consts[k]
        for wi, b, w in bits[k]:
            if (words[wi] >> b) & 1: f += w
        if interp[k]:
            for par in PARENTS[k]: f += shar(prev if par == 'p' else s[par])
        s[k] = f & M16
    return s


def table_decode(mode, w, state):
    interp = [mode['interp'][k] for k in range(8)]
    h1 = decode_half((w[0], w[2], w[4]), mode['bits1'], mode['consts1'], interp, state & M16)
    h2 = decode_half((w[1], w[3], w[5]), mode['bits2'], mode['consts2'], interp, h1[7])
    return h1 + h2, h2[7]


class Probe:
    def __init__(self):
        self.codec = rdac_emu.Codec()
        self.calls = 0

    def decode(self, words, state):
        self.calls += 1
        out, st, _ = self.codec.decode_frame(struct.pack('>6H', *[w & M16 for w in words]), state)
        return [x & M16 for x in out], st & M16

    def derive(self, a, b, v, e, rnd):
        """Try the widest payload first (W0/W1 bit 12 as data), fall back to treating them as header bits."""
        # (W0 payload top, W1 payload top, v is payload, e is payload)
        attempts = [(14, 14, True, True)] if a <= 5 else [(13, 13, True, True), (13, 12, False, True), (12, 13, True, False), (12, 12, False, False)]
        best = None
        for top0, top1, v_free, e_free in attempts:
            if a <= 5: hdr = [(a & 6) << 13, (b & 6) << 13, 0, 0, 0, 0]
            else: hdr = [(a << 13) | (0 if e_free else e << 12), (b << 13) | (0 if v_free else v << 12), 0, 0, 0, 0]
            pay = [(0, bb) for bb in range(top0)] + [(2, bb) for bb in range(16)] + [(4, bb) for bb in range(16)]                 + [(1, bb) for bb in range(top1)] + [(3, bb) for bb in range(16)] + [(5, bb) for bb in range(16)]
            base, _ = self.decode(hdr, 0)
            flips = {}
            for wi, bb in pay:
                w = list(hdr); w[wi] ^= 1 << bb
                flips[(wi, bb)] = self.decode(w, 0)[0]
            for pat in PATTERNS:
                interp = [c == '1' for c in pat]
                r1 = residuals(base[:8], interp, 0); r2 = residuals(base[8:], interp, base[7])
                bits1 = {k: [] for k in range(8)}; bits2 = {k: [] for k in range(8)}
                for (wi, bb), out in flips.items():
                    if wi in (0, 2, 4):
                        rr = residuals(out[:8], interp, 0)
                        for k in range(8):
                            d = sgn(rr[k] - r1[k])
                            if d: bits1[k].append(({0: 0, 2: 1, 4: 2}[wi], bb, d))
                    else:
                        rr = residuals(out[8:], interp, out[7])
                        for k in range(8):
                            d = sgn(rr[k] - r2[k])
                            if d: bits2[k].append(({1: 0, 3: 1, 5: 2}[wi], bb, d))
                mode = {'a': a, 'b': b, 'v': v, 'e': e, 'pattern': pat, 'bits1': bits1, 'bits2': bits2, 'consts1': r1, 'consts2': r2,
                        'interp': {k: interp[k] for k in range(8)}, 'payload_top': (top0, top1)}
                errs = 0
                for _ in range(150):
                    w = list(hdr)
                    for wi, bb in pay:
                        if rnd.random() < 0.5: w[wi] |= 1 << bb
                    if not v_free: w[1] = (w[1] & ~0x1000) | (v << 12)
                    if not e_free: w[0] = (w[0] & ~0x1000) | (e << 12)
                    st = rnd.randrange(0x10000)
                    out, st_o = self.decode(w, st)
                    pred, st_p = table_decode(mode, w, st)
                    if pred != out or st_p != st_o: errs += 1
                mode['errors'] = errs
                if best is None or errs < best['errors']: best = mode
                if errs == 0: return best
        return best


def main(out_path):
    pr = Probe(); rnd = random.Random(7); modes = []
    for a in range(8):
        for b in range(8):
            for v in (0, 1):
                for e in (0, 1):
                    idx = (a << 5) | (b << 2)
                    if int.from_bytes(pr.codec.e.boot[0x6D66 + idx:0x6D66 + idx + 4], 'big') == 0x6D38: continue
                    m = pr.derive(a, b, v, e, rnd)
                    print('mode A%d B%d v%d e%d: pattern %s payload %s errors %d/150' % (a, b, v, e, m['pattern'], m['payload_top'], m['errors']))
                    modes.append(m)
    json.dump(modes, open(out_path, 'w'))
    bad = [m for m in modes if m['errors']]
    print('%d modes, %d with mismatches, %d oracle calls -> %s' % (len(modes), len(bad), pr.calls, out_path))


if __name__ == '__main__':
    main(sys.argv[1])
