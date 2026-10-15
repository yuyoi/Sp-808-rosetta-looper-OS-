"""v1.98 in the H8S emulator: SYNTH ONLY (SAMPLE 0 = the KEYS page plays at once, no source pad; raising SAMPLE then
asks for a pad; SAMPLE above 0 keeps the pick-first flow) and the MPC / MFX cursors on their own bytes.
usage: python -I tools/test_synth.py work/build_v10/sp808_v10.bin out.png"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, ui_gfx, keysdsp
bm = test_v10.bm


def main(image_path, out):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    W = lambda n: (bm.dsp_addr(n) & 0xFFC) >> 2
    cf = lambda n: sim.prog[W(n)] & 0xFF
    for v_, val_ in ((bm.KTHRU, 1), (bm.KMXS, 0), (bm.KMXSAW, 16), (bm.KSUS, 16), (bm.KLAF, 6), (bm.KFDEC, 6), (bm.KSTEP, 1),
                     (bm.KPW, 8), (bm.KDET, 2), (bm.KOCT, 2), (bm.TREMF, 64), (bm.KLFR, 6), (bm.ACUR, 0xFF), (bm.MV, 0xFF),
                     (bm.KUS, 8), (bm.KNOSMP, 0)): e.wb(v_, val_)
    live = lambda: [v for v in range(bm.NV) if e.rb(bm.VSTATE + v) in (1, 2, 4, 5, 6, 7)]
    hz = lambda v: round(keysdsp.osc_freq(cf('v%d_o2a' % v), cf('v%d_o1a' % v), cf('v%d_o0a' % v)), 1)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    sim.key(bm.K_SYSTEM); sim.run(30)
    print('SAMPLE 0   enter KEYS: state', sim.kstate(), 'KNOSMP', e.rb(bm.KNOSMP), '(expect PLAY 1, no pad hit)')
    shots.append(('KEYS: SYNTH ONLY', sim.shot()))
    sim.pad_playing = None                                      # the harness's endless boot-sound tone off
    sim.out = []; sim.pad(7); sim.run(300)
    vs = live(); f, pk = test_v10.freq(sim.out)
    print('pad 8      voices', vs, 'osc', [hz(v) for v in vs], 'sample level', [cf('v%d_mxs' % v) for v in vs],
          'out f = %.1f Hz peak %.3f' % (f, pk), '(expect 1 voice, 261.6 Hz, level 0, sound)')
    sim.run(1500); print('held 1.8 s still sounding:', live(), '(synth only: held = sounding)')
    sim.pad(7, False); sim.run(800); print('released  ', live())
    e.wb(bm.KMXS, 8); sim.call('dds_ap0')
    print('SAMPLE 8   state', sim.kstate(), 'KNOSMP', e.rb(bm.KNOSMP), '(expect IDLE 0: the next pad picks the source)')
    sim.pad(2); sim.run(5); print('pad 3      state', sim.kstate(), 'KSRC', e.rb(bm.KSRC), '(expect WAIT/REC.., source 2)')
    sim.pad(2, False); sim.run(1200); print('           after the take:', sim.kstate(), 'KNOSMP', e.rb(bm.KNOSMP))
    shots.append(('KEYS: PLAY SRC 03', sim.shot()))
    e.wb(bm.KMXS, 0); sim.call('dds_ap0')
    print('SAMPLE 0   with a source: state', sim.kstate(), 'KNOSMP', e.rb(bm.KNOSMP), '(expect PLAY 0, the source kept)')
    sim.key(bm.K_EXIT); sim.run(10); e.wb(bm.KMXS, 16)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('keys')); sim.key(bm.K_ENTER); sim.run(30)
    print('SAMPLE 16  re-enter: state', sim.kstate(), '(expect PLAY: the source stays loaded)')
    # cursors
    print('cursors    MPC MCUR %06X, MFX MFCUR %06X: %s' % (bm.MCUR, bm.MFCUR, 'separate' if bm.MCUR != bm.MFCUR else 'SHARED'))
    print('odd word/long accesses:', ['pc %06X @%06X' % x for x in sorted(e.odd)] or 'none')
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:])
