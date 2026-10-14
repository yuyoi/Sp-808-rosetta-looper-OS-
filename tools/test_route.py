"""ROUTING page (v1.91) in the H8S emulator: navigation, presets, FX LOCATION, mixer writes, dial step, screenshots.

usage: python -I tools/test_route.py work/build_v10/sp808_v10.bin out.png
The stock FX LOCATION apply (0x1361CE) is faked like the OS does it: FX on (0x426D98 bit 1) and the mixer location in
use (0x426DD0 bit 7) -> code of entry 0x426DD1 -> MIXER_PARAM(7, 0, code). MIXER_PARAM itself is a logging stub.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10, ui_gfx
bm = test_v10.bm


def main(image_path, out):
    sim = test_v10.KeysSim(open(image_path, 'rb').read(), bm.build()[1])
    e, shots = sim.e, []
    applied = []
    def loc_apply(e):
        if not e.rb(0x426D98) & 2: code = 0
        elif e.rb(bm.MIXER_LOC_FLAGS) & 0x80:
            idx = e.rb(bm.MIXER_LOC_IDX); code = bm.RT_LOC_CODES[idx] if idx < 16 else None
            if code is None: code = 0x0C                     # FX PATCH: the patch's own location (master here)
        else: code = 0x0C
        applied.append(code); sim.routing.append((round(sim.t, 1), 7, 0, code)); e.wb(bm.FX_ROUTE_CODE, code)
    e.stubs[bm.FX_LOC_APPLY] = loc_apply
    e.wb(0x426D98, 2)                                        # EFFECTS on
    for g in range(5): e.wb(bm.mx(g, 11), 100); e.wb(bm.mx(g, 12), 64)
    e.wb(bm.mx(0, 12), 0); e.wb(bm.mx(1, 12), 127); e.wb(bm.mx(2, 12), 70)
    e.wb(bm.mx(5, 0), 100); e.wb(bm.mx(6, 0), 100); e.wb(bm.MIXER_LOC_IDX, 14)
    for v_, val_ in ((bm.KSTEP, 1), (bm.KTHRU, 1), (bm.KMXS, 16), (bm.KSUS, 16)): e.wb(v_, val_)
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    tile = [t for t, _ in bm.TILES].index('route')
    for _ in range(tile): sim.key(bm.K_RIGHT)
    sim.run(5); shots.append(('home: ROUTING tile', sim.shot()))
    sim.key(bm.K_ENTER); sim.run(20)
    print('enter      page', e.rb(bm.PAGE), '(expect %d)' % bm.P_ROUTE, 'KEYS active', e.rb(bm.KACTIVE), 'tab', e.rb(bm.RTAB))
    shots.append(('ROUTING quick setup', sim.shot()))
    n = len(sim.routing)
    for _ in range(3): sim.key(bm.K_RIGHT)
    print('preset     RPRE', e.rb(bm.RPRE), bm.RT_PRESETS[e.rb(bm.RPRE)][0], 'loc idx', e.rb(bm.MIXER_LOC_IDX),
          'flags %02X' % e.rb(bm.MIXER_LOC_FLAGS), 'mixer calls', [r[1:] for r in sim.routing[n:]])
    shots.append(('preset LOOP FX', sim.shot()))
    sim.key(bm.K_DOWN); n = len(sim.routing); sim.key(bm.K_RIGHT); sim.run(5)
    print('FX AT +1   loc idx', e.rb(bm.MIXER_LOC_IDX), bm.RT_LOC_NAMES[e.rb(bm.MIXER_LOC_IDX)], 'preset', e.rb(bm.RPRE),
          'mixer', [r[1:] for r in sim.routing[n:]], 'FX_ROUTE_CODE %02X' % e.rb(bm.FX_ROUTE_CODE))
    shots.append(('FX AT INS MASTER, preset CUSTOM', sim.shot()))
    for _ in range(4): sim.key(bm.K_RIGHT)
    shots.append(('FX AT MIC/LINE POST', sim.shot()))
    sim.key(bm.K_ENTER); sim.run(5); shots.append(('submode menu', sim.shot()))
    sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(5)
    print('LEVELS     tab', e.rb(bm.RTAB), 'row', e.rb(bm.RCUR))
    n = len(sim.routing)
    e.ww(bm.ENC_DELTA, 5); sim.run(10); e.ww(bm.ENC_DELTA, 0); sim.run(10)
    print('dial +5    TRACK A level', e.rb(bm.mx(0, 11)), '(expect 105) KSTEP', e.rb(bm.KSTEP), 'mixer', [r[1:] for r in sim.routing[n:]])
    e.ww(bm.ENC_DELTA, 30); sim.run(10); e.ww(bm.ENC_DELTA, 0); sim.run(10)
    print('dial +30   TRACK A level', e.rb(bm.mx(0, 11)), '(expect 113: step capped at 8)')
    for _ in range(3): e.ww(bm.ENC_DELTA, 8); sim.run(10)
    e.ww(bm.ENC_DELTA, 0); sim.run(10)
    print('dial up    TRACK A level', e.rb(bm.mx(0, 11)), '(expect 127, clamped)')
    e.ww(bm.ENC_DELTA, -8); sim.run(10); e.ww(bm.ENC_DELTA, 0)
    sim.key(bm.K_LEFT)
    print('dial -8, LEFT  level', e.rb(bm.mx(0, 11)), '(expect 118)')
    for _ in range(5): sim.key(bm.K_DOWN)
    sim.run(5); shots.append(('LEVELS (scrolled to REC BUS)', sim.shot()))
    sim.key(bm.K_ENTER); sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(5)
    shots.append(('PAN: L64 R63 R6', sim.shot()))
    sim.key(bm.K_ENTER); sim.key(bm.K_DOWN); sim.key(bm.K_DOWN); sim.run(5); shots.append(('menu scrolled', sim.shot()))
    sim.key(bm.K_ENTER); sim.run(5); shots.append(('AUX SENDS', sim.shot()))
    sim.key(bm.K_EXIT); sim.run(5)
    print('EXIT       page', e.rb(bm.PAGE), 'cursor', e.rb(bm.CUR), '(expect 0, %d)' % tile)
    print('applied codes', applied)
    # ---- LAB: ANALOG INPUTS (live bars) and BUTTONS (last key, factory name) ----
    for ch in range(bm.ADC_N): e.wb(bm.ADC_TAB + ch, ch * 18)
    e.wb(bm.LCH, 9)                                          # as the boot RAM init sets it
    sim.key(bm.K_RIGHT); sim.key(bm.K_ENTER); sim.run(50)
    print('LAB        page', e.rb(bm.PAGE), '(expect %d) tab' % bm.P_LAB, e.rb(bm.LTAB), 'channel', e.rb(bm.LCH))
    shots.append(('LAB analog (ch 9 = 162)', sim.shot()))
    e.wb(bm.ADC_TAB + 9, 250); t0 = e.rl(bm.LABT); sim.run(60)
    print('live       LABT moved by', e.rl(bm.LABT) - t0, 'ms in 60 ms (expect > 0: redraws every 40 ms)')
    shots.append(('BEAM L moved to 250', sim.shot()))
    e.ww(bm.ENC_DELTA, -3); sim.run(10); e.ww(bm.ENC_DELTA, 0)
    print('dial -1    channel', e.rb(bm.LCH), '(expect 8)')
    sim.key(bm.K_ENTER); sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(10)
    shots.append(('LAB buttons (nothing yet)', sim.shot()))
    for code in (0x93, 0x4093, 0x101, 0xC0):
        sim.key(code); sim.run(5)
        row = bytes(e.rb(bm.KROW + i) for i in range(32)).split(b'\0')[0].decode()
        print('key %04X   LKEYW %04X  row [%s]' % (code, e.rw(bm.LKEYW), row))
    shots.append(('LAB buttons: INFO', sim.shot()))
    sim.key(0x4093); sim.run(5); shots.append(('LAB buttons: MARK released', sim.shot()))
    # ---- LAB: LED SHOW (Roland's LED on / off modelled on the state bits) ----
    leds = []
    def led_mask(code): return e.rw(bm.LED_MASKS + 2 * (code & 15)), bm.LED_ROWS + 2 * ((code >> 4) & 15)
    def led_on(e):
        m, a = led_mask(e.g16(0)); e.ww(a, e.rw(a) | m); leds.append(('on', e.g16(0)))
    def led_off(e):
        m, a = led_mask(e.g16(0)); e.ww(a, e.rw(a) & ~m); leds.append(('off', e.g16(0)))
    e.stubs[bm.LED_ON], e.stubs[bm.LED_OFF] = led_on, led_off
    m, a = led_mask(0x40); e.ww(a, e.rw(a) | m)              # the stock had LOC 1 lit
    before = [e.rw(bm.LED_ROWS + 2 * r) for r in range(16)]
    sim.key(bm.K_ENTER); sim.key(bm.K_DOWN); sim.key(bm.K_ENTER); sim.run(10)
    print('LED SHOW   tab', e.rb(bm.LTAB), 'LED', e.rb(bm.LEDIX), 'lit', e.rb(bm.LEDON), 'events', leds)
    shots.append(('LED SHOW: LED 1', sim.shot()))
    sim.key(bm.K_RIGHT); sim.run(5)
    print('RIGHT      LED', e.rb(bm.LEDIX), 'was on', e.rb(bm.LEDWAS), 'events', leds[-3:])
    shots.append(('LED SHOW: LOC 1', sim.shot()))
    sim.key(bm.K_UP); sim.run(400)
    print('chase 400 ms -> LED', e.rb(bm.LEDIX), '(expect about 5-6)')
    shots.append(('LED SHOW: chase', sim.shot()))
    sim.key(bm.K_DOWN); sim.key(bm.K_LEFT); sim.key(bm.K_LEFT); sim.run(5)
    sim.key(bm.K_EXIT); sim.run(20)
    after = [e.rw(bm.LED_ROWS + 2 * r) for r in range(16)]
    print('EXIT       page', e.rb(bm.PAGE), 'LED rows restored:', before == after, 'lit', e.rb(bm.LEDON))
    print(ui_gfx.render(shots, out))


if __name__ == '__main__':
    main(*sys.argv[1:])
