"""Run our screen-5 draw routine in the H8S emulator for each page and render what reaches the LCD.

usage: python -I test_ui.py build_module image.bin out.png      e.g. build_v07 build_v07/sp808_v07.bin art/ui_emu.png
The blit stub (boot API 0x400478) copies the strips into a 136x32 LCD model; stock calls are stubbed.
"""
import importlib, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h8emu, ui_gfx

USED = {0, 1, 2, 3, 4, 5, 6, 8, 9, 12}          # pads with a sample (0-based), as in the mockup


def run(bm, image, labels, setup):
    emu = h8emu.Emu(image)
    lcd = [[0] * 136 for _ in range(32)]
    def blit(e):
        x, y = e.g8(8), e.g8(0)                  # r0l, r0h
        w, rows = e.g16(8) >> 8, e.g16(8) & 0xFF
        src = e.g32(1)
        for r in range(rows):
            word = e.rl(src + 4 * r)
            for i in range(w):
                if 0 <= y + r < 32 and 0 <= x + i < 136: lcd[y + r][x + i] = (word >> (31 - i)) & 1
    emu.stubs[0x400478] = blit
    emu.stubs[bm.PAD_USED] = lambda e: e.s16(0, int(e.g16(0) in USED))
    for addr, val in setup.items(): emu.wb(addr, val)
    emu.call(labels['draw'])
    c = ui_gfx.Canvas()
    for y in range(32):
        for x in range(128): c.px[y][x] = lcd[y][x + 2]
    edge = any(lcd[y][x] for y in range(32) for x in (0, 1, 130, 131, 132, 133, 134, 135))
    return c, emu.steps, edge


def main(mod, image_path, out):
    bm = importlib.import_module(mod)
    image = open(image_path, 'rb').read()
    blob, labels = bm.build()
    base = {bm.SMODE: bm.SM_CLASSIC, bm.SELPAD: 4, bm.MCUR: 0, bm.TRIG_MODE: 0, bm.PAGE: bm.P_MPC}
    cases = [('HOME, LOOP selected', {**base, bm.PAGE: bm.P_HOME, bm.CUR: 1}),
             ('HOME, MPC selected + RAM!', {**base, bm.PAGE: bm.P_HOME, bm.CUR: 0, bm.WARN: 1}),
             ('MPC, pad 5 used, row PAD', base),
             ('MPC, pad 8 empty, row START, ON SIGNAL', {**base, bm.SELPAD: 7, bm.MCUR: 2, bm.TRIG_MODE: 3}),
             ('MPC, no pad + HIT A PAD FIRST', {**base, bm.SELPAD: 0xFF, bm.MSG: 2}),
             ('MPC, TAKE CANCELED', {**base, bm.MSG: 3, bm.MCUR: 1}),
             ('MPC TAP armed', {**base, bm.SMODE: bm.SM_TAP, bm.MSTATE: bm.MS_ARMED}),
             ('LOOPER page', {**base, bm.PAGE: bm.P_LOOP})]
    screens = []
    for name, setup in cases:
        c, steps, edge = run(bm, image, labels, setup)
        print('%-42s %7d steps%s' % (name, steps, '  (pixels outside x 2..129!)' if edge else ''))
        screens.append((name, c))
    print(ui_gfx.render(screens, out))


if __name__ == '__main__':
    main(*sys.argv[1:4])
