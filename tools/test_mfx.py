"""MFX (v1.91) in the H8S emulator + the DSP1 model: engine on/off, the program load (through the flash table and the
loader), the three slots passing audio at their levels, routing calls, the control mapping, the write gate.

usage: python -I tools/test_mfx.py work/build_v10/sp808_v10.bin out.png
"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, ui_gfx
bm = test_v10.bm

INS = {0: (0x71, 0x75), 1: (0xD1, 0xD3), 2: (0xD5, 0xD7)}       # what DSP0 sends, as DSP1 reads it
OUTS = {0: (0x73, 0x77), 1: (0x65, 0x6D), 2: (0x67, 0x6F)}       # what DSP1 returns, as DSP0 reads it


def slot_gains(sim, n=1500):
    core = sim.core
    peak = {(s, c): 0 for s in range(3) for c in (0, 1)}
    for k in range(n):
        for s in range(3):
            for c in (0, 1):
                core.wg(INS[s][c], int(0x200000 * math.sin(2 * math.pi * (300 + 200 * s + 50 * c) * k / 44100)))
        core.run_sample(); sim.eram.tick_sample()
        if k > 200:
            for s in range(3):
                for c in (0, 1): peak[(s, c)] = max(peak[(s, c)], abs(core.rg(OUTS[s][c])))
    return [round(max(peak[(s, 0)], peak[(s, 1)]) / 0x200000, 3) for s in range(3)]


def main(image_path, out):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    loads = []
    def loc_apply(e):
        idx = e.rb(bm.MIXER_LOC_IDX)
        code = (bm.RT_LOC_CODES[idx] if idx < 16 else 0) if e.rb(bm.MIXER_LOC_FLAGS) & 0x80 else 0x0C
        if code is None: code = 0x0C
        if not e.rb(0x426D98) & 2: code = 0
        sim.routing.append((round(sim.t, 1), 7, 0, code)); e.wb(bm.FX_ROUTE_CODE, code)
    e.stubs[bm.FX_LOC_APPLY] = loc_apply
    e.stubs[bm.FX_LOAD_PATCH] = lambda e: loads.append(e.g32(0))
    e.wb(0x426D98, 2); e.wb(bm.MIXER_LOC_IDX, 14); e.wb(bm.MIXER_LOC_FLAGS, 0)
    e.ww(bm.FX_PATCH_BUF, 7)                                 # the stock patch: algorithm 7
    for v_, val_ in ((bm.KSTEP, 1), (bm.KTHRU, 1), (bm.KMXS, 16), (bm.KSUS, 16), (bm.MSLOT, 12), (bm.MLVL, 64),
                     (bm.MLVL + 1, 64), (bm.MLVL + 2, 64)): e.wb(v_, val_)
    for i in range(6): e.wb(bm.MCLAST + i, 0xFF)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    tile = [t for t, _ in bm.TILES].index('mfx')
    for _ in range(tile): sim.key(bm.K_RIGHT)
    sim.run(5); shots.append(('home: MFX tile', sim.shot()))
    sim.key(bm.K_ENTER); sim.run(10)
    print('enter      page', e.rb(bm.PAGE), '(expect %d)' % bm.P_MFX)
    shots.append(('MFX off', sim.shot()))
    n = len(sim.routing)
    sim.key(bm.K_RIGHT); sim.run(20)                         # ENGINE ON
    print('ENGINE ON  MON', e.rb(bm.MON), 'loaded', e.rb(bm.MLOADED), 'KGATE %02X' % e.rb(bm.KGATE), 'loads',
          [x for x in sim.dsp_log if x[1] == 'load'], 'FX_CUR %04X' % e.rw(bm.FX_CUR))
    print('           routing', [r[1:] for r in sim.routing[n:]], 'stock loc idx', e.rb(bm.MIXER_LOC_IDX),
          'saved', e.rb(bm.MSAVEIDX))
    w0 = (bm.MFX_PARAMS['m0_odl'][1])
    print('           program at 0x3C..: %s' % ['%07X' % sim.prog[w] for w in range(0x3C, 0x41)], 'm0_odl coef', sim.prog[w0] & 0xFF)
    print('slots      gains', slot_gains(sim), '(expect 1.0 1.0 1.0)')
    shots.append(('MFX on', sim.shot()))
    sim.key(bm.K_DOWN); sim.key(bm.K_DOWN); sim.key(bm.K_DOWN)            # SLOT 2 AT
    n = len(sim.routing)
    for _ in range(3): sim.key(bm.K_RIGHT)
    print('SLOT 2 AT  code', e.rb(bm.MSLOT + 1), bm.MF_CODE_NAMES[e.rb(bm.MSLOT + 1)], 'routing (last pass)', [r[1:] for r in sim.routing[n:]][-3:])
    sim.key(bm.K_DOWN)
    e.ww(bm.ENC_DELTA, -8); sim.run(10)
    for _ in range(3): sim.run(10)
    e.ww(bm.ENC_DELTA, 0); sim.run(10)
    print('SLOT 2 LVL', e.rb(bm.MLVL + 1), '(expect 32) gains', slot_gains(sim), '(expect 1.0 0.5 1.0)')
    shots.append(('slot 2 at TR.A POST, level 32', sim.shot()))
    for _ in range(3): sim.key(bm.K_DOWN)
    sim.run(5); shots.append(('FX CHAIN scrolled', sim.shot()))
    sim.key(bm.K_ENTER); [sim.key(bm.K_DOWN) for _ in range(4)]; sim.key(bm.K_ENTER); sim.run(5)   # CONTROLS (tab 4)
    for _ in range(3): sim.key(bm.K_RIGHT)                   # KNOB A -> SLOT 3 LEVEL
    e.wb(bm.ADC_TAB + 6, 200); sim.run(30)
    print('KNOB A     -> target', e.rb(bm.MCTRL), bm.MF_TGTS[e.rb(bm.MCTRL)], 'raw 200 -> SLOT 3 LEVEL', e.rb(bm.MLVL + 2),
          '(expect 100) gains', slot_gains(sim), '(expect 1.0 0.5 1.56)')
    e.wb(bm.ADC_TAB + 6, 0); sim.run(30); print('KNOB A 0   SLOT 3 LEVEL', e.rb(bm.MLVL + 2), 'gains', slot_gains(sim))
    shots.append(('CONTROLS', sim.shot()))
    # ---- PADS 1-3 = FX SWITCH: pad 2 bypasses slot 2 (level 32 -> x1), the pad LEDs show the slots that are on ----
    prow = bm.LED_ROWS + 2
    def lit(): return [p + 1 for p in range(16) if e.rw(prow) & e.rw(bm.LED_MASKS + 2 * p)]
    for _ in range(6): sim.key(bm.K_DOWN)
    sim.key(bm.K_RIGHT); sim.run(30)
    print('PADS       mode', e.rb(bm.MPADS), bm.MF_CODE_NAMES and '', 'pads lit', lit(), '(expect 1 2 3)')
    shots.append(('CONTROLS: PADS FX SWITCH', sim.shot()))
    sim.pad(1); sim.pad(1, False); sim.run(20)
    print('pad 2      MBYP %d lit %s gains %s (expect 2, [1, 3], slot 2 back to 1.0)' % (e.rb(bm.MBYP), lit(), slot_gains(sim)))
    sim.pad(1); sim.pad(1, False); sim.run(20)
    print('pad 2 again MBYP %d lit %s gains %s' % (e.rb(bm.MBYP), lit(), slot_gains(sim)))
    n_on = len([x for x in sim.log if x[1] == 'on'])
    sim.pad(5); sim.pad(5, False); sim.run(20)
    print('pad 6      plays as usual:', len([x for x in sim.log if x[1] == 'on']) - n_on, 'note-on (expect 1)')
    sim.key(bm.K_LEFT); sim.run(20); print('PADS PLAY  lit', lit(), '(pads given back)')
    n0 = len(sim.dsp_log); e.s16(0, 0x1000 | (w0 << 2)); e.s16(8, 0x7F00)
    sim.call('gate_coef'); print('gate       Roland write while MFX on -> %d writes (expect 0)' % (len(sim.dsp_log) - n0))
    sim.key(bm.K_ENTER); [sim.key(bm.K_UP) for _ in range(4)]; sim.key(bm.K_ENTER); sim.run(5)     # FX CHAIN
    n = len(sim.routing)
    sim.key(bm.K_LEFT); sim.run(10)                          # ENGINE OFF
    print('ENGINE OFF MON', e.rb(bm.MON), 'loaded', e.rb(bm.MLOADED), 'KGATE %02X' % e.rb(bm.KGATE), 'routing',
          [r[1:] for r in sim.routing[n:]], 'stock loc idx', e.rb(bm.MIXER_LOC_IDX), 'stock FX reload', ['%06X' % x for x in loads])
    try: sim.call('gate_coef'); r = 'dropped'
    except RuntimeError as x: r = 'passed on to the stock writer (%s)' % x
    print('gate       Roland write after OFF ->', r)
    # back on, then KEYS takes DSP1 and gives it back: MFX reloads by itself
    sim.key(bm.K_RIGHT); sim.run(10); nl = len([x for x in sim.dsp_log if x[1] == 'load'])
    sim.key(bm.K_EXIT); sim.run(5)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('keys')); sim.key(bm.K_ENTER); sim.run(30)
    print('KEYS       active', e.rb(bm.KACTIVE), 'KLOADED', e.rb(bm.KLOADED), 'MLOADED', e.rb(bm.MLOADED), 'KGATE %02X' % e.rb(bm.KGATE))
    sim.key(bm.K_EXIT); sim.run(30)
    print('KEYS exit  active', e.rb(bm.KACTIVE), 'MLOADED', e.rb(bm.MLOADED), 'KGATE %02X' % e.rb(bm.KGATE),
          'loads since', len([x for x in sim.dsp_log if x[1] == 'load']) - nl, '(expect 2: KEYS, MFX again) gains', slot_gains(sim))
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:])
