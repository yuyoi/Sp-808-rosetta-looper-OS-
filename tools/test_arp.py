"""Arpeggiator (v1.93) in the H8S emulator: held pads -> one note per 1/16 step in UP / DOWN / UP+DOWN / RANDOM,
OCTAVES, GATE, releases, mode switching.  usage: python -I tools/test_arp.py work/build_v10/sp808_v10.bin out.png"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, ui_gfx
bm = test_v10.bm


def main(image_path, out):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    for v_, val_ in ((bm.KTHRU, 1), (bm.KMXS, 0), (bm.KSUS, 16), (bm.KLAF, 6), (bm.KFDEC, 6), (bm.KSTEP, 1), (bm.KPW, 8),
                     (bm.KDET, 2), (bm.KOCT, 2), (bm.TREMF, 64), (bm.KLFR, 6), (bm.KARR, 6), (bm.KARG, 1), (bm.KARO, 1),
                     (bm.ACUR, 0xFF)): e.wb(v_, val_)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    sim.key(bm.K_SYSTEM); sim.run(30); sim.pad(2); sim.pad(2, False); sim.run(900)
    sim.key(bm.K_EXIT); sim.run(10)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('dds')); sim.key(bm.K_ENTER); sim.run(20)
    e.wb(bm.KMXSAW, 16); sim.call('dds_ap1'); e.wb(bm.KMXS, 0); sim.call('dds_ap0')   # synth only (no one-shot end)
    def sounding(): return sorted({e.rb(bm.VKEY + v) for v in range(bm.NV) if e.rb(bm.VSTATE + v) in (1, 2, 4, 5, 6, 7)})
    def trace(ms, every=25):
        out_ = []
        for _ in range(ms // every):
            sim.run(every); k = sounding(); out_.append('-' if not k else '/'.join(str(x - bm.KEY_LO) for x in k))
        return ' '.join(out_)
    def mode(m): e.wb(bm.KARP, m); sim.call('arp_mode')
    mode(1)
    print('ARP UP     held list', [e.rb(bm.AHELD + i) for i in range(e.rb(bm.AN))])
    for p in (7, 11, 14): sim.pad(p)                         # keys 0, +4, +7 (C E G)
    print('held       list', [e.rb(bm.AHELD + i) - bm.KEY_LO for i in range(e.rb(bm.AN))], '(expect 0 4 7)')
    print('UP 120 BPM gate 50 %%, note per 25 ms (125 ms steps): %s' % trace(1000))
    mode(2); [sim.pad(p) for p in (7, 11, 14)]
    print('DOWN       %s' % trace(800))
    mode(3); [sim.pad(p) for p in (7, 11, 14)]
    print('UP+DOWN    %s' % trace(1300))
    e.wb(bm.KARO, 2); mode(1); [sim.pad(p) for p in (7, 11, 14)]
    print('UP 2 OCT   %s' % trace(1600))
    e.wb(bm.KARO, 1); e.wb(bm.KARG, 3); mode(4); [sim.pad(p) for p in (7, 11, 14)]
    print('RANDOM 100%% gate (legato) %s' % trace(1000))
    sim.pad(11, False); sim.run(10); print('E released list', [e.rb(bm.AHELD + i) - bm.KEY_LO for i in range(e.rb(bm.AN))], '(expect 0 7)')
    print('           %s' % trace(500))
    sim.pad(7, False); sim.pad(14, False); sim.run(60)
    print('all up     AN %d ACUR %02X sounding %s (expect 0 FF, releasing or none)' % (e.rb(bm.AN), e.rb(bm.ACUR), sounding()))
    sim.run(500)
    mode(0); sim.pad(7); sim.pad(14); sim.run(60)
    print('ARP OFF    two pads held -> sounding', sounding(), '(expect both: [24, 31])')
    sim.pad(7, False); sim.pad(14, False); sim.run(300)
    sim.key(bm.K_ENTER); [sim.key(bm.K_DOWN) for _ in range(4)]; sim.key(bm.K_ENTER); sim.run(5)
    sim.key(bm.K_RIGHT); sim.run(5); shots.append(('ARP tab: MODE UP', sim.shot()))
    print('ARP tab    tab %d mode %d' % (e.rb(bm.KDTAB), e.rb(bm.KARP)))
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:])
