"""v1.99b in the H8S emulator: diskless mode (stock message screen 3 now leaves with EXIT) and the Mac pages' EXIT
one level up (tab -> tab list -> home). usage: python -I tools/test_diskless.py work/build_v10/sp808_v10.bin"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10
bm = test_v10.bm


def main(image_path):
    img = open(image_path, 'rb').read()
    sim = test_v10.KeysSim(img, bm.build()[1])
    e, L = sim.e, sim.L
    o = bm.SCREEN_TABLE - 0x100000 + 22 * bm.MSG_SCREEN
    print('screen 3   handler %06X (scr_msg %06X)' % (struct.unpack('>I', img[o + 4:o + 8])[0], L['scr_msg']))
    calls = []
    e.stubs[bm.MSG_HANDLER] = lambda e: calls.append(('stock', e.g16(0)))
    e.stubs[bm.FORCE_SCREEN] = lambda e: calls.append(('goto', e.g16(0)))
    e.wb(bm.DISKLESS, 0); e.wb(bm.MSG_INDEX, 1)                         # another message (e.g. Wrong Disk)
    for ev in (0, 5, 6): sim.call('scr_msg', ev)
    e.ww(bm.KEY_EVENT, bm.K_RIGHT); sim.call('scr_msg', 9)
    print('events     0/5/6 -> stock, RIGHT ignored:', calls, '(expect 3 x stock, no goto)')
    del calls[:]; e.ww(bm.KEY_EVENT, bm.K_EXIT); sim.call('scr_msg', 9)
    print('EXIT       ->', calls, 'DISKLESS', e.rb(bm.DISKLESS), '(expect goto 5, 1)')
    del calls[:]; e.wb(bm.DISKLESS, 0); e.wb(bm.MSG_INDEX, 0); sim.call('scr_msg', 0)
    print('no disk    "Please Insert Zip Disk" opens ->', calls, 'DISKLESS', e.rb(bm.DISKLESS), '(expect goto 5 at once, 1)')
    # Mac pages: EXIT on a tab opens the tab list, EXIT on the list goes home
    e.wb(bm.PAGE, bm.P_HOME); sim.call('menu', 0); sim.run(5)
    e.wb(bm.CUR, [t for t, _ in bm.TILES].index('route')); sim.key(bm.K_ENTER); sim.run(10)
    p0 = e.rb(bm.PAGE); sim.key(bm.K_EXIT); sim.run(5)
    p1, m1 = e.rb(bm.PAGE), e.rb(bm.KDMENU); sim.key(bm.K_EXIT); sim.run(5)
    print('ROUTING    page %d -> EXIT: page %d tab list %d -> EXIT: page %d tab list %d (expect %d, %d 1, 0 0)' % (
        p0, p1, m1, e.rb(bm.PAGE), e.rb(bm.KDMENU), bm.P_ROUTE, bm.P_ROUTE))
    # ROUTING preset VOCODER: input send hard L, tracks' sends hard R, send/return
    e.stubs[bm.FX_LOC_APPLY] = lambda e: None
    del sim.routing[:]; e.wb(bm.RPRE, [n for n, _ in bm.RT_PRESETS].index('VOCODER')); sim.call('rt_preset')
    pans = {g: v for _, g, i, v in sim.routing if i == 18}; lv = {g: v for _, g, i, v in sim.routing if i == 17}
    print('VOCODER    send pans %s levels %s FX loc idx %d (expect input 4 -> 0 = L, tracks 0-3 -> 127 = R, 100s, 0)' % (
        pans, lv, e.rb(bm.MIXER_LOC_IDX)))
    print('odd word/long accesses:', ['pc %06X @%06X' % x for x in sorted(e.odd)] or 'none')


if __name__ == '__main__':
    main(*sys.argv[1:])
