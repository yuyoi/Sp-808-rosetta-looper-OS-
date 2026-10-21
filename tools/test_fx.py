"""MFX effects (v1.97) through the firmware in the H8S emulator: the SLOT tabs set TYPE / params, the firmware writes
the coefficients (compared with mfxdsp.coefs, the model) and delay-RAM groups, and the harness's DSP1 model plays a
test signal through each slot. usage: python -I tools/test_fx.py work/build_v10/sp808_v10.bin out.png"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, ui_gfx, mfxdsp as M
bm = test_v10.bm
INS = {0: (0x71, 0x75), 1: (0xD1, 0xD3), 2: (0xD5, 0xD7)}       # what DSP0 sends, as DSP1 reads it
OUTS = {0: (0x73, 0x77), 1: (0x65, 0x6D), 2: (0x67, 0x6F)}       # what DSP1 returns, as DSP0 reads it
A = 0x200000


def main(image_path, out):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    e.stubs[bm.FX_LOC_APPLY] = lambda e: None
    e.stubs[bm.FX_LOAD_PATCH] = lambda e: None
    e.wb(0x426D98, 2); e.wb(bm.MIXER_LOC_IDX, 14); e.wb(bm.MIXER_LOC_FLAGS, 0); e.ww(bm.FX_PATCH_BUF, 7)
    for v_, val_ in ((bm.KSTEP, 1), (bm.KTHRU, 1), (bm.KMXS, 16), (bm.KSUS, 16), (bm.MSLOT, 12), (bm.MLVL, 64),
                     (bm.MLVL + 1, 64), (bm.MLVL + 2, 64)): e.wb(v_, val_)
    for i in range(6): e.wb(bm.MCLAST + i, 0xFF)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    for _ in range([t for t, _ in bm.TILES].index('mfx')): sim.key(bm.K_RIGHT)
    sim.key(bm.K_ENTER); sim.run(10); sim.key(bm.K_RIGHT); sim.run(30)          # MFX page, ENGINE ON
    print('ENGINE ON  loaded', e.rb(bm.MLOADED))
    core = sim.core
    def types(): return [e.rb(bm.MTYPE + k) for k in range(3)]
    def params(k): return [e.rb(bm.MP + 3 * k + j) for j in range(3)]
    def check(k):                                              # the slot's words vs the model
        typ, (p1, p2, p3) = types()[k], params(k)
        by = e.rb(bm.MBYP) >> k & 1
        want = M.coefs(k, 0 if by else typ, p1, p2, p3, 64 if by else e.rb(bm.MLVL + k), M.regions(types())[k])
        bad = []
        for n, (c, sh) in want.items():
            w = bm.MFX_PARAMS[n][1]
            if (sim.prog[w] & 0xFF) != c or (sh is not None and ((sim.prog[w] >> 8) & 3) != sh):
                bad.append((n, sim.prog[w] & 0xFF, c))
        return 'OK' if not bad else bad[:4]
    def ew(k): return (sim.prog[bm.MFX_PARAMS['m%d_ew' % k][1]] >> 23) & 0x1F
    def play(k, sig, n, skip=0):                              # sig(i) -> (l, r) into slot k only
        res = []
        for i in range(n):
            l, r = sig(i)
            for s in range(3):
                core.wg(INS[s][0], int(l) if s == k else 0); core.wg(INS[s][1], int(r) if s == k else 0)
            core.run_sample(); sim.eram.tick_sample()
            if i >= skip: res.append((core.rg(OUTS[k][0]), core.rg(OUTS[k][1])))
        return res
    def pk(res, ch=0): return round(max(abs(o[ch]) for o in res) / A, 3)
    sine = lambda f: (lambda i: (A * math.sin(2 * math.pi * f * i / 44100),) * 2)
    def tab(t):                                               # open the MFX tab t through the submode menu
        sim.key(bm.K_ENTER)
        for _ in range(5): sim.key(bm.K_UP)
        for _ in range(t): sim.key(bm.K_DOWN)
        sim.key(bm.K_ENTER); sim.run(5)
    # ---- SLOT 1 = FILTER ----
    tab(1); sim.key(bm.K_RIGHT); sim.run(10)
    print('SLOT 1     type', M.TYPES[types()[0]], 'params', params(0), '(defaults LP 64 30) words', check(0))
    print('           200 Hz %.3f  4 kHz %.3f (low-pass at %d Hz)' % (pk(play(0, sine(200), 3000, 1500)),
                                                                     pk(play(0, sine(4000), 3000, 1500)), M.cutoff_hz(64)))
    shots.append(('SLOT 1: FILTER', sim.shot()))
    sim.key(bm.K_DOWN); sim.key(bm.K_RIGHT); sim.key(bm.K_RIGHT); sim.run(10)    # MODE -> HP
    print('MODE HP    params', params(0), 'words', check(0), '200 Hz %.3f 4 kHz %.3f' % (
        pk(play(0, sine(200), 3000, 1500)), pk(play(0, sine(4000), 3000, 1500))))
    sim.key(bm.K_RIGHT); sim.run(5); print('MODE past HP stays', params(0)[0], '(clamped to 2)')
    n0 = len([x for x in sim.dsp_log if x[1] == 'coef'])
    sim.key(bm.K_DOWN); sim.key(bm.K_RIGHT); sim.run(10)                            # CUTOFF + 1
    print('CUTOFF +1  params', params(0), 'words', check(0), 'coef writes', len([x for x in sim.dsp_log if x[1] == 'coef']) - n0,
          '(only the f words that changed)')
    shots.append(('SLOT 1: HP, cutoff 65', sim.shot()))
    # ---- SLOT 3 = DRIVE, then DELAY ----
    tab(3); sim.key(bm.K_RIGHT); sim.key(bm.K_RIGHT); sim.run(10)
    print('SLOT 3     type', M.TYPES[types()[2]], 'params', params(2), 'words', check(2))
    res = play(2, sine(220), 2000, 1000)
    print('           220 Hz sine through DRIVE: peak %.2f, clipped share %.2f' % (
        pk(res), sum(1 for o in res if abs(o[0]) > 0.95 * max(abs(p[0]) for p in res)) / len(res)))
    shots.append(('SLOT 3: DRIVE', sim.shot()))
    sim.key(bm.K_RIGHT); sim.run(10)
    reg = M.regions(types())
    print('SLOT 3     type', M.TYPES[types()[2]], 'params', params(2), 'words', check(2), 'mask', e.rb(bm.MREGM),
          'region', reg[2], 'WRITE group mode %02X' % ew(2))
    d = min(M.TAB_DTIME[params(2)[0]], reg[2][1] - reg[2][0] - 2)
    play(2, lambda i: (0, 0), d + 2000)                       # flush: the line kept recording in DRIVE
    res = play(2, lambda i: (A, A) if i == 0 else (0, 0), d + 400)
    hits = [(i, round(o[0] / A, 2)) for i, o in enumerate(res) if abs(o[0]) > A * 0.2 and i > 0]
    print('           impulse: echo near D', [h for h in hits if abs(h[0] - d) < 40][:2], '(D = %d samples = %.0f ms; '
          'older line content still recirculating: %d hits)' % (d, M.delay_ms(params(2)[0]), len(hits)))
    shots.append(('SLOT 3: DELAY', sim.shot()))
    # ---- SLOT 2 = DELAY too: the delay RAM is split ----
    tab(2); [sim.key(bm.K_RIGHT) for _ in range(3)]; sim.run(10)
    reg = M.regions(types())
    print('SLOT 2     DELAY too: mask', e.rb(bm.MREGM), 'regions', reg[1], reg[2], 'words', check(1), check(2))
    from keysdsp import host_image_eram
    ews = [x for x in sim.dsp_log if x[1] == 'eram' and x[2] in (bm.MFX_PARAMS['m1_ew'][1], bm.MFX_PARAMS['m2_ew'][1])][-2:]
    print('           WRITE bases now', [(x[2], x[4]) for x in ews], '(slot 2 base %d, slot 3 base %d)' % (reg[1][0], reg[2][0]))
    d1 = min(M.TAB_DTIME[params(1)[0]], reg[1][1] - reg[1][0] - 2)
    play(1, lambda i: (0, 0), d1 + 2000)
    res = play(1, lambda i: (A, A) if i == 0 else (0, 0), d1 + 400)
    print('           slot 2 echo at', [i for i, o in enumerate(res) if abs(o[0]) > A * 0.2 and i > 0][:2], '(%d)' % d1)
    # ---- SLOT 1 = MOD (tremolo) ----
    tab(1); sim.key(bm.K_UP); sim.key(bm.K_UP); sim.key(bm.K_UP)
    [sim.key(bm.K_RIGHT) for _ in range(3)]; sim.run(10)
    print('SLOT 1     type', M.TYPES[types()[0]], 'params', params(0), 'words', check(0))
    res = play(0, lambda i: (A, A), int(44100 / M.lfo_hz(params(0)[1], False)) + 3000, 3000)
    print('           TREMOLO %.2f Hz: gain %.2f .. %.2f' % (M.lfo_hz(params(0)[1], False), min(o[0] for o in res) / A,
                                                            max(o[0] for o in res) / A))
    shots.append(('SLOT 1: MOD', sim.shot()))
    # ---- bypass (pads / LOC later): slot 1 transparent at x1 ----
    e.wb(bm.MBYP, 1); sim.call('mfx_levels'); print('BYPASS 1   words', check(0), 'gain', pk(play(0, lambda i: (A, A), 2000, 1500)))
    e.wb(bm.MBYP, 0); sim.call('mfx_levels')
    # ---- CONTROLS: KNOB A -> SLOT 1 P2 (RATE), KNOB B -> SLOT 1 P1 (MODE, 0..2) ----
    tab(4)
    for _ in range(5): sim.key(bm.K_RIGHT)                    # KNOB A -> target 5 = SLOT 1 P2
    sim.key(bm.K_DOWN); [sim.key(bm.K_RIGHT) for _ in range(4)]   # KNOB B -> target 4 = SLOT 1 P1
    e.wb(bm.ADC_TAB + 6, 200); e.wb(bm.ADC_TAB + 7, 255); sim.run(40)
    print('KNOBS      targets', bm.MF_TGTS[e.rb(bm.MCTRL)], '/', bm.MF_TGTS[e.rb(bm.MCTRL + 1)], '-> params', params(0),
          '(expect P2 100, P1 5 = PHASER: MODE has 6 entries since v1.99) words', check(0))
    shots.append(('CONTROLS', sim.shot()))
    # ---- KEYS takes DSP1: our groups cleared; back: everything again ----
    sim.key(bm.K_EXIT); sim.run(5)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('keys')); sim.key(bm.K_ENTER); sim.run(30)
    left = [k for k in range(3) if ew(k)]
    print('KEYS       MLOADED', e.rb(bm.MLOADED), 'MFX WRITE groups still set:', left, '(expect [])')
    sim.key(bm.K_EXIT); sim.run(30)
    print('KEYS exit  MLOADED', e.rb(bm.MLOADED), 'words', check(0), check(1), check(2), 'WRITE groups', [ew(k) for k in range(3)])
    print('odd word/long accesses:', ['pc %06X @%06X' % x for x in sorted(e.odd)] or 'none')
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:])
