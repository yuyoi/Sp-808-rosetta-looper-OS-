"""KEYS: the held keys on the pad LEDs (v1.91), the stock's pad LEDs back on exit.

usage: python -I tools/test_padled.py work/build_v10/sp808_v10.bin
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10
bm = test_v10.bm


def main(image_path):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e = sim.e
    for v_, val_ in ((bm.KTHRU, 1), (bm.KMXS, 16), (bm.KSUS, 16), (bm.KLAF, 6), (bm.KFDEC, 6), (bm.KSTEP, 1)): e.wb(v_, val_)
    row = bm.LED_ROWS + 2
    def pads_lit(): return [p + 1 for p in range(16) if e.rw(row) & e.rw(bm.LED_MASKS + 2 * p)]
    for p in (2, 5): e.ww(row, e.rw(row) | e.rw(bm.LED_MASKS + 2 * p))   # the stock had pads 3 and 6 lit
    stock = e.rw(row)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    sim.key(bm.K_SYSTEM); sim.run(30)
    print('KEYS on      pads lit', pads_lit(), '(expect none)')
    sim.pad(2); sim.pad(2, False); sim.run(900)
    print('sampled      state', sim.kstate())
    sim.pad(7); sim.pad(14); sim.run(30)
    print('pads 8 + 15  held -> lit', pads_lit(), '(expect [8, 15])')
    sim.pad(7, False); sim.run(400)
    print('8 released   lit', pads_lit(), '(15 too: its one-shot voice ended with the sample after ~430 ms)')
    sim.pad(14, False); sim.run(400)
    print('all released lit', pads_lit(), '(expect none)')
    sim.pad(0); sim.run(30); print('pad 1 held   lit', pads_lit())
    sim.key(bm.K_EXIT); sim.run(30)
    print('EXIT         lit', pads_lit(), '(expect the stock\'s [3, 6]) row back:', e.rw(row) == stock)
    print('LED calls', len(sim.leds))


if __name__ == '__main__':
    main(*sys.argv[1:])
