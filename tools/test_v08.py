"""Run v0.8's record / take-done screens and the 7-segment ticker in the H8S emulator.

usage: python -I test_v08.py build_v08/sp808_v08.bin out.png
Fakes a take: waiting for the signal, then a decaying level over 7 s (and a 2 min take for the history merge),
renders what gfx_flush wrote into the LCD RAM and decodes the 7-segment digits written through the APIs.
"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h8emu, ui_gfx, gfxlib
import build_v08 as bm

LCD_RAM, DOTS = 0x40187A, 0x4018AA


def make(image, labels):
    emu = h8emu.Emu(image)
    emu.wl(gfxlib.LCD_FBPTR, DOTS)
    emu.seg = {}
    emu.segpos = 0
    def seg_pos(e): e.segpos = e.g8(8)
    def seg_put(e):
        e.seg[e.segpos] = e.g32(0); e.segpos += 1
    emu.stubs[bm.SEG_POS] = seg_pos
    emu.stubs[bm.SEG_PUT] = seg_put
    emu.stubs[bm.MEM_CHECK] = lambda e: e.s16(0, 1)
    emu.stubs[bm.STOCK_SCR22] = lambda e: (_ for _ in ()).throw(RuntimeError('stock 0x22 event %d' % e.g16(0)))
    emu.ww(bm.FREE_BLK, 3000); emu.ww(bm.RSV_BLK, 0)
    emu.wb(bm.REC_PAD, 4); emu.wb(bm.SMP_PAD, 4)
    emu.wb(bm.HIST_DIV, 1)
    emu.labels = labels
    return emu


def screen(emu):
    c = ui_gfx.Canvas()
    for y in range(32):
        px = gfxlib.unpack6(bytes(emu.rb(DOTS + 24 * y + i) for i in range(24)))
        for x in range(128): c.px[y][x] = px[x + gfxlib.LCD_X0]
    return c


def segline(emu):
    return ''.join(bm.seg_decode(emu.seg.get(i, 0)) for i in range(bm.SEG_DIGITS))


def run(emu, lbl):
    emu.steps = 0
    emu.call(emu.labels[lbl])
    emu.maxsteps = max(getattr(emu, 'maxsteps', 0), emu.steps)


def take(emu, secs, level_fn, wait_ms=600, step=20):
    """rec_init, wait for the signal, then record `secs` seconds; returns ms ticks"""
    t = 1_000_000
    emu.wl(bm.TICK_MS, t)
    emu.wb(bm.SIG_WAIT_LO, 0x05); emu.wb(bm.SIG_STAT, 1)
    run(emu, 'rec_init')
    shots = {}
    while t < 1_000_000 + wait_ms + secs * 1000:
        t += step; emu.wl(bm.TICK_MS, t)
        if t >= 1_000_000 + wait_ms: emu.wb(bm.SIG_STAT, 0)
        rec_t = (t - 1_000_000 - wait_ms) / 1000.0
        lv = level_fn(rec_t) if rec_t >= 0 else 3
        emu.wb(bm.LVL_L, lv); emu.wb(bm.LVL_R, max(0, lv - 9))
        run(emu, 'rec_idle')
        if 'wait' not in shots and t >= 1_000_000 + 300: shots['wait'] = screen(emu)
    return shots


def main(image_path, out):
    image = open(image_path, 'rb').read()
    blob, labels = bm.build()
    screens = []

    def env(t):                                         # hits every ~0.8 s, decaying
        k = t % 0.8
        return int(min(127, 120 * math.exp(-k * 5) * (0.6 + 0.4 * math.sin(t * 1.3) ** 2) + 2))
    emu = make(image, labels)
    shots = take(emu, 7.3, env)
    print('wait  7-seg: [%s]' % segline(emu))
    screens.append(('WAITING (pad 05)', shots['wait']))
    screens.append(('RECORDING 7.3 s', screen(emu)))
    print('rec   REC_MS %d  HIST_N %d DIV %d  meter %d peak %d' % (emu.rl(bm.REC_MS), emu.rb(bm.HIST_N),
          emu.rb(bm.HIST_DIV), emu.rb(bm.METER_N), emu.rb(bm.PEAK)))
    print('      max steps per rec_idle (a frame) %d' % emu.maxsteps)
    run(emu, 'done_draw'); screens.append(('TAKE DONE 7.3 s', screen(emu)))
    print('      done_draw steps %d' % emu.steps)

    emu2 = make(image, labels)
    emu2.ww(bm.FREE_BLK, 900); emu2.wb(bm.MONO_FLAG, 2)
    take(emu2, 125, lambda t: int(60 + 60 * math.sin(t / 9.0) ** 2) if t < 100 else 4, step=50)
    print('long  REC_MS %d  HIST_N %d DIV %d' % (emu2.rl(bm.REC_MS), emu2.rb(bm.HIST_N), emu2.rb(bm.HIST_DIV)))
    screens.append(('RECORDING 2:05, mono, 900 blocks', screen(emu2)))
    run(emu2, 'done_draw'); screens.append(('TAKE DONE 2:05', screen(emu2)))

    for name, page in (('HOME', bm.P_HOME), ('MPC', bm.P_MPC), ('LOOP (coming soon)', bm.P_LOOP)):
        e = make(image, labels)
        e.stubs[bm.PAD_USED] = lambda e: e.s16(0, int(e.g16(0) in (0, 1, 2, 4, 8, 12)))
        for v, x in ((bm.PAGE, page), (bm.SMODE, bm.SM_CLASSIC), (bm.SELPAD, 4), (bm.CUR, 1)): e.wb(v, x)
        run(e, 'draw'); screens.append((name, screen(e)))
    for pg in range(3):                                  # 7-seg pages
        e = make(image, labels)
        e.wb(bm.SEG_PG, pg); e.wl(bm.TICK_MS, 100); e.wl(bm.SEG_T, 0)
        run(e, 'seg_tick')
        print('page %d 7-seg: [%s] steps %d' % (pg, segline(e), e.steps))
    print(ui_gfx.render(screens, out))


if __name__ == '__main__':
    main(*sys.argv[1:3])
