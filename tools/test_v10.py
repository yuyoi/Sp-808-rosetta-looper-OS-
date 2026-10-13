"""KEYS mode end-to-end test: the v1.0 firmware runs in the H8S emulator, every DSP write it makes is applied to the
ESP (DSP1) model, which runs 44 samples per emulated millisecond.  The "source pad" is a 1 kHz sine fed into the
FX input while the pad plays.  Checks: program load, routing call, sampling (onset, length), notes on pads.

usage: python -I tools/test_v10.py build_v10/sp808_v10.bin out.png
"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['LOOPER_BUILD'] = 'build_v10'
import test_v09, keysdsp, esp, ui_gfx
bm = test_v09.bm

FS = 44100


class KeysSim(test_v09.Sim):
    def __init__(self, image, labels):
        super().__init__(image, labels)
        e, s = self.e, self.e.stubs
        self.prog = [0] * 0x300                              # what the hardware DSP1 holds (DSP view)
        import json
        P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'dsp', 'programs.json')))
        base = [esp.rom_to_dsp(w) for w in P['dsp1_base']['words']]
        self.prog[:len(base)] = base
        self.gram = [0] * 256; self.eram = esp.Eram(17)
        self.core = esp.Core(self.prog, self.gram, self.eram, name='dsp1')
        self.prog = self.core.prog                           # the core keeps its own copy: write into that one
        self.dsp_log = []; self.pad_playing = None; self.pad_t = 0.0; self.routing = []
        self.out = []
        s[bm.DSP_LOAD] = self.dsp_load; s[bm.DSP_COEF] = self.dsp_coef; s[bm.DSP_ERAM] = self.dsp_eram
        s[bm.MIXER_PARAM] = lambda e: self.routing.append((round(self.t, 1), e.g16(0), e.g16(8), e.g16(1)))
        s[bm.PAD_NOTE_ON] = self.note_on_stub; s[bm.STOP_PAD] = self.stop_stub
        def stock_pad(e):                                    # stock pad handler: a press plays the pad
            k = e.rw(bm.KEY_EVENT); self.log.append((round(self.t, 1), 'stockpad', k))
            if not k & 0x4000: e.s16(0, k & 15); self.note_on_stub(e)
            e.s16(0, 1)
        s[bm.STOCK_G1] = stock_pad; s[bm.STOCK_G8] = lambda e: e.s16(0, 0)
        e.wb(bm.FX_ROUTE_CODE, 0x01)                         # stock: send/return
        for p in range(16): self.pads[p] = bytearray(test_v09.EMPTY)
        import struct
        start = 100000; n_units = int(0.6 * FS / 16)         # pad 3 holds a 0.6 s sample
        self.pads[2] = bytearray(struct.pack('>IIIHBB', start, start + n_units, start, 7, 0x05, 100) + bytes(16))

    # ---- DSP host port stubs ----
    def dsp_load(self, e):
        chip, start, count, src = e.g16(0), e.g16(8), e.g16(1), e.rl(e.er[7])     # stub: no return address pushed
        assert chip == 1 and start == 0x3C and start + count <= 0x300, (chip, start, count)
        for i in range(count):
            w = (e.rb(src + 3 * i) << 16) | (e.rb(src + 3 * i + 1) << 8) | e.rb(src + 3 * i + 2)
            self.prog[start + i] = esp.rom_to_dsp(w)
        self.prog[0x2F2] = 0                                   # (the OS would put JMP 0xF1 here; harmless nops there)
        self.dsp_log.append((round(self.t, 1), 'load', count))
    def dsp_coef(self, e):
        addr, val = e.g16(0), e.g16(8)
        assert addr & 0x1000, 'coef write to DSP0 %04X' % addr
        w = (addr & 0xFFC) >> 2
        keysdsp.set_coef(self.prog, w, val >> 8, val & 3)
        self.dsp_log.append((round(self.t, 1), 'coef', w, val))
    def dsp_eram(self, e):
        addr, img = e.g16(0), e.g32(1)
        assert addr & 0x1000
        w = (addr & 0xFFC) >> 2
        mode = (img >> 27) & 0x1F
        imm = ((img >> 16) & 0xFF) | (((img >> 8) & 0xFF) << 8) | ((img & 0xF) << 16)
        keysdsp.set_eram(self.prog, w, mode, imm)
        self.dsp_log.append((round(self.t, 1), 'eram', w, mode, imm))
    def note_on_stub(self, e):
        self.log.append((round(self.t, 1), 'on', e.g16(0)))
        self.pad_playing, self.pad_t = e.g16(0), self.t + 60     # the disk needs ~60 ms before sound comes out
    def stop_stub(self, e):
        self.log.append((round(self.t, 1), 'stop', e.g16(0))); self.pad_playing = None

    # ---- time: 1 ms of DSP per idle pass ----
    def dsp_ms(self):
        for k in range(44):
            self.nsamp = getattr(self, 'nsamp', 0) + 1     # the tone's time base is the DSP sample count
            s = 0
            if self.pad_playing is not None and self.t >= self.pad_t:
                s = int(0.5 * 0x7FFFFF * math.sin(2 * math.pi * 1000 * self.nsamp / FS))
            self.core.wg(0x71, s); self.core.wg(0x75, s)
            self.core.run_sample(); self.eram.tick_sample()
            self.out.append(self.core.rg(0x73))
        v = self.core.hostreg & 0xFFFFFF                       # readback bytes: the 24-bit value, low byte first
        self.e.hwrd[4:8] = bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, 0])
    def run(self, ms):
        end = self.t + ms
        while self.t < end:
            self.commit()
            self.call(self.handlers[self.screen], 6)
            self.dsp_ms()
            self.t += 1; self.e.wl(bm.TICK_MS, int(self.t))
        self.commit()
    def key(self, code):                                     # dispatch like the OS: key groups, then the screen
        e = self.e; e.ww(bm.KEY_EVENT, code); base = code & 0xFF
        if base in (bm.K_SONG, bm.K_SYSTEM, bm.K_SAMPLE) or code == bm.K_SH_SYSTEM: r = self.call('g8')
        elif (base & 0xF0) == 0x10: r = self.call('g1')
        elif base == bm.K_PADSMPL: r = self.call('g2')
        else: r = 0
        if r == 0: self.call(self.handlers[self.screen], 9)
        self.commit()
    def pad(self, p, down=True): self.key((0x10 | p) | (0 if down else 0x4000))
    def kstate(self): return ['IDLE', 'WAIT', 'REC0', 'REC', 'PLAY'][self.e.rb(bm.KSTATE)]


def freq(ys):
    ys = ys[len(ys) // 4:]
    zc = sum(1 for a, b in zip(ys, ys[1:]) if a < 0 <= b)
    return zc * FS / max(1, len(ys)), max(abs(y) for y in ys) / 0x7FFFFF


def main(image_path, out):
    sim = KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    sim.key(bm.K_SYSTEM); sim.run(30)                        # SYSTEM = KEYS page: program load + routing
    print('enter    ', sim.kstate(), 'loaded', e.rb(bm.KLOADED), 'log', sim.dsp_log[0], '... %d writes' % len(sim.dsp_log),
          'routing', sim.routing)
    shots.append(('KEYS idle', sim.shot()))
    sim.key(bm.K_RIGHT); sim.key(bm.K_RIGHT); sim.run(5)      # source pad 3
    print('src pad  ', e.rb(bm.KSRC) + 1)
    n0 = len(sim.dsp_log)
    sim.key(bm.K_ENTER); sim.run(20)
    print('sample   ', sim.kstate(), 'pad on at', [x for x in sim.log if x[1] == 'on'][-1], 'writes', sim.dsp_log[n0:n0 + 3])
    sim.run(60); print('onset    ', sim.kstate(), 't=%.0f' % sim.t, 'hostreg %06X' % (sim.core.hostreg & 0xFFFFFF))
    shots.append(('SAMPLING', sim.shot()))
    sim.run(800)
    print('done     ', sim.kstate(), 'rec ms', e.rl(bm.KREC_MS), 'stop', [x for x in sim.log if x[1] == 'stop'][-1:],
          'writes off', [x for x in sim.dsp_log if x[1] == 'eram' and x[3] == 0][-2:])
    shots.append(('PLAY', sim.shot()))
    # notes: pad 8 (root), pad 15 (+7), pad 1 (-7)
    for p, name in ((7, 'root'), (14, '+7'), (0, '-7')):
        sim.out = []
        sim.pad(p); sim.run(6)
        st = [e.rb(bm.VSTATE + v) for v in range(bm.NV)]
        sim.run(200); f, pk = freq(sim.out)
        sim.pad(p, False); sim.run(30)
        ratio = 2 ** ((p - bm.KEYS_ROOT) / 12)
        print('pad %2d %-4s voices %s  f = %7.1f Hz (expect %7.1f) peak %.3f  after release: %s' % (
            p + 1, name, st, f, 1000 * ratio, pk, [e.rb(bm.VSTATE + v) for v in range(bm.NV)]))
    sim.pad(7); sim.pad(14); sim.run(5); shots.append(('2 notes', sim.shot())); sim.run(100)
    sim.out = []; sim.run(100); f, pk = freq(sim.out); print('chord     peak %.3f' % pk)
    sim.pad(7, False); sim.pad(14, False); sim.run(50)
    sim.key(bm.K_EXIT); sim.run(10)
    print('exit      page', e.rb(bm.PAGE), 'routing calls', sim.routing, 'route code %02X' % e.rb(bm.FX_ROUTE_CODE))
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:3])
