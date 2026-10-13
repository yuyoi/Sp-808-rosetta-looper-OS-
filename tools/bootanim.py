"""Roland-chan boot animation for the SP-808 OS (replaces the stock S-P/808 slide-up logo).

Stock routine 0x14871A (called once at boot from 0x11F0D6):
    setup calls, clear LCD (0x4003D4) at 0x148746, then
    0x14874A  mov.l #0x1684BA,er1 ... draws "Groove Sampler" (0x400470) and slides S-P/8/0/8 up
              with the blit API 0x400478, 17 frames, 0x1480EA(62500) between frames
    0x1487F0  epilogue (adds #4,sp x2, ldm er4-er6, ldm er2-er3, rts)
We patch 0x14874A to jmp to our player, which ends with jmp 0x1487F0. Stack and saved regs are untouched.

Blit API 0x400478 (as the stock code uses it): r0h = y, r0l = x, er1 = bitmap rows, e0 = (width << 8) | rows,
one long pushed (0) as a stack argument. Rows are padded to 4 bytes, MSB = leftmost pixel, 1 = dark.
er2-er6 survive the call (the stock loop relies on it).
Since v0.7f the player does not blit at all: each 132x32 frame is stored pre-packed in the boot ROM's LCD RAM
format (32 rows x 24 bytes, 6 px per byte, see gfxlib) and copied to @0x401EC4, which an interrupt streams to the
LCD. The blit reads its source as 7 px per byte, so the old 22 px strips lost every 8th pixel.
x = 2: centred on the 136 px wide screen (the stock logo spans x 3..133).

Frames come from tools/roland_chan.py (the user's art, option 5 = lanczos + sharpen + dither).
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm

PATCH_AT, PATCH_WAS, EPILOGUE = 0x14874A, bytes.fromhex('7a01001684ba'), 0x1487F0
BLIT, DELAY = 0x400478, 0x1480EA
TICK = 50000                # 0x1480EA units per tick; stock waits 62500 per frame (likely us)
X0, STRIP, NSTRIP, ROWS = 2, 22, 6, 32


FRAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'roland_chan_frames.npz')


def frames():
    """[(32x132 bool screen, ticks)] from assets/roland_chan_frames.npz (made by: roland_chan.py export)"""
    import numpy as np
    z = np.load(FRAMES)
    s, t = z['screens'].astype(bool), z['ticks']
    assert s.shape[1:] == (ROWS, STRIP * NSTRIP)
    return [(s[i], int(t[i])) for i in range(len(t))]


def pack(scr):
    """frame -> the boot ROM's LCD RAM image (32 rows x 24 bytes, 6 px per byte), frame at LCD x X0.
    (Until v0.7f this was 6 blits of 22 px strips; the blit reads 7 px per byte, so every 8th pixel was lost.)"""
    import gfxlib
    return b''.join(gfxlib.pack6(scr[r], X0) for r in range(ROWS))


def build(base, prologue=None):
    """-> (blob, labels) for the player + frame data, assembled at base.
    prologue(asm): optional code run once at boot before the animation (e.g. init our RAM)."""
    steps = frames()
    uniq, idx, table = [], {}, []
    for scr, ticks in steps:
        b = pack(scr)
        if b not in idx: idx[b] = len(uniq); uniq.append(b)
        table.append((idx[b], ticks))
    a = Asm(base)
    a.label('anim')
    if prologue: prologue(a)
    a.mov_l_imm('anim_table', 4)
    a.label('an_next')
    a.mov_l_ind(4, 6)                        # er6 = frame (0 = end)
    a.beq16('an_done')
    a.mov_l_from_abs(0x401EC4, 5)            # LCD dot rows (boot ROM pointer), streamed to the LCD by interrupt
    a.mov_w_imm(ROWS * 24 // 4, 2)           # copy 768 bytes as longs
    a.label('an_copy')
    a.mov_l_ind(6, 0); a.mov_l_st(0, 5); a.adds4(6); a.adds4(5); a.dec_w1(2); a.bne('an_copy')
    a.mov_w_disp(4, 4, 6)                    # r6 = ticks
    a.label('an_wait')
    a.mov_l_imm(TICK, 0); a.jsr(DELAY)
    a.dec_w1(6); a.bne('an_wait')
    a.add_l_imm(8, 4)
    a.bra16('an_next')
    a.label('an_done')
    a.jmp(EPILOGUE)
    a.align2()
    a.label('anim_table')
    for f, ticks in table:
        a.dc_l('anim_f%d' % f); a.raw(struct.pack('>HH', ticks, 0))
    a.dc_l(0); a.dc_l(0)
    for i, b in enumerate(uniq):
        a.label('anim_f%d' % i); a.raw(b)
    blob = a.assemble()
    print('boot anim: %d steps, %d unique frames, %d bytes at 0x%X' % (len(table), len(uniq), len(blob), base))
    return blob, a.labels


def patch(img, base, prologue=None):
    """write the player + frames at base (must be empty flash) and hook the stock routine"""
    blob, labels = build(base, prologue)
    off = base - 0x100000
    assert not any(img[off:off + len(blob)]), 'boot anim target flash not empty'
    img[off:off + len(blob)] = blob
    p = PATCH_AT - 0x100000
    assert bytes(img[p:p + 6]) == PATCH_WAS, 'boot routine changed?'
    an = labels['anim']
    img[p:p + 6] = bytes((0x5A, (an >> 16) & 0xFF, (an >> 8) & 0xFF, an & 0xFF, 0x00, 0x00))
    return blob, labels
