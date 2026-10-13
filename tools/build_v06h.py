"""JSW v0.6h = v0.6g + MPC page rework + CLASSIC "replace" + pad-pick fix attempt + debug line.

User, v0.6g on hw (2026-10-13):
- CLASSIC: "recorded in slot 1 when I pressed 13": the take stayed on the take pad T, no swap.
- "after 1 sample it says full": the bank was already full of old test takes (BANK FULL = all 16 used).
- Menu: no ENTER -> mode list. Change Rec with </> like Start. ENTER and SAMPLE start sampling.
Changes:
- MPC page: UP/DOWN picks the Rec or Start line, </> changes it, ENTER = take (same as PAD SAMPLING).
  SAMPLE opens the MPC page from anywhere; on the MPC page it starts a take. The mode-list page is gone.
- CLASSIC = replace (user: "Replace"): the take records into the first free pad T, or pad 16 if the bank
  is full. T's 32-byte entry is saved before the take. Pad P on the result screen: P <- take,
  T <- its saved entry. P's old sample is dropped from the pad (its data stays on disk). P == T: stays on T.
  (Recording over a used pad does not delete its data: event 2 of 0x23 only rewrites the pad entry.)
- The pad hit on the result screen is caught twice over: key group 1 (g1) and the screen wrapper w23.
  The key dispatcher 0x13F2F0 skips a group handler when its bit is set in the mask 0x427906 (set by
  0x13F2E8; bit 1 = pads, set to 0x0002 at 0x13AC1C) and then sends the key to the screen as event 9.
- Debug line on the MPC page after a take: "<path> T<t0>/<t> P<p> <res>", pads 1-based.
  path G = g1, W = w23, E = ENTER. t0 = take pad when the take started, t = 0x4277C8 at the hit,
  p = pad hit. res K = done, k = done but T not restored, S = same pad, F = pad read failed,
  N = not CLASSIC, C = not on screen 0x23, - = ENTER.
- Fixes: our 4 mode keys and PAD SAMPLING are ignored while our take runs (PAD SAMPLING still reaches
  the record screen, where stock stops the take; before, it could start a second take), and
  PAD SAMPLING goes to stock on the stock sampling screens 0x1F-0x24.

Earlier notes: build_v06g.py and the docstring chain before it.
usage: python -I build_v06h.py raw.bin outdir
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm
from make_prg import check, SIZE, VER_HDR, VER_CODE
import bootanim

VERSION = 1064
CODE_BASE = 0x16B000
PAD_GET, PAD_SET, PAD_SET_POST, PAD_REFRESH = 0x122946, 0x1229C2, 0x10B8DC, 0x137BC4
SMP_BANK, SMP_PAD, CUR_BANK = 0x4277C7, 0x4277C8, 0x40323C
SMP_FLAGS_LO = 0x4277D1                     # low byte of the sampling flags word 0x4277D0 (word bit 6 = take done)
ANIM_BASE = 0x170000
PAD_NORMAL = 0x137042                       # pad vtable -> normal play (0x1653E8)
# 0x148812: jsr 0x4003D4 (clear) / mov.l #0x1687E6,er0 / jsr 0x13177C (first 2 bytes) ...
SPLASH2_AT, SPLASH2_WAS = 0x148812, bytes.fromhex('5e4003d4' '7a00001687e6' '5e13')
SPLASH2_NEW = bytes.fromhex('5e11f15c' '5e4003cc' '5a148886')   # jsr 0x11F15C, jsr 0x4003CC, jmp epilogue
SCREEN_TABLE, SCREEN = 0x166D74, 5
KEYGROUP_TABLE = 0x166BE4
API_CLS, API_CURSOR, API_PUTS = 0x4003D4, 0x400434, 0x400440
GOTO_SCREEN, SMPL_LOCK, SMPL_UNLOCK = 0x13FC0E, 0x13F2D0, 0x13F2DA
KEY_EVENT, SCREEN_FLAGS, HOME_SCREEN, CUR_SCREEN, PENDING_SCREEN = 0x4278BA, 0x4278E2, 0x403256, 0x4278FC, 0x4278FE
STOCK_G1, STOCK_G2, STOCK_G8 = 0x13F3B6, 0x13F5C4, 0x13F44E
STOCK_SCR22, STOCK_SCR23 = 0x13C938, 0x13CE1C
FIRST_FREE_PAD, SELECT_PAD, ARM_TRIGGER, MEM_CHECK = 0x14D8EC, 0x13C426, 0x13C30E, 0x14D91E
TAKE_DISCARD_A, TAKE_DISCARD_B, SMPL_RESET = 0x14D136, 0x14D078, 0x13CDEE
SEL_PAD, TRIG_MODE = 0x4277D4, 0x4277C9
SCR_SELECT_PAD, SCR_PARAMS, SCR_RECORD, SCR_DONE, SCR_AUTOTRIM, SCR_SYSTEM = 0x1F, 0x20, 0x22, 0x23, 0x24, 0x41
K_UP, K_DOWN, K_LEFT, K_RIGHT, K_EXIT, K_ENTER = 0x70, 0x71, 0x72, 0x73, 0xB0, 0xB1
K_SONG, K_SYSTEM, K_SAMPLE, K_SH_SYSTEM = 0x80, 0x81, 0x82, 0x181
K_PADSMPL, K_SH_PADSMPL = 0x22, 0x122
WAIT_LEVEL = 3
TEMP_PAD = 15                               # pad 16: CLASSIC records here when the bank is full

RAM_BASE = 0x43C000                         # unused RAM after the OS's last variable (0x43BAFE), see v0.6f
CANARY, PAGE, CUR, SMODE, WARN = RAM_BASE, RAM_BASE + 4, RAM_BASE + 5, RAM_BASE + 6, RAM_BASE + 7
MSTATE, REC_PAD, REC_HOLD, MSG = RAM_BASE + 8, RAM_BASE + 9, RAM_BASE + 10, RAM_BASE + 11
MCUR, D_PATH, D_T0, D_T, D_P, D_RES, SAVED_OK = (RAM_BASE + i for i in range(12, 19))
SAVED, DBGSTR = RAM_BASE + 0x20, RAM_BASE + 0x40          # 32-byte pad entry, 16-byte debug text
RAM_VARS = (PAGE, CUR, WARN, MSTATE, REC_PAD, REC_HOLD, MSG, MCUR, D_PATH, D_T0, D_T, D_P, D_RES, SAVED_OK)
MAGIC = 0x4A535721
P_HOME, P_MPC, P_LOOP, P_KEYS = 0, 1, 2, 3
SM_NEXT, SM_CLASSIC, SM_TAP, SM_HOLD = 0, 1, 2, 3
MS_IDLE, MS_ARMED, MS_REC = 0, 1, 2

HOME_ITEMS = ['MPC      [SAMPLE]', 'LOOPER   [SONG]', 'KEYS     [SYSTEM]', 'SYSTEM   [SH+SYS]']
SMODE_NAMES = ['NEXT FREE', 'CLASSIC MPC', 'TAP  (SH+pad)', 'HOLD (SH+pad)']


def build():
    a = Asm(CODE_BASE)
    n = [0]
    def uniq(p): n[0] += 1; return '%s_%d' % (p, n[0])
    def cursor(row, col=0): a.mov_b_imm(row, 'r0h'); a.mov_b_imm(col, 'r0l'); a.jsr(API_CURSOR)
    def puts(lbl): a.mov_l_imm(lbl, 0); a.jsr(API_PUTS)
    def prow(row, lbl): cursor(row); puts(lbl)
    def set_byte(var, val): a.mov_b_imm(val, 'r0l'); a.mov_b_to_abs('r0l', var)
    def select_puts(var, lbls):
        done = uniq('sel')
        a.mov_b_from_abs(var, 'r0l')
        for i, l in enumerate(lbls[:-1]):
            nx = uniq('nx'); a.cmp_b_imm(i, 'r0l'); a.bne(nx); a.mov_l_imm(l, 0); a.bra(done); a.label(nx)
        a.mov_l_imm(lbls[-1], 0)
        a.label(done); a.jsr(API_PUTS)
    def arrow(var, i):                     # "> " if var == i, else "  "
        m, p = uniq('m'), uniq('p')
        a.mov_b_from_abs(var, 'r0l'); a.cmp_b_imm(i, 'r0l'); a.bne(m)
        a.mov_l_imm('s_arrow', 0); a.bra(p)
        a.label(m); a.mov_l_imm('s_blank', 0)
        a.label(p); a.jsr(API_PUTS)
    def draw_list(labels):
        for i, l in enumerate(labels): cursor(i); arrow(CUR, i); puts(l)
    def move_cursor(maxv, redraw):
        nd, nu = uniq('nd'), uniq('nu')
        a.cmp_w_imm(K_UP, 5); a.bne(nu)
        a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16(redraw)
        a.add_b_imm(0xFF, 'r0l'); a.mov_b_to_abs('r0l', CUR); a.bra16(redraw)
        a.label(nu)
        a.cmp_w_imm(K_DOWN, 5); a.bne(nd)
        a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(maxv, 'r0l'); a.beq16(redraw)
        a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', CUR); a.bra16(redraw)
        a.label(nd)
    def show_page():                       # redraw if on screen 5, else go there
        g, d = uniq('go5'), uniq('shown')
        a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.bne(g)
        a.bsr16('draw'); a.bra(d)
        a.label(g); a.mov_w_imm(SCREEN, 0); a.jsr(GOTO_SCREEN)
        a.label(d)

    # ================= screen 5 handler =================
    a.label('menu')
    a.push_l(6); a.push_l(5)
    a.mov_w_rr(0, 6)
    a.mov_b_rr('r6h', 'r6h'); a.bne16('done')
    a.cmp_b_imm(0x00, 'r6l'); a.beq16('enter')
    a.cmp_b_imm(0x05, 'r6l'); a.beq16('redraw')
    a.cmp_b_imm(0x09, 'r6l'); a.beq16('key')
    a.bra16('done')

    a.label('enter')
    a.mov_w_imm(SCREEN, 0); a.mov_w_to_abs(0, HOME_SCREEN)
    a.jsr(0x120332)
    a.mov_w_imm(0, 1); a.mov_w_imm(9, 8); a.mov_w_imm(7, 0)
    a.jsr(0x11F2AE)
    a.bsr16('ramcheck')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.bne16('redraw')
    set_byte(MSTATE, MS_IDLE)                     # back home: any take flow is over
    a.bra16('redraw')

    a.label('key')
    a.mov_w_from_abs(KEY_EVENT, 5)
    set_byte(MSG, 0)
    a.mov_b_from_abs(PAGE, 'r0l')
    a.cmp_b_imm(P_HOME, 'r0l'); a.beq16('k_home')
    a.cmp_b_imm(P_MPC, 'r0l'); a.beq16('k_mpc')
    a.bra16('k_other')

    a.label('k_home')
    move_cursor(3, 'redraw')
    a.cmp_w_imm(K_ENTER, 5); a.bne16('done')
    a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(3, 'r0l'); a.beq16('goto_sys')
    a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', PAGE); a.bra16('redraw')
    a.label('goto_sys'); a.mov_w_imm(SCR_SYSTEM, 0); a.jsr(GOTO_SCREEN); a.bra16('done')

    a.label('k_mpc')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.bne('km_norm')
    a.cmp_w_imm(K_EXIT, 5); a.beq('km_disarm')            # armed: EXIT or ENTER cancels
    a.cmp_w_imm(K_ENTER, 5); a.bne16('done')
    a.label('km_disarm')
    set_byte(MSTATE, MS_IDLE); a.bra16('redraw')
    a.label('km_norm')
    a.cmp_w_imm(K_ENTER, 5); a.bne('km_up')
    a.bsr16('take_key'); a.bra16('done')                  # ENTER = PAD SAMPLING
    a.label('km_up')
    a.cmp_w_imm(K_UP, 5); a.bne('km_down')
    set_byte(MCUR, 0); a.bra16('redraw')
    a.label('km_down')
    a.cmp_w_imm(K_DOWN, 5); a.bne('km_lr')
    set_byte(MCUR, 1); a.bra16('redraw')
    a.label('km_lr')
    a.cmp_w_imm(K_LEFT, 5); a.beq('km_val')
    a.cmp_w_imm(K_RIGHT, 5); a.bne16('km_exit')
    a.label('km_val')
    a.mov_b_from_abs(MCUR, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('km_tog')
    a.mov_b_from_abs(SMODE, 'r0l')                        # Rec line: step through the 4 sample modes
    a.cmp_w_imm(K_RIGHT, 5); a.bne('km_prev')
    a.add_b_imm(1, 'r0l'); a.bra('km_wrap')
    a.label('km_prev'); a.add_b_imm(0xFF, 'r0l')
    a.label('km_wrap'); a.and_w_imm(0x0003, 0); a.mov_b_to_abs('r0l', SMODE); a.bra16('redraw')
    a.label('km_tog')                                     # Start line: INSTANT <-> WAIT SIGNAL
    a.mov_b_from_abs(TRIG_MODE, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('km_inst')
    a.mov_b_imm(WAIT_LEVEL, 'r0l'); a.bra('km_st')
    a.label('km_inst'); a.mov_b_imm(0, 'r0l')
    a.label('km_st'); a.mov_b_to_abs('r0l', TRIG_MODE); a.bra16('redraw')
    a.label('km_exit')
    a.cmp_w_imm(K_EXIT, 5); a.bne16('done')
    set_byte(PAGE, P_HOME); set_byte(CUR, 0); a.bra16('redraw')

    a.label('k_other')
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
    draw_list(['h%d' % i for i in range(4)])
    a.mov_b_from_abs(WARN, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq('d_rts')
    cursor(0, 18); puts('s_ramwarn')
    a.label('d_rts'); a.rts()
    a.label('d_mpc')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.bne('d_mpc_norm')
    prow(0, 's_armed'); prow(1, 's_hitpad')
    cursor(2); puts('s_start'); select_puts(TRIG_MODE, ['s_instant', 's_wait'])
    prow(3, 's_cancel')
    a.rts()
    a.label('d_mpc_norm')
    prow(0, 's_mpc')
    cursor(1); arrow(MCUR, 0); puts('s_rec'); select_puts(SMODE, ['sm%d' % i for i in range(4)])
    cursor(2); arrow(MCUR, 1); puts('s_start'); select_puts(TRIG_MODE, ['s_instant', 's_wait'])
    a.mov_b_from_abs(MSG, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne16('d_full')
    a.mov_b_from_abs(D_PATH, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne16('d_dbg')
    prow(3, 's_mpchelp'); a.rts()
    a.label('d_full'); prow(3, 's_bankfull'); a.rts()
    a.label('d_dbg')                                      # "G T01/01 P13 K"
    a.mov_b_to_abs('r0l', DBGSTR)
    set_byte(DBGSTR + 1, ord(' ')); set_byte(DBGSTR + 2, ord('T'))
    for src, at in ((D_T0, 3), (D_T, 6), (D_P, 10)):
        a.mov_b_from_abs(src, 'r0l'); a.bsr16('dec2')
        a.mov_b_to_abs('r0h', DBGSTR + at); a.mov_b_to_abs('r0l', DBGSTR + at + 1)
    set_byte(DBGSTR + 5, ord('/')); set_byte(DBGSTR + 8, ord(' ')); set_byte(DBGSTR + 9, ord('P'))
    set_byte(DBGSTR + 12, ord(' '))
    a.mov_b_from_abs(D_RES, 'r0l'); a.mov_b_to_abs('r0l', DBGSTR + 13)
    set_byte(DBGSTR + 14, 0)
    cursor(3); a.mov_l_imm(DBGSTR, 0); a.jsr(API_PUTS)
    a.rts()
    a.label('d_loop')
    prow(0, 's_looper'); prow(2, 's_soon'); prow(3, 's_exithelp')
    a.rts()
    a.label('d_keys')
    prow(0, 's_keys'); prow(2, 's_soon'); prow(3, 's_exithelp')
    a.rts()

    # pad index r0l (0-15) -> 1-based decimal: r0h = tens char, r0l = ones char
    a.label('dec2')
    a.add_b_imm(1, 'r0l')
    a.cmp_b_imm(10, 'r0l'); a.bcs('dec2_lo')
    a.add_b_imm(0x100 - 10, 'r0l'); a.mov_b_imm(ord('1'), 'r0h'); a.bra('dec2_o')
    a.label('dec2_lo'); a.mov_b_imm(ord('0'), 'r0h')
    a.label('dec2_o'); a.add_b_imm(ord('0'), 'r0l')
    a.rts()

    # ================= RAM canary =================
    a.label('ramcheck')
    a.mov_l_from_abs(CANARY, 0); a.cmp_l_imm(MAGIC, 0); a.beq16('rc_ok')
    a.cmp_l_imm(0, 0); a.beq16('rc_init')
    for v in RAM_VARS: set_byte(v, 0)
    set_byte(WARN, 1); set_byte(SMODE, SM_CLASSIC)
    a.label('rc_init')
    a.mov_l_imm(MAGIC, 0); a.mov_l_to_abs(0, CANARY)
    a.label('rc_ok'); a.rts()

    # ================= PAD SAMPLING / ENTER / SAMPLE on the MPC page: start a take =================
    a.label('take_key')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.bne('tk_go')
    set_byte(MSTATE, MS_IDLE); set_byte(PAGE, P_MPC)              # second press cancels the arm
    show_page(); a.rts()
    a.label('tk_go')
    a.mov_b_from_abs(SMODE, 'r0l')
    a.cmp_b_imm(SM_NEXT, 'r0l'); a.beq('tk_next')
    a.cmp_b_imm(SM_CLASSIC, 'r0l'); a.beq16('tk_classic')
    set_byte(MSTATE, MS_ARMED); set_byte(PAGE, P_MPC)             # TAP / HOLD: arm, the pad picks
    show_page(); a.rts()
    a.label('tk_next')
    a.jsr(FIRST_FREE_PAD)
    a.cmp_w_imm(0xFFFF, 0); a.beq('tk_full')
    a.bra16('start_rec')
    a.label('tk_full')
    set_byte(MSG, 1); set_byte(PAGE, P_MPC)
    show_page(); a.rts()
    a.label('tk_classic')                                         # record into T now, pick the pad at the end
    a.jsr(FIRST_FREE_PAD)
    a.cmp_w_imm(0xFFFF, 0); a.bne('tk_t')
    a.mov_w_imm(TEMP_PAD, 0)                                      # bank full: borrow pad 16
    a.label('tk_t')
    a.push_l(6)
    a.mov_b_rr('r0l', 'r6l'); a.mov_b_to_abs('r6l', D_T0)
    a.mov_b_rr('r6l', 'r0h'); a.mov_b_from_abs(CUR_BANK, 'r0l')
    a.mov_l_imm(SAVED, 1); a.jsr(PAD_GET)                         # T's entry as it is before the take
    a.mov_b_to_abs('r0l', SAVED_OK)
    a.mov_b_rr('r6l', 'r0l')
    a.pop_l(6)
    a.bra16('start_rec')

    # ================= start recording into pad r0l (our flow) =================
    a.label('start_rec')
    a.push_l(6)
    a.bclr_abs(6, SMP_FLAGS_LO)                                 # clear stale "take done" so mode 3 re-enters sampling
    a.mov_b_rr('r0l', 'r6l')
    set_byte(D_PATH, 0)                                         # new take: hide the last debug line
    a.mov_b_to_abs('r6l', REC_PAD); a.mov_b_to_abs('r6l', SEL_PAD)
    a.mov_b_from_abs(SMODE, 'r0l'); a.cmp_b_imm(SM_HOLD, 'r0l'); a.bne('sr_tap')
    a.mov_b_imm(1, 'r0l'); a.bra('sr_h')
    a.label('sr_tap'); a.mov_b_imm(0, 'r0l')
    a.label('sr_h'); a.mov_b_to_abs('r0l', REC_HOLD)
    a.jsr(SELECT_PAD)
    a.jsr(ARM_TRIGGER)
    a.mov_w_imm(1, 0); a.jsr(MEM_CHECK)
    a.mov_w_rr(0, 0); a.beq('sr_fail')
    set_byte(MSTATE, MS_REC)
    a.mov_w_imm(SCR_RECORD, 0); a.jsr(GOTO_SCREEN)
    a.jsr(SMPL_LOCK)
    a.pop_l(6); a.rts()
    a.label('sr_fail')
    set_byte(MSTATE, MS_IDLE)
    a.pop_l(6); a.rts()

    # ================= is the current key our stop? -> r0 = 1/0 =================
    a.label('check_stop')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.bne('cs_no')
    a.mov_w_from_abs(KEY_EVENT, 1)
    a.mov_b_from_abs(REC_HOLD, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq('cs_tap')
    a.mov_b_from_abs(REC_PAD, 'r0l'); a.add_b_imm(0x10, 'r0l')
    a.cmp_b_rr('r0l', 'r1l'); a.bne('cs_no')
    a.btst_imm(6, 'r1h'); a.beq('cs_no'); a.bra('cs_yes')      # HOLD: release of the held pad stops
    a.label('cs_tap')                                           # TAP / CLASSIC / NEXT FREE: ANY pad press stops
    a.mov_b_rr('r1l', 'r0l'); a.and_w_imm(0x00F0, 0); a.cmp_w_imm(0x0010, 0); a.bne('cs_no')
    a.btst_imm(6, 'r1h'); a.bne('cs_no')
    a.label('cs_yes'); a.mov_w_imm(1, 0); a.rts()
    a.label('cs_no'); a.mov_w_imm(0, 0); a.rts()

    # ================= key group 1: pads =================
    a.label('g1')
    a.push_l(5)
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.bne16('g1_notrec')
    # our take flow: pads never reach the stock handler
    a.mov_w_from_abs(KEY_EVENT, 5)
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCR_RECORD, 0); a.bne('g1_take')
    a.bsr16('check_stop')
    a.mov_w_rr(0, 0); a.beq('g1_eat')                        # recording: other pads do nothing
    a.mov_w_imm(K_PADSMPL, 0); a.mov_w_to_abs(0, KEY_EVENT)  # becomes PAD SAMPLING for the record screen
    a.mov_w_imm(0, 0); a.pop_l(5); a.rts()                   # 0 = not handled -> event 9 to screen 0x22
    a.label('g1_take')                                       # take done (or any other screen): pad press = pick + KEEP
    a.btst_imm(6, 'r5h'); a.bne('g1_eat')
    a.mov_b_rr('r5l', 'r0l'); a.and_w_imm(0x000F, 0); a.mov_b_imm(ord('G'), 'r0h')
    a.bsr16('pick')
    a.label('g1_eat')
    a.mov_w_imm(1, 0); a.pop_l(5); a.rts()
    a.label('g1_notrec')
    a.mov_w_from_abs(KEY_EVENT, 5)
    a.btst_imm(6, 'r5h'); a.bne16('g1_stock')                # releases: stock
    a.mov_w_rr(5, 0); a.and_w_imm(0x00F0, 0); a.cmp_w_imm(0x0010, 0); a.bne16('g1_stock')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.beq('g1_go')
    a.btst_imm(0, 'r5h'); a.beq16('g1_stock')                # not SHIFT
    a.mov_b_from_abs(SMODE, 'r0l'); a.cmp_b_imm(SM_TAP, 'r0l'); a.bcs16('g1_stock')   # TAP(2)/HOLD(3) only
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.bne16('g1_stock')
    a.label('g1_go')
    a.mov_w_rr(5, 0); a.and_w_imm(0x000F, 0)
    a.bsr16('start_rec')
    a.mov_w_imm(1, 0); a.pop_l(5); a.rts()
    a.label('g1_stock')
    a.pop_l(5); a.jmp(STOCK_G1)

    # ================= pad hit after the take: r0l = pad, r0h = path tag. Pick (CLASSIC), then KEEP =================
    a.label('pick')
    a.push_l(6)
    a.mov_b_rr('r0l', 'r6l'); a.mov_b_rr('r0h', 'r6h')
    a.mov_b_to_abs('r6h', D_PATH); a.mov_b_to_abs('r6l', D_P)
    a.mov_b_from_abs(SMP_PAD, 'r0l'); a.mov_b_to_abs('r0l', D_T)
    a.mov_b_from_abs(SMODE, 'r0l'); a.cmp_b_imm(SM_CLASSIC, 'r0l'); a.bne('pk_n')
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCR_DONE, 0); a.bne('pk_c')
    a.mov_b_rr('r6l', 'r0l'); a.bsr16('assign'); a.bra('pk_keep')
    a.label('pk_n'); set_byte(D_RES, ord('N')); a.bra('pk_keep')
    a.label('pk_c'); set_byte(D_RES, ord('C'))
    a.label('pk_keep')
    a.bsr16('keep')
    a.pop_l(6); a.rts()

    # ================= CLASSIC: pad r0l gets the take, the take pad T gets back its saved entry =================
    # stock 0x23 event 2 has already written the take into T: 0x1229C2(T<<8|bank, &0x4277D8)
    a.label('assign')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_b_rr('r0l', 'r6l')                                  # r6l = P
    a.mov_b_from_abs(SMP_PAD, 'r6h')                          # r6h = T
    a.cmp_b_rr('r6l', 'r6h'); a.bne('as_diff')
    set_byte(D_RES, ord('S')); a.bra16('as_out')              # same pad: the take stays where it is
    a.label('as_diff')
    a.mov_b_from_abs(SMP_BANK, 'r5l')                         # r5l = bank
    a.sub_l_imm(32, 7)                                        # sp+0 = the take's pad entry
    a.mov_b_rr('r6h', 'r0h'); a.mov_b_rr('r5l', 'r0l'); a.mov_l_rr(7, 1); a.jsr(PAD_GET)
    a.mov_w_rr(0, 0); a.bne('as_got')
    set_byte(D_RES, ord('F')); a.bra16('as_free')
    a.label('as_got')
    a.mov_b_rr('r6l', 'r0h'); a.mov_b_rr('r5l', 'r0l'); a.mov_l_rr(7, 1); a.jsr(PAD_SET)        # P <- take
    a.mov_b_from_abs(SAVED_OK, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('as_rest')
    a.mov_b_imm(ord('k'), 'r0l'); a.bra('as_res')
    a.label('as_rest')
    a.mov_b_rr('r6h', 'r0h'); a.mov_b_rr('r5l', 'r0l'); a.mov_l_imm(SAVED, 1); a.jsr(PAD_SET)  # T <- before the take
    a.mov_b_imm(ord('K'), 'r0l')
    a.label('as_res'); a.mov_b_to_abs('r0l', D_RES)
    a.mov_w_imm(0, 8); a.mov_b_imm(0, 'r0l'); a.jsr(PAD_SET_POST)                             # as stock after a set
    a.mov_w_imm(1, 0); a.jsr(PAD_REFRESH)
    a.label('as_free'); a.add_l_imm(32, 7)
    a.label('as_out')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

    # ================= screen 0x22 (recording) wrapper =================
    a.label('w22')
    a.push_l(6)
    a.mov_w_rr(0, 6)
    a.cmp_w_imm(0x0009, 6); a.bne('w22_stock')
    a.bsr16('check_stop')
    a.mov_w_rr(0, 0); a.beq('w22_stock')
    a.mov_w_imm(K_PADSMPL, 0); a.mov_w_to_abs(0, KEY_EVENT)
    a.label('w22_stock')
    a.mov_w_rr(6, 0); a.pop_l(6); a.jmp(STOCK_SCR22)

    # ================= screen 0x23 (sample done) wrapper: KEEP / RETRY / pad pick =================
    a.label('w23')
    a.push_l(6)
    a.mov_w_rr(0, 6)
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.bne16('w23_stock')
    a.cmp_w_imm(0x0009, 6); a.bne16('w23_ev')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(K_ENTER, 0); a.bne('w23_notkeep')
    set_byte(D_PATH, ord('E')); set_byte(D_RES, ord('-'))       # ENTER: keep on the take pad
    a.mov_b_from_abs(SMP_PAD, 'r0l'); a.mov_b_to_abs('r0l', D_T); a.mov_b_to_abs('r0l', D_P)
    a.bsr16('keep')
    a.pop_l(6); a.rts()
    a.label('w23_notkeep')
    a.cmp_w_imm(K_EXIT, 0); a.bne('w23_pad')
    a.jsr(TAKE_DISCARD_A); a.jsr(TAKE_DISCARD_B)                # RETRY: stock discard ...
    a.jsr(SMPL_UNLOCK); a.jsr(SMPL_RESET)
    a.mov_b_from_abs(REC_PAD, 'r0l')                            # ... then record the same pad again
    a.bsr16('start_rec')
    a.pop_l(6); a.rts()
    a.label('w23_pad')                                          # pads land here if the screen masks key group 1
    a.mov_w_rr(0, 1); a.and_w_imm(0x00F0, 0); a.cmp_w_imm(0x0010, 0); a.bne16('w23_stock')
    a.btst_imm(6, 'r1h'); a.bne('w23_ret')                      # release: swallow
    a.mov_b_rr('r1l', 'r0l'); a.and_w_imm(0x000F, 0); a.mov_b_imm(ord('W'), 'r0h')
    a.bsr16('pick')
    a.label('w23_ret')
    a.pop_l(6); a.rts()
    a.label('w23_ev')
    a.cmp_w_imm(0x0000, 6); a.bne('w23_stock')
    a.mov_w_rr(6, 0); a.jsr(STOCK_SCR23)                        # stock enter, then see where it went
    a.mov_w_from_abs(PENDING_SCREEN, 0); a.and_w_imm(0x7FFF, 0)
    a.cmp_w_imm(SCR_PARAMS, 0); a.beq('w23_cancelled')
    a.cmp_w_imm(SCR_AUTOTRIM, 0); a.bne('w23_out')
    set_byte(MSTATE, MS_IDLE)                                   # auto trim/divide: leave it to stock
    a.bra('w23_out')
    a.label('w23_cancelled')                                    # empty take: home instead of stock params
    set_byte(MSTATE, MS_IDLE)
    a.jsr(SMPL_UNLOCK)
    a.jsr(PAD_NORMAL)
    a.mov_w_imm(SCREEN, 0); a.jsr(GOTO_SCREEN)
    a.label('w23_out')
    a.pop_l(6); a.rts()
    a.label('w23_stock')
    a.mov_w_rr(6, 0); a.pop_l(6); a.jmp(STOCK_SCR23)

    # ================= KEEP the take: back to the MPC page with normal pad play =================
    a.label('keep')
    a.jsr(SMPL_UNLOCK)
    a.jsr(PAD_NORMAL)
    a.bclr_abs(6, SMP_FLAGS_LO)                                 # take flow over: clear "take done"
    set_byte(MSTATE, MS_IDLE); set_byte(PAGE, P_MPC)
    a.mov_w_imm(SCREEN, 0); a.jsr(GOTO_SCREEN)
    a.rts()

    # ================= key group 8: SONG / SYSTEM / SAMPLE =================
    a.label('g8')
    a.mov_w_from_abs(KEY_EVENT, 0)
    for k in (K_SONG, K_SAMPLE, K_SYSTEM, K_SH_SYSTEM):
        a.cmp_w_imm(k, 0); a.beq('g8_ours')
    a.jmp(STOCK_G8)
    a.label('g8_ours')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.beq16('g8_ret1')   # our take runs: ignore
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(K_SONG, 0); a.beq('g8_loop')
    a.cmp_w_imm(K_SYSTEM, 0); a.beq('g8_keys')
    a.cmp_w_imm(K_SH_SYSTEM, 0); a.beq16('g8_sys')
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.bne('g8_mpc')         # SAMPLE ...
    a.mov_b_from_abs(PAGE, 'r0l'); a.cmp_b_imm(P_MPC, 'r0l'); a.bne('g8_mpc')
    a.bsr16('take_key'); a.bra16('g8_ret1')                                          # ... on the MPC page = take
    a.label('g8_loop'); a.mov_b_imm(P_LOOP, 'r0l'); a.bra('g8_set')
    a.label('g8_mpc'); a.mov_b_imm(P_MPC, 'r0l'); a.bra('g8_set')
    a.label('g8_keys'); a.mov_b_imm(P_KEYS, 'r0l')
    a.label('g8_set'); a.mov_b_to_abs('r0l', PAGE)
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.bne('g8_show')
    set_byte(MSTATE, MS_IDLE)
    a.label('g8_show')
    show_page()
    a.bra('g8_ret1')
    a.label('g8_sys'); a.mov_w_imm(SCR_SYSTEM, 0); a.jsr(GOTO_SCREEN)
    a.label('g8_ret1'); a.mov_w_imm(1, 0); a.rts()

    # ================= key group 2: PAD SAMPLING =================
    a.label('g2')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(K_PADSMPL, 0); a.beq('ps_plain')
    a.cmp_w_imm(K_SH_PADSMPL, 0); a.beq16('ps_shift')
    a.jmp(STOCK_G2)
    a.label('ps_plain')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.beq16('ret0')     # our take: the screen decides
    a.mov_w_from_abs(SCREEN_FLAGS, 0); a.btst_imm(7, 'r0l'); a.bne16('ret0')
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCR_SELECT_PAD, 0); a.bcs('ps_ok')
    a.cmp_w_imm(SCR_AUTOTRIM + 1, 0); a.bcs16('ret0')                                # 0x1F..0x24: stock sampling
    a.label('ps_ok')
    a.bsr16('take_key'); a.bra16('ret1')
    a.label('ps_shift')
    set_byte(MSTATE, MS_IDLE)                                     # stock flow: drop ours
    a.mov_w_from_abs(SCREEN_FLAGS, 0); a.btst_imm(7, 'r0l'); a.bne('ret0')
    a.mov_w_imm(SCR_SELECT_PAD, 0); a.jsr(GOTO_SCREEN)
    a.label('ret1'); a.mov_w_imm(1, 0); a.rts()
    a.label('ret0'); a.mov_w_imm(0, 0); a.rts()

    # ================= strings (LCD: 4 rows x ~21 cols) =================
    for i, s in enumerate(HOME_ITEMS): a.label('h%d' % i); a.string(s)
    for i, s in enumerate(SMODE_NAMES): a.label('sm%d' % i); a.string(s)
    for lbl, s in (('s_arrow', '> '), ('s_blank', '  '), ('s_ramwarn', 'RAM!'),
                   ('s_mpc', 'MPC MODE'), ('s_rec', 'Rec: '), ('s_start', 'Start: '),
                   ('s_instant', 'INSTANT'), ('s_wait', 'WAIT SIGNAL'), ('s_mpchelp', 'ENTER/SAMPLE: record'),
                   ('s_bankfull', '** BANK FULL **'),
                   ('s_armed', 'MPC  ** ARMED **'), ('s_hitpad', 'hit a pad to sample'),
                   ('s_cancel', 'EXIT = cancel'),
                   ('s_looper', 'LOOPER MODE'), ('s_keys', 'KEYBOARD MODE'),
                   ('s_soon', 'coming soon'), ('s_exithelp', 'EXIT: all modes')):
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

    def patch_screen(idx, want_handler, new_handler, params=None, page=None):
        e = SCREEN_TABLE - 0x100000 + 22 * idx
        fl, h, pa, pg, x, par = struct.unpack('>IIIIIH', img[e:e + 22])
        assert h == want_handler, 'screen %x handler %x' % (idx, h)
        img[e:e + 22] = struct.pack('>IIIIIH', fl, new_handler,
                                    pa if params is None else params, pg if page is None else page, x, par)
    patch_screen(SCREEN, 0x13D224, labels['menu'], params=0xFFFFFFFF, page=0)
    patch_screen(SCR_RECORD, STOCK_SCR22, labels['w22'])
    patch_screen(SCR_DONE, STOCK_SCR23, labels['w23'])
    for grp, stock, lbl in ((1, STOCK_G1, 'g1'), (2, STOCK_G2, 'g2'), (8, STOCK_G8, 'g8')):
        k = KEYGROUP_TABLE - 0x100000 + 4 * grp
        assert struct.unpack('>I', img[k:k + 4])[0] == stock
        img[k:k + 4] = struct.pack('>I', labels[lbl])
    assert CODE_BASE + len(blob) < ANIM_BASE
    def ram_init(a):                        # once per power-on, before the animation
        a.mov_l_imm(MAGIC, 0); a.mov_l_to_abs(0, CANARY)
        a.mov_b_imm(0, 'r0l')
        for v in RAM_VARS: a.mov_b_to_abs('r0l', v)
        a.mov_b_imm(SM_CLASSIC, 'r0l'); a.mov_b_to_abs('r0l', SMODE)
    ablob, alabels = bootanim.patch(img, ANIM_BASE, ram_init)
    p = SPLASH2_AT - 0x100000
    assert bytes(img[p:p + len(SPLASH2_WAS)]) == SPLASH2_WAS, 'splash 2 code changed?'
    img[p:p + len(SPLASH2_NEW)] = SPLASH2_NEW

    v = struct.pack('>H', VERSION)
    for o in VER_HDR: img[o:o + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_v06h.bin'), 'wb').write(img)
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(struct.pack('>II', 0x100000, 0x1C0000) + img)
    print('v0.6h built: %d bytes at 0x%X + boot anim %d bytes at 0x%X, version %d'
          % (len(blob), CODE_BASE, len(ablob), ANIM_BASE, VERSION))
    for k in ('menu', 'draw', 'take_key', 'start_rec', 'g1', 'pick', 'assign', 'w22', 'w23', 'keep', 'g8', 'g2'):
        print('  %-10s 0x%X' % (k, labels[k]))


if __name__ == '__main__':
    main(*sys.argv[1:3])
