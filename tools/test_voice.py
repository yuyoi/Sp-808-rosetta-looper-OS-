"""Voice modes (v1.94) in the H8S emulator: POLY, UNISON (4 detuned voices), MONO (legato, last note wins, GLIDE).
usage: python -I tools/test_voice.py work/build_v10/sp808_v10.bin"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, keysdsp
bm = test_v10.bm


def main(image_path):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e = sim.e
    W = lambda n: (bm.dsp_addr(n) & 0xFFC) >> 2
    cf = lambda n: sim.prog[W(n)] & 0xFF
    for v_, val_ in ((bm.KTHRU, 1), (bm.KMXS, 0), (bm.KSUS, 16), (bm.KLAF, 6), (bm.KFDEC, 6), (bm.KSTEP, 1), (bm.KPW, 8),
                     (bm.KDET, 2), (bm.KOCT, 2), (bm.TREMF, 64), (bm.KLFR, 6), (bm.KARR, 6), (bm.KARG, 1), (bm.KARO, 1),
                     (bm.ACUR, 0xFF), (bm.MV, 0xFF), (bm.KUS, 8)): e.wb(v_, val_)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    sim.key(bm.K_SYSTEM); sim.run(30); sim.pad(2); sim.pad(2, False); sim.run(900)
    sim.key(bm.K_EXIT); sim.run(10)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('dds')); sim.key(bm.K_ENTER); sim.run(20)
    e.wb(bm.KMXSAW, 16); sim.call('dds_ap1'); e.wb(bm.KMXS, 0); sim.call('dds_ap0')
    def hz(v): return round(keysdsp.osc_freq(cf('v%d_o2a' % v), cf('v%d_o1a' % v), cf('v%d_o0a' % v)), 1)
    def live(): return [v for v in range(bm.NV) if e.rb(bm.VSTATE + v) in (1, 2, 4, 5, 6, 7)]
    def mode(m): e.wb(bm.KVM, m); sim.call('vm_mode')
    # POLY
    sim.pad(7); sim.pad(11); sim.run(40)
    print('POLY       voices', [(v, e.rb(bm.VKEY + v) - bm.KEY_LO, hz(v)) for v in live()], '(C4 261.6, E4 329.6)')
    sim.pad(7, False); sim.pad(11, False); sim.run(600)
    # UNISON
    mode(2); sim.pad(7); sim.run(40)
    vs = live()
    print('UNISON 8   voices', [(v, e.rb(bm.VKEY + v) - bm.KEY_LO, e.rb(bm.VDET + v) - (256 if e.rb(bm.VDET + v) > 127 else 0), hz(v),
                                  e.rb(bm.VTGT + v)) for v in vs], '(4 voices, detune -6 -2 2 6 /16 st, half level)')
    sim.pad(7, False); sim.run(600); print('           released ->', live())
    # MONO, glide 150 ms (index 7)
    mode(1); e.wb(bm.KGL, 7)
    sim.pad(7); sim.run(40); mv = e.rb(bm.MV)
    print('MONO       C held: MV', mv, 'live', live(), hz(mv))
    sim.pad(11); trace = []
    for _ in range(8): sim.run(20); trace.append((hz(mv), e.rw(bm.GOFF) - (65536 if e.rw(bm.GOFF) > 32767 else 0)))
    print('C+E        same voice?', e.rb(bm.MV) == mv, 'live', live(), 'glide (Hz, GOFF) every 20 ms:', trace)
    sim.pad(11, False); trace = []
    for _ in range(8): sim.run(20); trace.append(hz(mv))
    print('E up       back to C (glide):', trace, 'MV', e.rb(bm.MV), 'held', [e.rb(bm.MHELD + i) - bm.KEY_LO for i in range(e.rb(bm.MHN))])
    sim.pad(7, False); sim.run(40); print('C up       MV %02X live %s (expect FF, releasing)' % (e.rb(bm.MV), live()))
    sim.run(600)
    e.wb(bm.KGL, 0); sim.pad(7); sim.run(30); sim.pad(14); sim.run(30)
    print('GLIDE OFF  C then G: %s Hz at once (expect 392.0), voices %s' % (hz(e.rb(bm.MV)), live()))
    sim.pad(14, False); sim.pad(7, False); sim.run(600)
    # MONO + ARP: one voice, arpeggiated
    e.wb(bm.KARP, 1); sim.call('arp_mode'); [sim.pad(p) for p in (7, 11, 14)]
    seen = []
    for _ in range(12): sim.run(30); seen.append((tuple(live()), e.rb(bm.MV)))
    print('MONO + ARP (voices, MV) per 30 ms:', seen)
    [sim.pad(p, False) for p in (7, 11, 14)]; sim.run(300)
    e.wb(bm.KARP, 0); sim.call('arp_mode'); mode(0)
    sim.pad(7); sim.pad(11); sim.run(40)
    print('POLY again voices', [(v, e.rb(bm.VKEY + v) - bm.KEY_LO, e.rb(bm.VDET + v), hz(v)) for v in live()])


if __name__ == '__main__':
    main(*sys.argv[1:])
