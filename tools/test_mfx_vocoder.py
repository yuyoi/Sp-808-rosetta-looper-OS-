"""MFX v2.0 VOICE (Narrator chain + vocoder, vocdsp.py) through the firmware in the H8S emulator: ENGINE = VOICE loads
the program, the firmware's coefficient bytes are compared with vocdsp.values(the UI bytes in RAM) after presets and
row edits, the harness's DSP1 model plays a modulator (L) / carrier (R) through it, slots 2/3 pass through, KEYS takes
DSP1 and the guard reloads VOICE, and ENGINE = MFX / OFF hands back.
usage: python -I tools/test_mfx_vocoder.py work/build_v10/sp808_v10.bin out.png"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, ui_gfx, vocdsp as V, mfxdsp as M
bm = test_v10.bm
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
    for v_, val_ in bm.INIT_MFX: e.wb(v_, val_)                 # the lane's power-on values (boot init isn't run here)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    for _ in range([t for t, _ in bm.TILES].index('mfx')): sim.key(bm.K_RIGHT)
    sim.key(bm.K_ENTER); sim.run(10)
    core = sim.core
    fails = []
    def ui(): return {k: e.rb(bm.VUI + i) for i, k in enumerate(V.UI_KEYS)}
    def check(label=''):
        want = V.values(ui())
        bad = [(n, sim.prog[bm.VOX_PARAMS[n][1]] & 0xFF, c & 0xFF) for n, c in want.items()
               if (sim.prog[bm.VOX_PARAMS[n][1]] & 0xFF) != (c & 0xFF)]
        if bad: fails.append('words ' + label)
        return 'OK (%d words)' % len(want) if not bad else '%d bad: %s' % (len(bad), bad[:4])
    def tab(t):
        sim.key(bm.K_ENTER)
        for _ in range(10): sim.key(bm.K_UP)
        for _ in range(t): sim.key(bm.K_DOWN)
        sim.key(bm.K_ENTER); sim.run(5)
    def top(): [sim.key(bm.K_UP) for _ in range(25)]
    def row(i, delta):                                          # on the open tab: row i, LEFT / RIGHT x |delta|
        top()
        for _ in range(i): sim.key(bm.K_DOWN)
        for _ in range(abs(delta)): sim.key(bm.K_RIGHT if delta > 0 else bm.K_LEFT)
        sim.run(10)
    def play(sig, n, skip=0, slot=0):
        INS = {0: (0x71, 0x75), 1: (0xD1, 0xD3), 2: (0xD5, 0xD7)}
        OUTS = {0: (0x73, 0x77), 1: (0x65, 0x6D), 2: (0x67, 0x6F)}
        res = []
        for i in range(n):
            l, r = sig(i)
            for s in range(3):
                core.wg(INS[s][0], int(l) if s == slot else 0); core.wg(INS[s][1], int(r) if s == slot else 0)
            core.run_sample(); sim.eram.tick_sample()
            if i >= skip: res.append((core.rg(OUTS[slot][0]), core.rg(OUTS[slot][1])))
        return res
    def gz(xs, f):
        w = 2 * math.pi * f / 44100; c = 2 * math.cos(w); s1 = s2 = 0.0
        for x in xs: s0 = x + c * s1 - s2; s2, s1 = s1, s0
        return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / len(xs) / A
    saw = lambda i: ((i * 110.0 / 44100) % 1.0) * 2 - 1
    def vocode(fmod):
        res = play(lambda i: (A * math.sin(2 * math.pi * fmod * i / 44100), A * saw(i)), 5000, 2500)
        ys = [o[0] for o in res]
        return round(gz(ys, 330), 4), round(gz(ys, 2530), 4)
    # ---- ENGINE: OFF -> MFX -> VOICE ----
    sim.key(bm.K_RIGHT); sim.run(30); sim.key(bm.K_RIGHT); sim.run(40)
    print('ENGINE     %s  VLOADED %d MLOADED %d  words' % (['OFF', 'MFX', 'VOICE'][e.rb(bm.MON)], e.rb(bm.VLOADED),
                                                          e.rb(bm.MLOADED)), check('load'))
    if e.rb(bm.MON) != 2 or e.rb(bm.VLOADED) != 1 or e.rb(bm.MLOADED) != 0: fails.append('engine voice')
    prog_ok = all((sim.prog[w] & ~0xFF & 0x7FFFFF) == (V_w & ~0xFF & 0x7FFFFF) for w, V_w in
                  enumerate(bm.VOX_PROG) if 0x3C <= w < 0x2F1)
    print('           program words (op / address / shift) = vocdsp.build():', prog_ok)
    if not prog_ok: fails.append('program')
    shots.append(('FX CHAIN: ENGINE VOICE', sim.shot()))
    TABS = [t for t, _ in bm.MFX_TABS]
    # ---- VOCODER tab: presets ----
    tab(TABS.index('VOCODER'))
    shots.append(('VOCODER', sim.shot()))
    print('VC MONO    330 / 2530 Hz for mod 300 Hz:', vocode(300), ' mod 2500 Hz:', vocode(2500))
    row(0, 1)
    print('PRESET     %s  UI = preset: %s  words' % (V.PRESET_NAMES[ui()['preset']], ui() == V.preset_ui(1)), check('stereo'))
    if ui() != V.preset_ui(1): fails.append('preset stereo')
    row(0, 1)
    print('PRESET     %s  UI = preset: %s  words' % (V.PRESET_NAMES[ui()['preset']], ui() == V.preset_ui(2)), check('narrator'))
    if ui() != V.preset_ui(2): fails.append('preset narrator')
    a3, a25 = vocode(300)
    print('NARRATOR   330 / 2530 Hz for mod 300 Hz:', (a3, a25))
    if not a3 > 5 * a25: fails.append('vocodes')
    # ---- rows: FILTER 4-POLE, BANDS, FORMANT ----
    row(1, 1); print('FILTER     %s words' % ['2-POLE', '4-POLE'][ui()['filt']], check('4pole'))
    print('           4-POLE 330 / 2530 Hz for mod 300 Hz:', vocode(300))
    row(2, -6); print('BANDS      %d words' % ui()['bands'], check('bands'))
    row(1, -1); row(3, 12); print('FORMANT    %+d words' % (ui()['formant'] - 24), check('formant'))
    shots.append(('VOCODER: 2-POLE, FORMANT +12', sim.shot()))
    row(7, 1); print('HOLD       %d words' % ui()['hold'], check('hold')); row(7, -1)
    # ---- NARRATOR tab: signed rows, EQ ----
    tab(TABS.index('NARRATOR'))
    row(4, -6); print('LMT LEVEL  %+d DB words' % (ui()['lm_level'] - 60), check('lmlevel'))
    row(13, -5); print('LOW GAIN   %+d DB words' % (ui()['eq_lg'] - 12), check('eqlg'))
    row(16, 7); print('MID FREQ   %d HZ words' % round(V.mf_hz(ui()['eq_mf'])), check('eqmf'))
    shots.append(('NARRATOR: LOW GAIN', sim.shot()))
    # ---- BANDS tab ----
    tab(TABS.index('BANDS'))
    row(3, -30); print('BAND 4     %d words' % ui()['vchar3'], check('band4'))
    shots.append(('BANDS', sim.shot()))
    # ---- slots 2 / 3 pass through ----
    res = play(lambda i: (A * math.sin(2 * math.pi * 440 * i / 44100), A // 2), 400, 100, slot=1)
    pk = max(abs(o[0]) for o in res) / A
    print('SLOT 2     pass-through peak %.2f (1.0)  R %.2f (0.5)' % (pk, sum(o[1] for o in res) / len(res) / A))
    if abs(pk - 1.0) > 0.05: fails.append('slot 2 pass')
    # ---- KEYS takes DSP1, the guard reloads VOICE ----
    sim.key(bm.K_EXIT); sim.run(5)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('keys')); sim.key(bm.K_ENTER); sim.run(30)
    print('KEYS       KLOADED %d (VOICE words not rewritten while KEYS owns DSP1)' % e.rb(bm.KLOADED))
    sim.key(bm.K_EXIT); sim.run(30)
    for _ in range(12): sim.key(bm.K_LEFT)
    for _ in range([t for t, _ in bm.TILES].index('mfx')): sim.key(bm.K_RIGHT)
    sim.key(bm.K_ENTER); sim.run(40)
    print('KEYS exit  VLOADED %d KLOADED %d words' % (e.rb(bm.VLOADED), e.rb(bm.KLOADED)), check('after keys'))
    if e.rb(bm.VLOADED) != 1 or e.rb(bm.KLOADED) != 0: fails.append('reload after keys')
    # ---- ENGINE back to MFX, then OFF ----
    tab(TABS.index('FX CHAIN')); row(0, -1)
    mf_ok = all((sim.prog[bm.MFX_PARAMS[n][1]] & 0xFF) == c for n, (c, sh) in
                M.coefs(0, e.rb(bm.MTYPE), *[e.rb(bm.MP + j) for j in range(3)], e.rb(bm.MLVL),
                        M.regions([M.eff_type(e.rb(bm.MTYPE + k), e.rb(bm.MP + 3 * k)) for k in range(3)])[0],
                        tuple(e.rb(bm.MPX + n_) for n_ in range(3))).items())
    print('ENGINE     MFX  MLOADED %d VLOADED %d  slot 1 words = mfxdsp:' % (e.rb(bm.MLOADED), e.rb(bm.VLOADED)), mf_ok)
    if e.rb(bm.MLOADED) != 1 or e.rb(bm.VLOADED) != 0 or not mf_ok: fails.append('back to mfx')
    row(0, 1); row(0, -2)
    print('ENGINE     OFF  MLOADED %d VLOADED %d' % (e.rb(bm.MLOADED), e.rb(bm.VLOADED)))
    if e.rb(bm.MLOADED) or e.rb(bm.VLOADED): fails.append('off')
    print('odd word/long accesses:', ['pc %06X @%06X' % x for x in sorted(e.odd)] or 'none')
    if e.odd: fails.append('odd')
    print(ui_gfx.render(shots, out))
    print('RESULT', 'PASS' if not fails else 'FAIL %s' % fails)
    if fails: raise SystemExit(1)                              # (run_all ignores main's return value)


if __name__ == '__main__':
    main(*sys.argv[1:])
