"""JSW v0.6f = v0.6e + our RAM moved out of the stock event pool.

Bug (user, v0.6e on hw): still "goes back to mode select" after a take.
Cause: since v0.4 our 12 bytes lived at 0x42BFF0 ("end of BSS"). But the stock pool at 0x427A6E is
2000 records x 40 bytes (init 0x143566: count 0x7D0 at 0x427A4A, prev/next word links, type byte 0x10 = free),
so it runs to 0x43B2EE, way past the BSS clear (0x42BFFF). Our bytes sat inside records #444/#445:
the OS overwrote our canary (-> ramcheck reset: HOME page = "mode select", SMODE = NEXT FREE) and we
overwrote record #445's prev/next links and type (corrupt free list -> loops / hangs).
Fix: our block moves to 0x43C000. The last OS variable is 0x43BAFE; nothing in the OS references
0x43BB00..0x43FFF7 (the PRG loader starts at 0x43FFF8, sample RAM at 0x440000), so it is not the stack top.
That RAM is not cleared at boot, so the boot-animation player (runs once per power-on) writes the canary
and zeroes our variables first. ramcheck stays as a tripwire.

v0.6e notes follow.
JSW v0.6e = v0.6d + second-take fix.

Bug (user, v0.6d on hw): "only works once, then starts looping menus and never gets back to the record screen".
Cause: the record screen 0x22 enters transport mode 3 (0x1404F8(3)). The sampling-group handler 0x141232
event 2 only runs "enter sampling mode" (0x13659A: input routing, flag) while word bit 6 of 0x4277D0 is clear.
Stock 0x23 sets that bit ("take done") at its event 2 and nothing clears it on our KEEP -> screen 5 route
(stock never needs to: its 0x1F/0x20 screens call 0x13659A themselves). So take 2 started without sampling
mode and fell straight through 0x23 -> 0x20 -> our menu.
Fix: clear word bit 6 (bclr #6,@0x4277D1) at the start of every take (start_rec) and in KEEP, so every
take starts like the first one after boot. RETRY never leaves mode 3, so it was not affected.

v0.6d notes follow.
JSW v0.6d = v0.6c + CLASSIC MPC works like a real MPC (record first, pick the pad at KEEP).

CLASSIC (user, 2026-10-13: "real MPC flow"):
- PAD SAMPLING starts a take at once into the first free pad T (BANK FULL if none). Any pad / PAD SAMPLING stops.
- Result screen (stock 0x23 has already written the take into T at its event 2: 0x1229C2(T<<8|bank, &0x4277D8)):
    hit pad P  -> swap the pad entries of T and P (stock get 0x122946 / set 0x1229C2, 2 x 32 bytes on the
                  stack), then refresh like stock does after a set (0x10B8DC(0,0), 0x137BC4(1)), then KEEP.
                  P's old sample (if any) lands on T, so nothing is lost or orphaned.
    ENTER      -> KEEP on T.   EXIT -> RETRY into T.
TAP / HOLD / NEXT FREE unchanged from v0.6c (pad on the result screen = KEEP).

v0.6c notes follow.
JSW v0.6c = v0.6b (MPC flow + Roland-chan boot) + take-flow fix + no second splash.

v0.6c fixes (user, 2026-10-13: CLASSIC MPC, INSTANT, "bugs if I hit another pad before closing the result screen"):
- The user can't remember which pad started the take (never used an MPC), so in TAP / CLASSIC / NEXT FREE
  ANY pad press stops the recording. HOLD still stops on releasing the held pad.
- While our take flow runs (MSTATE == REC), pads never reach the stock pad handler:
    record screen 0x22: only the stop pad (check_stop) acts, every other pad press/release is swallowed;
    any other screen (0x23 take done, error screens): a pad press = KEEP, releases are swallowed.
- KEEP (ENTER or pad on 0x23) and the cancelled-take path restore the normal pad-play vtable
  (0x137042 -> 0x1653E8). Stock 0x23 leaves the take-preview vtable 0x166342 in place.
- Second boot splash (0x1487FE: "Groove Sampler" layout 0x1687E6 + 8-frame tile animation, ~0.7 s)
  skipped: 0x148812 becomes jsr 0x11F15C, jsr 0x4003CC, jmp 0x148886 (its two init calls are kept).
  Roland-chan's last frame stays up until the OS draws its first screen.

v0.6 notes follow.
JSW v0.6: MPC mode flow (MPC2000XL-style, see LOOPER_DESIGN.md / chat) on top of v0.5b.

v0.5b recap: screen 5 page engine (HOME / MPC / LOOPER / KEYS / SAMPLE MODES), mode buttons via
key group 8, PAD SAMPLING one-press via key group 2, screen-5 params=-1 (no contrast/encoder hijack).

New in v0.6 (MPC mode):
- PAD SAMPLING: NEXT FREE -> record into first free pad at once ("BANK FULL" if none).
                CLASSIC / TAP / HOLD -> ARM ("hit a pad"). PAD SAMPLING again = cancel arm.
- Pads (key group 1 hook, stock 0x13F3B6):
    armed + pad press        -> record into THAT pad (overwrites if used)
    TAP/HOLD + SHIFT+pad     -> record into that pad (from our screen)
    while recording (scr 0x22): TAP: same pad pressed again -> stop; HOLD: that pad released -> stop.
    Stop = rewrite the key to 0x22 (PAD SAMPLING) and let the stock record screen stop it.
- Screen 0x22 (record) wrapped too, in case it masks pads: same stop check, then stock handler.
- Screen 0x23 (stock "sample done": take already assigned to the pad by 0x13CB54/0x1229C2) wrapped:
    ENTER = KEEP  -> back to our MPC page.
    EXIT  = RETRY -> stock discard (0x14D136, 0x14D078) then re-record into the same pad.
    If stock enter-handling bails out (cancelled take -> screen 0x20, auto-trim -> 0x24) we drop our flow.
RAM (end of BSS, canary-guarded): 0x42BFF0 canary, F4 page, F5 cursor, F6 sample mode, F7 warn,
F8 mpc state (0 idle, 1 armed, 2 recording/our take), F9 rec pad, FA hold flag, FB message.

usage: python -I build_v06.py raw.bin outdir
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm
from make_prg import check, SIZE, VER_HDR, VER_CODE
import bootanim

VERSION = 1062
CODE_BASE = 0x16B000
PAD_GET, PAD_SET, PAD_SET_POST, PAD_REFRESH = 0x122946, 0x1229C2, 0x10B8DC, 0x137BC4
SMP_BANK, SMP_PAD = 0x4277C7, 0x4277C8
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

RAM_BASE = 0x43C000                         # unused RAM after the OS's last variable (0x43BAFE), see docstring
CANARY, PAGE, CUR, SMODE, WARN = RAM_BASE, RAM_BASE + 4, RAM_BASE + 5, RAM_BASE + 6, RAM_BASE + 7
MSTATE, REC_PAD, REC_HOLD, MSG = RAM_BASE + 8, RAM_BASE + 9, RAM_BASE + 10, RAM_BASE + 11
RAM_VARS = (PAGE, CUR, SMODE, WARN, MSTATE, REC_PAD, REC_HOLD, MSG)
MAGIC = 0x4A535721
P_HOME, P_MPC, P_LOOP, P_KEYS, P_SMODES = 0, 1, 2, 3, 4
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
    def draw_list(labels):
        for i, l in enumerate(labels):
            cursor(i)
            m, p = uniq('m'), uniq('p')
            a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(i, 'r0l'); a.bne(m)
            a.mov_l_imm('s_arrow', 0); a.bra(p)
            a.label(m); a.mov_l_imm('s_blank', 0)
            a.label(p); a.jsr(API_PUTS)
            puts(l)
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
    a.cmp_b_imm(P_SMODES, 'r0l'); a.beq16('k_smodes')
    a.bra16('k_other')

    a.label('k_home')
    move_cursor(3, 'redraw')
    a.cmp_w_imm(K_ENTER, 5); a.bne16('done')
    a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(3, 'r0l'); a.beq16('goto_sys')
    a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', PAGE); a.bra16('redraw')
    a.label('goto_sys'); a.mov_w_imm(SCR_SYSTEM, 0); a.jsr(GOTO_SCREEN); a.bra16('done')

    a.label('k_mpc')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.bne('km_norm')
    a.cmp_w_imm(K_EXIT, 5); a.bne16('done')              # armed: EXIT cancels
    set_byte(MSTATE, MS_IDLE); a.bra16('redraw')
    a.label('km_norm')
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
    a.cmp_b_imm(P_SMODES, 'r0l'); a.beq16('d_smodes')
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
    cursor(1); puts('s_rec'); select_puts(SMODE, ['sm%d' % i for i in range(4)])
    cursor(2); puts('s_start'); select_puts(TRIG_MODE, ['s_instant', 's_wait'])
    a.mov_b_from_abs(MSG, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('d_full')
    prow(3, 's_mpchelp'); a.rts()
    a.label('d_full'); prow(3, 's_bankfull'); a.rts()
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
    set_byte(WARN, 1)
    for v in (PAGE, CUR, SMODE, MSTATE, REC_PAD, REC_HOLD, MSG): set_byte(v, 0)
    a.label('rc_init')
    a.mov_l_imm(MAGIC, 0); a.mov_l_to_abs(0, CANARY)
    a.label('rc_ok'); a.rts()

    # ================= start recording into pad r0l (our flow) =================
    a.label('start_rec')
    a.push_l(6)
    a.bclr_abs(6, SMP_FLAGS_LO)                                 # clear stale "take done" so mode 3 re-enters sampling
    a.mov_b_rr('r0l', 'r6l')
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
    a.label('g1_take')                                       # take done (or any other screen): pad press = KEEP
    a.btst_imm(6, 'r5h'); a.bne('g1_eat')
    a.mov_b_from_abs(SMODE, 'r0l'); a.cmp_b_imm(SM_CLASSIC, 'r0l'); a.bne('g1_keep')
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCR_DONE, 0); a.bne('g1_keep')
    a.mov_b_rr('r5l', 'r0l'); a.and_w_imm(0x000F, 0)          # CLASSIC: the take goes onto the pad you hit
    a.bsr16('swap_pad')
    a.label('g1_keep')
    a.bsr16('keep')
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

    # ================= screen 0x23 (sample done) wrapper: KEEP / RETRY =================
    a.label('w23')
    a.push_l(6)
    a.mov_w_rr(0, 6)
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.bne16('w23_stock')
    a.cmp_w_imm(0x0009, 6); a.bne16('w23_ev')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(K_ENTER, 0); a.bne('w23_notkeep')
    a.bsr16('keep')
    a.pop_l(6); a.rts()
    a.label('w23_notkeep')
    a.cmp_w_imm(K_EXIT, 0); a.bne16('w23_stock')
    a.jsr(TAKE_DISCARD_A); a.jsr(TAKE_DISCARD_B)                # RETRY: stock discard ...
    a.jsr(SMPL_UNLOCK); a.jsr(SMPL_RESET)
    a.mov_b_from_abs(REC_PAD, 'r0l')                            # ... then record the same pad again
    a.bsr16('start_rec')
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

    # ================= swap pad entries: take pad T (0x4277C8) <-> pad r0l, current sampling bank =================
    a.label('swap_pad')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_b_rr('r0l', 'r6l')                                  # r6l = P
    a.mov_b_from_abs(SMP_PAD, 'r6h')                          # r6h = T
    a.cmp_b_rr('r6l', 'r6h'); a.beq16('sw_out')               # same pad: nothing to move
    a.mov_b_from_abs(SMP_BANK, 'r5l')                         # r5l = bank
    a.sub_l_imm(64, 7)                                        # sp+0 = T entry, sp+32 = P entry
    a.mov_b_rr('r6h', 'r0h'); a.mov_b_rr('r5l', 'r0l'); a.mov_l_rr(7, 1); a.jsr(PAD_GET)
    a.mov_w_rr(0, 0); a.beq('sw_free')
    a.mov_b_rr('r6l', 'r0h'); a.mov_b_rr('r5l', 'r0l'); a.mov_l_rr(7, 1); a.add_l_imm(32, 1); a.jsr(PAD_GET)
    a.mov_w_rr(0, 0); a.beq('sw_free')
    a.mov_b_rr('r6l', 'r0h'); a.mov_b_rr('r5l', 'r0l'); a.mov_l_rr(7, 1); a.jsr(PAD_SET)                    # P <- take
    a.mov_b_rr('r6h', 'r0h'); a.mov_b_rr('r5l', 'r0l'); a.mov_l_rr(7, 1); a.add_l_imm(32, 1); a.jsr(PAD_SET)  # T <- P's old
    a.mov_w_imm(0, 8); a.mov_b_imm(0, 'r0l'); a.jsr(PAD_SET_POST)                                         # as stock after a set
    a.mov_w_imm(1, 0); a.jsr(PAD_REFRESH)
    a.label('sw_free')
    a.add_l_imm(64, 7)
    a.label('sw_out')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

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
    a.cmp_w_imm(K_SONG, 0); a.beq('g8_loop')
    a.cmp_w_imm(K_SAMPLE, 0); a.beq('g8_mpc')
    a.cmp_w_imm(K_SYSTEM, 0); a.beq('g8_keys')
    a.cmp_w_imm(K_SH_SYSTEM, 0); a.beq16('g8_sys')
    a.jmp(STOCK_G8)
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
    a.mov_w_from_abs(SCREEN_FLAGS, 0); a.btst_imm(7, 'r0l'); a.bne16('ret0')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.bne('ps_notarmed')
    set_byte(MSTATE, MS_IDLE); set_byte(PAGE, P_MPC)             # cancel arm
    show_page(); a.bra16('ret1')
    a.label('ps_notarmed')
    a.mov_b_from_abs(SMODE, 'r0l'); a.cmp_b_imm(SM_NEXT, 'r0l'); a.beq('ps_free')
    a.cmp_b_imm(SM_CLASSIC, 'r0l'); a.bne('ps_arm')           # CLASSIC: record now, pick the pad at the end
    a.label('ps_free')
    a.jsr(FIRST_FREE_PAD)
    a.cmp_w_imm(0xFFFF, 0); a.beq('ps_full')
    a.bsr16('start_rec'); a.bra16('ret1')
    a.label('ps_full')
    set_byte(MSG, 1); set_byte(PAGE, P_MPC)
    show_page(); a.bra16('ret1')
    a.label('ps_arm')
    set_byte(MSTATE, MS_ARMED); set_byte(PAGE, P_MPC)
    show_page(); a.bra16('ret1')
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
                   ('s_mpc', 'MPC MODE'), ('s_rec', 'Rec  : '), ('s_start', 'Start: '),
                   ('s_instant', 'INSTANT'), ('s_wait', 'WAIT SIGNAL'), ('s_mpchelp', 'ENTER:mode </>:start'),
                   ('s_bankfull', '** BANK FULL **'),
                   ('s_armed', 'MPC  ** ARMED **'), ('s_hitpad', 'hit a pad to sample'),
                   ('s_cancel', 'PAD SMPL = cancel'),
                   ('s_looper', 'LOOPER MODE'), ('s_keys', 'KEYBOARD MODE'),
                   ('s_soon', 'coming soon (v0.6)'), ('s_exithelp', 'EXIT: all modes')):
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
    ablob, alabels = bootanim.patch(img, ANIM_BASE, ram_init)
    p = SPLASH2_AT - 0x100000
    assert bytes(img[p:p + len(SPLASH2_WAS)]) == SPLASH2_WAS, 'splash 2 code changed?'
    img[p:p + len(SPLASH2_NEW)] = SPLASH2_NEW

    v = struct.pack('>H', VERSION)
    for o in VER_HDR: img[o:o + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_v06f.bin'), 'wb').write(img)
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(struct.pack('>II', 0x100000, 0x1C0000) + img)
    print('v0.6f built: %d bytes at 0x%X + boot anim %d bytes at 0x%X, version %d'
          % (len(blob), CODE_BASE, len(ablob), ANIM_BASE, VERSION))
    for k in ('menu', 'draw', 'start_rec', 'check_stop', 'g1', 'w22', 'w23', 'keep', 'g8', 'g2'):
        print('  %-10s 0x%X' % (k, labels[k]))


if __name__ == '__main__':
    main(*sys.argv[1:3])
