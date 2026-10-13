"""Extract the DSP programs (24-bit words) from the decoded SP-808 OS image.

usage: python -I tools/dspdump.py sp808_v1050_raw.bin work/dsp
Writes one .txt per program (index, hex, fields) plus programs.json. The output is Roland data: keep it in work/.

DSP word = 3 bytes b0 b1 b2 in ROM; the loader (0x1096D2) stores b0<<24 | b1<<16 | b2<<8 into 0xC0x000 + 4*i.
Live parameter writes (0x108936 / 0x1089C6 / 0x108A5C) only ever change b0 (8-bit coefficient) and b1 bits 1-0.
"""
import json, os, struct, sys

BASE = 0x100000
FX_PTR_TABLE = 0x16A9E8          # ROM copy of RAM 0x403002: 20 longs
FX_LEN_TABLE = 0x157860          # 20 words
FX_NAMES = ['Isolator', 'Filter', 'Tape Echo', 'EZ Delay', 'Comp/Limiter', '3-Band EQ', 'Reverb+Gate', "'80s Phaser",
            'St. Flanger', 'St. Chorus', 'Delay RSS', 'Synth', 'Simple Delay', 'Chorus/Flang', 'Analog Delay',
            'AnalogChorus', 'fx16', 'fx17', 'fx18', 'fx19']   # order unverified; see fxnames() below

FIXED = [('dsp0_main', 0x151FE2, 0x2F5), ('dsp1_base', 0x1528C1, 0x3A), ('p15296F_16w', 0x15296F, 0x10),
         ('p15299F_115w', 0x15299F, 0x73)]


def words(img, addr, n):
    o = addr - BASE
    return [int.from_bytes(img[o + 3 * i:o + 3 * i + 3], 'big') for i in range(n)]


def programs(img):
    out = {}
    for name, addr, n in FIXED: out[name] = (addr, words(img, addr, n))
    o = FX_PTR_TABLE - BASE
    ptrs = struct.unpack('>20I', img[o:o + 80])
    o = FX_LEN_TABLE - BASE
    lens = struct.unpack('>20H', img[o:o + 40])
    for i in range(20): out['fx%02d' % i] = (ptrs[i], words(img, ptrs[i], lens[i]))
    return out


def fields(w):
    """Split a word into the fields the OS touches: coefficient b0, code b1[1:0], and the rest."""
    return (w >> 16) & 0xFF, (w >> 8) & 3, (w >> 10) & 0x3F, w & 0xFF


def main(image_path, outdir):
    img = open(image_path, 'rb').read()
    os.makedirs(outdir, exist_ok=True)
    progs = programs(img)
    js = {}
    for name, (addr, ws) in progs.items():
        js[name] = {'addr': addr, 'words': ws}
        with open(os.path.join(outdir, name + '.txt'), 'w') as f:
            f.write('; %s @%06X, %d words\n' % (name, addr, len(ws)))
            for i, w in enumerate(ws):
                c, k, m, lo = fields(w)
                f.write('%03X: %06X   c=%02X k=%d m=%02X lo=%02X\n' % (i, w, c, k, m, lo))
        print('%-14s @%06X %4d words' % (name, addr, len(ws)))
    json.dump(js, open(os.path.join(outdir, 'programs.json'), 'w'))


if __name__ == '__main__':
    main(*sys.argv[1:3])
