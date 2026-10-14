# SP-808 controls map (OS v1.05, found 2026-10-13)

Sources:
- the factory self-test code (SW / FADER / POT / BEAM / FOOT SW / ENCORDER CHECK at 0x11C000-0x11DF00)
- the key tables at 0x15F9E8 (names) and 0x16414C (matrix → logical code)

"Inferred" = read from code, not yet confirmed by moving the control on the unit.

## Buttons (key matrix, 80 slots)
- **Event:** RAM `0x4278BA` (word). Low byte = logical code, `+0x100` = SHIFT held, `+0x4000` = release / second action.
- **Is key held now:** `0x1313A6(code)`, which goes through the boot API `0x400494`.
- **LED on/blink:** boot API `0x4004B8(code)` (inferred: the encoder test blinks REC/PLAY with it).
- **LEDs (OS API, 2026-10-15):** `0x132866(code)` on, `0x132880(code)` off, blink variants 0x13289A / 0x1328E0 /
  0x1328FC / 0x132934 / 0x132944; state bits 0x427390 + 2 * (code >> 4), mask table 0x16464E[code & 15]. 65 LEDs,
  codes like the keys (pads 0x10-0x1F, LOC 0x40-0x43, EFX 0x50-0x54, STATUS 0x60-0x67 two per track); the factory
  LED CHECK list is at 0x15F91E. Used by v1.91 (LAB LED SHOW, KEYS pad LEDs).

| group | buttons → logical code |
|---|---|
| Pads | PAD 1-16 → 0x10-0x1F (velocity, matrix flag 0x50) |
| Track | STATUS A-D (ST A-D) → 0x60-0x63; EFFECTS A-D (EFX A-D) → 0x50-0x53 |
| Pad side | BANK 0x20, CLIP 0x21, PAD SAMPLING 0x22, HOLD 0x23 |
| Locators | LOC 1-4 0x40-0x43, CLEAR 0x44 |
| Transport | REC (O) 0x30, PLAY 0x31, STOP 0x32, FF 0x33, REW 0x34, ZERO 0x35 |
| Mode | SONG 0x80, SYSTEM 0x81, SAMPLE 0x82 |
| Edit | TRIM 0x90, LEVEL 0x91, REGION 0x92, MARK 0x93, UNDO 0xF0 |
| Nav | CURSOR up 0x70, down 0x71, left 0x72, right 0x73; EXIT 0xB0, ENTER 0xB1 |
| Display | INFO 0xC0, S.MOD 0xC1, ROW 0xC2, ON/OFF 0xC3 |
| FX | S.TRI 0xD0, PITCH 0xD1, EFX 0xD2, MIC FX 0x54, MUTE 0xF3 |
| Other | TO-> 0xA0, SCRUB 0xA1, PLAY (2nd) 0xF2, VARI 0xF1, SHIFT 0x101 |

## Analog inputs: 14 ADC channels
- **Scan:** 0x127842 (scans channels 0-7 and 8-13 on alternate passes).
- **Smoothed value table:** RAM `0x426CBE`.
- **Read:** `0x1277E8(ch)` returns 0-127. Raw values for ch 9 and up: `0x12780E(ch-9)`.

| ch | control | evidence |
|---|---|---|
| 0-3 | **Faders A-D** (track) | FADER CHECK loops 6 faders, ch 0-5 |
| 4 | **Fader 5** (master? or pad/input) | used alone at 0x135774 / 0x136502 |
| 5 | **Fader 6** | read right after ch 4 at 0x136502 |
| 6-8 | **3 knobs: PARA-A / B / C** (FX control) | POT CHECK = ch 6+n, n<3 |
| 9-10 | **D-Beam L / R** sensors | BEAM CHECK "L:" "R:"; separate path 0x12787C / 0x127A66 |
| 11 | **Footswitch jack** (read as analog, so an expression pedal is possible) | FOOT SW CHECK reads ch 11 |
| 12-13 | ? (not used by the tests; maybe spare / internal) | |

Check ch 4 and 5 on the unit: move each fader and watch.

## Encoder (VALUE dial)
- **Signed delta per poll:** boot API `0x400490`. The ENCORDER CHECK accumulates it.

## Display (graphic LCD) via boot API (inferred)
| api | guess |
|---|---|
| 0x4003D4 | clear / init screen |
| 0x400434 | set cursor (r0h, r0l) |
| 0x400440 | print string (er0) |
| 0x400448 | print number |
| 0x40043C | print char |
| 0x400450 | text attribute / invert |
| 0x40045C / 0x400460 / 0x40046C | draw lines and boxes in **pixel** coordinates (x up to at least 0x76) |
| 0x400470 | print string at position |

Pixel drawing exists, so the screen is bitmap-addressable. That's good news for Doom.

## Boot-ROM API (RAM jump table 0x400200-0x4005FF, 106 entries used)
- The low-level drivers live in the boot block, not in the OS image.
- The OS calls them through 4-byte entries.
- We can call them, and we could re-point an entry in RAM to our own code (hooking).

| api | guess |
|---|---|
| 0x400220 | memset |
| 0x400224 | memcpy |
| 0x400228 | memcmp |
| 0x4002C8 | delay ms |
| 0x4003AC | disk sector write (LBA, count, src) |
| 0x400494 | key matrix read |
| 0x400490 | encoder delta |
| 0x4004B8 | LED |
| 0x4005BC | flash program |

## Other I/O
- MIDI in / out / thru (MIDI CHECK).
- Optional SP808-OP1 board: SCSI + digital coax / optical (DIGITAL CHECK, SCSI CHECK).
- Analog: LINE / PHONE, AUX in, MASTER / AUX out routing (ANALOG CHECK); 44.1 / 32 kHz.
