"""v1.99 MIDI talk-back in the H8S emulator: channel-16 CCs set the registers, CC 30 queues a command, the main loop
(rk_getkey) runs it and replies as SysEx F0 7D 08 <cmd> ... F7 on MIDI OUT (rm_tx captured here).
usage: python -I tools/test_talkback.py work/build_v10/sp808_v10.bin"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v10
bm = test_v10.bm


def main(image_path):
    img = open(image_path, 'rb').read()
    sim = test_v10.KeysSim(img, bm.build()[1])
    e, L = sim.e, sim.L
    o = bm.MIDI_CC_SLOT - 0x100000
    print('CC slot    %06X -> %06X (m_cc_tr %06X)' % (bm.MIDI_CC_SLOT, struct.unpack('>I', img[o:o + 4])[0], L['m_cc_tr']))
    out, stock = [], []
    e.stubs[L['rm_tx']] = lambda e: out.append(e.g16(0) & 0xFF)
    e.stubs[bm.GETKEY] = lambda e: e.s16(0, 0)
    e.stubs[bm.STOCK_M_CC] = lambda e: stock.append(e.g16(0) & 0xFF)
    for v_ in [bm.RM_CMD, bm.RKR, bm.RKW] + [bm.RM_REG + i for i in range(8)]: e.wb(v_, 0)
    def cc(ch, n, v): e.wb(bm.MIDI_NOTE, n); e.wb(bm.MIDI_VEL, v); sim.call('m_cc_tr', ch - 1)
    def cmd(c, addr=0, n=0, val=0):
        for i, s in enumerate((21, 14, 7, 0)): cc(16, 20 + i, (addr >> s) & 0x7F)
        cc(16, 24, (n >> 7) & 0x7F); cc(16, 25, n & 0x7F); cc(16, 26, val & 0x7F); cc(16, 27, val >> 7)
        del out[:]; cc(16, 30, c)
        pend = e.rb(bm.RM_CMD); sim.call('rk_getkey')
        return pend, list(out)
    def nib(bs): return bytes(bs[i] << 4 | bs[i + 1] for i in range(0, len(bs), 2))
    p, r = cmd(3)
    print('PING       pending %d before the main loop, reply %s -> version %d (expect %d)' % (
        p, ' '.join('%02X' % b for b in r), struct.unpack('>H', nib(r[4:8]))[0], bm.VERSION))
    for i in range(16): e.wb(bm.KROW + i, 0x41 + i)
    p, r = cmd(1, bm.KROW, 16)
    print('PEEK RAM   16 bytes @%06X -> %s (expect ABCDEFGHIJKLMNOP), framing %02X..%02X, %d bytes' % (
        bm.KROW, nib(r[10:-1]), r[0], r[-1], len(r)))
    p, r = cmd(1, 0x10000E, 2)
    print('PEEK flash 0x10000E -> %d (the image version word: %d)' % (struct.unpack('>H', nib(r[10:-1]))[0], struct.unpack('>H', img[0x0E:0x10])[0]))
    p, r = cmd(1, 0x40187A, 816)
    print('PEEK LCD   816 bytes (34 rows x 24) -> %d data bytes back' % (len(r[10:-1]) // 2))
    for a_, n_ in ((0x0FFFFF, 4), (0x7FFFFF, 2), (bm.KROW, 0), (bm.KROW, 3000)):
        p, r = cmd(1, a_, n_); print('PEEK bad   @%06X len %d -> %s (expect F0 7D 08 7F F7)' % (a_, n_, ' '.join('%02X' % b for b in r)))
    p, r = cmd(2, bm.KROW + 3, val=0xC5)
    print('POKE       @%06X = C5 -> RAM %02X, reply %s' % (bm.KROW + 3, e.rb(bm.KROW + 3), ' '.join('%02X' % b for b in r)))
    p, r = cmd(2, 0x427906, val=0xFF)
    print('POKE bad   @427906 (stock RAM) -> %s, KEYMASK still %04X' % (' '.join('%02X' % b for b in r), e.rw(0x427906)))
    cc(1, 7, 100); cc(10, 30, 1)
    print('other ch   CCs on ch 1 / 10 -> stock handler %s, RM_CMD %d (expect [0, 9], 0)' % (stock, e.rb(bm.RM_CMD)))
    print('odd word/long accesses:', ['pc %06X @%06X' % x for x in sorted(e.odd)] or 'none')


if __name__ == '__main__':
    main(*sys.argv[1:])
