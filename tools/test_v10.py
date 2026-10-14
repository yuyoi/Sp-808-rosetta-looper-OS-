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
        s[labels['own_load']] = self.dsp_load; s[labels['own_coef']] = self.dsp_coef; s[labels['own_eram']] = self.dsp_eram
        self.knobs = {6: 127, 7: 0, 8: 0}                   # PARA-A fully open (filter off), B and C at 0
        s[bm.KNOB_READ] = lambda e: e.s16(0, self.knobs.get(e.g16(0), 0))
        s[bm.MIXER_PARAM] = lambda e: self.routing.append((round(self.t, 1), e.g16(0), e.g16(8), e.g16(1)))
        s[bm.PAD_NOTE_ON] = self.note_on_stub; s[bm.STOP_PAD] = self.stop_stub
        def stock_pad(e):                                    # stock pad handler: a press plays the pad
            k = e.rw(bm.KEY_EVENT); self.log.append((round(self.t, 1), 'stockpad', k))
            if not k & 0x4000: e.s16(0, k & 15); self.note_on_stub(e)
            e.s16(0, 1)
        s[bm.STOCK_G1] = stock_pad; s[bm.STOCK_G8] = lambda e: e.s16(0, 0)
        s[0x13EFF0] = lambda e: None                         # stock "ignore" MIDI handler
        self.banks = {}
        def bank_switch(e):                                  # stock 0x137B5A: save the bank, load the new one, wait
            nb, ob = e.g16(0) & 0xFF, e.rb(bm.CUR_BANK)
            self.banks[ob] = self.pads
            self.pads = self.banks.get(nb) or {p: bytearray(test_v09.EMPTY) for p in range(16)}
            e.wb(bm.CUR_BANK, nb); self.log.append((round(self.t, 1), 'bank', nb))
        s[bm.BANK_SWITCH] = bank_switch
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
        elif (base & 0xF0) == 0x20: r = self.call('g2')          # PAD BANK, PAD SAMPLING, ...
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
    e.wb(bm.KTHRU, 1)                                        # as the boot RAM init (not run here) sets it
    for v_, val_ in ((bm.KMXS, 16), (bm.KPW, 8), (bm.KDET, 2), (bm.KOCT, 2)): e.wb(v_, val_)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    sim.key(bm.K_SYSTEM); sim.run(30)                        # SYSTEM = KEYS page: program load + routing
    print('enter    ', sim.kstate(), 'loaded', e.rb(bm.KLOADED), 'log', sim.dsp_log[0], '... %d writes' % len(sim.dsp_log),
          'routing', sim.routing)
    shots.append(('KEYS idle', sim.shot()))
    n0 = len(sim.dsp_log)
    sim.pad(2); sim.pad(2, False); sim.run(20)                # hitting pad 3 takes it onto the keys
    print('src pad  ', e.rb(bm.KSRC) + 1, 'bank', e.rb(bm.KBANK) + 1)
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
    # one-shot: a held note stops when its sample (639 ms recorded) runs out; an octave up after half the time
    tw = (bm.dsp_addr('thru_l') & 0xFFC) >> 2
    print('thru in PLAY: coef %d (64 = pads/tracks at full level through KEYS)' % (sim.prog[tw] & 0xFF))
    for p, name in ((7, 'root'), (14, '+7')):
        t0 = sim.t; sim.pad(p); end = None
        for _ in range(900):
            sim.run(1)
            if end is None and all(e.rb(bm.VSTATE + v) in (0, 3) for v in range(bm.NV)) and sim.t - t0 > 10: end = sim.t - t0
        sim.pad(p, False); sim.run(20)
        print('held %-4s 900 ms: voice stopped by itself after %s ms (sample 639 ms / ratio %.3f = %.0f ms)' % (
            name, None if end is None else round(end), 2 ** ((p - bm.KEYS_ROOT) / 12), 639 / 2 ** ((p - bm.KEYS_ROOT) / 12)))
    sim.pad(7); sim.pad(14); sim.run(40); shots.append(('2 notes', sim.shot())); sim.run(100)
    sim.out = []; sim.run(100); f, pk = freq(sim.out); print('chord     peak %.3f' % pk)
    sim.pad(7, False); sim.pad(14, False); sim.run(50)
    # MIDI keyboard through the stock parser's handler table: note 72 = +12, velocity, release ramp
    def midi(note, vel):
        e.wb(bm.MIDI_NOTE, note); e.wb(bm.MIDI_VEL, vel); sim.call('m_on_tr' if vel else 'm_off_tr', 0)
    midi(72, 127); sim.run(6); st = [e.rb(bm.VSTATE + v) for v in range(bm.NV)]
    sim.out = []; sim.run(200); f, pk = freq(sim.out); midi(72, 0); sim.run(30)
    print('midi 72   voices %s  f = %7.1f Hz (expect  2000.0) peak %.3f  after off: %s' % (st, f, pk, [e.rb(bm.VSTATE + v) for v in range(bm.NV)]))
    midi(60, 40); sim.run(6); sim.out = []; sim.run(200); f, pk2 = freq(sim.out); midi(60, 0); sim.run(30)
    print('midi 60 v40  f = %7.1f Hz (expect  1000.0) peak %.3f (expect %.3f)' % (f, pk2, pk * bm.VEL_TAB[40] / bm.KEYS_LEVEL))
    e.wb(bm.KREL, 5)                                          # release 500 ms
    midi(60, 127); sim.run(100); midi(60, 0); pks = []
    for _ in range(6):
        sim.out = []; sim.run(100); pks.append('%.3f' % freq(sim.out)[1])
    print('release 500ms: peak per 100 ms after note off', pks, 'states', [e.rb(bm.VSTATE + v) for v in range(bm.NV)])
    shots.append(('MIDI', sim.shot()))
    # the real path: raw bytes through the stock parser (status 0x134B0A -> handler table -> our trampolines)
    def midi_bytes(*bs):
        for b in bs: sim.call(0x134B0A if b & 0x80 else 0x134BFE, b)
    sim.call(0x134C52, 0)                                     # stock parser reset (handler pointers = ignore)
    midi_bytes(0x93, 72, 100); sim.run(6)                     # note-on, channel 4
    vp = [e.rb(bm.VPAD + v) for v in range(bm.NV)]; vs = [e.rb(bm.VSTATE + v) for v in range(bm.NV)]
    midi_bytes(72, 0); sim.run(6)                             # running status, velocity 0 = off
    print('stock parser: note 72 ch4 -> key %s, states %s; vel 0 off -> %s' % (
        36 in vp, vs, [e.rb(bm.VSTATE + v) for v in range(bm.NV)]))
    midi(10, 127); midi(120, 127); sim.run(5)
    print('out-of-range notes ignored:', e.rb(bm.MWR) == e.rb(bm.MRD), ' states', [e.rb(bm.VSTATE + v) for v in range(bm.NV)])
    sim.key(bm.K_RIGHT); sim.key(bm.K_RIGHT); sim.run(5); print('dial in PLAY: REL ->', e.rb(bm.KREL), 'src pad still', e.rb(bm.KSRC) + 1)
    sim.key(bm.K_UP); sim.run(5); print('UP in PLAY: src pad ->', e.rb(bm.KSRC) + 1)
    shots.append(('PLAY src', sim.shot()))
    sim.pad(7); sim.run(10)                                   # a note is sounding when SHIFT+EXIT comes
    sim.key(bm.K_SH_EXIT); sim.run(5)
    print('SHIFT+EXIT', sim.kstate(), 'voices', [e.rb(bm.VSTATE + v) for v in range(bm.NV)], 'page', e.rb(bm.PAGE) == bm.P_KEYS)
    shots.append(('re-pick', sim.shot()))
    sim.pad(4); sim.pad(4, False); sim.run(50); print('hit empty pad 5 ->', sim.kstate())
    import struct
    other = {p: bytearray(test_v09.EMPTY) for p in range(16)}
    other[5] = bytearray(struct.pack('>IIIHBB', 100000, 100000 + int(0.4 * FS / 16), 100000, 9, 0x05, 100) + bytes(16))
    sim.banks[4] = other                                      # bank 5, pad 6 holds a 0.4 s sample
    for _ in range(4): sim.key(bm.K_RIGHT)
    sim.run(5); print('dial x4 -> bank', e.rb(bm.KBANK) + 1, '(machine still on', e.rb(bm.CUR_BANK) + 1, ')')
    shots.append(('pick bank 5', sim.shot()))
    sim.pad(5); sim.pad(5, False); sim.run(900)
    print('hit pad 6 ->', sim.kstate(), 'machine bank', e.rb(bm.CUR_BANK) + 1, 'rec ms', e.rl(bm.KREC_MS),
          [x for x in sim.log if x[1] in ('bank', 'on')][-2:])
    sim.out = []; sim.pad(7); sim.run(200); ys = list(sim.out)
    f, pk = freq(ys); sim.pad(7, False); sim.run(30)
    print('new sample on the keys: f = %.1f Hz peak %.3f' % (f, pk))
    # ---- v1.72: PAD BANK inside KEYS (the stock bank screen left our page and switched banks behind KEYS' back) ----
    sim.run(400)                                               # earlier notes released: idle voices get muted
    Wm = lambda n: (bm.dsp_addr(n) & 0xFFC) >> 2
    print('idle voices muted: VMUTE %s lvlk %s g %s' % ([e.rb(bm.VMUTE + v) for v in range(bm.NV)],
          [sim.prog[Wm('v%d_lvlk' % v)] & 0xFF for v in range(bm.NV)], [sim.prog[Wm('v%d_g' % v)] & 0xFF for v in range(bm.NV)]))
    sim.out = []; sim.run(300); print('idle output peak %.6f' % (max(abs(y) for y in sim.out) / 0x7FFFFF))
    b0 = e.rb(bm.KBANK)
    sim.key(bm.K_PADBANK); sim.run(10)
    print('PAD BANK in PLAY -> state %s KBSEL %d bank %d page %d' % (sim.kstate(), e.rb(bm.KBSEL), e.rb(bm.KBANK) + 1, e.rb(bm.PAGE)))
    shots.append(('PAD BANK', sim.shot()))
    sim.key(bm.K_PADBANK); sim.run(10); print('PAD BANK again -> bank %d (+16)' % (e.rb(bm.KBANK) + 1))
    sim.pad(2); sim.pad(2, False); sim.run(10)
    print('pad 3 -> bank %d KBSEL %d state %s (no sampling)' % (e.rb(bm.KBANK) + 1, e.rb(bm.KBSEL), sim.kstate()))
    sim.key(bm.K_PADBANK); sim.key(bm.K_EXIT); sim.run(10)
    print('PAD BANK, EXIT -> KBSEL %d page %d (still KEYS)' % (e.rb(bm.KBSEL), e.rb(bm.PAGE)))
    for _ in range(4): sim.key(bm.K_PADBANK)                   # on, +16, +16, +16: back to banks 1-16
    sim.pad(b0); sim.pad(b0, False); sim.run(10)
    print('back to bank %d (was %d)' % (e.rb(bm.KBANK) + 1, b0 + 1))
    sim.pad(5); sim.pad(5, False); sim.run(1200); f, pk = freq(sim.out[-4000:]) if False else (0, 0)
    print('hit pad 6 -> %s rec ms %d' % (sim.kstate(), e.rl(bm.KREC_MS)))
    # ---- v1.6: knobs (filter, attack), EDIT page, reverse, Roland's DSP writes gated ----
    W = lambda n: (bm.dsp_addr(n) & 0xFFC) >> 2
    cf = lambda n: sim.prog[W(n)] & 0xFF
    print('knobs at rest: wet %d dry %d (filter off: 0 64), KATT %d, gate %d' % (cf('flt_wet'), cf('flt_dry'), e.rb(bm.KATT), e.rb(bm.KGATE)))
    sim.knobs[6] = 80; sim.knobs[7] = 100; sim.run(30)
    print('knob A 80, B 100: wet %d dry %d f %d/%d q %d/%d (cutoff %d Hz; on: 64 0)' % (cf('flt_wet'), cf('flt_dry'), cf('flt_f1'), cf('flt_f1l'),
          cf('flt_q'), cf('flt_ql'), bm.CUT_HZ[80]))
    sim.knobs[6] = 127; sim.run(30); print('knob A 127: wet %d dry %d' % (cf('flt_wet'), cf('flt_dry')))
    sim.knobs[8] = 8 * 9; sim.run(30)                         # attack index 9 = 200 ms
    print('knob C %d -> KATT %d (%d ms)' % (sim.knobs[8], e.rb(bm.KATT), bm.ATT_MS[e.rb(bm.KATT)]))
    e.wb(bm.KREL, 3); sim.run(300)                            # let the earlier notes finish first
    sim.out = []; sim.pad(7); pk = []
    for _ in range(6):
        sim.run(50); pk.append('%.3f' % (max(abs(y) for y in sim.out[-2000:]) / 0x7FFFFF))
    st = [e.rb(bm.VSTATE + v) for v in range(bm.NV)]
    sim.pad(7, False); sim.run(400)
    print('attack 200 ms: peak per 50 ms', pk, 'states after 300 ms', st)
    sim.knobs[8] = 0; sim.run(30)
    # gate: Roland's coefficient write into DSP1 while KEYS owns it is dropped (returns without writing)
    n0 = len(sim.dsp_log); e.s16(0, 0x1000 | (W('flt_wet') << 2)); e.s16(8, 0x7F00)
    sim.call('gate_coef'); print('gate: Roland write while KEYS active -> %d writes' % (len(sim.dsp_log) - n0))
    # EDIT tile: home, cursor to EDIT, ENTER
    sim.key(bm.K_EXIT); sim.run(10)
    for _ in range(4): sim.key(bm.K_LEFT)
    for _ in range(3): sim.key(bm.K_RIGHT)
    sim.key(bm.K_ENTER); sim.run(20)
    print('EDIT tile -> page', e.rb(bm.PAGE), 'active', e.rb(bm.KACTIVE), 'state', sim.kstate())
    shots.append(('EDIT page', sim.shot()))
    sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(20)                     # THRU off (pads/tracks muted in KEYS)
    print('THRU toggled: KTHRU %d thru coef %d (expect 0 0)' % (e.rb(bm.KTHRU), sim.prog[W('thru_l')] & 0xFF))
    sim.key(bm.K_ENTER); sim.run(20); print('THRU toggled: KTHRU %d thru coef %d (expect 1 64)' % (e.rb(bm.KTHRU), sim.prog[W('thru_l')] & 0xFF))
    sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(20)
    print('REVERSE on: KREV %d ref_f %d ref_r %d v0_dir %d v7_dir %d' % (e.rb(bm.KREV), cf('ref_f'), cf('ref_r'),
          sim.prog[W('v0_dir')] & 0xFF, sim.prog[W('v7_dir')] & 0xFF))
    shots.append(('EDIT reverse', sim.shot()))
    sim.pad(7); sim.run(60); print('pad on EDIT page plays KEYS: states', [e.rb(bm.VSTATE + v) for v in range(bm.NV)]); sim.pad(7, False); sim.run(300)
    sim.key(bm.K_ENTER); sim.run(20); print('REVERSE off: KREV %d v0_dir %d' % (e.rb(bm.KREV), sim.prog[W('v0_dir')] & 0xFF))
    # LOOP: DOWN to the LOOP switch, ENTER; hold the root pad 3x the take, the sound must not stop
    sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(20)
    print('LOOP on: KLOOP %d  first %d ms, LL %d ms, XF %d ms, soff %d/%d/%d (take %d ms)' % (e.rb(bm.KLOOP), e.rw(bm.LP_FIRST),
          e.rw(bm.LP_LL), e.rw(bm.LP_XF), cf('soff_a'), cf('soff_b'), cf('soff_c'), e.rl(bm.KREC_MS)))
    shots.append(('S-EDIT loop', sim.shot()))
    sim.out = []; sim.pad(7); pk, sts = [], []
    for _ in range(15):
        sim.run(100); ys = sim.out[-4000:]; pk.append('%.3f' % (max(abs(y) for y in ys) / 0x7FFFFF))
        sts.append(''.join(str(e.rb(bm.VSTATE + v)) for v in range(bm.NV)))
    print('hold 1.5 s, peak per 100 ms:', pk)
    print('  voice states per 100 ms:', sts)
    ys = sim.out[2000:]; print('  f over the hold %.0f Hz' % freq(ys)[0])
    sim.pad(7, False); sim.run(700)
    print('  after release:', [e.rb(bm.VSTATE + v) for v in range(bm.NV)], 'VXF', [e.rb(bm.VXF + v) for v in range(bm.NV)])
    sim.key(bm.K_UP); sim.key(bm.K_ENTER); sim.run(20)                       # reverse on, loop still on
    sim.out = []; sim.pad(7); pk, sts = [], []
    for _ in range(15):
        sim.run(100); ys = sim.out[-4000:]; pk.append('%.3f' % (max(abs(y) for y in ys) / 0x7FFFFF))
        sts.append(''.join(str(e.rb(bm.VSTATE + v)) for v in range(bm.NV)))
    print('REVERSE + LOOP (KREV %d) hold 1.5 s, peak per 100 ms:' % e.rb(bm.KREV), pk)
    print('  voice states per 100 ms:', sts)
    ys = sim.out[2000:]; print('  f over the hold %.0f Hz' % freq(ys)[0])
    sim.pad(7, False); sim.run(700)
    print('  after release:', [e.rb(bm.VSTATE + v) for v in range(bm.NV)], 'VXF', [e.rb(bm.VXF + v) for v in range(bm.NV)])
    sim.key(bm.K_ENTER); sim.key(bm.K_DOWN); sim.run(20)                     # reverse off, cursor back on LOOP
    sim.key(bm.K_ENTER); sim.run(20); print('LOOP off: KLOOP', e.rb(bm.KLOOP))
    sim.key(bm.K_EXIT); sim.run(10); print('EXIT -> page', e.rb(bm.PAGE), 'active', e.rb(bm.KACTIVE), 'gate', e.rb(bm.KGATE), 'CUR', e.rb(bm.CUR))
    sim.key(bm.K_RIGHT); sim.run(5); shots.append(('home scrolled', sim.shot()))
    # ---- v1.8: DDS-DSP (oscillators per voice) ----
    sim.key(bm.K_ENTER); sim.run(20)
    print('DDS-DSP tile -> page %d active %d state %s' % (e.rb(bm.PAGE), e.rb(bm.KACTIVE), sim.kstate()))
    for _ in range(16): sim.key(bm.K_LEFT)                     # SAMPLE 16 -> 0
    sim.key(bm.K_DOWN)
    for _ in range(16): sim.key(bm.K_RIGHT)                    # SAW 0 -> 16
    sim.run(20); shots.append(('DDS-DSP', sim.shot()))
    print('SAMPLE %d SAW %d: v0 mxs %d mxsaw %d, v7 mxsaw %d' % (e.rb(bm.KMXS), e.rb(bm.KMXSAW), cf('v0_mxs'), cf('v0_mxsaw'), cf('v7_mxsaw')))
    sim.out = []; sim.pad(7); sim.run(1000)                    # root pad held 1 s (the take is 439 ms)
    st = [e.rb(bm.VSTATE + v) for v in range(bm.NV)]
    f, pk = freq(sim.out[-22000:])
    print('saw, pad 8 held 1 s: f = %.1f Hz (expect 261.6, C4) peak %.3f states %s (sustains past the take)' % (f, pk, st))
    sim.pad(7, False); sim.run(400); print('  released:', [e.rb(bm.VSTATE + v) for v in range(bm.NV)])
    for _ in range(2): sim.key(bm.K_DOWN)                      # -> PW
    for _ in range(4): sim.key(bm.K_RIGHT)                     # PW 8 -> 12 (75 %)
    sim.key(bm.K_DOWN); sim.key(bm.K_DOWN)                     # -> UNISON
    for _ in range(8): sim.key(bm.K_RIGHT)
    sim.key(bm.K_DOWN)                                         # -> DETUNE
    for _ in range(2): sim.key(bm.K_RIGHT)                     # 2 -> 4 (25 cents)
    sim.run(20); shots.append(('DDS-DSP 2', sim.shot()))
    print('PW %d (v0 pw coef %d) UNISON %d (v3 mxuni %d) DETUNE %d' % (e.rb(bm.KPW), sim.prog[W('v0_pw')] & 0xFF,
          e.rb(bm.KMXUNI), cf('v3_mxuni'), e.rb(bm.KDET)))
    sim.out = []; sim.pad(14); sim.run(600)                    # +7 semitones, saw + detuned unison saw
    o = [sim.prog[W('v%d_o2%s' % (v, ab))] & 0xFF for v in range(bm.NV) for ab in 'ab']
    f, pk = freq(sim.out[-13000:])
    print('pad 15 (+7) saw + unison: f = %.1f Hz (expect 392.0) peak %.3f; o2 fields a/b per voice %s' % (f, pk, o))
    sim.pad(14, False); sim.run(400)
    for _ in range(7): sim.key(bm.K_UP)                        # back to SAMPLE
    for _ in range(16): sim.key(bm.K_RIGHT)
    sim.key(bm.K_DOWN)
    for _ in range(16): sim.key(bm.K_LEFT)                     # SAW 0 again
    for _ in range(4): sim.key(bm.K_DOWN)
    for _ in range(8): sim.key(bm.K_LEFT)                      # UNISON 0
    print('restored: SAMPLE %d SAW %d UNISON %d' % (e.rb(bm.KMXS), e.rb(bm.KMXSAW), e.rb(bm.KMXUNI)))
    sim.key(bm.K_EXIT); sim.run(10); print('EXIT -> page %d CUR %d' % (e.rb(bm.PAGE), e.rb(bm.CUR)))
    sim.key(bm.K_LEFT)
    sim.key(bm.K_LEFT); sim.key(bm.K_ENTER); sim.run(20)                     # back to KEYS
    # leaving KEYS without EXIT (mode keys): the master routing must come back, KEYS re-arms on return
    sim.key(bm.K_SAMPLE); sim.run(10)
    print('SAMPLE -> page', e.rb(bm.PAGE), 'route code %02X' % e.rb(bm.FX_ROUTE_CODE), 'active', e.rb(bm.KACTIVE), 'state', sim.kstate())
    sim.key(bm.K_SYSTEM); sim.run(10)
    print('SYSTEM -> page', e.rb(bm.PAGE), 'route code %02X' % e.rb(bm.FX_ROUTE_CODE), 'active', e.rb(bm.KACTIVE), 'state', sim.kstate())
    sim.key(bm.K_SONG); sim.run(10)
    print('SONG   -> page', e.rb(bm.PAGE), 'route code %02X' % e.rb(bm.FX_ROUTE_CODE), 'active', e.rb(bm.KACTIVE))
    e.ww(bm.FX_CUR, 5)                                        # meanwhile the stock FX engine loads algorithm 5
    nl = len([x for x in sim.dsp_log if x[1] == 'load'])
    sim.key(bm.K_SYSTEM); sim.run(10)
    print('SYSTEM after a stock FX load -> reloaded', len([x for x in sim.dsp_log if x[1] == 'load']) - nl, 'state', sim.kstate(),
          'route code %02X' % e.rb(bm.FX_ROUTE_CODE))
    sim.call('menu', 1)                                       # screen 5 left for a stock screen (event 1); its idle stops
    print('leave event -> route code %02X' % e.rb(bm.FX_ROUTE_CODE), 'active', e.rb(bm.KACTIVE))
    sim.run(10); print('back (idle on page KEYS) -> route code %02X' % e.rb(bm.FX_ROUTE_CODE), 'active', e.rb(bm.KACTIVE))
    sim.key(bm.K_EXIT); sim.run(10)
    print('exit      page', e.rb(bm.PAGE), 'routing calls', sim.routing, 'route code %02X' % e.rb(bm.FX_ROUTE_CODE))
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:3])
