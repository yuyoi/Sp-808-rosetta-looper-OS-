"""JSW v0.5b (v0.5 + screen-5 params=-1 so CURSOR no longer changes LCD contrast): mode buttons + menus (4-row LCD), MPC sample-modes submenu.

Built on v0.4 (proven on hw: home screen 5, PAD SAMPLING one-press into next free pad).
- LCD is 4 text rows (rows 0-3), ~22 cols. v0.4 drew on rows 5/6 (off screen) - fixed.
- Key group 8 (SONG/SYSTEM/SAMPLE, table 0x166C04, stock 0x13F44E) -> wrapper:
    SONG = Looper page, SAMPLE = MPC page, SYSTEM = Keyboard page, SHIFT+SYSTEM = stock system menu (0x41).
- Screen 5 = our page engine: HOME (all modes list) / MPC / LOOPER / KEYS / SAMPLE MODES.
    CURSOR up/down move, ENTER select, EXIT back (screen 5 parent is 0xFFFF so EXIT reaches us).
- PAD SAMPLING: sample mode NEXT FREE = v0.4 one-press; CLASSIC (and TAP/HOLD until v0.6) = stock flow.
  SHIFT+PAD SAMPLING = stock flow.
- Our RAM: 16 bytes at the very end of the OS zero-initialised BSS (0x42BFF0..), guarded by a canary.
  Canary 0 = first boot (BSS was zeroed) -> init. Canary wrong = something else wrote here -> "RAM!" on HOME.

usage: python -I build_v05.py raw.bin outdir
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm
from make_prg import check, SIZE, VER_HDR, VER_CODE

VERSION = 1056
CODE_BASE = 0x16B000
SCREEN_TABLE, SCREEN = 0x166D74, 5
KEYGROUP_TABLE = 0x166BE4
API_CLS, API_CURSOR, API_PUTS = 0x4003D4, 0x400434, 0x400440
GOTO_SCREEN, KEYMASK_SAMPLING = 0x13FC0E, 0x13F2D0
KEY_EVENT, SCREEN_FLAGS, HOME_SCREEN, CUR_SCREEN = 0x4278BA, 0x4278E2, 0x403256, 0x4278FC
STOCK_G2, STOCK_G8 = 0x13F5C4, 0x13F44E
FIRST_FREE_PAD, SELECT_PAD, ARM_TRIGGER, MEM_CHECK = 0x14D8EC, 0x13C426, 0x13C30E, 0x14D91E
SEL_PAD, TRIG_MODE = 0x4277D4, 0x4277C9
SCR_SELECT_PAD, SCR_RECORD, SCR_SYSTEM = 0x1F, 0x22, 0x41
K_UP, K_DOWN, K_LEFT, K_RIGHT, K_EXIT, K_ENTER = 0x70, 0x71, 0x72, 0x73, 0xB0, 0xB1
K_SONG, K_SYSTEM, K_SAMPLE, K_SH_SYSTEM = 0x80, 0x81, 0x82, 0x181
K_PADSMPL, K_SH_PADSMPL = 0x22, 0x122
WAIT_LEVEL = 3

# our RAM (end of BSS 0x403000..0x42BFFC)
CANARY, PAGE, CUR, SMODE, WARN = 0x42BFF0, 0x42BFF4, 0x42BFF5, 0x42BFF6, 0x42BFF7
MAGIC = 0x4A535721            # 'JSW!'
P_HOME, P_MPC, P_LOOP, P_KEYS, P_SMODES = 0, 1, 2, 3, 4

HOME_ITEMS = ['MPC      [SAMPLE]', 'LOOPER   [SONG]', 'KEYS     [SYSTEM]', 'SYSTEM   [SH+SYS]']
SMODE_NAMES = ['NEXT FREE', 'CLASSIC MPC', 'TAP   (soon)', 'HOLD  (soon)']


def build():
    a = Asm(CODE_BASE)
    n = [0]
    def uniq(p): n[0] += 1; return '%s_%d' % (p, n[0])
    def cursor(row, col=0): a.mov_b_imm(row, 'r0h'); a.mov_b_imm(col, 'r0l'); a.jsr(API_CURSOR)
    def puts(lbl): a.mov_l_imm(lbl, 0); a.jsr(API_PUTS)
    def prow(row, lbl): cursor(row); puts(lbl)
    def select_puts(var, lbls):           # print lbls[value of byte var]; last label = default
        done = uniq('sel')
        a.mov_b_from_abs(var, 'r0l')
        for i, l in enumerate(lbls[:-1]):
            nxt = uniq('nx'); a.cmp_b_imm(i, 'r0l'); a.bne(nxt); a.mov_l_imm(l, 0); a.bra(done); a.label(nxt)
        a.mov_l_imm(lbls[-1], 0)
        a.label(done); a.jsr(API_PUTS)
    def draw_list(labels):
        for i, l in enumerate(labels):
            cursor(i)
            m, p = uniq('m'), uniq('p')
            a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(i, 'r0l'); a.bne(m)
            a.mov_l_imm('s_arrow', 0); a.bra(p)
            a.label(m); a.mov_l_imm('s_blank', 0)
            a.label(p); a.jsr(API_PUTS)
            puts(l)
    def set_byte(var, val): a.mov_b_imm(val, 'r0l'); a.mov_b_to_abs('r0l', var)
    def move_cursor(maxv, redraw):            # r5 = key; handles UP/DOWN on CUR (0..maxv)
        nd, nu = uniq('nd'), uniq('nu')
        a.cmp_w_imm(K_UP, 5); a.bne(nu)
        a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16(redraw)
        a.add_b_imm(0xFF, 'r0l'); a.mov_b_to_abs('r0l', CUR); a.bra16(redraw)
        a.label(nu)
        a.cmp_w_imm(K_DOWN, 5); a.bne(nd)
        a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(maxv, 'r0l'); a.beq16(redraw)
        a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', CUR); a.bra16(redraw)
        a.label(nd)

    # ================= screen 5 handler =================
    a.label('menu')
    a.push_l(6); a.push_l(5)
    a.mov_w_rr(0, 6)
    a.mov_b_rr('r6h', 'r6h'); a.bne16('done')
    a.cmp_b_imm(0x00, 'r6l'); a.beq16('enter')
    a.cmp_b_imm(0x05, 'r6l'); a.beq16('redraw')
    a.cmp_b_imm(0x09, 'r6l'); a.beq16('key')
    a.bra16('done')

    a.label('enter')                              # stock screen-5 duties
    a.mov_w_imm(SCREEN, 0); a.mov_w_to_abs(0, HOME_SCREEN)
    a.jsr(0x120332)
    a.mov_w_imm(0, 1); a.mov_w_imm(9, 8); a.mov_w_imm(7, 0)
    a.jsr(0x11F2AE)
    a.bsr16('ramcheck')
    a.bra16('redraw')

    a.label('key')
    a.mov_w_from_abs(KEY_EVENT, 5)
    a.mov_b_from_abs(PAGE, 'r0l')
    a.cmp_b_imm(P_HOME, 'r0l'); a.beq16('k_home')
    a.cmp_b_imm(P_MPC, 'r0l'); a.beq16('k_mpc')
    a.cmp_b_imm(P_SMODES, 'r0l'); a.beq16('k_smodes')
    a.bra16('k_other')

    a.label('k_home')
    move_cursor(3, 'redraw')
    a.cmp_w_imm(K_ENTER, 5); a.bne16('done')
    a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(3, 'r0l'); a.beq16('goto_sys')
    a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', PAGE); a.bra16('redraw')   # 0->MPC 1->LOOP 2->KEYS
    a.label('goto_sys'); a.mov_w_imm(SCR_SYSTEM, 0); a.jsr(GOTO_SCREEN); a.bra16('done')

    a.label('k_mpc')
    a.cmp_w_imm(K_ENTER, 5); a.bne('km_lr')
    a.mov_b_from_abs(SMODE, 'r0l'); a.mov_b_to_abs('r0l', CUR); set_byte(PAGE, P_SMODES); a.bra16('redraw')
    a.label('km_lr')
    a.cmp_w_imm(K_LEFT, 5); a.beq('km_tog')
    a.cmp_w_imm(K_RIGHT, 5); a.bne('km_exit')
    a.label('km_tog')
    a.mov_b_from_abs(TRIG_MODE, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('km_inst')
    a.mov_b_imm(WAIT_LEVEL, 'r0l'); a.bra('km_st')
    a.label('km_inst'); a.mov_b_imm(0, 'r0l')
    a.label('km_st'); a.mov_b_to_abs('r0l', TRIG_MODE); a.bra16('redraw')
    a.label('km_exit')
    a.cmp_w_imm(K_EXIT, 5); a.bne16('done')
    set_byte(PAGE, P_HOME); set_byte(CUR, 0); a.bra16('redraw')

    a.label('k_smodes')
    move_cursor(3, 'redraw')
    a.cmp_w_imm(K_ENTER, 5); a.bne('ks_exit')
    a.mov_b_from_abs(CUR, 'r0l'); a.mov_b_to_abs('r0l', SMODE); set_byte(PAGE, P_MPC); a.bra16('redraw')
    a.label('ks_exit')
    a.cmp_w_imm(K_EXIT, 5); a.bne16('done')
    set_byte(PAGE, P_MPC); a.bra16('redraw')

    a.label('k_other')                            # LOOPER / KEYS placeholders: EXIT -> HOME on that item
    a.cmp_w_imm(K_EXIT, 5); a.bne16('done')
    a.mov_b_from_abs(PAGE, 'r0l'); a.add_b_imm(0xFF, 'r0l'); a.mov_b_to_abs('r0l', CUR)
    set_byte(PAGE, P_HOME)

    a.label('redraw')
    a.bsr16('draw')
    a.label('done')
    a.pop_l(5); a.pop_l(6)
    a.rts()

    # ================= draw current page =================
    a.label('draw')
    a.jsr(API_CLS)
    a.mov_b_from_abs(PAGE, 'r0l')
    a.cmp_b_imm(P_MPC, 'r0l'); a.beq16('d_mpc')
    a.cmp_b_imm(P_LOOP, 'r0l'); a.beq16('d_loop')
    a.cmp_b_imm(P_KEYS, 'r0l'); a.beq16('d_keys')
    a.cmp_b_imm(P_SMODES, 'r0l'); a.beq16('d_smodes')
    # HOME
    draw_list(['h%d' % i for i in range(4)])
    a.mov_b_from_abs(WARN, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq('d_rts')
    cursor(0, 18); puts('s_ramwarn')
    a.label('d_rts'); a.rts()
    a.label('d_mpc')
    prow(0, 's_mpc')
    cursor(1); puts('s_rec'); select_puts(SMODE, ['sm%d' % i for i in range(4)])
    cursor(2); puts('s_start'); select_puts(TRIG_MODE, ['s_instant', 's_wait'])
    prow(3, 's_mpchelp')
    a.rts()
    a.label('d_loop')
    prow(0, 's_looper'); prow(2, 's_soon'); prow(3, 's_exithelp')
    a.rts()
    a.label('d_keys')
    prow(0, 's_keys'); prow(2, 's_soon'); prow(3, 's_exithelp')
    a.rts()
    a.label('d_smodes')
    draw_list(['sm%d' % i for i in range(4)])
    a.rts()

    # ================= RAM canary =================
    a.label('ramcheck')
    a.mov_l_from_abs(CANARY, 0); a.cmp_l_imm(MAGIC, 0); a.beq('rc_ok')
    a.cmp_l_imm(0, 0); a.beq('rc_init')
    set_byte(WARN, 1)                         # something else wrote our RAM
    set_byte(PAGE, 0); set_byte(CUR, 0); set_byte(SMODE, 0)
    a.label('rc_init')
    a.mov_l_imm(MAGIC, 0); a.mov_l_to_abs(0, CANARY)
    a.label('rc_ok'); a.rts()

    # ================= key group 8: SONG / SYSTEM / SAMPLE =================
    a.label('g8')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(K_SONG, 0); a.beq('g8_loop')
    a.cmp_w_imm(K_SAMPLE, 0); a.beq('g8_mpc')
    a.cmp_w_imm(K_SYSTEM, 0); a.beq('g8_keys')
    a.cmp_w_imm(K_SH_SYSTEM, 0); a.beq('g8_sys')
    a.jmp(STOCK_G8)
    a.label('g8_loop'); a.mov_b_imm(P_LOOP, 'r0l'); a.bra('g8_set')
    a.label('g8_mpc'); a.mov_b_imm(P_MPC, 'r0l'); a.bra('g8_set')
    a.label('g8_keys'); a.mov_b_imm(P_KEYS, 'r0l')
    a.label('g8_set'); a.mov_b_to_abs('r0l', PAGE)
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.bne('g8_go5')
    a.bsr16('draw'); a.bra('g8_ret1')
    a.label('g8_go5'); a.mov_w_imm(SCREEN, 0); a.jsr(GOTO_SCREEN); a.bra('g8_ret1')
    a.label('g8_sys'); a.mov_w_imm(SCR_SYSTEM, 0); a.jsr(GOTO_SCREEN)
    a.label('g8_ret1'); a.mov_w_imm(1, 0); a.rts()

    # ================= key group 2: PAD SAMPLING =================
    a.label('g2')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(K_PADSMPL, 0); a.beq('one_press')
    a.cmp_w_imm(K_SH_PADSMPL, 0); a.beq('shifted')
    a.jmp(STOCK_G2)
    a.label('one_press')
    a.mov_w_from_abs(SCREEN_FLAGS, 0); a.btst_imm(7, 'r0l'); a.bne16('ret0')
    a.mov_b_from_abs(SMODE, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('stock_menus')   # only NEXT FREE is one-press
    a.jsr(FIRST_FREE_PAD)
    a.cmp_w_imm(0xFFFF, 0); a.beq('stock_menus')
    a.mov_b_to_abs('r0l', SEL_PAD)
    a.jsr(SELECT_PAD)
    a.jsr(ARM_TRIGGER)
    a.mov_w_imm(1, 0); a.jsr(MEM_CHECK)
    a.mov_w_rr(0, 0); a.beq('ret1')
    a.mov_w_imm(SCR_RECORD, 0); a.jsr(GOTO_SCREEN)
    a.jsr(KEYMASK_SAMPLING)
    a.bra('ret1')
    a.label('shifted')
    a.mov_w_from_abs(SCREEN_FLAGS, 0); a.btst_imm(7, 'r0l'); a.bne('ret0')
    a.label('stock_menus')
    a.mov_w_imm(SCR_SELECT_PAD, 0); a.jsr(GOTO_SCREEN)
    a.label('ret1'); a.mov_w_imm(1, 0); a.rts()
    a.label('ret0'); a.mov_w_imm(0, 0); a.rts()

    # ================= strings =================
    for i, s in enumerate(HOME_ITEMS): a.label('h%d' % i); a.string(s)
    for i, s in enumerate(SMODE_NAMES): a.label('sm%d' % i); a.string(s)
    for lbl, s in (('s_arrow', '> '), ('s_blank', '  '), ('s_ramwarn', 'RAM!'),
                   ('s_mpc', 'MPC MODE'), ('s_rec', 'Rec  : '), ('s_start', 'Start: '),
                   ('s_instant', 'INSTANT'), ('s_wait', 'WAIT SIGNAL'), ('s_mpchelp', 'ENTER:mode </>:start'),
                   ('s_looper', 'LOOPER MODE'), ('s_keys', 'KEYBOARD MODE'),
                   ('s_soon', 'coming soon (v0.5b)'), ('s_exithelp', 'EXIT: all modes')):
        a.label(lbl); a.string(s)
    return a.assemble(), a.labels


def main(raw, outdir):
    img = bytearray(open(raw, 'rb').read()[:SIZE]); check(img)
    assert struct.unpack('>H', img[0x0E:0x10])[0] == 1050
    o = 0x626BE; assert img[o:o + 16] == b'System Edit Menu'; img[o:o + 16] = b'JunksmithWizard!'
    blob, labels = build()
    off = CODE_BASE - 0x100000
    assert not any(img[off:off + len(blob)]), 'target flash not empty'
    img[off:off + len(blob)] = blob
    e = SCREEN_TABLE - 0x100000 + 22 * SCREEN
    flags, handler, params, page, x, parent = struct.unpack('>IIIIIH', img[e:e + 22])
    assert handler == 0x13D224 and page == 0x1665AA and parent == 0xFFFF
    img[e:e + 22] = struct.pack('>IIIIIH', flags, labels['menu'], 0xFFFFFFFF, 0, x, parent)   # params -1: no default table (it mapped CURSOR up/down to LCD contrast)
    for grp, stock, lbl in ((2, STOCK_G2, 'g2'), (8, STOCK_G8, 'g8')):
        k = KEYGROUP_TABLE - 0x100000 + 4 * grp
        assert struct.unpack('>I', img[k:k + 4])[0] == stock
        img[k:k + 4] = struct.pack('>I', labels[lbl])
    v = struct.pack('>H', VERSION)
    for o in VER_HDR: img[o:o + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_v05b.bin'), 'wb').write(img)
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(struct.pack('>II', 0x100000, 0x1C0000) + img)
    print('v0.5b built: %d bytes at 0x%X, version %d' % (len(blob), CODE_BASE, VERSION))
    for k in ('menu', 'draw', 'ramcheck', 'g8', 'g2'): print('  %-9s 0x%X' % (k, labels[k]))


if __name__ == '__main__':
    main(*sys.argv[1:3])
