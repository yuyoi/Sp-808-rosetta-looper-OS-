"""JSW v0.9b = v0.9 + looper fixes after the first hw test + a debug trace.

User, v0.9 on hw: layer 1 fine; when layer 2 ended it landed on Roland's SAMPLING setup (0x20), loop 1
stopped, "Finished." popped up, and things felt slow ("loading").
Found:
- 0x13FC0E (go to screen) does nothing while 0x42790E bit 1 is set (the sampling lock: 0x13F2D0 sets it,
  0x13F2C2 sets bits 1-2, 0x13F2DA clears them). Stock uses 0x13FC8A to force it (unlock, switch, relock).
  Our looper cancel (double tap / hold / EXIT on 0x22) used the plain call: the jump was ignored, our state
  was already reset, so stock carried on (its record screen, "Finished.", SAMPLING setup, pads off).
  Now: unlock (0x13F2DA) before every looper jump back to screen 5.
- The commit (0x13F9C2) loops while current != pending (so a jump from event 0 is followed at once) and
  sends events 5 and 2 after that loop. Clearing MSTATE inside 0x23 event 2 let stock's own redraw draw
  "Finished.". Now event 2 only marks the take written; the layer is processed on the next 0x23 idle.
- w22/w23 test LOOPTAKE before MSTATE; screen 5 enter clears a stale LOOPTAKE.
- LOOP page / looper record frames: 4 per second (lp_draw is ~44k instructions).
Debug: ENTER on the LOOP page toggles a trace (last 15 looper events, letter + 4 hex digits):
  A arm (0 first, 1 overdub, FFFF no free pad)   S stop asked (1 tap, 2 auto)   E 0x23 enter: take wave
  P pending screen after 0x23 enter   W take written   D layer done: length units   F take failed
  C cancel (state)   X stop all   G jump back (go-to result, 1 = ok)   R tap (state)   H hold (state)
  plus a live line: M mstate, T looptake, S lstate, N layers, L lock byte 0x42790E.

v0.9 notes follow.
JSW v0.9 = v0.8 + LOOPER v1 (pad layers), all on the PAD SAMPLING button (= the user's footswitch).

Controls on the LOOP page (and while a looper take runs):
  tap            EMPTY -> REC (layer 1) -> tap closes the loop -> PLAY; PLAY -> DUB (a new layer, exactly
                 one loop long, ends by itself) -> PLAY; STOP -> PLAY (restart).
  double tap     (2nd press < 400 ms) stop all (cancels the take the 1st tap started); during REC: cancel.
  hold >= 1.2 s  (on release) UNDO the last layer (cancels the take the press started); if it was
                 stopped: CLEAR all layers. EXIT while recording cancels the take.
Engine:
- Layers = up to 4 free pads of the current bank, recorded with the stock sampler forced to Pad Play TRIG
  (0x4277CB = 1), Loop ON(S-E) (0x4277CC = 1), no auto trim/divide (0x4277CD/CE), overdubs INSTANT
  (0x4277C9 = 0); the user's settings are restored after each take.
- Pad entry (32 bytes, 0x4225B4 + 32 * pad): +0 start, +4 end, +8 loop point (longs, in 16-sample units:
  Roland's compressed blocks, 24 bytes stereo / 12 mono per unit; 0x14D584), +12 wave, +14 flags
  (bits 0-1 loop OFF/S-E/L-E, bits 2-3 pad play GATE 0 / TRIG 4 / DRUM 8, bit 7 mono; table 0x166012),
  +15 level, +16/+20 the recorded start/end. 0x122642 empties an entry, 0x122C1A frees a wave.
- Layer 1 sets the loop length LLEN (units). Every overdub is trimmed to exactly LLEN, so all layers loop
  sample-locked. The loop clock is LPHASE in units, advanced from the 1 ms counter (ms * 441 / 160, the
  remainder carried). An overdub starts at once (phase S) and later starts playing when the clock passes S
  again (spin-wait on the 1 ms counter for the last <= 60 ms). Restart: layer 1 at phase 0, the others at S.
- Pads keep playing while a looper take records: the stock "all pads off" (0x1371F4 @0x13C9D6) and the pad
  vtable switches (0x13704A @0x13C99E, 0x13CE62, 0x13CDFE; a switch stops all pads) are skipped while
  LOOPTAKE is set. The sampling vtable 0x1662D6 is the normal one plus "pad press starts an armed take".
- Single pad stop: 0x137448(r0 pad, r1l 0) (r1l 0xFF = by pad play mode: TRIG/DRUM ignore note-off).
- The take is written into its pad by stock 0x23 event 2; then we trim it and go back to the LOOP page.
v1.0: KEYS mode (SYSTEM / the KEYS tile): the pads play one sample from DSP1's delay RAM, 8 voices, pad 8 = root.
Not yet: MIDI control (the MIDI input path is table driven, still to find).

v0.8 notes follow.
JSW v0.8 = v0.7f + our own record / take-done screens + the 7-segment line as a ticker.

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

VERSION, VER_TXT = 1100, '1.0'
LOCK_BYTE = 0x42790E                        # bit 1: sampling lock (go-to-screen refused while set)
LP_FRAME_MS = 250                           # LOOP page refresh
# looper
PAD_PLAY_SET, LOOP_SET, AUTO_TRIM_SET, AUTO_DIV_SET = 0x4277CB, 0x4277CC, 0x4277CD, 0x4277CE
VT_SWITCH, ALL_PADS_OFF, STOP_PAD = 0x13704A, 0x1371F4, 0x137448
WAVE_FREE, ENTRY_EMPTY = 0x122C1A, 0x122642
TAKE_ENTRY, TAKE_WAVE = 0x4277D8, 0x4277E4
PATCH_VT, PATCH_OFF = (0x13C99E, 0x13CE62, 0x13CDFE), (0x13C9D6,)     # jsr 0x13704A / jsr 0x1371F4 sites
MAX_LAYERS, DTAP_MS, HOLD_MS, DUB_MARGIN_MS = 4, 400, 1200, 150
TRIG_WIN = 165                              # units (60 ms): spin-wait window for a layer start
MIN_UNITS, MAX_UNITS = 276, 165375          # 100 ms .. 60 s
LS_EMPTY, LS_REC1, LS_BUSY, LS_PLAY, LS_DUB, LS_STOP = range(6)
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
ANIM_BASE = 0x1A0000                        # moved from 0x170000: our code area grew past 20 KB
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
# ---- KEYS: our 8-voice sampler program in DSP1 (built by keysdsp.py, loaded with the OS's own DSP routines) ----
import keysdsp
DSP_BASE = 0x1B8000                         # the DSP1 program table (3 bytes per word) in free flash
DSP_LOAD, DSP_COEF, DSP_ERAM = 0x1096D2, 0x108936, 0x108B64      # load program / coef+shift field / ERAM group
MIXER_PARAM, FX_CUR, FX_ROUTE_CODE = 0x11F2AE, 0x403000, 0x4031B6  # param 7 = FX insert point; 0x0C = master insert
FX_MUTE_WORDS = (0x1D, 0x2B)                # base words the OS mutes (0xF800) while swapping programs
DSP_READBACK = 0xC00004                     # 4 readback bytes written by the DSP (hostreg)
KS_IDLE, KS_WAIT, KS_REC0, KS_REC, KS_PLAY = range(5)
KEYS_LEVEL, KEYS_MAX_MS, KEYS_ROOT = 48, 1480, 7                  # level target, 65536 samples, pad 8 = root
NV = keysdsp.NVOICES
DSP_PROG, DSP_PARAMS = keysdsp.build()
def dsp_addr(name): return 0x1000 | (DSP_PARAMS[name][1] << 2)
RATIOS = [keysdsp.delta_fields(2 ** ((p - KEYS_ROOT) / 12))[:3] for p in range(16)]

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
# looper (bytes, then longs)
(LSTATE, LOOPTAKE, NLAYER, LP_DISCARD, LPEND, LRUN, LMSG, LPRESSED, LST_AT_PRESS) = (RAM_BASE + 0x180 + i for i in range(9))
LSAVE = RAM_BASE + 0x18A                    # 5 bytes: pad play, loop, auto trim, auto divide, trigger
LAYPAD = RAM_BASE + 0x190                   # 4 bytes
LLEN_MS, LACC = RAM_BASE + 0x194, RAM_BASE + 0x196                  # words
LLEN, LPHASE, LCLK_LAST, LPRESS_T, LTAKE_PH, LDRAW_T = (RAM_BASE + 0x198 + 4 * i for i in range(6))
LAYPH = RAM_BASE + 0x1B0                    # 4 longs: the phase each layer starts at
LP_WRITTEN, LDEBUG, TR_POS = RAM_BASE + 0x1C0, RAM_BASE + 0x1C1, RAM_BASE + 0x1C2   # bytes
TRACE, TR_N = RAM_BASE + 0x1D0, 16          # 16 x (char, word)
DBGTXT = RAM_BASE + 0x200                   # 40 bytes
# KEYS (bytes at +0x240, longs at +0x260)
KSTATE, KSRC, KLOADED, KROUTE, KNEXT = (RAM_BASE + 0x240 + i for i in range(5))
VPAD, VSTATE = RAM_BASE + 0x248, RAM_BASE + 0x250                   # per voice: pad (0xFF free), state 0-3
KREC_T0, KREC_MS, KTICK = (RAM_BASE + 0x260 + 4 * i for i in range(3))
RAM_VARS = (PAGE, CUR, WARN, MSTATE, REC_PAD, REC_HOLD, MSG, MCUR, D_PATH, D_T0, D_T, D_P, D_RES, SAVED_OK, GMODE,
            BOOTSND, SEG_PG, PEAK, PEAK_HOLD, HIST_N, HIST_CNT, HIST_MAX, METER_N,
            LSTATE, LOOPTAKE, NLAYER, LP_DISCARD, LPEND, LRUN, LMSG, LPRESSED, LST_AT_PRESS,
            LP_WRITTEN, LDEBUG, TR_POS, KSTATE, KLOADED, KNEXT)
LP_MSGS = [('s_lm1', 'BANK FULL'), ('s_lm2', '4 LAYERS MAX'), ('s_lm3', 'TAKE CANCELED'), ('s_lm4', 'DISK FULL'),
           ('s_lm5', 'TOO SHORT')]                                  # LMSG 1-5
PLAY_ICON = ['X......', 'XXX....', 'XXXXX..', 'XXXXXXX', 'XXXXX..', 'XXX....', 'X......']
STOP_ICON = ['.......', '.XXXXX.', '.XXXXX.', '.XXXXX.', '.XXXXX.', '.XXXXX.', '.......']
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
    def trace(ch, setup):                  # debug trace: (letter, value made in r0 by setup()); keeps registers
        a.push_l(0); a.push_l(1)
        setup()
        a.mov_b_imm(ord(ch), 'r1l'); a.bsr16('tr_add')
        a.pop_l(1); a.pop_l(0)
    def trace_b(ch, var):                  # trace a byte variable
        trace(ch, lambda: (a.mov_b_from_abs(var, 'r0l'), a.extu_w(0)))
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
    a.bsr16('lp_idle')                            # looper clock, layer starts, LOOP page refresh
    a.bsr16('keys_idle')                          # KEYS: sampling timer / onset, pending note-ons
    a.mov_b_from_abs(BOOTSND, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('id_dial')   # boot sound: pad 16, once
    set_byte(BOOTSND, 1)
    a.mov_w_imm(BOOT_PAD, 0); a.mov_b_imm(127, 'r1l'); a.jsr(PAD_NOTE_ON)
    a.label('id_dial')                            # VALUE dial: turn it into arrow keys
    a.mov_w_from_abs(ENC_DELTA, 0); a.beq16('done')
    a.mov_b_from_abs(PAGE, 'r1l')
    a.cmp_b_imm(P_MPC, 'r1l'); a.beq('id_mpc')
    a.cmp_b_imm(P_KEYS, 'r1l'); a.beq('id_mpc')
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
    a.btst_abs(0, LOOPTAKE); a.beq('en_nolt')            # back home with a looper take still marked: drop it
    a.bsr16('lp_end_take'); set_byte(MSTATE, MS_IDLE); set_byte(LP_WRITTEN, 0)
    a.label('en_nolt')
    a.btst_abs(0, LP_DISCARD); a.beq('en_nodisc')        # a cancelled looper take: free its wave
    set_byte(LP_DISCARD, 0)
    a.mov_w_from_abs(TAKE_WAVE, 0); a.cmp_w_imm(0xFFFF, 0); a.beq('en_nowave'); a.jsr(WAVE_FREE)
    a.label('en_nowave')
    a.mov_l_imm(TAKE_ENTRY, 0); a.jsr(ENTRY_EMPTY)
    a.label('en_nodisc')
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
    a.cmp_b_imm(P_KEYS, 'r0l'); a.beq16('k_keys')
    a.cmp_b_imm(P_LOOP, 'r0l'); a.bne16('k_other')
    a.cmp_w_imm(K_ENTER, 5); a.bne16('k_other')                   # LOOP page: ENTER = debug trace on/off
    a.mov_b_from_abs(LDEBUG, 'r0l'); a.xor_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', LDEBUG); a.bra16('redraw')

    a.label('k_home')                                     # tiles: LEFT/RIGHT work like UP/DOWN
    a.cmp_w_imm(K_LEFT, 5); a.bne('kh_r'); a.mov_w_imm(K_UP, 5)
    a.label('kh_r')
    a.cmp_w_imm(K_RIGHT, 5); a.bne('kh_go'); a.mov_w_imm(K_DOWN, 5)
    a.label('kh_go')
    move_cursor(3, 'redraw')
    a.cmp_w_imm(K_ENTER, 5); a.bne16('done')
    a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(3, 'r0l'); a.beq16('goto_sys')
    a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', PAGE)
    a.cmp_b_imm(P_KEYS, 'r0l'); a.bne16('redraw'); a.bsr16('keys_enter'); a.bra16('redraw')
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

    a.label('k_keys')                                     # KEYS page
    a.cmp_w_imm(K_ENTER, 5); a.bne('kk_lr')
    a.bsr16('keys_sample'); a.bra16('redraw')
    a.label('kk_lr')
    a.cmp_w_imm(K_LEFT, 5); a.beq('kk_val')
    a.cmp_w_imm(K_RIGHT, 5); a.bne('kk_exit')
    a.label('kk_val')
    a.mov_b_from_abs(KSTATE, 'r0l'); a.cmp_b_imm(KS_IDLE, 'r0l'); a.beq('kk_pick')
    a.cmp_b_imm(KS_PLAY, 'r0l'); a.bne16('redraw')                 # the source pad changes while idle / after
    a.label('kk_pick')
    a.mov_b_from_abs(KSRC, 'r0l')
    a.cmp_w_imm(K_RIGHT, 5); a.bne('kk_prev')
    a.add_b_imm(1, 'r0l'); a.bra('kk_wrap')
    a.label('kk_prev'); a.add_b_imm(0xFF, 'r0l')
    a.label('kk_wrap'); a.and_w_imm(0x000F, 0); a.mov_b_to_abs('r0l', KSRC); a.bra16('redraw')
    a.label('kk_exit')
    a.cmp_w_imm(K_EXIT, 5); a.bne16('done')
    a.bsr16('keys_exit')

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
    a.mov_b_from_abs(PAGE, 'r0l'); a.cmp_b_imm(P_LOOP, 'r0l'); a.beq16('lp_draw')
    a.push_l(2); a.push_l(3)
    a.bsr16('gfx_clear')
    a.mov_b_from_abs(PAGE, 'r0l')
    a.cmp_b_imm(P_MPC, 'r0l'); a.beq16('d_mpc')
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

    # ---- KEYS page ----
    a.label('d_keys')
    D.text(1, 1, 's_keys')
    a.mov_b_from_abs(KSTATE, 'r0l'); a.cmp_b_imm(KS_PLAY, 'r0l'); a.beq16('dk_play')
    a.cmp_b_imm(KS_IDLE, 'r0l'); a.bne16('dk_rec')
    D.text(1, 11, 's_ksrc'); a.mov_b_from_abs(KSRC, 'r0l'); a.bsr16('dec2')          # SRC PAD nn
    a.mov_b_to_abs('r0h', PADSTR); a.mov_b_to_abs('r0l', PADSTR + 1); set_byte(PADSTR + 2, 0)
    D.text(49, 11, PADSTR)
    D.text(1, 27, 's_khelp', 'font_tiny'); a.bra16('dk_grid')
    a.label('dk_rec'); D.text(1, 11, 's_ksamp'); D.text(1, 27, 's_kwait', 'font_tiny'); a.bra16('dk_grid')
    a.label('dk_play'); D.text(1, 11, 's_kplay'); D.text(1, 27, 's_kphelp', 'font_tiny')
    a.label('dk_grid')                                    # 4x4 map: filled = a voice plays that pad / the source
    for p in range(16):
        x, y = GRID_X + (p % 4) * 7, GRID_Y + (3 - p // 4) * 7
        on, nx = uniq('ko'), uniq('kn')
        a.mov_w_imm(p, 0); a.bsr16('keys_pad_on'); a.mov_w_rr(0, 0); a.bne(on)
        D.frame(x, y, 6, 6); a.bra16(nx)
        a.label(on); D.fill(x, y, 6, 6)
        a.label(nx)
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

    # ================= KEYS: the pads play one sample held in DSP1's delay RAM (DSP program: keysdsp.py) ========
    def coef_val(name, c): return keysdsp.coef_value(DSP_PROG, DSP_PARAMS, name, c)
    def dsp_coef(name, c):                     # 0x108936: r0 = word address (chip 1), e0 = coef << 8 | shift sel
        a.mov_w_imm(coef_val(name, c), 8); a.mov_w_imm(dsp_addr(name), 0); a.jsr(DSP_COEF)
    def dsp_eram(name, mode, imm=0):           # 0x108B64: r0 = word address, er1 = packed mode + offset
        a.mov_l_imm(keysdsp.host_image_eram(mode, imm), 1); a.mov_w_imm(dsp_addr(name), 0); a.jsr(DSP_ERAM)
    def dsp_voice_coef(tab, c=None):           # voice in r6l: r0 = kt_<tab>[v]; e0 = c, or already set; write
        a.mov_b_rr('r6l', 'r1l'); a.extu_w(1); a.extu_l(1); a.add_l_rr(1, 1)         # er1 = 2 * voice
        a.mov_l_imm('kt_' + tab, 2); a.add_l_rr(1, 2); a.mov_w_ld(2, 0)              # r0 = table[v] (e0 untouched)
        if c is not None: a.mov_w_imm(coef_val('v0_' + tab, c), 8)
        a.jsr(DSP_COEF)
    def wait_ms(ms):
        lp = uniq('wt')
        a.mov_l_from_abs(TICK_MS, 1); a.add_l_imm(ms, 1)
        a.label(lp); a.mov_l_from_abs(TICK_MS, 0); a.cmp_l_rr(1, 0); a.bcs(lp)
    def k_since(var): a.mov_l_from_abs(TICK_MS, 0); a.mov_l_from_abs(var, 1); a.sub_l(1, 0)
    def on_keys_page(lbl_no):                  # branch to lbl_no unless the KEYS page is on screen
        a.mov_b_from_abs(PAGE, 'r0l'); a.cmp_b_imm(P_KEYS, 'r0l'); a.bne16(lbl_no)
        a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.bne16(lbl_no)
    def voices_silent():
        for v in range(NV): dsp_coef('v%d_t' % v, 0); set_byte(VSTATE + v, 0); set_byte(VPAD + v, 0xFF)

    a.label('keys_enter')                      # KEYS page opened: our program in DSP1, the master through the FX
    a.mov_b_from_abs(KLOADED, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('ke_loaded')
    a.bsr16('keys_load')
    a.label('ke_loaded')
    a.bsr16('keys_route_on')
    a.mov_b_from_abs(KSTATE, 'r0l'); a.cmp_b_imm(KS_PLAY, 'r0l'); a.beq('ke_out')     # a sample is loaded: keep it
    set_byte(KSTATE, KS_IDLE)
    dsp_coef('thru_l', 32); dsp_coef('thru_r', 32)                                   # hear the pads meanwhile
    a.label('ke_out'); a.rts()

    a.label('keys_load')                       # mute, swap the DSP1 algorithm for ours, set it up, unmute
    for w in FX_MUTE_WORDS: a.mov_w_imm(0xF800, 8); a.mov_w_imm(0x1000 | (w << 2), 0); a.jsr(DSP_COEF)
    wait_ms(15)
    a.mov_l_imm(DSP_BASE, 0); a.push_l(0)
    a.mov_w_imm(0x300 - 0x3C, 1); a.mov_w_imm(0x3C, 8); a.mov_w_imm(1, 0); a.jsr(DSP_LOAD); a.adds4(7)
    for v in range(NV): dsp_eram('v%d_rdA' % v, 0x18, 0); dsp_eram('v%d_rdB' % v, 0x18, 2)
    dsp_eram('rec_w0', 0); dsp_eram('rec_w1', 0)
    for v in range(NV): dsp_coef('v%d_t' % v, 0); dsp_coef('v%d_g' % v, 64)
    dsp_coef('age_g', 64); dsp_coef('rec_l', 32); dsp_coef('rec_r', 32); dsp_coef('thru_l', 0); dsp_coef('thru_r', 0)
    a.mov_w_imm(0xFFFF, 0); a.mov_w_to_abs(0, FX_CUR)         # the stock FX engine must reload its algorithm later
    for w in FX_MUTE_WORDS: a.mov_w_imm(0x0100, 8); a.mov_w_imm(0x1000 | (w << 2), 0); a.jsr(DSP_COEF)
    set_byte(KLOADED, 1)
    a.rts()

    a.label('keys_route_on')                   # FX insert point -> master (0x0C) through the OS mixer routine
    a.mov_b_from_abs(FX_ROUTE_CODE, 'r0l'); a.cmp_b_imm(0x0C, 'r0l'); a.beq('kr_done')
    a.mov_b_to_abs('r0l', KROUTE)
    a.mov_w_imm(0x0C, 1); a.mov_w_imm(0, 8); a.mov_w_imm(7, 0); a.jsr(MIXER_PARAM)
    set_byte(FX_ROUTE_CODE, 0x0C)
    a.label('kr_done'); a.rts()
    a.label('keys_route_off')
    a.mov_b_from_abs(KROUTE, 'r0l'); a.cmp_b_imm(0xFF, 'r0l'); a.beq('kro_done')
    a.mov_b_rr('r0l', 'r1l'); a.mov_b_imm(0, 'r1h'); a.mov_w_imm(0, 8); a.mov_w_imm(7, 0); a.jsr(MIXER_PARAM)
    a.mov_b_from_abs(KROUTE, 'r0l'); a.mov_b_to_abs('r0l', FX_ROUTE_CODE); set_byte(KROUTE, 0xFF)
    a.label('kro_done'); a.rts()

    a.label('keys_exit')                       # leaving the page: voices off, recording off, routing back
    voices_silent()
    a.mov_b_from_abs(KSTATE, 'r0l'); a.cmp_b_imm(KS_IDLE, 'r0l'); a.beq('kx_r'); a.cmp_b_imm(KS_PLAY, 'r0l'); a.beq('kx_r')
    a.bsr16('keys_rec_stop'); set_byte(KSTATE, KS_IDLE)
    a.label('kx_r')
    dsp_coef('thru_l', 0); dsp_coef('thru_r', 0)
    a.bsr16('keys_route_off')
    a.rts()

    a.label('keys_rec_stop')                   # writes off, the source pad stops
    dsp_eram('rec_w0', 0); dsp_eram('rec_w1', 0)
    a.mov_b_from_abs(KSRC, 'r0l'); a.extu_w(0); a.mov_b_imm(0, 'r1l'); a.jsr(STOP_PAD)
    a.rts()

    a.label('keys_sample')                     # ENTER: play the source pad through DSP1 and record it there
    a.mov_b_from_abs(KSTATE, 'r0l'); a.cmp_b_imm(KS_IDLE, 'r0l'); a.beq('ks_go')
    a.cmp_b_imm(KS_PLAY, 'r0l'); a.bne16('ks_out')
    a.label('ks_go')
    a.mov_b_from_abs(KSRC, 'r0l'); a.and_w_imm(0x000F, 0); a.jsr(PAD_USED); a.mov_w_rr(0, 0); a.beq16('ks_out')
    a.mov_b_from_abs(KSRC, 'r0h'); a.mov_b_from_abs(CUR_BANK, 'r0l'); a.mov_l_imm(SAVED, 1); a.jsr(PAD_GET)
    a.mov_l_from_abs(SAVED + 4, 0); a.mov_l_from_abs(SAVED, 1); a.sub_l(1, 0)         # units
    a.bsr16('u2ms')
    a.cmp_l_imm(KEYS_MAX_MS, 0); a.bcs('ks_len'); a.mov_l_imm(KEYS_MAX_MS, 0)
    a.label('ks_len'); a.add_l_imm(40, 0); a.mov_l_to_abs(0, KREC_MS)
    voices_silent()
    dsp_coef('thru_l', 32); dsp_coef('thru_r', 32)
    dsp_eram('rec_w0', 0x10, 0); dsp_eram('rec_w1', 0x10, 0x10000)
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, KREC_T0)
    set_byte(KSTATE, KS_WAIT)
    a.mov_b_from_abs(KSRC, 'r0l'); a.extu_w(0); a.mov_b_imm(127, 'r1l'); a.jsr(PAD_NOTE_ON)
    a.label('ks_out'); a.rts()

    a.label('keys_idle')                       # every main-loop pass while on screen 5
    a.mov_b_from_abs(KSTATE, 'r0l')
    a.cmp_b_imm(KS_WAIT, 'r0l'); a.beq('ki_wait')
    a.cmp_b_imm(KS_REC0, 'r0l'); a.beq16('ki_rec0')
    a.cmp_b_imm(KS_REC, 'r0l'); a.beq16('ki_rec')
    a.cmp_b_imm(KS_PLAY, 'r0l'); a.beq16('ki_voices')
    a.rts()
    a.label('ki_wait')                         # the DSP reports |input| (saturated) in the readback bytes
    a.bsr16('keys_signal'); a.mov_w_rr(0, 0); a.bne('ki_sig')
    k_since(KREC_T0); a.cmp_l_imm(2000, 0); a.bcs16('ki_out')                        # no sound in 2 s: give up
    a.bsr16('keys_rec_stop'); set_byte(KSTATE, KS_IDLE); a.bra16('ki_redraw')
    a.label('ki_sig')
    dsp_coef('age_g', 0)                                                             # age := 0 (held one pass)
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, KTICK)
    set_byte(KSTATE, KS_REC0); a.rts()
    a.label('ki_rec0')
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_from_abs(KTICK, 1); a.cmp_l_rr(1, 0); a.beq16('ki_out')   # next ms
    dsp_coef('age_g', 64)
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, KREC_T0)
    set_byte(KSTATE, KS_REC); a.bra16('ki_redraw')
    a.label('ki_rec')
    k_since(KREC_T0); a.mov_l_from_abs(KREC_MS, 1); a.cmp_l_rr(1, 0); a.bcs16('ki_out')
    a.bsr16('keys_rec_stop'); set_byte(KSTATE, KS_PLAY)
    dsp_coef('thru_l', 0); dsp_coef('thru_r', 0)
    a.label('ki_redraw')
    on_keys_page('ki_out')
    a.bsr16('draw')
    a.label('ki_out'); a.rts()
    a.label('ki_voices')                       # note-ons wrote g = 0 (phase reset); a ms later let them run
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_from_abs(KTICK, 1); a.cmp_l_rr(1, 0); a.beq('ki_out')
    for v in range(NV):
        nx = uniq('kv')
        a.mov_b_from_abs(VSTATE + v, 'r0l'); a.cmp_b_imm(1, 'r0l'); a.bne(nx)
        dsp_coef('v%d_g' % v, 64); dsp_coef('v%d_t' % v, KEYS_LEVEL); set_byte(VSTATE + v, 2)
        a.label(nx)
    a.rts()

    a.label('keys_signal')                     # r0 = 1 if any readback byte's low nibble is all ones
    for k in range(4):
        a.mov_b_from_abs(DSP_READBACK + k, 'r0l'); a.and_b_imm(0x0F, 'r0l'); a.cmp_b_imm(0x0F, 'r0l'); a.beq('ksg_yes')
    a.mov_w_imm(0, 0); a.rts()
    a.label('ksg_yes'); a.mov_w_imm(1, 0); a.rts()

    a.label('keys_note_on')                    # r0l = pad: next voice round robin, pitch = pad - root semitones
    a.push_l(2); a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_b_rr('r0l', 'r4l')
    a.mov_b_from_abs(KNEXT, 'r6l')
    a.mov_b_rr('r6l', 'r0l'); a.add_b_imm(1, 'r0l'); a.and_b_imm(NV - 1, 'r0l'); a.mov_b_to_abs('r0l', KNEXT)
    a.mov_b_rr('r6l', 'r0l'); a.extu_w(0); a.extu_l(0)
    a.mov_l_imm(VPAD, 1); a.add_l_rr(0, 1); a.mov_b_st('r4l', 1)
    a.mov_l_imm(VSTATE, 1); a.add_l_rr(0, 1); a.mov_b_imm(1, 'r0l'); a.mov_b_st('r0l', 1)
    a.mov_b_rr('r4l', 'r0l'); a.extu_w(0); a.extu_l(0); a.mov_l_rr(0, 5); a.add_l_rr(0, 5); a.add_l_rr(0, 5)
    a.add_l_rr(5, 5)                                                                 # er5 = pad * 6
    a.mov_l_imm('ratio_tab', 1); a.add_l_rr(1, 5)                                    # -> 3 coefficient values
    for tab in ('d2', 'd1', 'd0'):
        a.mov_w_ld(5, 8); a.adds1(5); a.adds1(5)                                     # e0 = value; er5 += 2
        dsp_voice_coef(tab)
    dsp_voice_coef('t', 0); dsp_voice_coef('g', 0)
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, KTICK)
    on_keys_page('kn_out'); a.bsr16('draw')
    a.label('kn_out'); a.pop_l(6); a.pop_l(5); a.pop_l(4); a.pop_l(2); a.rts()

    a.label('keys_note_off')                   # r0l = pad: release every voice playing it
    a.push_l(4); a.push_l(6)
    a.mov_b_rr('r0l', 'r4l')
    for v in range(NV):
        nx, off = uniq('nf'), uniq('nfo')
        a.mov_b_from_abs(VPAD + v, 'r0l'); a.cmp_b_rr('r4l', 'r0l'); a.bne(nx)
        set_byte(VPAD + v, 0xFF)
        a.mov_b_from_abs(VSTATE + v, 'r0l'); a.cmp_b_imm(2, 'r0l'); a.beq(off)
        set_byte(VSTATE + v, 0); a.bra(nx)                                           # not started yet: cancel
        a.label(off); dsp_coef('v%d_t' % v, 0); set_byte(VSTATE + v, 3)
        a.label(nx)
    on_keys_page('nf_out'); a.bsr16('draw')
    a.label('nf_out'); a.pop_l(6); a.pop_l(4); a.rts()

    a.label('keys_pad_on')                     # r0l = pad -> r0 = 1 if it should be lit on the map
    a.push_l(4); a.mov_b_rr('r0l', 'r4l')
    a.mov_b_from_abs(KSTATE, 'r0l'); a.cmp_b_imm(KS_PLAY, 'r0l'); a.beq('kp_play')
    a.mov_b_from_abs(KSRC, 'r0l'); a.cmp_b_rr('r4l', 'r0l'); a.beq16('kp_yes'); a.bra16('kp_no')
    a.label('kp_play')
    for v in range(NV):
        nx = uniq('kp')
        a.mov_b_from_abs(VSTATE + v, 'r0l'); a.cmp_b_imm(2, 'r0l'); a.bne(nx)
        a.mov_b_from_abs(VPAD + v, 'r0l'); a.cmp_b_rr('r4l', 'r0l'); a.beq16('kp_yes')
        a.label(nx)
    a.label('kp_no'); a.mov_w_imm(0, 0); a.pop_l(4); a.rts()
    a.label('kp_yes'); a.mov_w_imm(1, 0); a.pop_l(4); a.rts()

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
    a.btst_abs(0, LOOPTAKE); a.bne('sr_ok')                     # an MPC take stops all pads (stock):
    set_byte(LRUN, 0); set_byte(LPEND, 0)                       # the looper is stopped too
    a.mov_b_from_abs(LSTATE, 'r0l'); a.cmp_b_imm(LS_PLAY, 'r0l'); a.bne('sr_ok')
    set_byte(LSTATE, LS_STOP)
    a.label('sr_ok')
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
    a.btst_abs(0, LOOPTAKE); a.beq('g1_ours'); a.jmp(STOCK_G1)    # looper take: pads play as usual
    a.label('g1_ours')
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
    a.mov_w_rr(5, 0); a.and_w_imm(0x00F0, 0); a.cmp_w_imm(0x0010, 0); a.bne('g1_nk')      # a pad code?
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.bne('g1_nk')
    a.mov_b_from_abs(PAGE, 'r0l'); a.cmp_b_imm(P_KEYS, 'r0l'); a.beq16('g1_keys')
    a.label('g1_nk')
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
    a.label('g1_keys')                                       # KEYS page: the pads are the keyboard
    a.mov_b_from_abs(KSTATE, 'r0l'); a.cmp_b_imm(KS_PLAY, 'r0l'); a.bne('g1k_src')
    a.mov_w_rr(5, 0); a.and_w_imm(0x000F, 0)
    a.btst_imm(6, 'r5h'); a.bne('g1k_off')
    a.bsr16('keys_note_on'); a.bra('g1k_eat')
    a.label('g1k_off'); a.bsr16('keys_note_off')
    a.label('g1k_eat'); a.mov_w_imm(1, 0); a.pop_l(5); a.rts()
    a.label('g1k_src')                                       # not playing: a pad press picks the source (and plays)
    a.btst_imm(6, 'r5h'); a.bne16('g1_stock')
    a.cmp_b_imm(KS_IDLE, 'r0l'); a.bne('g1k_eat')            # sampling: pads do nothing
    a.mov_b_rr('r5l', 'r0l'); a.and_w_imm(0x000F, 0); a.mov_b_to_abs('r0l', KSRC)
    a.bsr16('draw')
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
    a.btst_abs(0, LOOPTAKE); a.bne('w22_ours')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.bne16('w22_stock')    # stock flows: stock screen
    a.label('w22_ours')
    a.cmp_w_imm(0x0005, 6); a.bne('w22_n5')
    a.bsr16('take_draw'); a.bra16('w22_ret')                    # redraw: ours only
    a.label('w22_n5')
    a.cmp_w_imm(0x0006, 6); a.bne('w22_n6')
    a.bsr16('rec_idle'); a.bra16('w22_ret')                     # idle: stock logic without its drawing
    a.label('w22_n6')
    a.cmp_w_imm(0x0000, 6); a.bne('w22_n0')
    a.mov_w_rr(6, 0); a.jsr(STOCK_SCR22)                        # enter: stock arms the take, then our state
    a.bsr16('rec_init')
    a.btst_abs(0, LOOPTAKE); a.beq16('w22_ret')
    a.bsr16('lp_clock'); a.mov_l_from_abs(LPHASE, 0); a.mov_l_to_abs(0, LTAKE_PH)   # overdub starts here
    a.bra16('w22_ret')
    a.label('w22_n0')
    a.cmp_w_imm(0x0009, 6); a.bne16('w22_stock')
    a.mov_w_from_abs(KEY_EVENT, 0); a.cmp_w_imm(K_EXIT, 0); a.bne('w22_pad')
    a.btst_abs(0, LOOPTAKE); a.beq('w22_mpcx')
    a.bsr16('lp_cancel'); set_byte(LMSG, 3); a.bra16('w22_ret') # looper take: EXIT cancels it
    a.label('w22_mpcx')
    set_byte(MSTATE, MS_IDLE); set_byte(MSG, 3); set_byte(D_PATH, 0)   # EXIT: cancel. Leaving 0x22 stops it,
    set_byte(PAGE, P_MPC)                                               # 0x23 never writes the take to a pad
    a.jsr(SMPL_UNLOCK)                                                  # (go-to is refused while locked)
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
    a.btst_abs(0, LOOPTAKE); a.bne16('w23_lp')
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
    # looper take: no keys, our page, the layer is processed as soon as stock has written it
    a.label('w23_lp')
    a.cmp_w_imm(0x0009, 6); a.beq16('w23_out')
    a.cmp_w_imm(0x0005, 6); a.bne('w23_l5')
    a.bsr16('lp_draw'); a.bra16('w23_out')
    a.label('w23_l5')
    a.cmp_w_imm(0x0006, 6); a.bne('w23_l6')
    a.bsr16('seg_tick'); a.bsr16('lp_clock'); a.bsr16('lp_sched')
    a.btst_abs(0, LP_WRITTEN); a.beq16('w23_out')               # first idle after stock wrote the take:
    set_byte(LP_WRITTEN, 0); a.bsr16('lp_layer_done'); a.bra16('w23_out')     # outside the commit
    a.label('w23_l6')
    a.cmp_w_imm(0x0002, 6); a.bne('w23_l2')
    a.mov_w_rr(6, 0); a.jsr(STOCK_SCR23)                        # stock writes the take into its pad
    set_byte(LP_WRITTEN, 1)
    trace('W', lambda: (a.mov_b_from_abs(SMP_PAD, 'r0l'), a.extu_w(0)))
    a.bsr16('lp_draw'); a.bra16('w23_out')                      # cover stock's "Now Working..."
    a.label('w23_l2')
    a.cmp_w_imm(0x0000, 6); a.bne16('w23_stock')
    trace('E', lambda: a.mov_w_from_abs(TAKE_WAVE, 0))
    a.mov_w_rr(6, 0); a.jsr(STOCK_SCR23)
    trace('P', lambda: a.mov_w_from_abs(PENDING_SCREEN, 0))
    a.mov_w_from_abs(PENDING_SCREEN, 0); a.and_w_imm(0x7FFF, 0)
    a.cmp_w_imm(SCR_PARAMS, 0); a.bne16('w23_out')
    a.bsr16('lp_take_failed'); a.bra16('w23_out')               # empty take

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
    a.label('g8_keys'); a.bsr16('keys_enter'); a.mov_b_imm(P_KEYS, 'r0l')
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
    a.mov_b_from_abs(PAGE, 'r0l'); a.cmp_b_imm(P_LOOP, 'r0l'); a.bne('g2_nl')      # looper: PAD SAMPLING
    a.btst_abs(0, LOOPTAKE); a.bne('g2_lp')                                         # (= footswitch) is ours
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.bne('g2_nl')
    a.label('g2_lp')
    a.mov_w_from_abs(KEY_EVENT, 0)
    a.cmp_w_imm(K_PADSMPL, 0); a.bne('g2_lr')
    a.bsr16('lp_press'); a.bra16('ret1')
    a.label('g2_lr')
    a.cmp_w_imm(K_PADSMPL | 0x4000, 0); a.bne('g2_nl')
    a.bsr16('lp_release'); a.bra16('ret1')
    a.label('g2_nl')
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
    def emit_meter(y0):                                         # 4 lit rows from y0, baseline, peak mark (uses r3l)
        nx = uniq('mt')
        a.mov_b_from_abs(METER_N, 'r3l'); a.mov_b_rr('r3l', 'r0l'); a.add_b_rr('r0l', 'r3l'); a.add_b_rr('r0l', 'r3l')
        a.inc_b('r3l')                                          # lit width 3n + 1
        for y in range(y0, y0 + 5):
            a.mov_l_imm('meter_pat', 0); a.mov_b_imm(y, 'r1h')
            if y < y0 + 4: a.mov_b_rr('r3l', 'r2l')
            else: a.mov_b_imm(128, 'r2l')                       # baseline under every segment
            a.bsr16('gfx_patrow')
        a.mov_b_from_abs(PEAK, 'r0l'); a.beq(nx)
        a.mov_b_rr('r0l', 'r1l'); a.add_b_rr('r0l', 'r1l'); a.add_b_rr('r0l', 'r1l'); a.add_b_imm(0x100 - 2, 'r1l')
        a.mov_b_imm(y0 - 1, 'r1h'); a.mov_b_imm(2, 'r2l'); a.mov_b_imm(6, 'r2h'); a.bsr16('gfx_fill')   # peak mark
        a.label(nx)
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
    a.btst_abs(0, LOOPTAKE); a.beq('ri_frame')
    a.bsr16('lp_clock'); a.bsr16('lp_sched')                    # looper: layers keep starting on time
    a.mov_b_from_abs(LSTATE, 'r0l'); a.cmp_b_imm(LS_DUB, 'r0l'); a.bne('ri_rec1')
    a.mov_w_from_abs(LLEN_MS, 0); a.extu_l(0); a.add_l_imm(DUB_MARGIN_MS, 0)       # overdub: one loop + margin
    a.bra('ri_lim')
    a.label('ri_rec1')
    a.mov_l_imm(MAX_UNITS * 160 // 441 + DUB_MARGIN_MS, 0)                          # first layer: 60 s max
    a.label('ri_lim')
    a.mov_l_from_abs(REC_MS, 1); a.cmp_l_rr(0, 1); a.bcs('ri_frame')
    set_byte(LSTATE, LS_BUSY); trace('S', lambda: a.mov_w_imm(2, 0))
    a.mov_w_imm(EV_STOCK_FINISH, 0); a.jmp(STOCK_SCR22)         # long enough: stock stops the take -> 0x23
    a.label('ri_frame')
    since(LAST_DRAW)
    a.btst_abs(0, LOOPTAKE); a.beq('ri_fr100')
    a.cmp_l_imm(LP_FRAME_MS, 0); a.bcs('ri_out'); a.bra('ri_fr')               # looper page: 4 per second
    a.label('ri_fr100')
    a.cmp_l_imm(FRAME_MS, 0); a.bcs('ri_out')
    a.label('ri_fr')
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, LAST_DRAW)
    a.bsr16('rec_frame'); a.bsr16('take_draw')
    a.label('ri_out')
    a.mov_w_imm(0, 0); a.rts()
    a.label('take_draw')                                        # our record screen or the LOOP page
    a.btst_abs(0, LOOPTAKE); a.beq16('rec_draw'); a.bra16('lp_draw')

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
    emit_meter(18)
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

    # ================= LOOPER (see docstring) =================
    SETS = (PAD_PLAY_SET, LOOP_SET, AUTO_TRIM_SET, AUTO_DIV_SET, TRIG_MODE)
    def layer_idx(var, reg, base):                              # er1 = base + @var (byte index); @er1 -> reg
        a.mov_b_from_abs(var, 'r0l'); a.extu_w(0); a.extu_l(0); a.mov_l_imm(base, 1); a.add_l_rr(0, 1)
        a.mov_b_ld(1, reg)

    # stock call sites that would stop the layers (patched in main())
    a.label('lp_vt')
    a.btst_abs(0, LOOPTAKE); a.bne('lpv_skip'); a.jmp(VT_SWITCH)
    a.label('lpv_skip'); a.rts()
    a.label('lp_off')
    a.btst_abs(0, LOOPTAKE); a.bne('lpv_skip'); a.jmp(ALL_PADS_OFF)

    a.label('u2ms')                                             # er0 units -> er0 ms (units < 180000); uses er1, r2
    a.mov_l_rr(0, 1); a.shl32(1, 5); a.shl32(0, 7); a.add_l_rr(1, 0)           # * 160
    a.mov_w_imm(441, 2); a.divxu_w(2, 0); a.extu_l(0); a.rts()

    a.label('lp_clock')                                         # LPHASE += elapsed ms * 441 / 160, mod LLEN
    a.btst_abs(0, LRUN); a.bne('lc_run'); a.rts()
    a.label('lc_run')
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_from_abs(LCLK_LAST, 1); a.mov_l_to_abs(0, LCLK_LAST)
    a.sub_l(1, 0)
    a.cmp_l_imm(20000, 0); a.bcs('lc_dt'); a.mov_l_imm(20000, 0)
    a.label('lc_dt')
    a.mov_w_imm(441, 1); a.mulxu_w(1, 0)
    a.mov_w_from_abs(LACC, 1); a.extu_l(1); a.add_l_rr(1, 0)
    a.mov_w_imm(160, 1); a.divxu_w(1, 0); a.mov_w_rr(8, 1); a.mov_w_to_abs(1, LACC)
    a.extu_l(0); a.mov_l_from_abs(LPHASE, 1); a.add_l_rr(0, 1)
    a.mov_l_from_abs(LLEN, 0)
    a.label('lc_wrap')
    a.cmp_l_rr(0, 1); a.bcs('lc_done'); a.sub_l(0, 1); a.bra('lc_wrap')
    a.label('lc_done')
    a.mov_l_to_abs(1, LPHASE); a.rts()

    # start pending layers: layer 1 starts the clock; layer n starts when the clock reaches its phase
    a.label('lp_sched')
    a.push_l(4)
    a.mov_b_from_abs(LPEND, 'r0l'); a.beq16('ls_out')
    a.btst_abs(0, LRUN); a.bne16('ls_run')
    a.btst_imm(0, 'r0l'); a.beq16('ls_out')
    a.sub_l(0, 0); a.mov_l_to_abs(0, LPHASE); a.mov_w_to_abs(0, LACC)
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, LCLK_LAST)
    set_byte(LRUN, 1); a.bclr_abs(0, LPEND)
    a.mov_b_from_abs(LAYPAD, 'r0l'); a.extu_w(0); a.mov_b_imm(127, 'r1l'); a.jsr(PAD_NOTE_ON)
    a.bra16('ls_out')
    a.label('ls_run')
    for i in range(1, MAX_LAYERS):
        nx, ok, spin = uniq('ls'), uniq('lo'), uniq('lsp')
        a.btst_abs(i, LPEND); a.beq16(nx)
        a.mov_l_from_abs(LAYPH + 4 * i, 0); a.mov_l_from_abs(LPHASE, 1); a.sub_l(1, 0)   # units to go
        a.bcc(ok); a.mov_l_from_abs(LLEN, 1); a.add_l_rr(1, 0)
        a.label(ok)
        a.cmp_l_imm(TRIG_WIN, 0); a.bhi16(nx)
        a.bsr16('u2ms'); a.mov_l_from_abs(TICK_MS, 4); a.add_l_rr(0, 4)              # er4 = start time
        a.label(spin)
        a.mov_l_from_abs(TICK_MS, 0); a.sub_l(4, 0); a.bmi(spin)
        a.bclr_abs(i, LPEND)
        a.mov_b_from_abs(LAYPAD + i, 'r0l'); a.extu_w(0); a.mov_b_imm(127, 'r1l'); a.jsr(PAD_NOTE_ON)
        a.bsr16('lp_clock'); a.bra16('ls_out')                                         # one start per pass
        a.label(nx)
    a.label('ls_out')
    a.pop_l(4); a.rts()

    a.label('lp_idle')                                          # screen 5 idle
    a.bsr16('lp_clock'); a.bsr16('lp_sched')
    a.mov_b_from_abs(PAGE, 'r0l'); a.cmp_b_imm(P_LOOP, 'r0l'); a.bne('li_out')
    a.btst_abs(0, LRUN); a.beq('li_out')
    since(LDRAW_T); a.cmp_l_imm(LP_FRAME_MS, 0); a.bcs('li_out')
    a.bra16('lp_draw')
    a.label('li_out'); a.rts()

    a.label('lp_redraw')                                        # after a state change
    a.mov_b_from_abs(PAGE, 'r0l'); a.cmp_b_imm(P_LOOP, 'r0l'); a.bne('lrd_x')
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCREEN, 0); a.beq16('lp_draw')
    a.cmp_w_imm(SCR_RECORD, 0); a.beq16('lp_draw')
    a.label('lrd_x'); a.rts()

    a.label('lp_end_take')                                      # the user's sampling settings back, take over
    for k, s in enumerate(SETS): a.mov_b_from_abs(LSAVE + k, 'r0l'); a.mov_b_to_abs('r0l', s)
    set_byte(LOOPTAKE, 0); a.rts()

    # r0l = 0: first layer, 1: overdub. Records into the first free pad.
    a.label('lp_take')
    a.push_l(6)
    a.mov_b_rr('r0l', 'r6l')
    a.jsr(FIRST_FREE_PAD); a.cmp_w_imm(0xFFFF, 0); a.bne('lt_pad')
    trace('A', lambda: a.mov_w_imm(0xFFFF, 0))
    set_byte(LMSG, 1); a.bsr16('lp_redraw'); a.bra16('lt_out')
    a.label('lt_pad')
    a.mov_b_rr('r0l', 'r6h')
    trace('A', lambda: (a.mov_b_rr('r6l', 'r0l'), a.extu_w(0)))
    for k, s in enumerate(SETS): a.mov_b_from_abs(s, 'r0l'); a.mov_b_to_abs('r0l', LSAVE + k)
    set_byte(PAD_PLAY_SET, 1); set_byte(LOOP_SET, 1); set_byte(AUTO_TRIM_SET, 0); set_byte(AUTO_DIV_SET, 0)
    a.mov_b_imm(LS_REC1, 'r0l'); a.mov_b_rr('r6l', 'r6l'); a.beq('lt_st')
    set_byte(TRIG_MODE, 0); a.mov_b_imm(LS_DUB, 'r0l')          # overdubs start at once
    a.label('lt_st'); a.mov_b_to_abs('r0l', LSTATE)
    set_byte(LOOPTAKE, 1); set_byte(PAGE, P_LOOP)
    a.mov_b_rr('r6h', 'r0l'); a.bsr16('start_rec')
    a.mov_b_from_abs(MSTATE, 'r0l'); a.cmp_b_imm(MS_REC, 'r0l'); a.beq('lt_out')
    a.bsr16('lp_end_take'); set_byte(LMSG, 4)                   # no room on the disk
    a.mov_b_imm(LS_EMPTY, 'r0l'); a.mov_b_rr('r6l', 'r6l'); a.beq('lt_back'); a.mov_b_imm(LS_PLAY, 'r0l')
    a.label('lt_back'); a.mov_b_to_abs('r0l', LSTATE); a.bsr16('lp_redraw')
    a.label('lt_out')
    a.pop_l(6); a.rts()

    # PAD SAMPLING / footswitch pressed
    a.label('lp_press')
    trace_b('R', LSTATE)
    set_byte(LMSG, 0); set_byte(LPRESSED, 1)
    a.mov_b_from_abs(LSTATE, 'r0l'); a.mov_b_to_abs('r0l', LST_AT_PRESS)
    since(LPRESS_T); a.mov_l_from_abs(TICK_MS, 1); a.mov_l_to_abs(1, LPRESS_T)
    a.cmp_l_imm(DTAP_MS, 0); a.bcc('lpp_single')
    a.mov_b_from_abs(LSTATE, 'r0l')                             # double tap
    a.cmp_b_imm(LS_DUB, 'r0l'); a.beq16('lp_stop_all'); a.cmp_b_imm(LS_PLAY, 'r0l'); a.beq16('lp_stop_all')
    a.cmp_b_imm(LS_REC1, 'r0l'); a.bne('lpp_single')
    a.bsr16('lp_cancel'); a.bra16('lp_redraw')
    a.label('lpp_single')
    a.mov_b_from_abs(LSTATE, 'r0l')
    a.cmp_b_imm(LS_EMPTY, 'r0l'); a.bne('lpp_n0'); a.mov_b_imm(0, 'r0l'); a.bra16('lp_take')
    a.label('lpp_n0')
    a.cmp_b_imm(LS_REC1, 'r0l'); a.bne('lpp_n1')
    set_byte(LSTATE, LS_BUSY); trace('S', lambda: a.mov_w_imm(1, 0)); a.bsr16('lp_redraw')
    a.mov_w_imm(EV_STOCK_FINISH, 0); a.jmp(STOCK_SCR22)         # closes the loop: stock stops the take -> 0x23
    a.label('lpp_n1')
    a.cmp_b_imm(LS_PLAY, 'r0l'); a.bne('lpp_n3')
    a.mov_b_from_abs(NLAYER, 'r0l'); a.cmp_b_imm(MAX_LAYERS, 'r0l'); a.bcs('lpp_dub')
    set_byte(LMSG, 2); a.bra16('lp_redraw')
    a.label('lpp_dub'); a.mov_b_imm(1, 'r0l'); a.bra16('lp_take')
    a.label('lpp_n3')
    a.cmp_b_imm(LS_STOP, 'r0l'); a.beq16('lp_restart')
    a.rts()

    # released: a hold (>= HOLD_MS) undoes the last layer, or clears all if it was stopped
    a.label('lp_release')
    a.btst_abs(0, LPRESSED); a.bne('lr_go'); a.rts()
    a.label('lr_go')
    set_byte(LPRESSED, 0)
    since(LPRESS_T); a.cmp_l_imm(HOLD_MS, 0); a.bcc('lr_hold'); a.rts()
    a.label('lr_hold')
    trace_b('H', LST_AT_PRESS)
    a.mov_b_from_abs(LST_AT_PRESS, 'r0l')
    a.cmp_b_imm(LS_STOP, 'r0l'); a.beq16('lp_clear')
    a.cmp_b_imm(LS_PLAY, 'r0l'); a.beq('lr_undo')
    a.cmp_b_imm(LS_EMPTY, 'r0l'); a.bne('lr_x')
    a.bsr16('lp_cancel'); a.bra16('lp_redraw')                  # from READY: drop the take the press started
    a.label('lr_undo')
    a.bsr16('lp_cancel'); a.bsr16('lp_undo'); a.bra16('lp_redraw')
    a.label('lr_x'); a.rts()

    # cancel the looper take that is recording (screen 0x22): leave without keeping, free its wave later
    a.label('lp_cancel')
    a.btst_abs(0, LOOPTAKE); a.beq('lk_x')
    a.mov_w_from_abs(CUR_SCREEN, 0); a.cmp_w_imm(SCR_RECORD, 0); a.bne('lk_x')
    a.mov_b_from_abs(LSTATE, 'r0l'); a.cmp_b_imm(LS_DUB, 'r0l'); a.beq('lk_dub')
    a.cmp_b_imm(LS_REC1, 'r0l'); a.bne('lk_x')
    set_byte(LSTATE, LS_EMPTY); a.bra('lk_go')
    a.label('lk_dub'); set_byte(LSTATE, LS_PLAY)
    a.label('lk_go')
    trace_b('C', LSTATE)
    set_byte(LP_DISCARD, 1); set_byte(MSTATE, MS_IDLE)
    a.bsr16('lp_end_take')
    a.bsr16('lp_go5')
    a.label('lk_x'); a.rts()

    a.label('lp_go5')                                           # back to screen 5: unlock first (stock 0x13FC8A
    a.jsr(SMPL_UNLOCK)                                          # does the same), or the jump is ignored
    a.mov_w_imm(SCREEN, 0); a.jsr(GOTO_SCREEN)
    trace('G', lambda: None)
    a.rts()

    a.label('lp_stop_all')
    trace_b('X', NLAYER)
    a.bsr16('lp_cancel')
    a.jsr(ALL_PADS_OFF); set_byte(LRUN, 0); set_byte(LPEND, 0)
    a.mov_b_from_abs(NLAYER, 'r0l'); a.beq('lsa_e')
    set_byte(LSTATE, LS_STOP); a.bra16('lp_redraw')
    a.label('lsa_e'); set_byte(LSTATE, LS_EMPTY); a.bra16('lp_redraw')

    a.label('lp_restart')                                       # all layers from the top
    a.jsr(ALL_PADS_OFF); set_byte(LRUN, 0)
    layer_idx(NLAYER, 'r0l', 'lp_masks'); a.mov_b_to_abs('r0l', LPEND)
    set_byte(LSTATE, LS_PLAY); a.bra16('lp_redraw')

    a.label('lp_undo')                                          # stop + free the last layer
    a.push_l(6)
    a.mov_b_from_abs(NLAYER, 'r6l'); a.beq16('lu_out')
    a.dec_b('r6l'); a.mov_b_to_abs('r6l', NLAYER)
    layer_idx(NLAYER, 'r6h', LAYPAD)
    a.mov_b_rr('r6h', 'r0l'); a.extu_w(0); a.mov_b_imm(0, 'r1l'); a.jsr(STOP_PAD)
    a.mov_b_rr('r6h', 'r0l'); a.bsr16('lp_free_pad')
    layer_idx(NLAYER, 'r0h', 'lp_masks')
    a.mov_b_from_abs(LPEND, 'r0l'); a.and_b_rr('r0h', 'r0l'); a.mov_b_to_abs('r0l', LPEND)
    a.mov_b_from_abs(NLAYER, 'r0l'); a.bne('lu_out')
    a.jsr(ALL_PADS_OFF); set_byte(LRUN, 0); set_byte(LPEND, 0); set_byte(LSTATE, LS_EMPTY)
    a.label('lu_out')
    a.pop_l(6); a.rts()

    a.label('lp_clear')
    a.label('lcl_loop')
    a.mov_b_from_abs(NLAYER, 'r0l'); a.beq('lcl_done'); a.bsr16('lp_undo'); a.bra('lcl_loop')
    a.label('lcl_done')
    a.jsr(ALL_PADS_OFF); set_byte(LRUN, 0); set_byte(LPEND, 0); set_byte(LSTATE, LS_EMPTY)
    a.bra16('lp_redraw')

    a.label('lp_free_pad')                                      # r0l = pad: free its wave, empty the entry
    a.push_l(6)
    a.mov_b_rr('r0l', 'r6h'); a.mov_b_from_abs(CUR_BANK, 'r6l')
    a.sub_l_imm(32, 7)
    a.mov_w_rr(6, 0); a.mov_l_rr(7, 1); a.jsr(PAD_GET)
    a.mov_w_rr(0, 0); a.beq('lf_out')
    a.mov_w_disp(12, 7, 0); a.cmp_w_imm(0xFFFF, 0); a.beq('lf_nw'); a.jsr(WAVE_FREE)
    a.label('lf_nw')
    a.mov_l_rr(7, 0); a.jsr(ENTRY_EMPTY)
    a.mov_w_rr(6, 0); a.mov_l_rr(7, 1); a.jsr(PAD_SET)
    a.mov_w_imm(0, 8); a.mov_b_imm(0, 'r0l'); a.jsr(PAD_SET_POST)
    a.mov_w_imm(1, 0); a.jsr(PAD_REFRESH)
    a.label('lf_out')
    a.add_l_imm(32, 7)
    a.pop_l(6); a.rts()

    a.label('lp_take_failed')                                   # empty take (0x23 event 0 -> 0x20)
    trace('F', lambda: a.mov_w_imm(0, 0))
    set_byte(MSTATE, MS_IDLE); set_byte(LP_WRITTEN, 0)
    a.bsr16('lp_end_take')
    a.mov_b_from_abs(NLAYER, 'r0l'); a.beq('ltf_e'); set_byte(LSTATE, LS_PLAY); a.bra('ltf_go')
    a.label('ltf_e'); set_byte(LSTATE, LS_EMPTY)
    a.label('ltf_go'); set_byte(PAGE, P_LOOP)
    a.bra16('lp_go5')

    # 0x23 event 2, after stock wrote the take into its pad: trim to the loop, TRIG + loop, register the layer
    a.label('lp_layer_done')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.sub_l_imm(32, 7)
    a.mov_b_from_abs(SMP_PAD, 'r6h'); a.mov_b_from_abs(SMP_BANK, 'r6l')
    a.mov_w_rr(6, 0); a.mov_l_rr(7, 1); a.jsr(PAD_GET)
    a.mov_w_rr(0, 0); a.beq16('ld_fail')
    a.mov_w_disp(12, 7, 0); a.cmp_w_imm(0xFFFF, 0); a.beq16('ld_fail')   # no wave: nothing recorded
    a.mov_l_ind(7, 5); a.mov_l_ld_disp(4, 7, 4); a.sub_l(5, 4)            # er5 = start, er4 = length
    trace('D', lambda: a.mov_w_rr(4, 0))
    a.mov_b_from_abs(NLAYER, 'r0l'); a.bne16('ld_dub')
    a.cmp_l_imm(MIN_UNITS, 4); a.bcs16('ld_short')              # first layer sets the loop (100 ms .. 60 s)
    a.cmp_l_imm(MAX_UNITS, 4); a.bcs('ld_l1'); a.mov_l_imm(MAX_UNITS, 4)
    a.label('ld_l1')
    a.mov_l_to_abs(4, LLEN); a.mov_l_rr(4, 0); a.bsr16('u2ms'); a.mov_w_to_abs(0, LLEN_MS)
    a.sub_l(0, 0); a.mov_l_to_abs(0, LAYPH); set_byte(LRUN, 0)
    a.bra('ld_set')
    a.label('ld_dub')
    a.mov_l_from_abs(LLEN, 0); a.cmp_l_rr(0, 4); a.bcs('ld_set'); a.mov_l_rr(0, 4)   # exactly one loop
    a.label('ld_set')
    a.mov_l_rr(5, 0); a.add_l_rr(4, 0); a.mov_l_st_disp(0, 4, 7)           # end = start + length
    a.mov_l_st_disp(5, 8, 7)                                                 # loop point = start
    a.mov_b_ld_disp(14, 7, 'r0l'); a.and_b_imm(0xF0, 'r0l'); a.or_b_imm(0x05, 'r0l')   # TRIG, loop S-E
    a.mov_b_st_disp('r0l', 14, 7)
    a.mov_w_rr(6, 0); a.mov_l_rr(7, 1); a.jsr(PAD_SET)
    a.mov_w_imm(0, 8); a.mov_b_imm(0, 'r0l'); a.jsr(PAD_SET_POST)
    a.mov_w_imm(1, 0); a.jsr(PAD_REFRESH)
    for li in range(MAX_LAYERS):                                # layer li = NLAYER: pad, phase, start pending
        nx = uniq('ldn')
        a.mov_b_from_abs(NLAYER, 'r0l'); a.cmp_b_imm(li, 'r0l'); a.bne16(nx)
        a.mov_b_to_abs('r6h', LAYPAD + li)
        if li: a.mov_l_from_abs(LTAKE_PH, 0); a.mov_l_to_abs(0, LAYPH + 4 * li)
        a.bset_abs(li, LPEND); a.bra16('ld_reg')
        a.label(nx)
    a.label('ld_reg')
    a.mov_b_from_abs(NLAYER, 'r0l'); a.inc_b('r0l'); a.mov_b_to_abs('r0l', NLAYER)
    set_byte(LSTATE, LS_PLAY); a.bra16('ld_end')
    a.label('ld_short')                                         # under 100 ms: drop it
    a.mov_b_rr('r6h', 'r0l'); a.bsr16('lp_free_pad'); set_byte(LMSG, 5)
    a.label('ld_fail')
    a.mov_b_from_abs(NLAYER, 'r0l'); a.beq('ld_fe'); set_byte(LSTATE, LS_PLAY); a.bra('ld_end')
    a.label('ld_fe'); set_byte(LSTATE, LS_EMPTY)
    a.label('ld_end')
    a.add_l_imm(32, 7)
    a.bclr_abs(6, SMP_FLAGS_LO)
    set_byte(MSTATE, MS_IDLE); a.bsr16('lp_end_take'); set_byte(PAGE, P_LOOP)
    a.bsr16('lp_go5')
    a.pop_l(6); a.pop_l(5); a.pop_l(4); a.rts()

    # ---- debug trace (ENTER on the LOOP page) ----
    a.label('tr_add')                                           # r1l letter, r0 value -> ring (keeps er0, er1)
    a.push_l(2)
    a.mov_b_from_abs(TR_POS, 'r2l'); a.mov_b_imm(3, 'r2h'); a.mulxu_b('r2h', 2); a.extu_l(2); a.add_l_imm(TRACE, 2)
    a.mov_b_st('r1l', 2); a.mov_b_st_disp('r0h', 1, 2); a.mov_b_st_disp('r0l', 2, 2)
    a.mov_b_from_abs(TR_POS, 'r2l'); a.inc_b('r2l'); a.and_b_imm(TR_N - 1, 'r2l'); a.mov_b_to_abs('r2l', TR_POS)
    a.pop_l(2); a.rts()
    a.label('hex4')                                             # r0 -> 4 hex digits @er1+ (uses r2)
    a.push_l(0); a.mov_b_rr('r0h', 'r0l'); a.bsr16('hex2'); a.pop_l(0)
    a.label('hex2')                                             # r0l -> 2 hex digits @er1+
    a.mov_b_rr('r0l', 'r2l')
    for _ in range(4): a.shlr_b('r2l')
    a.bsr16('hexd')
    a.mov_b_rr('r0l', 'r2l'); a.and_b_imm(0x0F, 'r2l')
    a.label('hexd')
    a.add_b_imm(0x30, 'r2l'); a.cmp_b_imm(0x3A, 'r2l'); a.bcs('hd_ok'); a.add_b_imm(7, 'r2l')
    a.label('hd_ok'); a.mov_b_st('r2l', 1); a.adds1(1); a.rts()
    a.label('tr_fmt')                                           # entry r3l (mod 16) -> "Xhhhh " @er1+
    a.mov_b_rr('r3l', 'r2l'); a.and_b_imm(TR_N - 1, 'r2l'); a.mov_b_imm(3, 'r2h'); a.mulxu_b('r2h', 2)
    a.extu_l(2); a.add_l_imm(TRACE, 2)
    a.mov_b_ld(2, 'r0l'); a.bne('tf_l'); a.mov_b_imm(ord('-'), 'r0l')
    a.label('tf_l'); a.mov_b_st('r0l', 1); a.adds1(1)
    a.mov_b_ld_disp(1, 2, 'r0h'); a.mov_b_ld_disp(2, 2, 'r0l'); a.bsr16('hex4')
    putc(' '); a.rts()
    a.label('lp_draw_dbg')
    a.push_l(2); a.push_l(3)
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, LDRAW_T)
    a.bsr16('gfx_clear')
    a.mov_l_imm(DBGTXT, 1)
    for ch, var in (('M', MSTATE), ('T', LOOPTAKE), ('S', LSTATE), ('N', NLAYER)):
        putc(ch); a.mov_b_from_abs(var, 'r0l'); a.add_b_imm(0x30, 'r0l'); a.mov_b_st('r0l', 1); a.adds1(1); putc(' ')
    putc('L'); a.mov_b_from_abs(LOCK_BYTE, 'r0l'); a.bsr16('hex2'); putc(' ')
    putc('P'); a.mov_b_from_abs(LPEND, 'r0l'); a.bsr16('hex2'); putc('\0')
    D.text(1, 1, DBGTXT, 'font_tiny')
    for line in range(3):                                       # the last 15 events, oldest first
        a.mov_l_imm(DBGTXT, 1)
        for k in range(5):
            a.mov_b_from_abs(TR_POS, 'r3l'); a.add_b_imm(1 + 5 * line + k, 'r3l'); a.bsr16('tr_fmt')
        putc('\0')
        D.text(1, 8 + 6 * line, DBGTXT, 'font_tiny')
    D.text(1, 27, 's_dbghelp', 'font_tiny')
    a.bsr16('gfx_flush')
    a.pop_l(3); a.pop_l(2); a.rts()

    # ---- LOOP page ----
    LP_STATES = [(LS_EMPTY, 'icon_recring', 's_ls0', 's_lh0'), (LS_REC1, 'icon_recdot', 's_ls1', None),
                 (LS_BUSY, 'icon_recring', 's_ls2', 's_lh2'), (LS_PLAY, 'icon_play', 's_ls3', 's_lh3'),
                 (LS_DUB, 'icon_recdot', 's_ls4', None), (LS_STOP, 'icon_stop', 's_ls5', 's_lh5')]
    a.label('lp_draw')
    a.btst_abs(0, LDEBUG); a.bne16('lp_draw_dbg')
    a.push_l(2); a.push_l(3)
    a.mov_l_from_abs(TICK_MS, 0); a.mov_l_to_abs(0, LDRAW_T)
    a.bsr16('gfx_clear')
    for st, icon, lbl, help_ in LP_STATES:                      # icon + state, help line (or meter)
        nx, nb = uniq('lws'), uniq('lwb')
        a.mov_b_from_abs(LSTATE, 'r0l'); a.cmp_b_imm(st, 'r0l'); a.bne16(nx)
        if help_ is None:
            a.mov_l_from_abs(REC_MS, 0); a.btst_imm(1, 'r0h'); a.bne(nb)        # blinking dot
        D.bitmap(1, 1, icon)
        a.label(nb)
        D.text(11, 1, lbl)
        if help_: D.text(1, 27, help_, 'font_tiny')
        else: emit_meter(27)
        a.label(nx)
    # big time: the take while recording layer 1, the loop position while running, else the loop length
    a.mov_b_from_abs(LSTATE, 'r0l'); a.cmp_b_imm(LS_REC1, 'r0l'); a.bne('lw_t1')
    a.mov_l_from_abs(REC_MS, 0); a.bra('lw_t')
    a.label('lw_t1')
    a.btst_abs(0, LRUN); a.beq('lw_t2'); a.mov_l_from_abs(LPHASE, 0); a.bsr16('u2ms'); a.bra('lw_t')
    a.label('lw_t2')
    a.sub_l(0, 0); a.mov_b_from_abs(NLAYER, 'r1l'); a.beq('lw_t'); a.mov_w_from_abs(LLEN_MS, 0)
    a.label('lw_t')
    a.mov_l_imm(TXT, 1); a.bsr16('fmt_time'); D.text(72, 1, TXT, 'font_big')
    # "LEN 4.2S  2/4"
    a.mov_b_from_abs(NLAYER, 'r0l'); a.beq16('lw_noinfo')
    a.mov_l_imm(TXT, 1); puts_ram('LEN ')
    a.mov_w_from_abs(LLEN_MS, 0); a.extu_l(0); a.bsr16('fmt_len'); a.subs1(1)
    a.mov_b_rr('r0l', 'r0l'); a.beq('lw_nos'); putc('S')
    a.label('lw_nos')
    puts_ram('  ')
    a.mov_b_from_abs(NLAYER, 'r0l'); a.add_b_imm(0x30, 'r0l'); a.mov_b_st('r0l', 1); a.adds1(1)
    puts_ram('/%d\0' % MAX_LAYERS)
    D.text(1, 10, TXT, 'font_tiny')
    a.label('lw_noinfo')
    # layer boxes: running = filled, waiting to start / stopped = outline, recording = blinking
    for i in range(MAX_LAYERS):
        x, y, w, h = 1 + 32 * i, 15, 30, 9
        lbl = 's_L%d' % (i + 1)
        nl, pend, rec, emp, nx = uniq('lwn'), uniq('lwp'), uniq('lwr'), uniq('lwe'), uniq('lwx')
        a.mov_b_from_abs(NLAYER, 'r0l'); a.cmp_b_imm(i, 'r0l'); a.bls16(nl)
        a.btst_abs(i, LPEND); a.bne(pend)
        a.btst_abs(0, LRUN); a.beq(pend)
        D.fill(x, y, w, h); D.mode(gfxlib.M_CLR); D.text(x + 11, y + 2, lbl, 'font_tiny'); D.mode(gfxlib.M_SET)
        a.bra16(nx)
        a.label(pend)
        D.frame(x, y, w, h); D.text(x + 11, y + 2, lbl, 'font_tiny'); a.bra16(nx)
        a.label(nl)                                             # r0l = NLAYER
        a.cmp_b_imm(i, 'r0l'); a.bne16(emp)
        a.mov_b_from_abs(LSTATE, 'r0l')
        a.cmp_b_imm(LS_REC1, 'r0l'); a.beq(rec); a.cmp_b_imm(LS_DUB, 'r0l'); a.beq(rec)
        a.cmp_b_imm(LS_BUSY, 'r0l'); a.beq(pend); a.bra16(emp)
        a.label(rec)
        a.mov_l_from_abs(REC_MS, 0); a.btst_imm(1, 'r0h'); a.bne(pend)
        D.fill(x, y, w, h); D.mode(gfxlib.M_CLR); D.text(x + 11, y + 2, lbl, 'font_tiny'); D.mode(gfxlib.M_SET)
        a.bra16(nx)
        a.label(emp)
        D.fill(x, y + h - 1, w, 1); D.text(x + 11, y + 2, lbl, 'font_tiny')
        a.label(nx)
    # loop position bar under the boxes
    a.btst_abs(0, LRUN); a.beq('lw_nobar')
    a.mov_l_from_abs(LPHASE, 0); a.mov_l_from_abs(LLEN, 1)
    a.label('lw_sh')
    a.cmp_l_imm(0xFFFF, 1); a.bls('lw_div'); a.shlr_l(0); a.shlr_l(1); a.bra('lw_sh')
    a.label('lw_div')
    a.shl32(0, 7); a.divxu_w(1, 0)
    a.mov_b_rr('r0l', 'r2l'); a.beq('lw_nobar')
    a.mov_b_imm(0, 'r1l'); a.mov_b_imm(25, 'r1h'); a.mov_b_imm(1, 'r2h'); a.bsr16('gfx_fill')
    a.label('lw_nobar')
    for k, (plbl, s) in enumerate(LP_MSGS, 1):
        nx = uniq('lwm')
        a.mov_b_from_abs(LMSG, 'r0l'); a.cmp_b_imm(k, 'r0l'); a.bne16(nx)
        D.popup(plbl, len(s))
        a.label(nx)
    a.bsr16('gfx_flush')
    a.pop_l(3); a.pop_l(2); a.rts()

    # ================= graphics engine + data =================
    gfxlib.emit(a, FB, GMODE)
    a.label('icon_play'); a.raw(gfxlib.bitmap(PLAY_ICON))
    a.label('icon_stop'); a.raw(gfxlib.bitmap(STOP_ICON))
    a.label('lp_masks'); a.raw(bytes([0, 1, 3, 7, 15, 31]))
    for lbl, s in (LP_MSGS + [('s_ls0', 'READY'), ('s_ls1', 'REC'), ('s_ls2', 'SAVE'), ('s_ls3', 'PLAY'),
                              ('s_ls4', 'DUB'), ('s_ls5', 'STOP'), ('s_lh0', 'TAP=REC  EXIT=HOME'),
                              ('s_lh2', 'SAVING LAYER...'), ('s_lh3', 'TAP=DUB 2X=STOP HOLD=UNDO'),
                              ('s_lh5', 'TAP=PLAY  HOLD=CLEAR'), ('s_dbghelp', 'TRACE  ENTER=BACK')] +
                       [('s_L%d' % (i + 1), 'L%d' % (i + 1)) for i in range(MAX_LAYERS)]):
        a.label(lbl); a.string(s)
    a.align2()
    a.align2()
    a.label('seg_font'); a.raw(seg_font())
    a.label('meter_pat'); a.raw(meter_pattern())
    a.label('meter_tab'); a.raw(meter_table())
    a.label('env_tab'); a.raw(env_table())
    a.label('grid_xy')
    for p in range(16): a.raw(bytes((GRID_X + (p % 4) * 7, GRID_Y + (3 - p // 4) * 7)))
    a.align2()
    a.label('ratio_tab')                                       # pad -> the 3 pitch coefficient values (e0 format)
    for c2, c1, c0 in RATIOS: a.raw(struct.pack('>HHH', c2 << 8, c1 << 8, c0 << 8))
    for tab in ('t', 'g', 'd2', 'd1', 'd0'):                   # voice -> DSP word address of each field
        a.label('kt_' + tab); a.raw(struct.pack('>%dH' % NV, *[dsp_addr('v%d_%s' % (v, tab)) for v in range(NV)]))
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
                   ('s_soon', 'COMING SOON'), ('s_exithelp', 'EXIT=HOME'),
                   ('s_ksrc', 'SRC PAD'), ('s_khelp', 'PADS=PICK ENTER=SAMPLE'), ('s_ksamp', 'SAMPLING...'),
                   ('s_kwait', 'EXIT=CANCEL'), ('s_kplay', 'PLAY ROOT=PAD 8'), ('s_kphelp', 'PADS=NOTES EXIT=HOME')):
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
    tab = keysdsp.rom_table(DSP_PROG)                          # the DSP1 program, 708 words x 3 bytes
    o = DSP_BASE - 0x100000
    assert not any(img[o:o + len(tab)]), 'DSP table flash not empty'
    img[o:o + len(tab)] = tab

    def patch_screen(idx, want_handler, new_handler, params=None, page=None):
        e = SCREEN_TABLE - 0x100000 + 22 * idx
        fl, h, pa, pg, x, par = struct.unpack('>IIIIIH', img[e:e + 22])
        assert h == want_handler, 'screen %x handler %x' % (idx, h)
        img[e:e + 22] = struct.pack('>IIIIIH', fl, new_handler,
                                    pa if params is None else params, pg if page is None else page, x, par)
    patch_screen(SCREEN, 0x13D224, labels['menu'], params=0xFFFFFFFF, page=0)
    patch_screen(SCR_RECORD, STOCK_SCR22, labels['w22'])
    patch_screen(SCR_DONE, STOCK_SCR23, labels['w23'])
    for sites, target, ours in ((PATCH_VT, VT_SWITCH, 'lp_vt'), (PATCH_OFF, ALL_PADS_OFF, 'lp_off')):
        for s in sites:                         # looper takes must not stop the playing layers
            o = s - 0x100000
            assert img[o:o + 4] == bytes([0x5E]) + target.to_bytes(3, 'big'), 'site %X' % s
            img[o + 1:o + 4] = labels[ours].to_bytes(3, 'big')
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
        a.mov_b_imm(0, 'r0l')
        for i in range(NV): a.mov_b_to_abs('r0l', VSTATE + i)
        a.mov_b_imm(0xFF, 'r0l'); a.mov_b_to_abs('r0l', KROUTE)
        for i in range(NV): a.mov_b_to_abs('r0l', VPAD + i)
    ablob, alabels = bootanim.patch(img, ANIM_BASE, ram_init)
    assert ANIM_BASE + len(ablob) < DSP_BASE
    p = SPLASH2_AT - 0x100000
    assert bytes(img[p:p + len(SPLASH2_WAS)]) == SPLASH2_WAS, 'splash 2 code changed?'
    img[p:p + len(SPLASH2_NEW)] = SPLASH2_NEW

    v = struct.pack('>H', VERSION)
    for o in VER_HDR: img[o:o + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_v10.bin'), 'wb').write(img)
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(struct.pack('>II', 0x100000, 0x1C0000) + img)
    print('v1.0 built: %d bytes at 0x%X + boot anim %d bytes at 0x%X + DSP1 program %d bytes at 0x%X, version %d'
          % (len(blob), CODE_BASE, len(ablob), ANIM_BASE, len(tab), DSP_BASE, VERSION))
    for k in ('menu', 'draw', 'take_key', 'start_rec', 'g1', 'pick', 'assign', 'w22', 'w23', 'keep', 'g8', 'g2',
              'rec_idle', 'rec_draw', 'done_draw', 'seg_tick', 'lp_press', 'lp_layer_done', 'lp_draw',
              'keys_enter', 'keys_load', 'keys_sample', 'keys_idle', 'keys_note_on', 'd_keys'):
        print('  %-10s 0x%X' % (k, labels[k]))


if __name__ == '__main__':
    main(*sys.argv[1:3])
