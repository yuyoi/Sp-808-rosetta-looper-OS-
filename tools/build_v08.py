"""JSW v0.8 = v0.7f + our own record / take-done screens + the 7-segment line as a ticker.

Record screen (0x22, our take flow only; SHIFT+PAD SAMPLING keeps the stock screens):
- Event 5 (redraw) is ours alone. Event 6 (idle) re-does the stock logic without its drawing:
  disk full (0x14D91E(0) == 0) -> stock event 0x19, which stops the take and goes to 0x23;
  "Waiting Signal" -> "Now Sampling" when 0x4277D0 bit 2 is set and 0xFFF0DC bit 0 is clear
  (clear bit 2, text pointer 0x427910 = 0x166298). Then our redraw, at most every 100 ms.
- Timer: the boot ROM's 1 ms counter 0x40185E (8-bit timer 1 IRQ 0x93F0, which also drives the OS's
  10 ms tick 0x4278B4), started when the signal arrives. Big "MM:SS.T".
- Meter: max of the input meter records 0x427838 (L) / 0x42783E (R), byte +0 = level 0-127 (the high byte
  of the DSP peak word, written every main-loop pass by 0x13D0DE). 42 segments, 1 dB each (-42..0 dBFS),
  peak hold 1.5 s then falls 1 segment per frame.
- Remaining: free 32 KB blocks = @0x411B6E - @0x42741A - 3 (as stock 0x14D90E/0x14D948).
  Stereo 44.1 kHz = 0x8000 * 16 / 24 frames per block = 0.4953 s; mono (0x426E29 bit 1) twice that.
- Level history: the max level per frame, 128 slots; when full, pairs merge and the step doubles.
Take-done screen (0x23): event 2 stays stock (writes the take into the pad), then ours; 5 = ours; 6 = no meter.
  Shows the length, the pad and the take's level envelope.
7-segment line (LCD RAM rows 0-1): digits 0-11 are the stock time counter ("HH-MM-SS-FF", 0x1441FE).
  Boot ROM APIs: 0x4003DC set digit (r0l), 0x4003E4 write pattern er0 under mask er1 (digit++).
  Pattern = row 0 word << 16 | row 1 word, type-0 bits: row 0 a 0x2000 g 0x1000 c 0x0800 b 0x0400,
  row 1 f 0x2000 e 0x1000 d 0x0800 dp 0x0400 (other digit types are shifted by the ROM, tables 0xA226/0xA23F).
  Pages every 2.5 s on our screens: "ROSETTA OS", "VER 0.8", "<n> MB LEFT".
LOOP page: the LCD test page and the boot ROM dump are gone ("coming soon" until the looper lands).

v0.7f notes follow.
JSW v0.7f = v0.7e + pixel-exact LCD output (writes the boot ROM's LCD RAM directly) + boot sound.

The boot ROM dump (v0.7e, dump/BOOTROM.BIN) explains every LCD symptom: the blit API reads its source as
7 pixels per byte (bit 0 ignored), and the LCD RAM image at 0x40187A (34 rows x 24 bytes, 6 px per byte) is
streamed to the LCD by an interrupt. See gfxlib's docstring.
- gfx_flush packs the 128 px framebuffer into the LCD RAM (6 px per byte) at LCD x 4: no blit, exact pixels.
- Roland-chan's frames are stored in that format and copied straight in (bootanim): no more lost columns.
- Boot sound: the first idle event on screen 5 after power-on plays pad 16 (note-on 0x13735E, velocity 127),
  so whatever is recorded on pad 16 is the boot sound.
- Test page (SONG): T0 probe sheet through gfx_flush only; ENTER still saves the boot ROM dump.

v0.7e notes follow.
JSW v0.7e = v0.7d + boot ROM dump to disk (ENTER on the test page).

User, v0.7d on hw (photos 2026-10-13):
- T0 probe through the 24 px flush: every LCD pixel at x = 7 mod 8 (the last bit of each LCD byte) is missing,
  and at every strip seam 3 stray dots appear where the strip's 4th ("spill") byte lands shifted right by 5.
- T1 (22 px strips at x = 2 + 22s): the solid band breaks at every seam.
- T2: flag 0x80 is not a raw format (all six encodings garbage) - the OS's own bitmaps are compressed
  (0x1684BA: header 45 8E = 69 x 14 | 0x80, then run codes).
To stop guessing, dump the boot ROM (blit, LCD driver, every API) with Roland's own file save:
  stock "Saving..." for SP808.PRG (0x127670, from the boot combo at 0x11F264, drive 0): header at 0x440000,
  memcpy API 0x400224(er0 src, er1 dst, n on stack), then 0x10B61A(r0h 0x13, e0 0xFFFF, r0l drive,
  er1 = 11-char 8.3 name, stack: buffer, size).
ENTER on the test page saves BOOTROM.BIN (0x000000-0x0FFFFF) and BOOTRAM.BIN (0x400000-0x402FFF: the API jump
table at 0x400200 and the boot ROM's RAM), each with an 8-byte header (start, size), then prints both results.
It overwrites sample RAM at 0x440000-0x540008 like the stock PRG save does: power-cycle afterwards.

v0.7d notes follow.
JSW v0.7d = v0.7c + LCD probe test page (diagnostic).

User, v0.7c on hw (photos 2026-10-13): HOME clean. MPC page ~95%: a few strokes lost, all on the last pixel of
an LCD byte (LCD x 31, 47, 79: the final T stems of START / INSTANT, the L stem of CLASSIC). The OS only ever
calls the blit with flag 0x80 in the rows byte (0x132474: e0 = 0x14A0) on bitmaps from boot-ROM resources;
the flag-clear row format we use is only used by the boot logo (which has a seam gap too).
Test page (LOOP, dial):
  T0  probe sheet through gfx_flush (24 px strips): rows 0-7 sawtooth (pixel at (x, x mod 8)), rows 9-10 solid,
      rows 12-19 a 1 px line on every 3rd column, rows 22-31 ticks every 8 px (tall every 24) + labels
  T1  the same sheet as 22 px strips at x = 2 + 22*s (the old way)
  T2  flag-0x80 format probe: six 24x32 boxes at x = 0, 24 .. 120 (e0 = 0x18A0), digit n in box n, each in a
      different encoding: 1 page-major LSB-top, 2 page-major MSB-top, 3 column-major LSB-top,
      4 column-major MSB-top, 5 rows 3 bytes, 6 rows 4 bytes (our format)

v0.7c notes follow.
JSW v0.7c = v0.7b + LCD flush in 24 px strips at byte-aligned x (fix for the broken screens).

User, v0.7b on hw (photos 2026-10-13):
- Test page V0 (22 px strips from flash, the boot animation's format) draws right, except 1-2 dead columns
  at the strip seams x = 24, 46, 68, 90 (the boot logo has the same gap through the "O" of ROSETTA).
- The MPC page (32 px strips from RAM) is sheared diagonally: for w = 32 the boot ROM steps a longer row
  than 4 bytes. Fits "bytes per row = w/8 + 1, rounded up to even" (22 -> 4, 56 -> 8 as stock, 32 -> 6).
- Bottom line "SP FFF914 B FFF924": the stack is in on-chip RAM (0xFFFxxx), not near our RAM.
Fix (gfxlib.gfx_flush): convert the 128 px framebuffer into 6 strips of 24 px (4-byte rows) blitted at
LCD x = 0, 24 .. 120: every seam lands on a multiple of 6 and 8, so no strip shares an LCD byte with the next.
Canvas at LCD x 4-131.
Test page (LOOP, dial): V0 = 22 px strips from flash (reference), V1 = 24 px strips from flash,
V2 = the same 24 px strips copied to RAM first. Framebuffer stays at 0x43E000, staging at 0x43E200.

v0.7b notes follow.
JSW v0.7b = v0.7 + framebuffer moved to RAM 0x43E000 + LCD test page on LOOP (diagnostic build).

User, v0.7 on hw (photos 2026-10-13): HOME/MPC shapes in the right places, but thin lines and text broken
into dots everywhere ("less black stuff"). The emulator draws them right and h8sdis agrees with every engine
instruction, so the LCD path or the RAM at FB (0x43C100) misbehaves on the real unit.
- Normal pages: FB moved to 0x43E000 (guess: 0x43C100 is used by the stack or the boot ROM).
- LOOP page = test page. The dial / </> picks a variant (0-5). Each one clears the LCD (API 0x4003D4), blits
  the MPC page pre-rendered in Python (rows 0-23), then prints with Roland's text API on row 3:
  "V<n> SP<er7 now> B<er7 at boot>".
    V0  22-px strips (as the boot animation) from flash
    V1  32-px strips from flash
    V2  32-px strips from flash, blitted twice (does the blit combine with the screen?)
    V3  32-px strips copied to RAM 0x43C100 (old FB), blitted from there
    V4  same via RAM 0x43E000 (new FB)
    V5  same via RAM 0x43D000

v0.7 notes follow.
JSW v0.7 = v0.6j + our own graphics engine: new HOME and MPC page (no Roland text API on screen 5).

User, 2026-10-13: "with looper I want a fully new interface ... same for MPC mode, Roland did shitty graphics".
Mockups art/ui_mock_v1.png approved ("looks dope").
- tools/gfxlib.py: RAM framebuffer (FB, 512 bytes at RAM +0x100) drawn with our routines (put8 / fill / text /
  bitmap, modes set/clear/invert) and our fonts (tiny 3x5, 5x7, 7-segment digits) and icons (tools/ui_gfx.py),
  pushed to the LCD with the boot animation's blit call, 4 strips of 32 px at x = 2..129.
- HOME: 4 icon tiles (MPC / LOOP / KEYS / SYS), dial or arrows (LEFT/RIGHT too) move, ENTER opens.
- MPC page: PAD / REC / START rows (5x7), selected row inverted, 4x4 pad map (filled = has a sample,
  outline = empty, framed + inverted centre = selected; pad 1 bottom left), messages as pop-ups.
- The stock record / result screens (0x22 / 0x23) still draw Roland's graphics: next build.
- draw saves er2/er3 itself (the engine uses er0-er3), so every caller sees them kept.

v0.6j notes follow.
JSW v0.6j = v0.6i + EXIT cancels a take.

User, v0.6i on hw (2026-10-13): "works as expected". Then: EXIT while sampling must just stop, not save,
and go back to the menu.
- EXIT on the record screen 0x22 (recording or waiting for signal): our flow ends at once (MSTATE idle,
  "take canceled") and we go to screen 5. Stock 0x22 leave (event 1, 0x13CAB6) stops the recording
  (0x13CB54) and unlocks; 0x23 is never entered, so its event 2 never writes the take into a pad.
- EXIT on the result screen 0x23 (was RETRY): stop the take preview like stock EXIT does (0x14D136,
  0x14D078; stock then shows "Try Again."), put the take pad back to its entry from before the take,
  then home with "take canceled".
- The take pad's entry is now saved in start_rec for every mode (was CLASSIC only).

v0.6i notes follow.
JSW v0.6i = v0.6h + encoder in our menu + CLASSIC records into the pad you selected.

User, v0.6h on hw (2026-10-13): "it seems to sample now", but "ENTER can't start a random sample in
CLASSIC, it's got to show you what sample you've selected or say pick a sample as a start point".
Also "make the encoder also work in the menu".
- Encoder: the main loop stores the per-pass VALUE dial delta at 0x427058 (0x13139A, boot API 0x400490)
  before sending event 6 (idle, every pass with no screen change, 0x13FA32) to the screen.
  Screen 5 on event 6: delta > 0 acts as RIGHT (HOME page: DOWN), delta < 0 as LEFT (HOME: UP).
- MPC page rows: "Pad: 05 used" / "Rec: CLASSIC MPC" / "Start: INSTANT" / help or debug.
  UP/DOWN picks the row, </> or the dial changes it (Pad row: steps pad 1-16).
  Hitting a pad on the MPC page selects it (and plays it, stock). Power-on: no pad selected ("--").
- CLASSIC: ENTER / SAMPLE / PAD SAMPLING record into the selected pad S (its entry saved first).
  No pad selected -> "hit a pad first!". Result screen: ENTER = keep on S, pad P = P gets the take and
  S gets its saved entry back, then P becomes the selected pad. No more temp pad / first free pad.

v0.6h notes follow.
JSW v0.6h = v0.6g + MPC page rework + CLASSIC "replace" + pad-pick fix attempt + debug line.

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
usage: python -I build_v08.py raw.bin outdir
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm
from make_prg import check, SIZE, VER_HDR, VER_CODE
import bootanim
import gfxlib

VERSION, VER_TXT = 1080, '0.8'
PAD_NOTE_ON, BOOT_PAD = 0x13735E, 15        # note-on (r0 = pad 0-15, r1l = velocity); pad 16 = boot sound
CODE_BASE = 0x16B000
TICK_MS = 0x40185E                          # boot ROM 1 ms counter (32-bit)
SEG_POS, SEG_PUT, SEG_MASK = 0x4003DC, 0x4003E4, 0x3C003C00   # 7-seg: set digit r0l / write er0 under mask er1
SEG_DIGITS, SEG_PAGE_MS = 12, 2500          # the stock time counter digits 0-11
LVL_L, LVL_R = 0x427838, 0x42783E           # input meter records, byte +0 = level 0-127
FREE_BLK, RSV_BLK, MONO_FLAG = 0x411B6E, 0x42741A, 0x426E29     # disk blocks (32 KB), mono = bit 1
SIG_WAIT_LO, SIG_STAT = 0x4277D1, 0xFFF0DC  # 0x4277D0 bit 2 = waiting for the signal; 0xFFF0DC bit 0 = no signal yet
REC_TXT_PTR, TXT_NOW_SAMPLING = 0x427910, 0x166298
EV_STOCK_FINISH = 0x19                      # stock 0x22 event that returns 1 (stop the take, go to 0x23)
FRAME_MS, PEAK_HOLD_FR, METER_SEGS = 100, 15, 42
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
PREVIEW_STOP_A, PREVIEW_STOP_B = 0x14D136, 0x14D078   # what stock 0x23 EXIT calls first (take preview object 0x43B5A6)
SEL_PAD, TRIG_MODE = 0x4277D4, 0x4277C9
SCR_SELECT_PAD, SCR_PARAMS, SCR_RECORD, SCR_DONE, SCR_AUTOTRIM, SCR_SYSTEM = 0x1F, 0x20, 0x22, 0x23, 0x24, 0x41
K_UP, K_DOWN, K_LEFT, K_RIGHT, K_EXIT, K_ENTER = 0x70, 0x71, 0x72, 0x73, 0xB0, 0xB1
K_SONG, K_SYSTEM, K_SAMPLE, K_SH_SYSTEM = 0x80, 0x81, 0x82, 0x181
K_PADSMPL, K_SH_PADSMPL = 0x22, 0x122
WAIT_LEVEL = 3
ENC_DELTA = 0x427058                        # VALUE dial delta of this main-loop pass (signed word)
PAD_USED = 0x14D8AA                         # (r0 = pad) -> r0 = 1 if the pad holds a sample (current bank)
NO_PAD = 0xFF

RAM_BASE = 0x43C000                         # unused RAM after the OS's last variable (0x43BAFE), see v0.6f
CANARY, PAGE, CUR, SMODE, WARN = RAM_BASE, RAM_BASE + 4, RAM_BASE + 5, RAM_BASE + 6, RAM_BASE + 7
MSTATE, REC_PAD, REC_HOLD, MSG = RAM_BASE + 8, RAM_BASE + 9, RAM_BASE + 10, RAM_BASE + 11
MCUR, D_PATH, D_T0, D_T, D_P, D_RES, SAVED_OK, SELPAD = (RAM_BASE + i for i in range(12, 20))
SAVED, DBGSTR, PADSTR = RAM_BASE + 0x20, RAM_BASE + 0x40, RAM_BASE + 0x50   # pad entry, debug text, "05"
GMODE, FB = RAM_BASE + 0x14, 0x43E000                                    # gfx draw mode, framebuffer
BOOTSND = RAM_BASE + 0x16                                                # 1 once the boot sound has played
REC_T0, REC_MS, LAST_DRAW, SEG_T = (RAM_BASE + 0x80 + 4 * i for i in range(4))   # longs: ms ticks
SEG_PG, PEAK, PEAK_HOLD, HIST_N, HIST_DIV, HIST_CNT, HIST_MAX, METER_N = (RAM_BASE + 0x90 + i for i in range(8))
TXT, SEGTXT, NUMBUF, HIST = RAM_BASE + 0xA0, RAM_BASE + 0xC0, RAM_BASE + 0xD8, RAM_BASE + 0x100  # 24, 16, 8, 128 B
HIST_LEN = 128
RAM_VARS = (PAGE, CUR, WARN, MSTATE, REC_PAD, REC_HOLD, MSG, MCUR, D_PATH, D_T0, D_T, D_P, D_RES, SAVED_OK, GMODE,
            BOOTSND, SEG_PG, PEAK, PEAK_HOLD, HIST_N, HIST_CNT, HIST_MAX, METER_N)
MAGIC = 0x4A535721
P_HOME, P_MPC, P_LOOP, P_KEYS = 0, 1, 2, 3
SM_NEXT, SM_CLASSIC, SM_TAP, SM_HOLD = 0, 1, 2, 3
MS_IDLE, MS_ARMED, MS_REC = 0, 1, 2

TILES = [('mpc', 'MPC'), ('loop', 'LOOP'), ('keys', 'KEYS'), ('sys', 'SYS')]
SMODE_NAMES = ['NEXT FREE', 'CLASSIC', 'TAP', 'HOLD']
POPUPS = [('s_bankfull', 'BANK FULL'), ('s_pickpad', 'HIT A PAD FIRST'), ('s_canceled', 'TAKE CANCELED')]   # MSG 1-3
GRID_X, GRID_Y = 99, 1                      # 4x4 pad map, 6 px pads, 1 px gaps


# ---- 7-segment font for the top line (our own segment choices), chars 0x20-0x5A ----
SEG_BITS = {'a': 0x2000 << 16, 'g': 0x1000 << 16, 'c': 0x0800 << 16, 'b': 0x0400 << 16,
            'f': 0x2000, 'e': 0x1000, 'd': 0x0800}
SEG_DP = 0x0400
SEG_CHARS = {
    '0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg', '4': 'bcfg', '5': 'acdfg', '6': 'acdefg', '7': 'abc',
    '8': 'abcdefg', '9': 'abcdfg', '-': 'g', '_': 'd', '=': 'dg',
    'A': 'abcefg', 'B': 'cdefg', 'C': 'adef', 'D': 'bcdeg', 'E': 'adefg', 'F': 'aefg', 'G': 'acdef', 'H': 'bcefg',
    'I': 'ef', 'J': 'bcde', 'K': 'bcefg', 'L': 'def', 'M': 'abcef', 'N': 'ceg', 'O': 'abcdef', 'P': 'abefg',
    'Q': 'abcfg', 'R': 'eg', 'S': 'acdfg', 'T': 'defg', 'U': 'bcdef', 'V': 'cde', 'W': 'bcdef', 'X': 'bcefg',
    'Y': 'bcdfg', 'Z': 'abdeg'}


def seg_font():
    out = bytearray()
    for c in range(0x20, 0x5B):
        out += sum(SEG_BITS[s] for s in SEG_CHARS.get(chr(c), '')).to_bytes(4, 'big')
    return bytes(out)


def seg_decode(word):
    """pattern -> char (for tests)"""
    dp = '.' if word & SEG_DP else ''
    word &= ~SEG_DP
    for ch, segs in sorted(SEG_CHARS.items()):
        if sum(SEG_BITS[s] for s in segs) == word: return ch + dp
    return (' ' if word == 0 else '?') + dp


def meter_table():
    """level 0-127 -> lit segments 0-42 (1 dB each, -42..0 dBFS)"""
    import math
    return bytes(0 if v == 0 else max(0, min(METER_SEGS, round(METER_SEGS + 20 * math.log10(v / 127)))) for v in range(128))


def env_table():
    """level 0-127 -> envelope half height 1-6 (-36..0 dBFS)"""
    import math
    return bytes(1 if v == 0 else max(1, min(6, 1 + round((36 + 20 * math.log10(v / 127)) / 36 * 5))) for v in range(128))


def meter_pattern():
    """16-byte row: 2 px segments with 1 px gaps from x 1 (segment i = x 1 + 3i, 2 + 3i)"""
    bits = [1 <= x <= 3 * METER_SEGS and (x - 1) % 3 != 2 for x in range(128)]
    return bytes(sum(bits[8 * j + i] << (7 - i) for i in range(8)) for j in range(16))


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
    a.cmp_b_imm(0x06, 'r6l'); a.beq16('idle')
    a.bra16('done')

    a.label('idle')
    a.bsr16('seg_tick')                           # 7-segment line ticker
    a.mov_b_from_abs(BOOTSND, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('id_dial')   # boot sound: pad 16, once
    set_byte(BOOTSND, 1)
    a.mov_w_imm(BOOT_PAD, 0); a.mov_b_imm(127, 'r1l'); a.jsr(PAD_NOTE_ON)
    a.label('id_dial')                            # VALUE dial: turn it into arrow keys
    a.mov_w_from_abs(ENC_DELTA, 0); a.beq16('done')
    a.mov_b_from_abs(PAGE, 'r1l')
    a.cmp_b_imm(P_MPC, 'r1l'); a.beq('id_mpc')
    a.cmp_b_imm(P_HOME, 'r1l'); a.bne16('done')
    a.mov_w_imm(K_DOWN, 5); a.mov_w_rr(0, 0); a.bpl('id_key')
    a.mov_w_imm(K_UP, 5); a.bra('id_key')
    a.label('id_mpc')
    a.mov_w_imm(K_RIGHT, 5); a.mov_w_rr(0, 0); a.bpl('id_key')
    a.mov_w_imm(K_LEFT, 5)
    a.label('id_key'); a.bra16('key2')

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
    a.label('key2')                                       # r5 = key (real or from the dial)
    set_byte(MSG, 0)
    a.mov_b_from_abs(PAGE, 'r0l')
    a.cmp_b_imm(P_HOME, 'r0l'); a.beq16('k_home')
    a.cmp_b_imm(P_MPC, 'r0l'); a.beq16('k_mpc')
    a.bra16('k_other')

    a.label('k_home')                                     # tiles: LEFT/RIGHT work like UP/DOWN
    a.cmp_w_imm(K_LEFT, 5); a.bne('kh_r'); a.mov_w_imm(K_UP, 5)
    a.label('kh_r')
    a.cmp_w_imm(K_RIGHT, 5); a.bne('kh_go'); a.mov_w_imm(K_DOWN, 5)
    a.label('kh_go')
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
    a.label('km_up')                                      # rows: 0 Pad, 1 Rec, 2 Start
    a.cmp_w_imm(K_UP, 5); a.bne('km_down')
    a.mov_b_from_abs(MCUR, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('redraw')
    a.add_b_imm(0xFF, 'r0l'); a.mov_b_to_abs('r0l', MCUR); a.bra16('redraw')
    a.label('km_down')
    a.cmp_w_imm(K_DOWN, 5); a.bne('km_lr')
    a.mov_b_from_abs(MCUR, 'r0l'); a.cmp_b_imm(2, 'r0l'); a.bcc16('redraw')
    a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', MCUR); a.bra16('redraw')
    a.label('km_lr')
    a.cmp_w_imm(K_LEFT, 5); a.beq('km_val')
    a.cmp_w_imm(K_RIGHT, 5); a.bne16('km_exit')
    a.label('km_val')
    a.mov_b_from_abs(MCUR, 'r0l'); a.cmp_b_imm(1, 'r0l'); a.beq('km_rec')
    a.bcc16('km_tog')                                     # row 2 (Start)
    a.mov_b_from_abs(SELPAD, 'r0l')                       # Pad row: step pads 1-16 ("--" -> pad 1)
    a.cmp_b_imm(NO_PAD, 'r0l'); a.bne('km_pstep')
    a.mov_b_imm(0, 'r0l'); a.bra('km_pset')
    a.label('km_pstep')
    a.cmp_w_imm(K_RIGHT, 5); a.bne('km_pprev')
    a.add_b_imm(1, 'r0l'); a.bra('km_pwrap')
    a.label('km_pprev'); a.add_b_imm(0xFF, 'r0l')
    a.label('km_pwrap'); a.and_w_imm(0x000F, 0)
    a.label('km_pset'); a.mov_b_to_abs('r0l', SELPAD); a.bra16('redraw')
    a.label('km_rec')
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
    D = gfxlib.Draw(a, GMODE)
    def fill_r3(dx, dy, w, h):                           # rectangle at (r3l + dx, r3h + dy)
        a.mov_b_rr('r3l', 'r1l'); a.add_b_imm(dx, 'r1l'); a.mov_b_rr('r3h', 'r1h'); a.add_b_imm(dy, 'r1h')
        a.mov_b_imm(w, 'r2l'); a.mov_b_imm(h, 'r2h'); a.bsr16('gfx_fill')
    def select_text(var, lbls, x, y, font='font_57'):
        done = uniq('st')
        a.mov_b_from_abs(var, 'r0l')
        for i, l in enumerate(lbls[:-1]):
            nx = uniq('nx'); a.cmp_b_imm(i, 'r0l'); a.bne(nx); a.mov_l_imm(l, 3); a.bra(done); a.label(nx)
        a.mov_l_imm(lbls[-1], 3)
        a.label(done)
        a.mov_l_rr(3, 0); a.mov_b_imm(x, 'r1l'); a.mov_b_imm(y, 'r1h'); a.mov_l_imm(font, 2); a.bsr16('gfx_text')

    a.label('draw')
    a.push_l(2); a.push_l(3)
    a.bsr16('gfx_clear')
    a.mov_b_from_abs(PAGE, 'r0l')
    a.cmp_b_imm(P_MPC, 'r0l'); a.beq16('d_mpc')
    a.cmp_b_imm(P_LOOP, 'r0l'); a.beq16('d_loop')
    a.cmp_b_imm(P_KEYS, 'r0l'); a.beq16('d_keys')
    # ---- HOME: 4 icon tiles ----
    for i, (ic, label) in enumerate(TILES):
        D.bitmap(i * 32 + 8, 2, 'icon_' + ic)
        D.text(i * 32 + 16 - (4 * len(label) - 1) // 2, 22, 't_' + ic, 'font_tiny')
    a.mov_b_from_abs(CUR, 'r3l'); a.and_b_imm(3, 'r3l')
    for _ in range(5): a.shll_b('r3l')                   # x = CUR * 32
    a.mov_b_imm(0, 'r3h')
    fill_r3(1, 0, 30, 1); fill_r3(1, 31, 30, 1); fill_r3(1, 0, 1, 32); fill_r3(30, 0, 1, 32)
    D.mode(gfxlib.M_INV); fill_r3(2, 20, 28, 9); D.mode(gfxlib.M_SET)
    a.mov_b_from_abs(WARN, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('d_flush')
    D.text(112, 27, 's_ramwarn', 'font_tiny')
    a.bra16('d_flush')

    # ---- MPC page ----
    a.label('d_mpc')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.bne16('d_mpc_norm')
    D.fill(0, 0, 93, 9); D.mode(gfxlib.M_CLR); D.text(2, 1, 's_armed'); D.mode(gfxlib.M_SET)
    D.text(1, 13, 's_start'); select_text(TRIG_MODE, ['s_instant', 's_wait'], 37, 13)
    D.text(1, 27, 's_cancel', 'font_tiny')
    a.bra16('d_grid')
    a.label('d_mpc_norm')
    D.text(1, 1, 's_pad'); D.text(1, 9, 's_rec'); D.text(1, 17, 's_start')
    a.mov_b_from_abs(SMODE, 'r0l')                        # PAD row: the pad (CLASSIC) or what picks it
    a.cmp_b_imm(SM_NEXT, 'r0l'); a.bne('d_p_tap')
    D.text(37, 1, 's_nextfree'); a.bra16('d_rows')
    a.label('d_p_tap')
    a.cmp_b_imm(SM_CLASSIC, 'r0l'); a.beq('d_p_cls')
    D.text(37, 1, 's_youhit'); a.bra16('d_rows')
    a.label('d_p_cls')
    a.mov_b_from_abs(SELPAD, 'r0l'); a.cmp_b_imm(NO_PAD, 'r0l'); a.bne('d_p_num')
    D.text(37, 1, 's_nopad'); a.bra16('d_rows')
    a.label('d_p_num')
    a.bsr16('dec2')
    a.mov_b_to_abs('r0h', PADSTR); a.mov_b_to_abs('r0l', PADSTR + 1); set_byte(PADSTR + 2, 0)
    D.text(37, 1, PADSTR)
    a.mov_b_rr('r1l', 'r3l')                              # x after "05"
    a.mov_b_from_abs(SELPAD, 'r0l'); a.and_w_imm(0x000F, 0); a.jsr(PAD_USED)
    a.mov_b_rr('r3l', 'r1l'); a.mov_b_imm(1, 'r1h')
    a.mov_w_rr(0, 0); a.bne('d_p_used')
    D.text_at_r1('s_empty'); a.bra('d_rows')
    a.label('d_p_used'); D.text_at_r1('s_used')
    a.label('d_rows')
    select_text(SMODE, ['sm%d' % i for i in range(4)], 37, 9)
    select_text(TRIG_MODE, ['s_instant', 's_wait'], 37, 17)
    a.mov_b_from_abs(MCUR, 'r3h'); a.shll_b('r3h'); a.shll_b('r3h'); a.shll_b('r3h'); a.mov_b_imm(0, 'r3l')
    D.mode(gfxlib.M_INV); fill_r3(0, 0, 93, 9); D.mode(gfxlib.M_SET)       # selected row
    D.fill(0, 26, 13, 6); D.mode(gfxlib.M_CLR); D.text(1, 27, 't_mpc', 'font_tiny'); D.mode(gfxlib.M_SET)
    D.text(16, 27, 's_mpchelp', 'font_tiny')
    # ---- 4x4 pad map (pad 1 bottom left): filled = sample, outline = empty ----
    a.label('d_grid')
    for p in range(16):
        x, y = GRID_X + (p % 4) * 7, GRID_Y + (3 - p // 4) * 7
        emp, nx = uniq('pe'), uniq('pn')
        a.mov_w_imm(p, 0); a.jsr(PAD_USED); a.mov_w_rr(0, 0); a.beq(emp)
        D.fill(x, y, 6, 6); a.bra16(nx)
        a.label(emp); D.frame(x, y, 6, 6)
        a.label(nx)
    a.mov_b_from_abs(SELPAD, 'r0l'); a.cmp_b_imm(NO_PAD, 'r0l'); a.beq16('d_msg')
    a.and_b_imm(0x0F, 'r0l'); a.extu_w(0); a.add_b_rr('r0l', 'r0l'); a.extu_l(0)   # selected: frame + invert centre
    a.mov_l_imm('grid_xy', 3); a.add_l_rr(0, 3)
    a.mov_b_ldinc(3, 'r0l'); a.mov_b_ld(3, 'r3h'); a.mov_b_rr('r0l', 'r3l')
    fill_r3(-1 & 0xFF, -1 & 0xFF, 8, 1); fill_r3(-1 & 0xFF, 6, 8, 1); fill_r3(-1 & 0xFF, -1 & 0xFF, 1, 8); fill_r3(6, -1 & 0xFF, 1, 8)
    D.mode(gfxlib.M_INV); fill_r3(1, 1, 4, 4); D.mode(gfxlib.M_SET)
    # ---- message pop-ups ----
    a.label('d_msg')
    for k, (lbl, s) in enumerate(POPUPS, 1):
        nx = uniq('pm')
        a.mov_b_from_abs(MSG, 'r0l'); a.cmp_b_imm(k, 'r0l'); a.bne16(nx)
        D.popup(lbl, len(s))
        a.label(nx)
    a.bra16('d_flush')

    # ---- LOOP / KEYS (coming soon) ----
    for page, title, icon in (('d_loop', 's_looper', 'icon_loop'), ('d_keys', 's_keys', 'icon_keys')):
        a.label(page)
        D.bitmap(110, 2, icon)
        D.text(1, 1, title); D.text(1, 12, 's_soon', 'font_tiny'); D.text(1, 27, 's_exithelp', 'font_tiny')
        a.bra16('d_flush')

    a.label('d_flush')
    a.bsr16('gfx_flush')
    a.pop_l(3); a.pop_l(2)
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
    set_byte(WARN, 1); set_byte(SMODE, SM_CLASSIC); set_byte(SELPAD, NO_PAD)
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
    a.label('tk_classic')                                         # record into the selected pad S
    a.mov_b_from_abs(SELPAD, 'r0l'); a.cmp_b_imm(NO_PAD, 'r0l'); a.bne('tk_t')
    set_byte(MSG, 2); set_byte(PAGE, P_MPC); set_byte(MCUR, 0)    # none yet: "hit a pad first!"
    show_page(); a.rts()
    a.label('tk_t')
    a.bra16('start_rec')

    # ================= start recording into pad r0l (our flow) =================
    a.label('start_rec')
    a.push_l(6)
    a.bclr_abs(6, SMP_FLAGS_LO)                                 # clear stale "take done" so mode 3 re-enters sampling
    a.mov_b_rr('r0l', 'r6l')
    set_byte(D_PATH, 0)                                         # new take: hide the last debug line
    a.mov_b_to_abs('r6l', D_T0)
    a.mov_b_rr('r6l', 'r0h'); a.mov_b_from_abs(CUR_BANK, 'r0l')
    a.mov_l_imm(SAVED, 1); a.jsr(PAD_GET)                       # the pad's entry as it is before the take
    a.mov_b_to_abs('r0l', SAVED_OK)
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
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_ARMED, 'r0l'); a.beq16('g1_go')
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.bne('g1_nosel')
    a.mov_b_from_abs(PAGE, 'r0l'); a.cmp_b_imm(P_MPC, 'r0l'); a.bne('g1_nosel')
    a.mov_b_rr('r5l', 'r0l'); a.and_w_imm(0x000F, 0); a.mov_b_to_abs('r0l', SELPAD)   # MPC page: pad = select it
    set_byte(MSG, 0)
    a.bsr16('draw')
    a.mov_w_from_abs(KEY_EVENT, 5)
    a.label('g1_nosel')
    a.btst_imm(0, 'r5h'); a.beq16('g1_stock')                # not SHIFT (stock plays the pad)
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
    a.mov_b_to_abs('r6l', SELPAD)                                                              # P is now selected
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
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.bne16('w22_stock')    # stock flows: stock screen
    a.cmp_w_imm(0x0005, 6); a.bne('w22_n5')
    a.bsr16('rec_draw'); a.bra16('w22_ret')                     # redraw: ours only
    a.label('w22_n5')
    a.cmp_w_imm(0x0006, 6); a.bne('w22_n6')
    a.bsr16('rec_idle'); a.bra16('w22_ret')                     # idle: stock logic without its drawing
    a.label('w22_n6')
    a.cmp_w_imm(0x0000, 6); a.bne('w22_n0')
    a.mov_w_rr(6, 0); a.jsr(STOCK_SCR22)                        # enter: stock arms the take, then our state
    a.bsr16('rec_init'); a.bra16('w22_ret')
    a.label('w22_n0')
    a.cmp_w_imm(0x0009, 6); a.bne16('w22_stock')
    a.mov_w_from_abs(KEY_EVENT, 0); a.cmp_w_imm(K_EXIT, 0); a.bne('w22_pad')
    set_byte(MSTATE, MS_IDLE); set_byte(MSG, 3); set_byte(D_PATH, 0)   # EXIT: cancel. Leaving 0x22 stops it,
    set_byte(PAGE, P_MPC)                                               # 0x23 never writes the take to a pad
    a.mov_w_imm(SCREEN, 0); a.jsr(GOTO_SCREEN)
    a.pop_l(6); a.rts()
    a.label('w22_pad')
    a.bsr16('check_stop')
    a.mov_w_rr(0, 0); a.beq('w22_stock')
    a.mov_w_imm(K_PADSMPL, 0); a.mov_w_to_abs(0, KEY_EVENT)
    a.label('w22_stock')
    a.mov_w_rr(6, 0); a.pop_l(6); a.jmp(STOCK_SCR22)
    a.label('w22_ret')
    a.pop_l(6); a.rts()

    # ================= screen 0x23 (sample done) wrapper: KEEP / CANCEL / pad pick =================
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
    a.cmp_w_imm(K_EXIT, 0); a.bne16('w23_pad')
    a.jsr(PREVIEW_STOP_A); a.jsr(PREVIEW_STOP_B)                # EXIT: cancel. Stop the preview like stock EXIT,
    a.mov_b_from_abs(SAVED_OK, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq('w23_norest')
    a.mov_b_from_abs(SMP_PAD, 'r0h'); a.mov_b_from_abs(SMP_BANK, 'r0l')
    a.mov_l_imm(SAVED, 1); a.jsr(PAD_SET)                       # put the take pad back as it was before the take,
    a.mov_w_imm(0, 8); a.mov_b_imm(0, 'r0l'); a.jsr(PAD_SET_POST)
    a.mov_w_imm(1, 0); a.jsr(PAD_REFRESH)
    a.label('w23_norest')
    a.bsr16('keep')                                             # then home
    set_byte(MSG, 3); set_byte(D_PATH, 0)
    a.pop_l(6); a.rts()
    a.label('w23_pad')                                          # pads land here if the screen masks key group 1
    a.mov_w_rr(0, 1); a.and_w_imm(0x00F0, 0); a.cmp_w_imm(0x0010, 0); a.bne16('w23_stock')
    a.btst_imm(6, 'r1h'); a.bne('w23_ret')                      # release: swallow
    a.mov_b_rr('r1l', 'r0l'); a.and_w_imm(0x000F, 0); a.mov_b_imm(ord('W'), 'r0h')
    a.bsr16('pick')
    a.label('w23_ret')
    a.pop_l(6); a.rts()
    a.label('w23_ev')
    a.cmp_w_imm(0x0005, 6); a.bne('w23_n5')
    a.bsr16('done_draw'); a.bra16('w23_out')                    # redraw: ours only
    a.label('w23_n5')
    a.cmp_w_imm(0x0006, 6); a.bne('w23_n6')
    a.bsr16('seg_tick'); a.bra16('w23_out')                     # idle: no stock meter
    a.label('w23_n6')
    a.cmp_w_imm(0x0002, 6); a.bne('w23_n2')
    a.mov_w_rr(6, 0); a.jsr(STOCK_SCR23)                        # shown: stock writes the take into the pad
    a.bsr16('done_draw'); a.bra16('w23_out')                    # (and draws "Now Working..."), then ours
    a.label('w23_n2')
    a.cmp_w_imm(0x0000, 6); a.bne16('w23_stock')
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

    # ================= record screen (0x22) =================
    def putc(ch, ptr=1):                                        # @er<ptr>+ = ch
        a.mov_b_imm(ord(ch), 'r0l'); a.mov_b_st('r0l', ptr); a.adds1(ptr)
    def puts_ram(s, ptr=1):
        for ch in s: putc(ch, ptr)
    def since(var):                                             # er0 = now - @var (ms)
        a.mov_l_from_abs(TICK_MS, 0); a.mov_l_from_abs(var, 1); a.sub_l(1, 0)
    def pad_txt(var):                                           # TXT = "PAD 05" for pad index @var
        a.mov_l_imm(TXT, 1); puts_ram('PAD ')
        a.mov_b_from_abs(var, 'r0l'); a.and_b_imm(0x0F, 'r0l'); a.bsr16('dec2')
        a.mov_b_st('r0h', 1); a.adds1(1); a.mov_b_st('r0l', 1); a.adds1(1); putc('\0')

    a.label('rec_init')                                         # after stock enter
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, REC_T0); a.mov_l_to_abs(0, LAST_DRAW)
    a.sub_l(0, 0); a.mov_l_to_abs(0, REC_MS)
    for v in (PEAK, PEAK_HOLD, METER_N, HIST_N, HIST_CNT, HIST_MAX, HIST): a.mov_b_to_abs('r0l', v)
    set_byte(HIST_DIV, 1)
    a.rts()

    a.label('rec_idle')
    a.bsr16('seg_tick')
    a.mov_w_imm(0, 0); a.jsr(MEM_CHECK); a.mov_w_rr(0, 0); a.bne('ri_mem')
    a.mov_w_imm(EV_STOCK_FINISH, 0); a.jmp(STOCK_SCR22)         # disk full: stock stops the take -> 0x23
    a.label('ri_mem')
    a.btst_abs(2, SIG_WAIT_LO); a.beq('ri_rec')                 # waiting for the signal?
    a.btst_abs(0, SIG_STAT); a.bne('ri_wait')                   # not yet
    a.bclr_abs(2, SIG_WAIT_LO)                                  # it came: "Now Sampling" (as stock)
    a.mov_l_imm(TXT_NOW_SAMPLING, 0); a.mov_l_to_abs(0, REC_TXT_PTR)
    a.label('ri_wait')
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, REC_T0)    # the timer starts with the signal
    a.label('ri_rec')
    since(REC_T0); a.mov_l_to_abs(0, REC_MS)
    since(LAST_DRAW); a.cmp_l_imm(FRAME_MS, 0); a.bcs('ri_out')
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, LAST_DRAW)
    a.bsr16('rec_frame'); a.bsr16('rec_draw')
    a.label('ri_out')
    a.mov_w_imm(0, 0); a.rts()

    # one frame: meter segments + peak hold, level history (recording only)
    a.label('rec_frame')
    a.mov_b_from_abs(LVL_L, 'r0l'); a.mov_b_from_abs(LVL_R, 'r0h')
    a.cmp_b_rr('r0h', 'r0l'); a.bcc('rf_lr'); a.mov_b_rr('r0h', 'r0l')   # r0l = max(L, R)
    a.label('rf_lr')
    a.and_b_imm(0x7F, 'r0l')
    a.btst_abs(2, SIG_WAIT_LO); a.bne('rf_meter')
    a.mov_b_from_abs(HIST_MAX, 'r1l'); a.cmp_b_rr('r0l', 'r1l'); a.bcc('rf_hm')
    a.mov_b_to_abs('r0l', HIST_MAX)
    a.label('rf_hm')
    a.mov_b_from_abs(HIST_CNT, 'r1l'); a.inc_b('r1l'); a.mov_b_to_abs('r1l', HIST_CNT)
    a.mov_b_from_abs(HIST_DIV, 'r1h'); a.cmp_b_rr('r1h', 'r1l'); a.bcs('rf_meter')     # cnt < div
    a.push_l(0)
    a.mov_b_imm(0, 'r1l'); a.mov_b_to_abs('r1l', HIST_CNT)
    a.mov_b_from_abs(HIST_MAX, 'r0l'); a.bsr16('hist_push')
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', HIST_MAX)
    a.pop_l(0)
    a.label('rf_meter')
    a.extu_w(0); a.extu_l(0); a.mov_l_imm('meter_tab', 1); a.add_l_rr(0, 1); a.mov_b_ld(1, 'r0l')
    a.mov_b_to_abs('r0l', METER_N)
    a.mov_b_from_abs(PEAK, 'r1l'); a.cmp_b_rr('r1l', 'r0l'); a.bcs('rf_fall')          # n < peak
    a.mov_b_to_abs('r0l', PEAK); set_byte(PEAK_HOLD, PEAK_HOLD_FR); a.rts()
    a.label('rf_fall')
    a.mov_b_from_abs(PEAK_HOLD, 'r0l'); a.beq('rf_drop')
    a.dec_b('r0l'); a.mov_b_to_abs('r0l', PEAK_HOLD); a.rts()
    a.label('rf_drop')
    a.dec_b('r1l'); a.mov_b_to_abs('r1l', PEAK); a.rts()

    # r0l -> history; when full, merge pairs (max) and double the step
    a.label('hist_push')
    a.push_l(3)
    a.mov_b_rr('r0l', 'r3h')
    a.mov_b_from_abs(HIST_N, 'r0l'); a.cmp_b_imm(HIST_LEN, 'r0l'); a.bcs('hp_put')
    a.mov_l_imm(HIST, 1); a.mov_l_imm(HIST, 2); a.mov_b_imm(HIST_LEN // 2, 'r3l')
    a.label('hp_merge')
    a.mov_b_ldinc(1, 'r0l'); a.mov_b_ldinc(1, 'r0h')
    a.cmp_b_rr('r0h', 'r0l'); a.bcc('hp_mx'); a.mov_b_rr('r0h', 'r0l')
    a.label('hp_mx')
    a.mov_b_st('r0l', 2); a.adds1(2); a.dec_b('r3l'); a.bne('hp_merge')
    a.mov_b_from_abs(HIST_DIV, 'r0l'); a.cmp_b_imm(128, 'r0l'); a.bcc('hp_n')
    a.add_b_rr('r0l', 'r0l'); a.mov_b_to_abs('r0l', HIST_DIV)
    a.label('hp_n')
    a.mov_b_imm(HIST_LEN // 2, 'r0l'); a.mov_b_to_abs('r0l', HIST_N)
    a.label('hp_put')
    a.extu_w(0); a.extu_l(0); a.mov_l_imm(HIST, 1); a.add_l_rr(0, 1); a.mov_b_st('r3h', 1)
    a.inc_b('r0l'); a.mov_b_to_abs('r0l', HIST_N)
    a.pop_l(3); a.rts()

    a.label('rec_draw')
    a.push_l(2); a.push_l(3)
    a.bsr16('gfx_clear')
    pad_txt(REC_PAD); D.text(1, 10, TXT, 'font_tiny')
    a.btst_abs(2, SIG_WAIT_LO); a.beq('rd_rec')
    D.bitmap(1, 1, 'icon_recring'); D.text(11, 1, 's_wait4')
    D.text(1, 26, 's_waithelp', 'font_tiny'); a.bra16('rd_common')
    a.label('rd_rec')
    a.mov_l_from_abs(REC_MS, 0); a.btst_imm(1, 'r0h'); a.bne('rd_nodot')     # dot blinks (ms bit 9)
    D.bitmap(1, 1, 'icon_recdot')
    a.label('rd_nodot')
    D.text(11, 1, 's_rec'); D.text(1, 26, 's_rechelp', 'font_tiny')
    a.label('rd_common')
    a.mov_l_imm(TXT, 1); a.bsr16('fmt_remain'); D.text(30, 10, TXT, 'font_tiny')
    a.mov_l_from_abs(REC_MS, 0); a.mov_l_imm(TXT, 1); a.bsr16('fmt_time'); D.text(72, 1, TXT, 'font_big')
    a.mov_b_from_abs(METER_N, 'r3l'); a.mov_b_rr('r3l', 'r0l'); a.add_b_rr('r0l', 'r3l'); a.add_b_rr('r0l', 'r3l')
    a.inc_b('r3l')                                              # lit width 3n + 1
    for y in range(18, 23):
        a.mov_l_imm('meter_pat', 0); a.mov_b_imm(y, 'r1h')
        if y < 22: a.mov_b_rr('r3l', 'r2l')
        else: a.mov_b_imm(128, 'r2l')                           # baseline under every segment
        a.bsr16('gfx_patrow')
    a.mov_b_from_abs(PEAK, 'r0l'); a.beq('rd_flush')
    a.mov_b_rr('r0l', 'r1l'); a.add_b_rr('r0l', 'r1l'); a.add_b_rr('r0l', 'r1l'); a.add_b_imm(0x100 - 2, 'r1l')
    a.mov_b_imm(17, 'r1h'); a.mov_b_imm(2, 'r2l'); a.mov_b_imm(6, 'r2h'); a.bsr16('gfx_fill')   # peak mark
    a.label('rd_flush')
    a.bsr16('gfx_flush')
    a.pop_l(3); a.pop_l(2); a.rts()

    # ================= take done screen (0x23) =================
    a.label('done_draw')
    a.push_l(2); a.push_l(3)
    a.bsr16('gfx_clear')
    D.text(1, 1, 's_take')
    a.mov_l_from_abs(REC_MS, 0); a.mov_l_imm(TXT, 1); a.bsr16('fmt_len')       # r0l = 1: append the "S"
    a.mov_b_rr('r0l', 'r3h')
    D.text(30, 0, TXT, 'font_big')
    a.mov_b_rr('r3h', 'r3h'); a.beq('dd_nos')
    a.mov_b_imm(6, 'r1h'); D.text_at_r1('s_S', 'font_tiny')
    a.label('dd_nos')
    D.text(72, 1, 's_gt')
    D.fill(80, 0, 47, 9)
    pad_txt(SMP_PAD); D.mode(gfxlib.M_CLR); D.text(82, 1, TXT); D.mode(gfxlib.M_SET)
    a.mov_b_imm(0, 'r3l')                                       # level envelope, x 0-127
    a.label('dd_env')
    a.mov_b_from_abs(HIST_N, 'r0l'); a.mulxu_b('r3l', 0)
    for _ in range(7): a.shlr_w(0)                              # sample = x * n / 128
    a.extu_l(0); a.mov_l_imm(HIST, 1); a.add_l_rr(0, 1); a.mov_b_ld(1, 'r0l'); a.and_b_imm(0x7F, 'r0l')
    a.extu_w(0); a.extu_l(0); a.mov_l_imm('env_tab', 1); a.add_l_rr(0, 1); a.mov_b_ld(1, 'r2h')
    a.mov_b_imm(17, 'r1h'); a.sub_b_rr('r2h', 'r1h'); a.add_b_rr('r2h', 'r2h')
    a.mov_b_rr('r3l', 'r1l'); a.bsr16('gfx_vline')
    a.inc_b('r3l'); a.cmp_b_imm(128, 'r3l'); a.bne('dd_env')
    D.text(1, 26, 's_donehelp', 'font_tiny')
    a.bsr16('gfx_flush')
    a.pop_l(3); a.pop_l(2); a.rts()

    # ================= numbers -> text (er1 = destination, advances) =================
    a.label('fmt2')                                             # r0l 0-99 -> 2 digits
    a.extu_w(0); a.mov_b_imm(10, 'r2l'); a.divxu_b('r2l', 0)
    a.add_b_imm(0x30, 'r0l'); a.mov_b_st('r0l', 1); a.adds1(1)
    a.add_b_imm(0x30, 'r0h'); a.mov_b_st('r0h', 1); a.adds1(1)
    a.rts()
    a.label('fmt_u')                                            # r0 -> decimal, no leading zeros
    a.push_l(3)
    a.mov_l_imm(NUMBUF + 6, 3); a.extu_l(0)
    a.label('fu_dig')
    a.mov_w_imm(10, 2); a.divxu_w(2, 0); a.mov_w_rr(8, 2)
    a.add_b_imm(0x30, 'r2l'); a.subs1(3); a.mov_b_st('r2l', 3)
    a.extu_l(0); a.mov_w_rr(0, 0); a.bne('fu_dig')
    a.label('fu_cp')
    a.mov_b_ldinc(3, 'r0l'); a.mov_b_st('r0l', 1); a.adds1(1)
    a.cmp_l_imm(NUMBUF + 6, 3); a.bne('fu_cp')
    a.pop_l(3); a.rts()
    # er0 = ms -> r0 = whole seconds, r3l = tenths (ms capped at 99:59.9)
    a.label('ms_split')
    a.cmp_l_imm(6000000, 0); a.bcs('ms_ok'); a.mov_l_imm(5999999, 0)
    a.label('ms_ok')
    a.mov_w_imm(100, 2); a.divxu_w(2, 0); a.extu_l(0)
    a.mov_w_imm(10, 2); a.divxu_w(2, 0); a.mov_w_rr(8, 2); a.mov_b_rr('r2l', 'r3l'); a.extu_l(0)
    a.rts()
    a.label('fmt_time')                                         # er0 = ms -> "MM:SS.T"
    a.push_l(3)
    a.bsr16('ms_split')
    a.mov_w_imm(60, 2); a.divxu_w(2, 0); a.mov_w_rr(8, 2); a.mov_b_rr('r2l', 'r3h')
    a.bsr16('fmt2'); putc(':')
    a.mov_b_rr('r3h', 'r0l'); a.bsr16('fmt2'); putc('.')
    a.mov_b_rr('r3l', 'r0l'); a.add_b_imm(0x30, 'r0l'); a.mov_b_st('r0l', 1); a.adds1(1); putc('\0')
    a.pop_l(3); a.rts()
    a.label('fmt_len')                                          # er0 = ms -> "3.2" (r0l = 1) or "1:05" (r0l = 0)
    a.push_l(3)
    a.bsr16('ms_split')
    a.cmp_w_imm(100, 0); a.bcc('fl_min')
    a.bsr16('fmt_u'); putc('.')
    a.mov_b_rr('r3l', 'r0l'); a.add_b_imm(0x30, 'r0l'); a.mov_b_st('r0l', 1); a.adds1(1); putc('\0')
    a.mov_b_imm(1, 'r0l'); a.pop_l(3); a.rts()
    a.label('fl_min')
    a.extu_l(0); a.mov_w_imm(60, 2); a.divxu_w(2, 0); a.mov_w_rr(8, 2); a.mov_b_rr('r2l', 'r3h')
    a.bsr16('fmt_u'); putc(':'); a.mov_b_rr('r3h', 'r0l'); a.bsr16('fmt2'); putc('\0')
    a.mov_b_imm(0, 'r0l'); a.pop_l(3); a.rts()
    a.label('free_blk')                                         # r0 = free 32 KB blocks (as stock 0x14D90E - 3); uses r2
    a.mov_w_from_abs(FREE_BLK, 0); a.mov_w_from_abs(RSV_BLK, 2); a.sub_w_rr(2, 0)
    a.cmp_w_imm(3, 0); a.blt('fb_none')
    a.mov_w_imm(3, 2); a.sub_w_rr(2, 0); a.rts()
    a.label('fb_none'); a.mov_w_imm(0, 0); a.rts()
    a.label('fmt_remain')                                       # "24:31 LEFT"
    a.push_l(3)
    a.bsr16('free_blk')
    a.mov_w_imm(4953, 2); a.mulxu_w(2, 0); a.mov_w_imm(10000, 2); a.divxu_w(2, 0); a.extu_l(0)   # stereo s
    a.btst_abs(1, MONO_FLAG); a.beq('fr_st'); a.shll_l(0)
    a.label('fr_st')
    a.mov_w_imm(60, 2); a.divxu_w(2, 0); a.mov_w_rr(8, 2); a.mov_b_rr('r2l', 'r3l')
    a.bsr16('fmt_u'); putc(':'); a.mov_b_rr('r3l', 'r0l'); a.bsr16('fmt2'); puts_ram(' LEFT\0')
    a.pop_l(3); a.rts()

    # ================= 7-segment line: pages on digits 0-11 =================
    a.label('seg_tick')
    a.push_l(4); a.push_l(6)
    since(SEG_T); a.cmp_l_imm(SEG_PAGE_MS, 0); a.bcs('sg_show')
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, SEG_T)
    a.mov_b_from_abs(SEG_PG, 'r0l'); a.inc_b('r0l'); a.cmp_b_imm(3, 'r0l'); a.bcs('sg_pg'); a.mov_b_imm(0, 'r0l')
    a.label('sg_pg'); a.mov_b_to_abs('r0l', SEG_PG)
    a.label('sg_show')
    a.mov_b_from_abs(SEG_PG, 'r0l')
    a.cmp_b_imm(0, 'r0l'); a.bne('sg_p1'); a.mov_l_imm('s_seg0', 4); a.bra('sg_put')
    a.label('sg_p1')
    a.cmp_b_imm(1, 'r0l'); a.bne('sg_p2'); a.mov_l_imm('s_seg1', 4); a.bra('sg_put')
    a.label('sg_p2')                                            # "<n> MB LEFT"
    a.mov_l_imm(SEGTXT, 1); putc(' ')
    a.bsr16('free_blk')
    for _ in range(5): a.shlr_w(0)                              # 32 blocks = 1 MB
    a.bsr16('fmt_u'); puts_ram(' MB LEFT\0')
    a.mov_l_imm(SEGTXT, 4)
    a.label('sg_put')
    a.mov_b_imm(0, 'r0l'); a.jsr(SEG_POS)
    a.mov_b_imm(SEG_DIGITS, 'r6l')
    a.label('sg_ch')
    a.mov_b_ld(4, 'r0l'); a.beq('sg_blank')                     # end of text: blanks
    a.adds1(4)
    a.add_b_imm(0x100 - 0x20, 'r0l'); a.cmp_b_imm(0x5B - 0x20, 'r0l'); a.bcs('sg_ok')
    a.label('sg_blank')
    a.sub_l(0, 0); a.bra('sg_dp')
    a.label('sg_ok')
    a.extu_w(0); a.extu_l(0); a.shll_l2(0); a.mov_l_imm('seg_font', 1); a.add_l_rr(0, 1); a.mov_l_ind(1, 0)
    a.label('sg_dp')
    a.mov_b_ld(4, 'r1l'); a.cmp_b_imm(ord('.'), 'r1l'); a.bne('sg_wr')
    a.adds1(4); a.or_b_imm(SEG_DP >> 8, 'r0h')                  # "x." -> decimal point on x
    a.label('sg_wr')
    a.mov_l_imm(SEG_MASK, 1); a.jsr(SEG_PUT)
    a.dec_b('r6l'); a.bne('sg_ch')
    a.pop_l(6); a.pop_l(4); a.rts()

    # ================= graphics engine + data =================
    gfxlib.emit(a, FB, GMODE)
    a.align2()
    a.label('seg_font'); a.raw(seg_font())
    a.label('meter_pat'); a.raw(meter_pattern())
    a.label('meter_tab'); a.raw(meter_table())
    a.label('env_tab'); a.raw(env_table())
    a.label('grid_xy')
    for p in range(16): a.raw(bytes((GRID_X + (p % 4) * 7, GRID_Y + (3 - p // 4) * 7)))
    for ic, label in TILES: a.label('t_' + ic); a.string(label)
    for i, s in enumerate(SMODE_NAMES): a.label('sm%d' % i); a.string(s)
    for lbl, s in POPUPS: a.label(lbl); a.string(s)
    for lbl, s in (('s_ramwarn', 'RAM!'),
                   ('s_wait4', 'WAIT'), ('s_rechelp', 'PAD=STOP  EXIT=CANCEL'),
                   ('s_waithelp', 'PLAY TO START  EXIT=CANCEL'), ('s_take', 'TAKE'), ('s_gt', '>'), ('s_S', 'S'),
                   ('s_donehelp', 'ENTER=KEEP PAD=MOVE EXIT=CANCEL'),
                   ('s_seg0', ' ROSETTA OS'), ('s_seg1', '  VER ' + VER_TXT),
                   ('s_pad', 'PAD'), ('s_rec', 'REC'), ('s_start', 'START'),
                   ('s_nextfree', 'NEXT FREE'), ('s_youhit', 'YOU HIT'), ('s_nopad', '--'),
                   ('s_used', ' USED'), ('s_empty', ' EMPTY'),
                   ('s_instant', 'INSTANT'), ('s_wait', 'ON SIGNAL'), ('s_mpchelp', 'ENTER/SAMPLE=REC'),
                   ('s_armed', 'HIT A PAD'), ('s_cancel', 'EXIT=CANCEL'),
                   ('s_looper', 'LOOPER'), ('s_keys', 'KEYBOARD'),
                   ('s_soon', 'COMING SOON'), ('s_exithelp', 'EXIT=HOME')):
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
        a.mov_b_imm(NO_PAD, 'r0l'); a.mov_b_to_abs('r0l', SELPAD)
        a.mov_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', HIST_DIV)
    ablob, alabels = bootanim.patch(img, ANIM_BASE, ram_init)
    p = SPLASH2_AT - 0x100000
    assert bytes(img[p:p + len(SPLASH2_WAS)]) == SPLASH2_WAS, 'splash 2 code changed?'
    img[p:p + len(SPLASH2_NEW)] = SPLASH2_NEW

    v = struct.pack('>H', VERSION)
    for o in VER_HDR: img[o:o + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_v08.bin'), 'wb').write(img)
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(struct.pack('>II', 0x100000, 0x1C0000) + img)
    print('v0.8 built: %d bytes at 0x%X + boot anim %d bytes at 0x%X, version %d'
          % (len(blob), CODE_BASE, len(ablob), ANIM_BASE, VERSION))
    for k in ('menu', 'draw', 'take_key', 'start_rec', 'g1', 'pick', 'assign', 'w22', 'w23', 'keep', 'g8', 'g2',
              'rec_idle', 'rec_draw', 'done_draw', 'seg_tick'):
        print('  %-10s 0x%X' % (k, labels[k]))


if __name__ == '__main__':
    main(*sys.argv[1:3])
