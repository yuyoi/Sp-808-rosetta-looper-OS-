"""DDS-DSP LFO (v1.92) in the H8S emulator: vibrato (oscillator + sample pitch fields), tremolo (level targets),
filter (cutoff), delay fade-in, waves, back to rest at depth 0.

usage: python -I tools/test_lfo.py work/build_v10/sp808_v10.bin out.png
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, keysdsp, ui_gfx
bm = test_v10.bm


def main(image_path, out):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    W = lambda n: (bm.dsp_addr(n) & 0xFFC) >> 2
    cf = lambda n: sim.prog[W(n)] & 0xFF
    for v_, val_ in ((bm.KTHRU, 1), (bm.KMXS, 16), (bm.KSUS, 16), (bm.KLAF, 6), (bm.KFDEC, 6), (bm.KSTEP, 1), (bm.KPW, 8),
                     (bm.KDET, 2), (bm.KOCT, 2), (bm.TREMF, 64), (bm.KLFR, 6)): e.wb(v_, val_)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    sim.key(bm.K_SYSTEM); sim.run(30); sim.pad(2); sim.pad(2, False); sim.run(900)
    sim.key(bm.K_EXIT); sim.run(10)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('dds')); sim.key(bm.K_ENTER); sim.run(20)
    e.wb(bm.KMXSAW, 16); sim.call('dds_ap1')                    # saw on, sample on
    def voice(): return next(v for v in range(bm.NV) if e.rb(bm.VSTATE + v))
    def osc_hz(v): return keysdsp.osc_freq(cf('v%d_o2a' % v), cf('v%d_o1a' % v), cf('v%d_o0a' % v))
    def smp_ratio(v):
        d = [cf('v%d_%s' % (v, t)) for t in ('d2', 'd1', 'd0')]
        return (d[0] * 32768 + d[1] * 512 + d[2] * 8) / 65536 / 256 * 256   # relative units
    # ---- vibrato: TRIANGLE 2 Hz, PITCH 16 (a semitone) ----
    e.wb(bm.KLFW, 0); e.wb(bm.KLFP, 16)
    sim.pad(7); sim.run(20); v = voice(); base_s = None
    hz, rs = [], []
    for _ in range(24):
        sim.run(25); hz.append(round(osc_hz(v), 1)); rs.append(smp_ratio(v))
    print('vibrato    osc Hz every 25 ms:', hz)
    print('           min %.1f max %.1f (C4 261.6 +- 1 semitone: 246.9 .. 277.2)' % (min(hz), max(hz)))
    print('           sample pitch spread %.3f (expect about 2^(2/12) = 1.12)' % (max(rs) / min(rs)))
    sim.pad(7, False); sim.run(300)
    # ---- depth 0: back to rest ----
    e.wb(bm.KLFP, 0); sim.pad(7); sim.run(60); v = voice()
    print('PITCH 0    LFO_OFF %d osc %.1f Hz (expect 0, 261.6)' % (e.rb(bm.LFO_OFF), osc_hz(v)))
    sim.pad(7, False); sim.run(300)
    # ---- tremolo: LEVEL 16, SQUARE 4 Hz ----
    e.wb(bm.KLFL, 16); e.wb(bm.KLFW, 1); e.wb(bm.KLFR, 8)
    sim.pad(7); sim.run(30); v = voice(); ts = []
    for _ in range(16): sim.run(25); ts.append(cf('v%d_t' % v))
    print('tremolo    level target every 25 ms (square 4 Hz):', ts, 'TREMF', e.rb(bm.TREMF))
    sim.pad(7, False); sim.run(300); e.wb(bm.KLFL, 0); sim.run(40)
    print('LEVEL 0    TREMF %d (expect 64)' % e.rb(bm.TREMF))
    # ---- filter: knob A 60, FILTER 16, SAW 2 Hz ----
    sim.knobs[6] = 60; sim.run(40)
    e.wb(bm.KLFF, 16); e.wb(bm.KLFW, 2); e.wb(bm.KLFR, 6)
    sim.pad(7); fs = []
    for _ in range(20): sim.run(25); fs.append((e.rb(bm.FLFO) if e.rb(bm.FLFO) < 128 else e.rb(bm.FLFO) - 256, cf('flt_f1')))
    print('filter     (FLFO, f1) every 25 ms (saw 2 Hz):', fs)
    sim.pad(7, False); sim.run(300); e.wb(bm.KLFF, 0); sim.knobs[6] = 127; sim.run(40)
    # ---- delay: 500 ms fade-in ----
    e.wb(bm.KLFP, 16); e.wb(bm.KLFW, 1); e.wb(bm.KLFD, 7); e.wb(bm.KLFR, 10)
    sim.pad(7); vs = []
    for _ in range(14): sim.run(50); vs.append(e.rb(bm.LFO_V) if e.rb(bm.LFO_V) < 128 else e.rb(bm.LFO_V) - 256)
    print('delay 500  LFO value every 50 ms (square, grows to +-64):', vs)
    sim.pad(7, False); sim.run(300)
    for v_ in (bm.KLFP, bm.KLFD): e.wb(v_, 0)
    sim.run(40)
    # ---- the LFO tab ----
    for _ in range(3): sim.key(bm.K_ENTER) if False else None
    sim.key(bm.K_ENTER); [sim.key(bm.K_DOWN) for _ in range(3)]; sim.run(5); shots.append(('DDS menu: 4 tabs', sim.shot()))
    sim.key(bm.K_ENTER); sim.run(5)
    e.wb(bm.KLFP, 8); e.wb(bm.KLFD, 5); e.wb(bm.KLFF, 4)
    sim.run(5); sim.key(bm.K_RIGHT); sim.run(5); shots.append(('LFO tab', sim.shot()))
    for _ in range(3): sim.key(bm.K_DOWN)
    sim.run(5); shots.append(('LFO tab scrolled', sim.shot()))
    print('LFO tab    tab %d wave %d rate %d' % (e.rb(bm.KDTAB), e.rb(bm.KLFW), e.rb(bm.KLFR)))
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:])
