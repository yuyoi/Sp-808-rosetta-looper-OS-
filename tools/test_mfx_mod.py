"""MFX v1.98 CHORUS / FLANGER / PHASER through the firmware in the H8S emulator: TYPE rows set the new types, the
firmware's words are compared with mfxdsp.coefs (the model), the delay-RAM split (MREGM, WRITE bases, the R READvar
groups) is checked, and the harness's DSP1 model plays signals through each slot.
usage: python -I tools/test_mfx_mod.py work/build_v10/sp808_v10.bin out.png"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, ui_gfx, mfxdsp as M
bm = test_v10.bm
INS = {0: (0x71, 0x75), 1: (0xD1, 0xD3), 2: (0xD5, 0xD7)}
OUTS = {0: (0x73, 0x77), 1: (0x65, 0x6D), 2: (0x67, 0x6F)}
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
    fails = []
    def types(): return [e.rb(bm.MTYPE + k) for k in range(3)]
    def params(k): return [e.rb(bm.MP + 3 * k + j) for j in range(3)]
    def check(k):
        typ, (p1, p2, p3) = types()[k], params(k)
        want = M.coefs(k, typ, p1, p2, p3, e.rb(bm.MLVL + k), M.regions(types())[k])
        bad = [(n, sim.prog[bm.MFX_PARAMS[n][1]] & 0xFF, c) for n, (c, sh) in want.items()
               if (sim.prog[bm.MFX_PARAMS[n][1]] & 0xFF) != c or
               (sh is not None and ((sim.prog[bm.MFX_PARAMS[n][1]] >> 8) & 3) != sh)]
        if bad: fails.append('words slot %d' % (k + 1))
        return 'OK' if not bad else bad[:4]
    def eram(k, n): w = sim.prog[bm.MFX_PARAMS['m%d_%s' % (k, n)][1]]; return (w >> 23) & 0x1F
    def play(k, sig, n, skip=0):
        res = []
        for i in range(n):
            l, r = sig(i)
            for s in range(3):
                core.wg(INS[s][0], int(l) if s == k else 0); core.wg(INS[s][1], int(r) if s == k else 0)
            core.run_sample(); sim.eram.tick_sample()
            if i >= skip: res.append((core.rg(OUTS[k][0]), core.rg(OUTS[k][1])))
        return res
    def taps(k, n):
        play(k, lambda i: (0, 0), 3000)
        res = play(k, lambda i: (A, A) if i == 0 else (0, 0), n)
        return [next((i for i, o in enumerate(res) if i > 2 and abs(o[ch]) > A * 0.2), None) for ch in (0, 1)]
    def tab(t):
        sim.key(bm.K_ENTER)
        for _ in range(5): sim.key(bm.K_UP)
        for _ in range(t): sim.key(bm.K_DOWN)
        sim.key(bm.K_ENTER); sim.run(5)
    def set_type(k, t):                                        # SLOT k+1 tab, TYPE row RIGHT x t (from OFF)
        tab(k + 1); [sim.key(bm.K_RIGHT) for _ in range(t)]; sim.run(10)
    def set_param(j, v):                                       # on the open SLOT tab: row 1 + j to v (LEFT / RIGHT)
        k = e.rb(bm.MAPS)
        sim.key(bm.K_UP); sim.key(bm.K_UP); sim.key(bm.K_UP); sim.key(bm.K_UP)
        for _ in range(j + 1): sim.key(bm.K_DOWN)
        cur = params(k)[j]
        for _ in range(abs(v - cur)): sim.key(bm.K_RIGHT if v > cur else bm.K_LEFT)
        sim.run(10)
    # ---- SLOT 1 = CHORUS ----
    set_type(0, M.T_CHORUS)
    reg = M.regions(types())
    print('SLOT 1     type', M.TYPES[types()[0]], 'params', params(0), '(defaults %s)' % (M.P_DEFAULT[M.T_CHORUS],),
          'words', check(0), 'mask', e.rb(bm.MREGM), 'region', reg[0])
    if e.rb(bm.MREGM) != M.regmask(types()): fails.append('mask')
    ews = [x for x in sim.dsp_log if x[1] == 'eram' and x[2] == bm.MFX_PARAMS['m0_ew'][1]]
    from keysdsp import host_image_eram
    want = reg[0][0]
    print("           WRITE base", ews[-1][4] if ews else None, "want", want,
          'R READvar groups', eram(0, 'es0'), eram(0, 'es1'), '(24 = 0x18)')
    if (eram(0, 'es0'), eram(0, 'es1')) != (0x18, 0x18): fails.append('es groups')
    if not ews or ews[-1][4] != want: fails.append('WRITE base')
    set_param(0, 0); set_param(1, 127); set_param(2, 127)                         # slowest LFO, depth 4 ms, wet only
    t = taps(0, 700)
    print('CHORUS     params', params(0), 'words', check(0), 'L / R tap', t, 'sum %d (2 x %d: mirrored around the centre)'
          % (sum(t) if None not in t else -1, M.CH_CENTER))
    if None in t or abs(sum(t) - 2 * M.CH_CENTER) > 12 or abs(t[0] - t[1]) < 100: fails.append('chorus taps')
    set_param(0, 90)
    res = play(0, lambda i: (A * math.sin(2 * math.pi * 1000 * i / 44100),) * 2, 8000, 2000)
    zc = [i for i in range(1, len(res)) if res[i - 1][1] < 0 <= res[i][1]]
    per = [b - a for a, b in zip(zc, zc[1:])]
    print('           running %.1f Hz, 1 kHz tone: R period %d .. %d samples (44.1 = still), L != R: %s' % (
        M.lfo_hz(90, False), min(per), max(per), any(o[0] != o[1] for o in res)))
    shots.append(('SLOT 1: CHORUS', sim.shot()))
    # ---- SLOT 2 = FLANGER ----
    set_type(1, M.T_FLANGER)
    reg = M.regions(types())
    print('SLOT 2     type', M.TYPES[types()[1]], 'params', params(1), 'words', check(1), check(0), 'mask', e.rb(bm.MREGM),
          'regions', reg[0], reg[1])
    set_param(0, 0); set_param(1, 127); set_param(2, 0)
    t = taps(1, 700); dd = M.FL_MIN + M.TAB_DEP[127] // 8
    print('FLANGER    params', params(1), 'words', check(1), 'L / R tap', t, 'sum %d (2 x %d)' % (sum(t) if None not in t else -1, dd))
    if None in t or abs(sum(t) - 2 * dd) > 12: fails.append('flanger taps')
    set_param(1, 40); set_param(2, 110)
    play(1, lambda i: (0, 0), 3000)
    res = play(1, lambda i: (A, A) if i == 0 else (0, 0), 1500)
    hits = [(i, round(o[0] / A, 2)) for i, o in enumerate(res) if abs(o[0]) > A * 0.08]
    print('           feedback 110: repeats', hits[:6])
    if len(hits) < 4: fails.append('flanger feedback')
    shots.append(('SLOT 2: FLANGER', sim.shot()))
    # ---- SLOT 3 = PHASER ----
    set_type(2, M.T_PHASER)
    print('SLOT 3     type', M.TYPES[types()[2]], 'params', params(2), 'words', check(2), 'mask', e.rb(bm.MREGM))
    set_param(0, 60); set_param(1, 127); set_param(2, 64)
    res = play(2, lambda i: (A * math.sin(2 * math.pi * 700 * i / 44100),) * 2, 20000, 2000)
    lv = [max(abs(o[0]) for o in res[i:i + 200]) / A for i in range(0, len(res) - 200, 200)]
    print('PHASER     params', params(2), 'words', check(2), '700 Hz level %.2f .. %.2f, L = R: %s' % (
        min(lv), max(lv), all(o[0] == o[1] for o in res)))
    if not (min(lv) < 0.3 and max(lv) > 0.8) or not all(o[0] == o[1] for o in res): fails.append('phaser')
    shots.append(('SLOT 3: PHASER', sim.shot()))
    # ---- back to DELAY on slot 3: the split follows ----
    tab(3); sim.key(bm.K_UP); sim.key(bm.K_UP); sim.key(bm.K_UP); sim.key(bm.K_UP)
    [sim.key(bm.K_LEFT) for _ in range(M.T_PHASER - M.T_DELAY)]; sim.run(10)
    reg = M.regions(types())
    print('SLOT 3     type', M.TYPES[types()[2]], 'mask', e.rb(bm.MREGM), 'regions', reg, 'words', check(0), check(1), check(2))
    d = min(M.TAB_DTIME[params(2)[0]], reg[2][1] - reg[2][0] - 2)
    play(2, lambda i: (0, 0), d + 2000)
    res = play(2, lambda i: (A, A) if i == 0 else (0, 0), d + 300)
    hl = [i for i, o in enumerate(res) if abs(o[0]) > A * 0.2 and i > 0][:1]
    hr = [i for i, o in enumerate(res) if abs(o[1]) > A * 0.2 and i > 0][:1]
    print('DELAY      echo L', hl, 'R', hr, '(D = %d)' % d)
    if not hl or hl != hr or abs(hl[0] - d) > 20: fails.append('delay')
    # ---- KEYS takes DSP1: every group cleared; back: everything again ----
    sim.key(bm.K_EXIT); sim.run(5)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('keys')); sim.key(bm.K_ENTER); sim.run(30)
    left = [(k, n) for k in range(3) for n in ('ew', 'er0', 'er1', 'es0', 'es1') if eram(k, n)]
    print('KEYS       MLOADED', e.rb(bm.MLOADED), 'MFX groups still set:', left, '(expect [])')
    if left: fails.append('groups left')
    sim.key(bm.K_EXIT); sim.run(30)
    print('KEYS exit  MLOADED', e.rb(bm.MLOADED), 'words', check(0), check(1), check(2),
          'R groups', [(eram(k, 'es0'), eram(k, 'es1')) for k in range(3)])
    print('odd word/long accesses:', ['pc %06X @%06X' % x for x in sorted(e.odd)] or 'none')
    if e.odd: fails.append('odd')
    print(ui_gfx.render(shots, out))
    print('RESULT', 'PASS' if not fails else 'FAIL %s' % fails)
    if fails: raise SystemExit(1)                              # (run_all ignores main's return value)


if __name__ == '__main__':
    main(*sys.argv[1:])
