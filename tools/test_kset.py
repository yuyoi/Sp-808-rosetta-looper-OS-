"""S-EDIT on the Mac engine (v1.91): the old key sequences still work (ENTER toggles THRU / REVERSE / LOOP), the
knob rows are read-only.  usage: python -I tools/test_kset.py work/build_v10/sp808_v10.bin out.png"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, ui_gfx
bm = test_v10.bm


def main(image_path, out):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    W = lambda n: (bm.dsp_addr(n) & 0xFFC) >> 2
    for v_, val_ in ((bm.KTHRU, 1), (bm.KMXS, 16), (bm.KSUS, 16), (bm.KLAF, 6), (bm.KFDEC, 6), (bm.KSTEP, 1), (bm.KREL, 7)): e.wb(v_, val_)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    sim.key(bm.K_SYSTEM); sim.run(30); sim.pad(2); sim.pad(2, False); sim.run(900)
    sim.key(bm.K_EXIT); sim.run(10)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('edit')); sim.key(bm.K_ENTER); sim.run(20)
    print('S-EDIT     page', e.rb(bm.PAGE), '(expect %d) active' % bm.P_KSET, e.rb(bm.KACTIVE), sim.kstate())
    shots.append(('S-EDIT', sim.shot()))
    sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(20)
    print('THRU       KTHRU %d coef %d (expect 0 0)' % (e.rb(bm.KTHRU), sim.prog[W('thru_l')] & 0xFF))
    sim.key(bm.K_ENTER); sim.run(20)
    print('THRU       KTHRU %d coef %d (expect 1 64)' % (e.rb(bm.KTHRU), sim.prog[W('thru_l')] & 0xFF))
    sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(20)
    print('REVERSE    KREV %d v0_dir %d (expect 1 192)' % (e.rb(bm.KREV), sim.prog[W('v0_dir')] & 0xFF))
    shots.append(('S-EDIT reverse on', sim.shot()))
    sim.key(bm.K_ENTER); sim.run(20); print('REVERSE    KREV %d (expect 0)' % e.rb(bm.KREV))
    sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(20); print('LOOP       KLOOP %d (expect 1)' % e.rb(bm.KLOOP))
    sim.key(bm.K_ENTER); sim.run(20); print('LOOP       KLOOP %d (expect 0)' % e.rb(bm.KLOOP))
    sim.key(bm.K_UP); sim.key(bm.K_UP); sim.key(bm.K_UP)
    for _ in range(3): sim.key(bm.K_RIGHT)
    print('RELEASE    KREL %d (expect 10)' % e.rb(bm.KREL))
    sim.knobs[6] = 60; sim.knobs[7] = 90; sim.knobs[8] = 40; sim.run(60)
    for _ in range(4): sim.key(bm.K_DOWN)
    k0 = e.rb(bm.KNOB); sim.key(bm.K_RIGHT); sim.key(bm.K_LEFT); sim.key(bm.K_LEFT)
    print('CUTOFF row KNOB %d -> %d after RIGHT/LEFT x2 (read-only: unchanged)' % (k0, e.rb(bm.KNOB)))
    sim.run(5); shots.append(('S-EDIT knob rows', sim.shot()))
    for _ in range(3): sim.key(bm.K_DOWN)
    sim.run(5); shots.append(('S-EDIT bottom', sim.shot()))
    sim.key(bm.K_EXIT); sim.run(10); print('EXIT       page %d CUR %d active %d' % (e.rb(bm.PAGE), e.rb(bm.CUR), e.rb(bm.KACTIVE)))
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:])
