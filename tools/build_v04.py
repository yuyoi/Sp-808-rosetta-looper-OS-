"""JSW v0.4: one-press PAD SAMPLING -> record into the first free pad.

Changes vs v0.3 (proven on hw):
- Global key-group 2 handler (table 0x166BEC, stock 0x13F5C4) -> our wrapper:
    PAD SAMPLING (0x22)        : first free pad (0x14D8EC) -> select (0x4277D4, 0x13C426)
                                 -> arm trigger / mode byte (0x13C30E) -> memory check (0x14D91E)
                                 -> record screen 0x22 (+ key-group mask 0x13F2D0), as the stock
                                 transition at 0x13C7BE does. Press again = stock stop.
                                 Bank full -> stock sampling menus.
    SHIFT+PAD SAMPLING (0x122) : stock sampling menus (screen 0x1F).
    anything else              : stock handler.
- Home menu (screen 5): ENTER toggles start mode = sampling trigger byte 0x4277C9
  (0 = MANUAL: record at once, 3 = LEV.3: hardware waits for signal). BSS, so INSTANT at boot.

usage: python -I build_v04.py raw.bin outdir
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm
from make_prg import check, SIZE, VER_HDR, VER_CODE

VERSION = 1054
CODE_BASE = 0x16B000
SCREEN_TABLE, SCREEN = 0x166D74, 5
KEYGROUP_TABLE = 0x166BE4
API_CLS, API_CURSOR, API_PUTS = 0x4003D4, 0x400434, 0x400440
GOTO_SCREEN, KEYMASK_SAMPLING = 0x13FC0E, 0x13F2D0
KEY_EVENT, SCREEN_FLAGS, HOME_SCREEN = 0x4278BA, 0x4278E2, 0x403256
STOCK_GROUP2 = 0x13F5C4
FIRST_FREE_PAD, SELECT_PAD, ARM_TRIGGER, MEM_CHECK = 0x14D8EC, 0x13C426, 0x13C30E, 0x14D91E
SEL_PAD, TRIG_MODE = 0x4277D4, 0x4277C9
SCR_SELECT_PAD, SCR_RECORD, SCR_METER_AUX = 0x1F, 0x22, 0x06
KEY_PADSMPL, KEY_SHIFT_PADSMPL, KEY_ENTER, KEY_PLAY2 = 0x22, 0x122, 0xB1, 0xF2
WAIT_LEVEL = 3


def code():
    a = Asm(CODE_BASE)

    # ---------- home screen (screen 5) handler: r0.w = event ----------
    a.label('menu')
    a.push_l(6)
    a.mov_w_rr(0, 6)
    a.mov_b_rr('r6h', 'r6h'); a.bne16('done')
    a.cmp_b_imm(0x00, 'r6l'); a.beq16('enter')
    a.cmp_b_imm(0x05, 'r6l'); a.beq16('draw')
    a.cmp_b_imm(0x09, 'r6l'); a.beq16('key')
    a.bra16('done')

    a.label('enter')                              # stock screen-5 duties
    a.mov_w_imm(SCREEN, 0); a.mov_w_to_abs(0, HOME_SCREEN)
    a.jsr(0x120332)
    a.mov_w_imm(0, 1); a.mov_w_imm(9, 8); a.mov_w_imm(7, 0)
    a.jsr(0x11F2AE)
    a.label('draw')
    a.jsr(API_CLS)
    for row, lbl in ((0, 's_title'), (2, 's_l1'), (3, 's_l2'), (6, 's_l4'), (5, 's_start')):
        a.mov_b_imm(row, 'r0h'); a.mov_b_imm(0, 'r0l'); a.jsr(API_CURSOR)
        a.mov_l_imm(lbl, 0); a.jsr(API_PUTS)          # 'Start: ' last so the mode prints after it
    a.mov_b_from_abs(TRIG_MODE, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('draw_wait')
    a.mov_l_imm('s_instant', 0); a.bra('draw_mode')
    a.label('draw_wait'); a.mov_l_imm('s_wait', 0)
    a.label('draw_mode'); a.jsr(API_PUTS)            # cursor already after "Start: "
    a.bra16('done')

    a.label('key')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(KEY_ENTER, 0); a.beq('toggle')
    a.cmp_w_imm(KEY_PLAY2, 0); a.bne16('done')    # stock: -> AUX meter
    a.mov_w_imm(SCR_METER_AUX, 0); a.jsr(GOTO_SCREEN); a.bra16('done')
    a.label('toggle')
    a.mov_b_from_abs(TRIG_MODE, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('to_instant')
    a.mov_b_imm(WAIT_LEVEL, 'r0l'); a.bra('store_mode')
    a.label('to_instant'); a.mov_b_imm(0, 'r0l')
    a.label('store_mode'); a.mov_b_to_abs('r0l', TRIG_MODE)
    a.bra16('draw')

    a.label('done')
    a.pop_l(6)
    a.rts()

    # ---------- key group 2 wrapper (BANK/CLIP/PAD SAMPLING/HOLD) ----------
    a.label('g2')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(KEY_PADSMPL, 0); a.beq('one_press')
    a.cmp_w_imm(KEY_SHIFT_PADSMPL, 0); a.beq('shifted')
    a.jmp(STOCK_GROUP2)

    a.label('one_press')
    a.mov_w_from_abs(SCREEN_FLAGS, 0); a.btst_imm(7, 'r0l'); a.bne('ret0')   # same guard as stock
    a.jsr(FIRST_FREE_PAD)
    a.cmp_w_imm(0xFFFF, 0); a.beq('stock_menus')
    a.mov_b_to_abs('r0l', SEL_PAD)
    a.jsr(SELECT_PAD)
    a.jsr(ARM_TRIGGER)
    a.mov_w_imm(1, 0); a.jsr(MEM_CHECK)
    a.mov_w_rr(0, 0); a.beq('ret1')                # not enough memory: stock already showed a message
    a.mov_w_imm(SCR_RECORD, 0); a.jsr(GOTO_SCREEN)
    a.jsr(KEYMASK_SAMPLING)
    a.bra('ret1')

    a.label('shifted')
    a.mov_w_from_abs(SCREEN_FLAGS, 0); a.btst_imm(7, 'r0l'); a.bne('ret0')
    a.label('stock_menus')
    a.mov_w_imm(SCR_SELECT_PAD, 0); a.jsr(GOTO_SCREEN)
    a.label('ret1'); a.mov_w_imm(1, 0); a.rts()
    a.label('ret0'); a.mov_w_imm(0, 0); a.rts()

    # ---------- strings ----------
    a.label('s_title'); a.string('JSW LOOPER v0.4')
    a.label('s_l1'); a.string('PAD SMPL: rec->pad')
    a.label('s_l2'); a.string('+SHIFT  : smpl menu')
    a.label('s_start'); a.string('Start: ')
    a.label('s_l4'); a.string('ENTER: toggle start')
    a.label('s_instant'); a.string('INSTANT')
    a.label('s_wait'); a.string('WAIT SIGNAL')
    return a.assemble(), a.labels


def main(raw, outdir):
    img = bytearray(open(raw, 'rb').read()[:SIZE]); check(img)
    assert struct.unpack('>H', img[0x0E:0x10])[0] == 1050
    o = 0x626BE; assert img[o:o + 16] == b'System Edit Menu'; img[o:o + 16] = b'JunksmithWizard!'
    blob, labels = code()
    off = CODE_BASE - 0x100000
    assert not any(img[off:off + len(blob)]), 'target flash not empty'
    img[off:off + len(blob)] = blob
    # screen 5 -> our menu, page 0 (v0.3 lesson)
    e = SCREEN_TABLE - 0x100000 + 22 * SCREEN
    flags, handler, params, page, x, parent = struct.unpack('>IIIIIH', img[e:e + 22])
    assert handler == 0x13D224 and page == 0x1665AA
    img[e:e + 22] = struct.pack('>IIIIIH', flags, labels['menu'], params, 0, x, parent)
    # key group 2 -> our wrapper
    k = KEYGROUP_TABLE - 0x100000 + 4 * 2
    assert struct.unpack('>I', img[k:k + 4])[0] == STOCK_GROUP2
    img[k:k + 4] = struct.pack('>I', labels['g2'])
    v = struct.pack('>H', VERSION)
    for o in VER_HDR: img[o:o + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_v04.bin'), 'wb').write(img)
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(struct.pack('>II', 0x100000, 0x1C0000) + img)
    print('v0.4 built: %d bytes at 0x%X (menu 0x%X, g2 0x%X), version %d'
          % (len(blob), CODE_BASE, labels['menu'], labels['g2'], VERSION))


if __name__ == '__main__':
    main(*sys.argv[1:3])
