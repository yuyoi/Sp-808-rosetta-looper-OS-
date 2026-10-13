"""JSW v0.3: own home menu (screen 5) -> ENTER starts the stock pad-sampling flow.

- Screen 5 (METER CH, the boot/home screen) handler -> our code at 0x16B000 (free flash).
- Screen 5 page -> 0: the stock page (0x1665AA) is a widget layout that drew the CH meters over our text (seen on hw v0.2).
- On enter we still run the stock meter-tap setup calls, then draw our text.
- Boot flow, disk detection and the update prompt are untouched (re-flash from disk keeps working).
- Version 1052 so a disk carrying it triggers "Update System?" on a unit running 1051.

usage: python -I build_v02.py raw.bin outdir
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm
from make_prg import check, SIZE, VER_HDR, VER_CODE

VERSION = 1053
CODE_BASE = 0x16B000                 # free flash (image offset 0x6B000)
SCREEN_TABLE = 0x166D74
SCREEN = 5
API_CLS, API_CURSOR, API_PUTS = 0x4003D4, 0x400434, 0x400440   # boot-ROM LCD calls
GOTO_SCREEN = 0x13FC0E
KEY_EVENT, HOME_SCREEN = 0x4278BA, 0x403256
KEY_ENTER, KEY_PLAY2 = 0x00B1, 0x00F2
SCR_SAMPLING, SCR_METER_AUX = 0x1F, 0x06


def menu_code():
    a = Asm(CODE_BASE)
    a.label('menu')                       # handler(r0.w = event)
    a.push_l(6)
    a.mov_w_rr(0, 6)
    a.mov_b_rr('r6h', 'r6h'); a.bne16('done')
    a.cmp_b_imm(0x00, 'r6l'); a.beq('enter')
    a.cmp_b_imm(0x05, 'r6l'); a.beq('draw')         # full redraw request
    a.cmp_b_imm(0x09, 'r6l'); a.beq('key')
    a.bra16('done')

    a.label('enter')                      # same as stock screen 5: become the home screen
    a.mov_w_imm(SCREEN, 0); a.mov_w_to_abs(0, HOME_SCREEN)
    a.jsr(0x120332)                       # stock: DSP meter tap setup
    a.mov_w_imm(0, 1); a.mov_w_imm(9, 8); a.mov_w_imm(7, 0)   # r1=0, e0=9, r0=7
    a.jsr(0x11F2AE)                       # stock: meter source config
    a.label('draw')
    a.jsr(API_CLS)
    for row, lbl in ((0, 's_title'), (2, 's_l1'), (3, 's_l2')):
        a.mov_b_imm(row, 'r0h'); a.mov_b_imm(0, 'r0l'); a.jsr(API_CURSOR)
        a.mov_l_imm(lbl, 0); a.jsr(API_PUTS)
    a.bra16('done')

    a.label('key')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(KEY_ENTER, 0); a.beq('sample')
    a.cmp_w_imm(KEY_PLAY2, 0); a.bne16('done')          # keep stock: this key -> AUX meter
    a.mov_w_imm(SCR_METER_AUX, 0); a.jsr(GOTO_SCREEN); a.bra16('done')
    a.label('sample')
    a.mov_w_imm(SCR_SAMPLING, 0); a.jsr(GOTO_SCREEN)

    a.label('done')
    a.pop_l(6)
    a.rts()

    a.label('s_title'); a.string('JSW LOOPER v0.3')
    a.label('s_l1'); a.string('ENTER: sample to pad')
    a.label('s_l2'); a.string('EXIT : back here')
    return a.assemble(), a.labels


def main(raw, outdir):
    img = bytearray(open(raw, 'rb').read()[:SIZE]); check(img)
    assert struct.unpack('>H', img[0x0E:0x10])[0] == 1050
    # keep the proven v0.1 patch
    o = 0x626BE; assert img[o:o + 16] == b'System Edit Menu'; img[o:o + 16] = b'JunksmithWizard!'
    # code into free flash
    code, labels = menu_code()
    off = CODE_BASE - 0x100000
    assert not any(img[off:off + len(code)]), 'target flash not empty'
    img[off:off + len(code)] = code
    # screen 5 entry: [flags:4][handler:4][params:4][page:4][?:4][parent:2]
    e = SCREEN_TABLE - 0x100000 + 22 * SCREEN
    flags, handler, params, page, x, parent = struct.unpack('>IIIIIH', img[e:e + 22])
    assert handler == 0x13D224 and page == 0x1665AA, 'unexpected screen 5 entry'
    img[e:e + 22] = struct.pack('>IIIIIH', flags, labels['menu'], params, 0, x, parent)   # page 0 = no stock widgets (meters)
    # version
    v = struct.pack('>H', VERSION)
    for o in VER_HDR: img[o:o + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_v03.bin'), 'wb').write(img)
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(struct.pack('>II', 0x100000, 0x1C0000) + img)
    print('v0.3 built: code %d bytes at 0x%X, version %d' % (len(code), CODE_BASE, VERSION))


if __name__ == '__main__':
    main(*sys.argv[1:3])
