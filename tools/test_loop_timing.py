"""Looper timing trace (LOOP lane): ms since the last looper press on every trace entry, ENTER cycles the pages.

usage: python -I tools/test_loop_timing.py work/build_v10/sp808_v10.bin out.png
Runs the v0.9 looper session sim (test_v09.Sim) on the current build: layer 1 (2 s), then a DUB that must end by
itself after one loop. Stock routines the old sim does not fake (0x132880 / 0x132866, 7-seg) run as no-ops.
Checks: the trace letters in order, ms rising along the take pipeline, the DUB auto-stop near one loop, the
ENTER cycle off -> values -> ms -> off. Renders both trace pages.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['LOOPER_BUILD'] = 'build_v10'
import h8emu

_goto = h8emu.Emu.goto_sub
def _goto_sub(self, target, ret):                               # unknown stock call: no-op returning 0
    if target in self.stubs or self.code_lo <= target < self.code_hi: return _goto(self, target, ret)
    self.s16(0, 0); self.pc = ret
h8emu.Emu.goto_sub = _goto_sub

import test_v09, ui_gfx
bm = test_v09.bm


def ring(e):                                                    # oldest first: (letter, value, ms)
    pos, out = e.rb(bm.TR_POS), []
    for k in range(1, 16):
        i = (pos + k) & 15
        ch = e.rb(bm.TRACE + 3 * i)
        if ch:
            out.append((chr(ch), (e.rb(bm.TRACE + 3 * i + 1) << 8) | e.rb(bm.TRACE + 3 * i + 2),
                        (e.rb(bm.LV_TRT + 2 * i) << 8) | e.rb(bm.LV_TRT + 2 * i + 1)))
    return out


def main(image_path, out):
    sim = test_v09.Sim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots, bad = sim.e, [], []
    def check(ok, what):
        print('%s %s' % ('ok  ' if ok else 'FAIL', what))
        if not ok: bad.append(what)
    e.wb(bm.PAGE, bm.P_LOOP); sim.call('menu', 5)
    sim.tap(); sim.run(2000); sim.tap(); sim.run(300)
    r = ring(e)
    print('loop 1:', ' '.join('%s%04X@%d' % x for x in r))
    letters = ''.join(x[0] for x in r)
    check(sim.state() == 'PLAY', 'layer 1 plays')
    check(letters.endswith('RQSEPBWDGN'), 'close-tap pipeline traced (R Q S E P B W D G N)')
    tail = [x[2] for x in r[-10:]]
    check(tail == sorted(tail) and tail[0] == 0, 'ms counts from the closing press and only rises')
    for m in (1, 2):
        e.wb(bm.LDEBUG, m); sim.call('lp_draw'); shots.append(('trace page %d (%s)' % (m, 'values' if m == 1 else 'ms'), sim.shot()))
    e.wb(bm.LDEBUG, 0)
    sim.run(500); sim.tap()
    llen = (e.rb(bm.LLEN_MS) << 8) | e.rb(bm.LLEN_MS + 1)
    sim.run(llen + 600)
    r = ring(e)
    print('dub   :', ' '.join('%s%04X@%d' % x for x in r))
    s = [x for x in r if x[0] == 'S']
    check(sim.state() == 'PLAY' and e.rb(bm.NLAYER) == 2, 'DUB ended by itself, 2 layers')
    check(bool(s) and s[-1][1] == 2 and llen <= s[-1][2] <= llen + 300, 'auto stop (S 0002) one loop after the press')
    check(any(x[0] == 'I' for x in r), 'first record idle traced (I)')
    e.wb(bm.LDEBUG, 2); sim.call('lp_draw'); shots.append(('ms page after the DUB', sim.shot()))
    e.wb(bm.LDEBUG, 0); seq = []
    for _ in range(3):
        e.ww(bm.KEY_EVENT, bm.K_ENTER); sim.call('menu', 9); seq.append(e.rb(bm.LDEBUG))
    check(seq == [1, 2, 0], 'ENTER cycles values -> ms -> off %s' % seq)
    print(ui_gfx.render(shots, out))
    if bad: sys.exit(1)


if __name__ == '__main__':
    main(*sys.argv[1:3])
