"""v1.98 MIDI remote keys in the H8S emulator: notes on MIDI channel 16 (codes 0x00-0x7F) / 15 (0x80 + note) become
raw key words in a ring that the OS key dispatcher reads first (its jsr 0x1311C6 is patched to rk_getkey); velocity 64+
= SHIFT, note-off / velocity 0 = release; other channels still reach KEYS / the stock handlers.
usage: python -I tools/test_remote.py work/build_v10/sp808_v10.bin"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10
bm = test_v10.bm


def main(image_path):
    img = open(image_path, 'rb').read()
    sim = test_v10.KeysSim(img, bm.build()[1])
    e, L = sim.e, sim.L
    o = bm.GETKEY_CALL - 0x100000
    print('call site  %06X: %s -> rk_getkey %06X: %s' % (bm.GETKEY_CALL, img[o:o + 4].hex(), L['rk_getkey'],
          'patched' if img[o:o + 4] == bytes([0x5E]) + L['rk_getkey'].to_bytes(3, 'big') else 'NOT PATCHED'))
    scanner = []
    e.stubs[bm.GETKEY] = lambda e: (scanner.append(1), e.s16(0, 0))         # the real key scanner: no key
    stock = []
    e.stubs[bm.STOCK_M_ON] = lambda e: stock.append(('on', e.g16(0) & 0xFF))
    e.stubs[bm.STOCK_M_OFF] = lambda e: stock.append(('off', e.g16(0) & 0xFF))
    for v_, val_ in ((bm.RKR, 0), (bm.RKW, 0)): e.wb(v_, val_)
    def midi(ch, note, vel, on=True):
        e.wb(bm.MIDI_NOTE, note); e.wb(bm.MIDI_VEL, vel); sim.call('m_on_tr' if on else 'm_off_tr', ch - 1)
    def drain():
        out = []
        for _ in range(10):
            n = len(scanner); r = sim.call('rk_getkey')
            if len(scanner) > n: break
            out.append('%04X' % r)
        return out
    midi(16, 0x22, 32); midi(16, 0x22, 0, on=False)                          # PAD SAMPLING tap
    midi(16, 0x22, 100); midi(16, 0x22, 0)                                  # SHIFT + PAD SAMPLING, release by vel 0
    midi(15, 0x31, 20); midi(15, 0x31, 20, on=False)                        # 0x80 + 0x31 = 0xB1 = ENTER
    print('ring       ch16 PAD SAMPLING tap, SHIFT tap, ch15 ENTER ->', drain(),
          '(expect 0022 4022 0122 4022 00B1 40B1)')
    print('empty      ring empty -> the key scanner was asked:', len(scanner) > 0)
    for i in range(10): midi(16, 0x10 + (i & 15), 32)
    print('full       10 presses -> kept', drain(), '(7: the ring holds 7, the rest dropped)')
    midi(1, 60, 100); midi(1, 60, 0, on=False); midi(10, 36, 90)
    print('other ch   ch 1 / ch 10 went to', stock, '(expect the stock handlers, channels 0 / 9)')
    # the OS's own key dispatcher (0x13F2F0, stock code) with remote keys: PAD SAMPLING reaches the group-2 hook (g2 =
    # PAD SAMPLING / looper) as KEY_EVENT 0x0022 / 0x4022, a pad reaches g1
    seen = []
    for lbl in ('g1', 'g2'):
        e.stubs[L[lbl]] = (lambda n: lambda e: (seen.append((n, '%04X' % e.rw(bm.KEY_EVENT))), e.s16(0, 1)))(lbl)
    e.wb(bm.PAGE, bm.P_LOOP)
    lo, hi = e.code_lo, e.code_hi; e.code_lo, e.code_hi = 0x100000, 0x1C0000      # run the stock dispatcher's helpers
    e.stubs[0x13F39E] = lambda e: seen.append(('screen', '%04X' % e.rw(bm.KEY_EVENT)))   # (not reached: hooks eat)
    midi(16, 0x22, 32); midi(16, 0x22, 0, on=False); midi(16, 0x13, 32)
    for _ in range(4): sim.call(0x13F2F0)
    e.code_lo, e.code_hi = lo, hi
    print('dispatcher remote PAD SAMPLING tap + pad 4 ->', seen, '(expect g2 0022, g2 4022, g1 0013)')
    print('odd word/long accesses:', ['pc %06X @%06X' % x for x in sorted(e.odd)] or 'none')


if __name__ == '__main__':
    main(*sys.argv[1:])
