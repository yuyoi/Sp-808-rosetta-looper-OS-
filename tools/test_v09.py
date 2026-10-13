"""Play through a LOOPER session of v0.9 in the H8S emulator, with the stock OS faked in Python.

usage: python -I test_v09.py build_v09/sp808_v09.bin out.png
Fakes: the screen engine (commit = old screen event 1, new screen 0, 5, 2; idle = event 6 every 10 ms), the
pad table, the stock record (0x22) / take (0x23) handlers, note-on/off and a 1 ms clock that also runs while
our code spins (1 ms per 2000 instructions). Checks layer lengths, start phases and undo; renders the LOOP page.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h8emu, ui_gfx, gfxlib
import importlib
bm = importlib.import_module(os.environ.get('LOOPER_BUILD', 'build_v09b'))

DOTS = 0x4018AA
UNITS_PER_MS = 44.1 / 16
EMPTY = b'\xff\xff' + bytes(2) + b'\xff\xff' + bytes(2) + b'\xff\xff' + bytes(2) + b'\xff\xff' + bytes(18)


class Sim:
    def __init__(self, image, labels):
        self.e = e = h8emu.Emu(image)
        self.L = labels
        e.wl(gfxlib.LCD_FBPTR, DOTS)
        self.t = 1000.0
        self.pads = {p: bytearray(EMPTY) for p in range(16)}
        self.log = []                                    # (ms, what, arg)
        self.screen, self.pending = bm.SCREEN, None
        self.rec_start = None
        self.wave = 10
        e.ww(bm.FREE_BLK, 3000); e.ww(bm.RSV_BLK, 0)
        e.wb(bm.CUR_BANK, 0); e.wb(bm.HIST_DIV, 1); e.ww(bm.CUR_SCREEN, bm.SCREEN)
        for v, x in ((bm.PAD_PLAY_SET, 0), (bm.LOOP_SET, 0), (bm.AUTO_TRIM_SET, 1), (bm.TRIG_MODE, 3)): e.wb(v, x)
        self.handlers = {bm.SCREEN: labels['menu'], bm.SCR_RECORD: labels['w22'], bm.SCR_DONE: labels['w23']}
        s = e.stubs
        def note(what):
            return lambda e: self.log.append((round(self.t, 1), what, e.g16(0)))
        s[bm.PAD_NOTE_ON] = note('on'); s[bm.STOP_PAD] = note('stop')
        s[bm.ALL_PADS_OFF] = lambda e: self.log.append((round(self.t, 1), 'alloff', 0))
        s[bm.WAVE_FREE] = note('free')
        s[bm.ENTRY_EMPTY] = lambda e: [e.wb(e.g32(0) + i, EMPTY[i]) for i in range(32)]
        s[bm.PAD_GET] = self.pad_get; s[bm.PAD_SET] = self.pad_set
        s[bm.PAD_SET_POST] = s[bm.PAD_REFRESH] = s[bm.PAD_NORMAL] = lambda e: None
        s[bm.SMPL_LOCK] = lambda e: self.lock(1); s[bm.SMPL_UNLOCK] = lambda e: self.lock(0)
        s[bm.ARM_TRIGGER] = lambda e: None
        s[0x120332] = s[0x11F2AE] = lambda e: None
        s[bm.SELECT_PAD] = lambda e: e.wb(bm.SMP_PAD, e.rb(bm.SEL_PAD))
        s[bm.MEM_CHECK] = lambda e: e.s16(0, 1)
        s[bm.FIRST_FREE_PAD] = lambda e: e.s16(0, next((p for p in range(16) if self.pads[p][:2] == b'\xff\xff'), 0xFFFF))
        s[bm.PAD_USED] = lambda e: e.s16(0, int(self.pads[e.g16(0) & 15][:2] != b'\xff\xff'))
        s[bm.GOTO_SCREEN] = self.goto
        s[bm.SEG_POS] = s[bm.SEG_PUT] = lambda e: None
        s[bm.STOCK_SCR22] = self.stock22; s[bm.STOCK_SCR23] = self.stock23
        e.on_step = self.clock

    def lock(self, on):                                  # 0x42790E bit 1 (+ bit 2 with 0x13F2C2)
        b = self.e.rb(0x42790E); self.e.wb(0x42790E, (b | 2) if on else (b & 0xF9))
    def goto(self, e):                                   # 0x13FC0E: ignored while locked
        if self.e.rb(0x42790E) & 2: e.s16(0, 0); self.log.append((round(self.t, 1), 'goto refused', e.g16(0))); return
        self.pending = e.g16(0); e.s16(0, 1)
    def clock(self, e):
        old = int(self.t); self.t += 1 / 2000
        if int(self.t) != old: e.wl(bm.TICK_MS, int(self.t))

    def pad_get(self, e):
        p = (e.g16(0) >> 8) & 15
        for i, b in enumerate(self.pads[p]): e.wb(e.g32(1) + i, b)
        e.s16(0, 1)
    def pad_set(self, e):
        p = (e.g16(0) >> 8) & 15
        self.pads[p] = bytearray(e.rb(e.g32(1) + i) for i in range(32))
        self.log.append((round(self.t, 1), 'set', p))

    def stock22(self, e):
        ev = e.g16(0)
        if ev == 0:                                      # arm: INSTANT -> recording now
            e.wb(bm.SIG_WAIT_LO, e.rb(bm.SIG_WAIT_LO) | 0x05); e.wb(bm.SIG_STAT, 0); self.lock(1)
            self.rec_start = self.t
        elif ev == 1:                                    # leave: unlock; unfinished = cancelled take
            self.lock(0)
            if self.rec_start is not None: e.ww(bm.TAKE_WAVE, self.wave); self.wave += 1; self.rec_start = None
        elif ev == bm.EV_STOCK_FINISH:
            self.take_ms = self.t - self.rec_start; self.rec_start = None
            self.lock(0); self.pending = bm.SCR_DONE; self.lock(1)
    def stock23(self, e):
        if e.g16(0) == 0: self.lock(0)
        if e.g16(0) == 2:                                # write the take into SMP_PAD
            self.lock(1)
            start = 5000 + 100000 * self.wave
            ent = struct.pack('>IIIHBB', start, start + int(self.take_ms * UNITS_PER_MS), start, self.wave, 0x05, 100)
            self.pads[e.rb(bm.SMP_PAD)] = bytearray(ent + bytes(16)); self.wave += 1

    # ---- screen engine ----
    def call(self, lbl_or_addr, r0=None):
        e = self.e
        if r0 is not None: e.s16(0, r0)
        e.steps = 0
        e.call(lbl_or_addr if isinstance(lbl_or_addr, int) else self.L[lbl_or_addr])
        return e.g16(0)
    def commit(self):
        while self.pending is not None:
            new, self.pending = self.pending, None
            self.call(self.handlers[self.screen], 1)
            self.screen = new; self.e.ww(bm.CUR_SCREEN, new)
            for ev in (0, 5, 2): self.call(self.handlers[new], ev)
    def run(self, ms):
        end = self.t + ms
        while self.t < end:
            self.commit()
            self.call(self.handlers[self.screen], 6)
            self.t += 10; self.e.wl(bm.TICK_MS, int(self.t))
        self.commit()
    def key(self, code):
        self.e.ww(bm.KEY_EVENT, code)
        if self.call('g2') == 0: self.call(self.handlers[self.screen], 9)
        self.commit()
    def tap(self): self.key(bm.K_PADSMPL); self.key(bm.K_PADSMPL | 0x4000)
    def shot(self):
        c = ui_gfx.Canvas()
        for y in range(32):
            px = gfxlib.unpack6(bytes(self.e.rb(DOTS + 24 * y + i) for i in range(24)))
            for x in range(128): c.px[y][x] = px[x + gfxlib.LCD_X0]
        return c
    def state(self): return ['EMPTY', 'REC1', 'BUSY', 'PLAY', 'DUB', 'STOP'][self.e.rb(bm.LSTATE)]
    def entry(self, p): return struct.unpack('>IIIHBB', bytes(self.pads[p][:16]))


def main(image_path, out):
    sim = Sim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    e.wb(bm.PAGE, bm.P_LOOP); sim.call('menu', 5); shots.append(('READY', sim.shot()))
    sim.tap(); sim.run(30); print('tap 1    ', sim.state(), 'screen %X' % sim.screen, 'pad play/loop/trig',
                                 e.rb(bm.PAD_PLAY_SET), e.rb(bm.LOOP_SET), e.rb(bm.TRIG_MODE))
    sim.run(2000); shots.append(('REC layer 1 (2 s)', sim.shot()))
    sim.tap(); print('tap 2    ', sim.state(), 'take %.0f ms' % sim.take_ms)
    sim.run(50)
    s, en, lp, w, fl, lv = sim.entry(0)
    llen, llen_ms = e.rl(bm.LLEN), e.rw(bm.LLEN_MS)
    print('layer 1   pad 1 len %d units = %d ms, loop pt %s, flags %02X | state %s, settings back %d %d %d'
          % (en - s, llen_ms, lp == s, fl, sim.state(), e.rb(bm.PAD_PLAY_SET), e.rb(bm.LOOP_SET), e.rb(bm.TRIG_MODE)))
    t0 = next(t for t, what, p in sim.log if what == 'on' and p == 0)
    sim.run(700); shots.append(('PLAY, 1 layer', sim.shot()))
    sim.tap(); ph_ms = e.rl(bm.LTAKE_PH) / UNITS_PER_MS
    print('tap 3     DUB starts at phase %.0f ms (expected %.0f)' % (ph_ms, (sim.t - t0) % llen_ms))
    sim.run(1000); shots.append(('DUB layer 2', sim.shot()))
    sim.run(llen_ms + 400)
    s2, en2 = sim.entry(1)[:2]
    print('layer 2   len %d units (loop %d) | state %s, pending %02X' % (en2 - s2, llen, sim.state(), e.rb(bm.LPEND)))
    sim.run(llen_ms + 100)
    t2 = [t for t, what, p in sim.log if what == 'on' and p == 1]
    print('layer 2   started at loop phase %.1f ms (recorded at %.1f ms)' % ((t2[0] - t0) % (llen / UNITS_PER_MS), ph_ms))
    shots.append(('PLAY, 2 layers', sim.shot()))
    sim.key(bm.K_PADSMPL); sim.run(100); sim.key(bm.K_PADSMPL); sim.run(30)
    print('2x tap    ', sim.state(), 'screen %X' % sim.screen, 'last:', sim.log[-3:])
    shots.append(('STOP (double tap)', sim.shot()))
    sim.tap(); sim.run(llen_ms + 100)
    print('tap       ', sim.state(), 'starts:', [(t, p) for t, w_, p in sim.log if w_ == 'on'][-2:])
    sim.key(bm.K_PADSMPL); sim.run(1500); sim.key(bm.K_PADSMPL | 0x4000); sim.run(50)
    print('hold      ', sim.state(), 'layers %d, pad 2 empty %s, screen %X, last:' % (e.rb(bm.NLAYER),
          sim.pads[1][:2] == b'\xff\xff', sim.screen), sim.log[-4:])
    shots.append(('after HOLD = undo', sim.shot()))
    sim.key(bm.K_PADSMPL); sim.run(100); sim.key(bm.K_PADSMPL); sim.run(30)
    sim.key(bm.K_PADSMPL); sim.run(1500); sim.key(bm.K_PADSMPL | 0x4000); sim.run(50)
    print('stop+hold ', sim.state(), 'layers %d, pad 1 empty %s' % (e.rb(bm.NLAYER), sim.pads[0][:2] == b'\xff\xff'))
    shots.append(('after STOP + HOLD = clear', sim.shot()))
    if hasattr(bm, 'LDEBUG'):
        e.wb(bm.LDEBUG, 1); sim.call('lp_draw'); shots.append(('ENTER = debug trace', sim.shot()))
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:3])
