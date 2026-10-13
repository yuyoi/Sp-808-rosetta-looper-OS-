"""Capture the live DSP programs: run the stock OS's DSP init and FX loader in the H8S emulator and dump the
DSP0/DSP1 program shadows (0x410362 / 0x410F62) with every runtime write applied (coefficients, ERAM fields).

usage: python -I tools/fxcapture.py sp808_v1050_raw.bin work/dsp [alg ...]
Writes work/dsp/live_dsp0.txt, live_fxNN.txt (disassembly) and live.json. Output is Roland data: keep it in work/.
"""
import json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h8emu, esp

DATA_SRC, DATA_END, DATA_DST = 0x16A9E6, 0x16ACBF, 0x403000     # C startup .data copy
DSP_INIT, PRESET_LOAD, FX_LOAD = 0x1267B8, 0x1080F0, 0x1081D6
PRESET_TAB, CUR_FX = 0x1576BC, 0x403000
SHADOW0, SHADOW1 = 0x410362, 0x410F62
TICK = 0x40185E
REC = 0x43F800                                                     # 256-byte FX parameter record


def make_emu(image):
    e = h8emu.Emu(image)
    e.code_lo = 0x100000                                           # run the stock OS natively
    for a in range(DATA_SRC, DATA_END): e.wb(DATA_DST + a - DATA_SRC, e.rb(a))
    boot = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dump', 'BOOTROM.BIN')
    if os.path.exists(boot):                                       # boot ROM: RAM jump table + its math routines
        e.boot = open(boot, 'rb').read(); e.code_lo = 0; e.code_hi = 0x1000000      # RAM jump table too
        e.call(0x0086AA); e.call(0x126686)                         # boot table init, then the OS's own overrides
    e.stubs[0x10985A] = lambda e: e.s16(0, 1)                      # DSP ready
    e.stubs[0x120C30] = e.stubs[0x14193E] = lambda e: None         # idle tasks
    def clock(e):
        if e.steps % 50 == 0: e.wl(TICK, e.rl(TICK) + 1)
    e.on_step = clock
    e.ww(CUR_FX, 0xFFFF)
    e.ww(0x403312, 1000); e.wb(0x4225B2, 1)                       # rate scale (per mille) and rate index 1 = 44.1 kHz
    e.hwrd[4:8] = bytes([1, 1, 1, 1])                              # DSP readback regs: tap-set handshake answers ready
    return e


def shadow_words(e, base):
    out = []
    for i in range(0x300):
        v = e.rl(base + 4 * i)
        out.append(esp.rom_to_dsp(v >> 8) | ((v & 0xFF) << 24))
    return out


def preset_for(img, alg):
    for p in range(100):
        ptr = struct.unpack('>I', img[PRESET_TAB - 0x100000 + 4 * p:][:4])[0]
        if struct.unpack('>H', img[ptr - 0x100000:][:2])[0] == alg: return p
    raise KeyError(alg)


def capture(image, outdir, algs):
    os.makedirs(outdir, exist_ok=True)
    img = image
    res = {}
    e = make_emu(image)
    e.call(DSP_INIT, limit=50_000_000)
    dsp0 = shadow_words(e, SHADOW0); base1 = shadow_words(e, SHADOW1)
    res['dsp0'] = dsp0
    with open(os.path.join(outdir, 'live_dsp0.txt'), 'w') as f: esp.disasm(dsp0, core=0, out=f)
    for alg in algs:
        e = make_emu(image)
        e.call(DSP_INIT, limit=50_000_000)
        p = preset_for(img, alg)
        try:
            e.s16(0, p); e.s32(1, REC); e.call(PRESET_LOAD, limit=50_000_000)
            e.s32(0, REC); e.call(FX_LOAD, limit=200_000_000)
        except Exception as ex:
            print('alg %2d: FAILED at pc %06X: %s' % (alg, e.pc, ex)); continue
        ws = shadow_words(e, SHADOW1)
        res['fx%02d' % alg] = ws
        n_eram = sum(1 for w in ws if (w >> 23) & 0x18)
        with open(os.path.join(outdir, 'live_fx%02d.txt' % alg), 'w') as f:
            f.write('; alg %d preset %d: live DSP1 program (base + algorithm), %d words with ERAM start bits\n' % (alg, p, n_eram))
            esp.disasm(ws, core=1, out=f)
        print('alg %2d: preset %3d, %d ERAM transactions, %d nonzero words' % (alg, p, n_eram, sum(1 for w in ws if w)))
    json.dump(res, open(os.path.join(outdir, 'live.json'), 'w'))


if __name__ == '__main__':
    image = open(sys.argv[1], 'rb').read()
    algs = [int(a) for a in sys.argv[3:]] or list(range(20))
    capture(image, sys.argv[2], algs)
