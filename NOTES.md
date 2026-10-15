# SP-808 OS v1.050 reverse engineering

Source: SP808v1050.zip (Roland) → upd/ (8 SMFs + README).
Output: `sp808_v1050_raw.bin`, the decoded flash image (0xC0004 bytes, including a 4-byte overhang).
Scripts are in the session scratchpad (msgs.py, build.py). Move them here if we keep going.

## Container (solved)
- SMF type 0, 2260 Roland DT1 SysEx messages: `F0 41 00 7C 12 <a0 a1 a2 a3> <body> <ck> F7`. All checksums OK.
- Control addresses:
  - `01 02 00 00` = file start/end marker (`00 00 00 00 nn 07 00` start / `.. 7F` end, nn = file index 0-7)
  - `01 03 00 00` = version string "SP-808 Ver 1.050 ..."
  - `01 00 00 00` = 20-byte block header
  - `01 01 00 00` = end of the whole transfer, body `00 00 00 00 23`; meaning of 0x23 unknown
- Data address `00 00 01 PP`, where PP = 64 KB page.
  - Body = 4 nibbles of offset within the page + 224 bytes of 7-bit data.
  - The 7-bit data is in groups of 8: 7 data bytes then 1 MSB byte. The MSB byte's bit6 belongs to the 1st byte, down to bit0 for the 7th.
  - Each message decodes to 196 bytes.
- **NOT compressed, NOT encrypted.** My first "looks compressed" read was wrong; it came from unpacking with the wrong bit order.

## Image layout
| image off | CPU addr (inferred) | what |
|---|---|---|
| 0x00000 | 0x100000 | header: `5A126616 "TS25ESYS" 004C041A 61040F00 000C0000 "RolandEC"` |
| 0x00020 | 0x100020 | code starts right away (stm/mov.l...) |
| ..0x6B000 | ..0x16B000 | end of code + data (~428 KB) |
| 0xBFFDA | 0x1BFFDA | `FF x6`, then a copy of the header at 0xBFFE0 (end-of-region marker) |

- Load base is 0x100000: JSR @aa:24 targets cluster at 0x10xxxx-0x16xxxx.
- The OS region is 0x100000-0x1BFFFF (768 KB, the 0x000C0000 in the header).
- The boot block / MIDI updater is NOT in this file. It is probably 0x000000-0x0FFFFF (internal ROM or a protected flash block), and survives updates.
- RAM refs are at 0x40xxxx-0x43xxxx (external RAM at 0x400000). 0xFFFFxx = on-chip I/O.

## CPU
- **Hitachi H8S/2xxx family.**
  - STM/LDM opcodes (`01 10 6D F2`, `01 20 6D F4`) exist only on H8S.
  - 24-bit absolute addressing.
  - `54 70` rts, `5E` jsr, `7A 0r` mov.l #imm.
- The exact part is unknown; read the chip on the board.
- Ghidra: stock may not have H8S. Use a community H8/H8S SLEIGH module, or IDA (it has H8S).

## Interesting strings
- Internal codename **TS25** ("TS25ESYSTEMPRMxxBAK", "TS25ESYS  Saving...").
- FX names/params live in the OS: Isolator, Filter, Reverb (Garage...), Step, Slicer, Dist, St. Chorus, Analog Delay, Dust, LFO, Tempo Sync...
  - So FX parameter tables are editable here. Whether the DSP microcode is in here too is still unknown.
- Hidden test mode: "ENCORDER CHECK", "ANALOG CHECK", "DEVEICE CHECK", "SEQ TEST", "MIDI THRU", "GRAM -- ERAM --".

## SOLVED 2026-10-12: no checksum. The OS self-updates from a FAT disk file
- Header +0 `5A 12 66 16` = `jmp 0x126616` (the OS entry: zero BSS 0x403000-0x42BFFC, copy .data → RAM 0x400000+).
- +0x0C `004C 041A`: 0x041A = 1050 = version 1.050. The running version comes from a code immediate at 0x12666E (`mov.w #0x041a,r0`), not from the header.
- Disks are **FAT12/FAT16** (OEM "Roland", label "SP-808TS25E").
- The OS looks for **`SP808.PRG`** (dir entry "SP808   PRG").
  - 0x127544: load the file to RAM 0x43FFF8. Size must be 0xC0008, and the first u32 must be 0x100000.
  - 0x127770 validate: byte0 0x5A, "TS25ESYS" at +4, first 32 bytes == last 32 bytes. **No checksum.**
  - 0x14865C: compares versions (0x426CB4 running vs 0x426CBC file). If the file is newer, or the update is forced, it shows "SYSTEM UPDATE / Update System?(Y/N) Ver x -> y". YES → RAM flasher 0x4005BC (runs from RAM, from the *current* OS).
  - Force path (0x148010): key 0x23 (= HOLD) held + disk → update even if the version isn't newer.
- The MIDI updater ("Waiting MIDI", "Receiving") is NOT in the OS image, so it lives in a boot block → recovery path = re-send the stock SMFs.

## Hidden power-on combos (OS init 0x11F0AC, key check 0x1313A6)
Logical key codes come from the table at 0x16414C, aligned with the SW CHECK name table at 0x15F9E8.

| hold at power-on | does |
|---|---|
| CLEAR + LOC 1 | SAVE SYSPROG **IMAGE**: raw-writes the OS to disk LBA 0x20000+ (64 MB offset, 12×128 sectors). **Overwrites disk data!** |
| CLEAR + LOC 2 | SAVE SYSPROG **FILE**: writes SP808.PRG to disk |
| ST D + EFX D | 0x11BDE6 (unknown; probably test mode) |
| HOLD (+disk) | force system update from SP808.PRG |
| STATUS + EFFECTS (Track A) | MIDI update (boot block, per Roland README) |

Logical key codes:
- pads 0x10-0x1F; ST A-D 0x60-63
- HOLD 23, PAD S 22, CLIP 21, BANK 20
- LOC1-4 40-43, CLEAR 44, PLAY F2
- TO-> A0, SCRUB A1
- SONG 80, SYS 81, SAMP 82
- TRIM 90, LEVEL 91, UNDO F0, REGIO 92, MARK 93
- EFX A-D 50-53, MICFX 54, MUTE F3
- CUR ^ 70, CUR v 71, CUR < 72, CUR > 73
- ROW C2, S.MOD C1, INFO C0, EXIT B0, ENTER B1
- S.TRI D0, PITCH D1, EFX D2, ONOFF C3, SHIFT 101, VARI F1
- transport: O 30, |> 31, STOP 32, >> 33, << 34, I<< 35

## Trial mod (built, NOT yet run on hardware)
- `tools/make_prg.py` → `build/SP808.PRG` + `build/sp808_mod.bin`
  - version 1050→1051 (header, trailer, code immediate)
  - "System Edit Menu" → "JunksmithWizard!"
- `tools/inject_prg.py disk.img sp808_v1050_raw.bin build/SP808.PRG` swaps a stock SP808.PRG (made with CLEAR+LOC 2) for the patched one in place. It makes a .bak first and refuses unless it finds exactly one contiguous stock copy.

- **ZuluIDE route (the user's unit, 2026-10-12):** `tools/fat_add.py disk.img build/SP808.PRG [--replace]` writes SP808.PRG straight into an SP-808 FAT12/16 .img (bare volume or MBR), with no on-unit save step.
  - It allocates contiguously, makes a .bak, and reads the file back to check it.
  - `--info` lists the volume and root directory.
  - Tested on synthetic FAT16 (MBR + flat) and FAT12 images only. Not yet tested on a real SP-808-formatted image.

## NEXT (after v0.9): hw test of the looper; then MIDI control for it; then keyboard mode (must be poly)

## Keyboard (piano) mode + max polyphony: research (2026-10-13)
- **Max poly = 4.** The kernel voice allocator 0x1000A6(pad flags) hands out 4 playback channels:
  state 0x403302 + ch (0x96 = idle), flags 0x40330A + ch (bits 4-6 = voice group, same group steals:
  pad flags bits 4-6), busy masks 0x40330E | 0x40330F; full: steal by priority (0x1002A6). Mono or stereo,
  a sample takes one channel. DSP0's 10 stream blocks = 4 stereo playback pairs + 2 record, so 8 mono
  voices would need kernel streaming + DSP0 microcode work (DSP0 is 757/768 words, ISA undocumented).
- **No per-voice pitch.** VARI (key 0xF1, params BPM TUNE / BPM RATE / VARI PITCH, table 0x166CF0) is a
  global rate: 0x14603C -> rate per mille @0x43B326 (1000 = normal) -> kernel 0x100630 turns it into a
  period (587000 / rate at 44.1 kHz, 625000 / rate at 32 kHz, clamped) at 0x403310 and sets 0xFFFEA4
  bit 0: the whole unit's sample clock changes (song, pads, recording). The DSP plays every channel 1:1.
- **CHANGE PITCH (screen 0x58, SHIFT+LEVEL) can make pitched copies:** source bank/pad 0x42769C/D ->
  to 0x42769E/F, params at 0x42774A grade 0-4, 0x42774B semitones -12..+12, 0x42774C fine -100..+100
  (descriptors 0x165B28..). Core 0x123810(er0 source entry, er1 dest entry, stack: grade, semis, fine)
  sets up DSP1 (0x11B6C0 loads the pitch shifter, 0x11F2AE mixer params) and bounces the pad through it in
  real time: length kept, DSP pitch-shifter quality. semis = fine = 0 just copies the entry (0x13AFF2).
  Callback 0x13AFA2 then writes the result pad.
- **So poly keyboard = 16 pre-pitched copies on 16 pads, 4 notes at once.** True resampled pitch exists
  only as the global VARI clock (mono use only).
- **VARI range:** 0x100630 clamps the period to 0x248..0xCA4 at 44.1 kHz (587000 / rate): rate
  181..1005 per mille, i.e. it can only slow the clock (to about -29.6 semitones), +0.5 % up. At 32 kHz
  (625000 / rate, clamp 0x1C6..0x9C4) it can go up to about +5.5 semitones. A mono true-pitch mode
  would bend everything that plays (loops, input, FX) and mostly pitch down.
- **Per-voice level, for a release:** per channel ch (0-3): 0x43B6C0 level, 0x43B6C4 multiplier
  (0x80 = unity), 0x43B629 effective = level * mult * 2 >> 8 (0x14F56E), pushed to the DSP by
  0x135882(r0h ch, r0l strip @0x43B649 + ch, e0 = param mask, 0x1000 = level; table 0x164C54).
  0x43B631 + ch = owner (0x10 + pad for pads). 0x43B6DC + 4 ch = per-voice callback run by the voice
  service (0x14F228; non-zero return = recompute + push the level). Stock de-click stop 0x14F4AC: mult 0,
  push, callback 0x14F436 waits @0x43B6D8 ticks of 0xFFF0E0, then 0x14F504 stops the voice.
  A release = our callback stepping the multiplier down, then the stock stop.
- **8 voices: dead end (dug 2026-10-13).** DSP0 is organised per kernel channel, 5 channels (4 playback +
  1 record): per channel one 12-word control block (DSP0 bytes 0x64, 0x98, 0xC8, 0xF8, 0x128 = table
  0x160058, the "5 x 12" section; 0x120768(ch) writes 0x8003 there on refill via 0x1089C6), two 28-word
  stream blocks (L/R, the "10 x 28" section) and one 18-word mixer strip (0x5C4 + 0x48 * ch, table 0x1601DE).
  Stereo is built into each channel; a mono sample still uses the whole channel. Two mono voices per
  channel would need new control/stream microcode in DSP0 (11 free words, ISA undocumented).
  Data path: the DSP reads the compressed audio itself; kernel channel records 0x4032DA + 10 ch, request
  bits 0xFFF0DE, on-chip channel state 0xFFEF34 + 0x30 ch, refill service 0x1225C2 (boot table 0x40036C).
  TPU5 (0xFFFEA0..) makes the audio clock: TGRA5 = period - 1 (0x11BC7E, from 0x403310 = VARI).
- **Banks:** 64 (params 0x42769C/E: 0..0x3F). Current bank @0x40323C; switch = 0x137AFA(bank) (state
  machine 0x137BF4 saves the old bank if dirty via 0x1220BC, clears the table, loads 0x1220FC from the
  song's PADBANK_VS2 file). PAD_GET/PAD_SET on another bank go through the disk buffer 0x421B80
  (0x122B26 read), so a scratch bank can be filled without switching.

## v1.0 (2026-10-13, built + emulator-tested, NOT on hw): KEYS = 8-voice pitched sampler running in the FX chip

The "4 voices" wall was DSP0's. The effects core (DSP1) is free to reprogram, so KEYS mode loads **our own DSP
program** there: the pads play one sample held in the FX delay RAM, 8 voices, pad 8 = root, -7..+8 semitones.
Files: `tools/esp.py` (decoder, disassembler, cycle simulator), `tools/dspdump.py` (programs out of the image),
`tools/fxcapture.py` (runs the stock FX loader in the H8S emulator, dumps the live programs with all runtime writes),
`tools/keysdsp.py` (our DSP1 program + model test), `tools/build_v10.py`, `tools/test_v10.py` (firmware driving the
DSP model end to end). Dumps live in `work/dsp/` (Roland data, not committed).

### The chip: Roland/Toshiba ESP2 (TC170C140 class), two cores
- DSP0 (window 0xC00000) = core 0, DSP1 (0xC01000) = core 1. Only core 1 reaches the external delay RAM.
- Instruction set decoded publicly by The Usual Suspects for their JP-8000 emulator (gearmulator, GPL; we only read
  it, our tools are independent): 768 words per core, **28-bit words** `EEEEE PPPPP MMMMMMMM SS CCCCCCCC`:
  E = ERAM slot (bits 27-23), P = opcode (`(w >> 16) & 0x7C`), M = IRAM/GRAM address (256 words, relative to a
  pointer that decrements once per sample: a value written at m is read next sample at m+1), S = shift after the
  24x8 multiply (0->7 1->6 2->5 3->3), C = signed 8-bit coefficient. Two 30-bit accumulators (A/B); a store sees the
  accumulator value from **3 instructions earlier**. op 0x30 multiplies by one of 8 24-bit `mulcoeff` registers
  (mc6 = the ERAM variable-offset fraction); op 0x34 is the special group (mem 0xA0.. `mcN = acc`, 0xC6 DMAC = the
  low 7 coefficient bits of a 15-bit pair, 0xC7 `eramvar = acc`, 0xCA `hostreg = acc`, 0xCB `eramwr = acc`,
  0xCC-0xCF `i[0xFC..0xFF] = eramrd`, 0xD0-0xD3 jumps). Full semantics: `esp.py`.
- In the OS image a word is 3 bytes **coefficient byte first**; the loader (0x1096D2) writes `b0<<24|b1<<16|b2<<8`
  to the host port, so bits 27-24 (ERAM slot high bits) can only be set with the host's ERAM-group write.
- Host port modes = latch byte 0x411B65 -> 0xC02003, bits 1-0: 0 raw word write (0x1088C0 / loader), 1 coefficient
  pair (0x108A5C: one 32-bit write updates a 15-bit coefficient split over two words), 2 ERAM group (0x108B64: one
  write sets the 5-bit E fields of 5 words = mode + 20-bit offset; 0x109696 packs a WRITE, 0x10965A a READ),
  3 readback (0x1098DA). 0x108936 = coefficient byte + shift of one word (e0 = coef << 8 | shift sel). Bit 4 = run.
- Readback: the DSP's `hostreg` value appears in 4 bytes at 0xC00004-7 (the OS reads them with 0x109964).
- **Delay RAM = 128K words** (the OS's clear routine 0x10861E writes 115 blocks spaced 1140 words), 16-bit
  block-float compressed. Transactions: the slot word starts it (0x10 write at pos+imm, 0x08 read at pos+imm, 0x18
  read at pos + (eramvar >> 12) + imm bit 1), the next 4 words carry the 20-bit offset in 5-bit pieces, the data is
  latched at start+10; a new transaction may start every 6 words. `pos` decrements once per sample (a delay line).
- I/O of the DSP1 program: Roland's 58-word base reads the FX send in g[0x71]/g[0x75], feeds the algorithm through
  i[0x12]/i[0x18] (after the wet ramp i[0x10]/i[0x16]: words 0x1D/0x2B are the OS's mute, 0xF800/0x0100), takes
  its output from i[0x13]/i[0x19] and writes g[0x72]/g[0x76]. The algorithm sits at word 0x3C. After every load the
  OS puts `JMP 0xF1` at word 0x2F2 (DSP0's own program has it too): we keep words 0xF1-0xFF as nops to be safe.
- The 20 FX algorithms (order 0 = Isolator&Filter .. 19 = Analog Synth) decode cleanly; the pitch shifter (12)
  uses exactly the variable-offset read pairs (+0/+1, fraction = crossfade) our sampler needs.

### Our DSP1 program (keysdsp.py), 0x3C-0x4F globals + 0x100-0x26E voices and mixer
- AGE += 256 per sample (16.8 fixed point, wraps at 65536 samples). Recording writes (inL+inR)/2 at offsets 0
  **and 0x10000** every sample (two copies make the 16-bit wrap consistent); the host switches the two write groups.
- Voice: PHI += DELTA (= 256 * ratio, three coefficient fields: *512, *8, /8), X = AGE - PHI (raw, wrapping),
  eramvar = 16 X, two reads (+0/+1) interpolated with the fraction, level one-pole smoothed from a target
  coefficient (zipper-free, ~1.5 ms), OUT = sample * level. Host resets a phase by writing its gain field 0 for a pass.
- Detector: leaky peak of |input|, saturated, to hostreg (all ones while the pad sounds) -> the host starts the
  age/recording at the real onset instead of at note-on (the disk start latency would otherwise be recorded).
- Limits of v1: sample <= 65536 samples (1.49 s at 44.1 kHz), pitch step 1/256 sample/sample (<= 7 cents at -7),
  8 voices (11-12 would fit), release = the level smoothing only.

### Host (build_v10.py): KEYS page (SYSTEM / KEYS tile)
- Entering: load our program (0x1096D2 chip 1 from 0x3C, 708 words from the table at 0x1B8000), set the ERAM groups
  and coefficients, `@0x403000 = 0xFFFF` so the stock FX engine reloads its algorithm later, then route the master
  through the FX: `0x11F2AE(r0 = 7, e0 = 0, r1 = 0x0C)` (= FX LOCATION "INS MASTER"; codes from the table at
  0x164D38: 0x01 send/return, 0x0C master, 0x0D record, 0x0E aux, 0x0A/0x0B mic, 0x02-0x09 track A-D pre/post,
  0x00 off; the current code is @0x4031B6). Restored on EXIT.
- IDLE: LEFT/RIGHT or a pad picks the source pad (it plays through, `thru` fields on). ENTER: pad length from the
  pad entry (capped 1480 ms + 40), both write groups on, pad note-on; WAIT polls the readback bytes for the onset,
  then age reset (one pass), REC until the length is up, writes off, pad stopped -> PLAY.
- PLAY: pad press = next voice round robin (pitch table `ratio_tab`, 3 values per pad), gain 0 + level 0, and a ms
  later gain 1 + level 48 (`keys_idle`); release = level 0. Pad map shows sounding pads.
- Boot animation moved to 0x1A0000 (our code is 23.5 KB now); DSP table at 0x1B8000.
- Build 1101 (2026-10-13): **DSP monitor line** on the KEYS page, tiny font at y = 20: `S<state> R<fx route code>
  <readback bytes 0xC00004..7>`, e.g. `S4 R0C 7F 7F 7F 7F`; redrawn 4x a second (not while waiting for the onset,
  so the onset latency stays one main-loop pass). On the first hardware test read it off the screen: R must be 0C
  on the page (01 after EXIT), the readback should move with the pads' audio (0F low nibbles = sound).

### v1.4-v1.6 (2026-10-14)
- **v1.4 (1140):** KEYS releases DSP1 + the master routing on every way out (keys_guard each idle pass: active <=>
  page KEYS or EDIT; screen-5 leave event 1); re-entry reloads our program when FX_CUR != 0xFFFF (stock FX loaded).
- **v1.5 (1150):** dry master through DSP1 at unity (THRU 64) = 4 disk voices + 8 KEYS voices together; one-shot
  notes stop at the sample end (VEND per voice = take ms * 4096/ratio >> 12); capture cap 1440 + 40 ms (< 65536
  samples, the 2nd copy's head was overwritten before).
- **v1.6 (1160), emulator-tested:**
  - Home: 5 tiles MPC LOOP KEYS **S-EDIT** SYS, 4 shown, the view scrolls one right for SYS (a '>' hints it).
  - S-EDIT page (P_KSET = 4) = the KEYS sound: CUTOFF/RESO (knobs PARA-A/B, ADC ch 6/7 via 0x1277E8 -> 0..127,
    A = 127 = filter off), ATTACK (PARA-C / 8 -> 0..2000 ms), RELEASE (dial), REVERSE (ENTER/dial). KEYS stays
    live on the EDIT page (pads and MIDI play the keyboard).
  - **Filter (DSP):** Chamberlin state-variable low-pass on the previous sample's voice sum (1 sample latency), in
    the free block 0x50-0xF0; f and q are 15-bit coefficients = an op (8 bits) + the DMAC `lo7` word (op 0x34 mem
    0xC6/0xE6), the same trick as Roland's base EQ; cutoff 30 Hz - 7 kHz exponential; model: -2.6 dB at fc,
    12 dB/oct, +11.8 dB peak at high resonance. out = lp * wet + voices * dry + input * thru.
  - **Reverse (DSP):** AGE_E counter reset by the host at the end of the take; REF = AGE * ref_f + AGE_E * ref_r;
    voices compute -X = PHI * dir - REF (dir +64 fwd, -64 rev) -> reverse reads from the take's end backwards.
  - **Attack/release ramps** count steps from the clock (elapsed / period), so a slow main-loop pass (a draw costs
    ms) doesn't stretch them. Voice states: 1 waiting, 2 held, 3 releasing, 4 attacking.
  - **Gate:** Roland's DSP writers 0x108936 (coef), 0x1088C0 (raw), 0x108A5C (pair), 0x108B64 (ERAM group),
    0x1096D2 (loader) start with `jmp gate_x`: chip-1 writes are dropped while KGATE (KEYS owns DSP1). The main loop
    turns PARA knob moves into FX parameter writes on any screen; without the gate they'd land in our program.
    Our own writes use own_coef / own_eram / own_load (straight into the routine after its first instruction).
  - Assembler: jsr/jmp accept labels (abs24 relocation).
  - **Phase fix (all KEYS builds before were affected):** PHI was stored saturating (B, op 0x0C) and froze at
    0x7FFFFF = 32767 source samples = 0.74 s: longer captures stopped advancing and turned into a DC level. The phase
    now lives in A and is stored raw (op 0x44, wraps mod 2^24 like AGE), the level moved to B (0x14/0x10, stored
    with 0x5C, mc2 written from B with 0x34 0xA5). Model: a 1.3 s take plays clean to the end.
  - Assembler rejects duplicate labels (the knob routine's `kn_out` exit had silently jumped into the note-on
    routine's `kn_out`, popping 4 registers: a crash on hardware).

### v1.7 (1170, 2026-10-14, emulator-tested, NOT on hw): LOOP (sustain while held)
- S-EDIT row 3 = LOOP on/off (KLOOP). Region from the take length L: loop end LE = L - L/16, loop start LS = 3L/8,
  crossfade XF = min(40 ms, (LE - LS)/2). Held notes play to LE, then cycle LS..LE; release ramps as before.
- **Why not two read heads per voice:** READvar = `pos + (eramvar >> 12) + ((imm >> 1) & 1)` (+ the bit-8 hiflag):
  only bit 1 of imm counts, so a second head at an arbitrary offset can't be read with the same eramvar.
- **Voice handoff instead:** 3 ms before LE - XF a free voice is prepared as a continuation (state 7, `v_sel` on:
  X gets `+ SOFF * sel`, SOFF = LS - XF in 16.8 from three coefficient fields soff_a/b/c at words 0x5A-0x5C, raw store
  at 0x5F), same pitch, level 0. At LE - XF it starts (phase reset) and the host ramps the two levels across XF
  (old voice state 5 fade-out, new state 6 fade-in), then the new voice is held (2) and links on again.
  VKEY/VLINK/VXF/VXL0/VXD/VLX/VXS track it per voice. Note-off on a link: 2/4/6 release, 7 is cancelled.
- Voice block back to 44 words (one head); SVF filter moved to word 0x60 (G1 + 16).
- **Mixer change:** out = voices + thru + lp * wet + voices * (wet ? -1 : 0), i.e. `flt_dry` now means dry - 1.
  keys_set_cut writes 0/0 (off) and 64/-64 (on). A stale 64 here doubled every level (0.187 instead of 0.094).
- Model: 0.44 s take held 1.5 s -> constant peak 0.094 per 100 ms, f 1001 Hz across 4 handoffs, clean release,
  no stuck links. Reverse + loop: same (peak 0.094 constant, 1002 Hz, 4 handoffs, clean release).
- Program end 0x2F1 of 0x2F2 words: DSP1 is now full.

### Lanes (2026-10-15 on): parallel sessions, each writes notes only under its own heading
Rules, space ledger and owners: `PARALLEL.md` (local, not in git). Newest note first under each heading.

#### Lane LEAD: KEYS / synth, merges, versions, the card
- **MIDI remote keys + hardware-in-the-loop (2026-10-15, user: "looper trigger via MIDI so the loop lane can fix the
  loop logic itself"; PC = Focusrite 6i6 audio + MIDI):** a note on MIDI channel 16 = key code <note>, channel 15 =
  0x80 + note, velocity 64+ = SHIFT, note-off / velocity 0 = release. `m_on_tr` / `m_off_tr` queue them (channels
  15/16 never reach KEYS or the stock pad handlers) into an 8-word ring; the OS key dispatcher's `jsr 0x1311C6` (next
  key from the scanner, at 0x13F2FC) now calls `rk_getkey`, which returns a queued raw key first. So the key goes
  through the whole stock path (0x131556 group info, KEYMASK, group handlers g1 / g2 / g8, the screen) like a press.
  Test: `test_remote.py` runs the stock dispatcher: a remote PAD SAMPLING tap arrives at g2 as 0x0022 / 0x4022.
  PC side: `tools/sp808_midi.py` (winmm via ctypes, no packages): `ports`, `key PADSMPL`, `run "PADSMPL 120; wait
  4000; ..." --rec out.wav` records "Analogue 1 + 2 (Focusrite)" and logs each event's sample index (device counter).
- **Synth only (2026-10-15, user: "needs me to press a sample pad to get any sound"):** with SAMPLE 0, keys_enter goes
  straight to PLAY with no source (`keys_synth_only`, KNOSMP = 1). The page shows SYNTH ONLY; the sample layer is
  muted and voices hold while held, so the stale delay RAM is never heard. Raising SAMPLE while KNOSMP is set =
  `keys_need_src`: back to IDLE, and the next pad hit picks the source as before. A real take clears KNOSMP. Test:
  `test_synth.py` (out 261.5 Hz for C4, held 1.8 s, the source kept when SAMPLE goes back to 0).
- **Cursor bug:** the MFX block redefined `MCUR` (0x433), so the MPC page cursor shared the MFX cursor byte. Renamed
  MFX's to `MFCUR`; MPC's MCUR is RAM_BASE + 12 again. test_arp / test_voice now enter KEYS with SAMPLE 16, so their
  pad hit still picks a source.

#### Lane MFX: effect modes and sound
- **2026-10-15: CHORUS / FLANGER / PHASER as own TYPEs (5-7)** (user chose: own TYPEs, stereo chorus/flanger, 2-notch
  mono phaser). Emulator-tested, NOT on hw.
  - **Scheduler (mfxdsp.Seq/schedule):** the old one-after-another placement left 216 nops in 581 words. Now the words
    are recorded in dataflow order and list-scheduled with the decoded ESP dependencies (acc read sees t-3, so a new
    chain may start under a pending store; IRAM/GRAM/mulcoeff/eramvar RAW/WAR/WAW; ERAM starts >= 6 apart, eramrd
    window; dmac adjacent). Roland's own FX code does the same overlap (316 of 715 A-stores have A macs in the 2 words
    before), so it's hw behaviour. The v1.97 selftest gave bit-identical numbers after the reschedule.
  - **SVF f through mc2** (`op30(2)` + dmac instead of coef pairs, same 15-bit precision): mc2 = fbase + span * u^2,
    u = the slot's MOD triangle (last sample) mapped to 0..1. FILTER = span 0, exact as before.
  - **CHORUS / FLANGER:** the DELAY read offset += tri * depth (coef + dmac pair, 1/8-sample steps); a second
    READvar pair (`es0`/`es1`, landing FE/FF) at offset - tri * depth = R. mc6 is read LIVE from eramvar, so the L
    interpolation must finish before the R eramvar (B accumulator) is written. In DELAY R reads the same offset, R = L.
    Each such slot gets MODLINE = 1024 words at the top of the delay RAM (MREGM bit 3+k), DELAY slots split the rest.
  - **Delay target resolution:** etb/etc only gave 16-sample steps (that was the v1.97 "echo 13264 for 13272" and the
    -5 in the DELAY selftest), which put the flanger's 4-sample minimum below zero = no wet. New word `etd` =
    -8 (half & 7): 2-sample steps (the accumulator is integer and the glide is NV = 128 T', so 1 sample needs T' 0.5).
  - **PHASER:** input (L+R)/2 (`xil`/`xir`), L SVF = ap1 = x - 2q bp (wb at SH5), R SVF input = ap1 (`sr`/`sf`), out
    = (x + ap1 - 2q bp)/2 (`xdry`), DRIVE dry L takes FR (`ddx`) so L = R. Model: notches at 62 / 362 Hz for f 150 Hz
    (theory 0.414 f / 2.414 f), ~1250 Hz at the 3 kHz top (the 2nd notch fades there: Chamberlin at f 0.43).
  - Program end 0x2D0 (32 words left). Host: MVAL (49) / MSHAD (58 x 3 x 2) moved to the MFX lane RAM 0xC00-0xD90.
  - Test: tools/test_mfx_mod.py (firmware words vs model, mask / WRITE bases / R groups, taps, feedback, phaser sweep,
    KEYS round trip).

#### Lane LOOP: Looper v2
- **Timing debug build (2026-10-15, for one hw run):** each trace entry also stores ms since the last looper press
  (LV_TRT 16 words, LV_T0 = tick of the press, both in the LOOP RAM block). ENTER on the LOOP page cycles
  OFF -> VALUES ("Xhhhh") -> MS ("Xdddd", 9999 max) -> OFF. New trace points: K = take armed (0x22 enter, value
  LSTATE), I = first record idle (value = 0x4277D1 byte << 8 | trigger mode 0x4277C9), Q = a press during a take
  (value = REC_MS), B = stock write begins (0x23 event 2), N = layer note-on (value = layer). Close-tap pipeline:
  R Q S E P B W D G N. Emulator (stock faked, so near-zero cost): note-on 105 ms after the press; DUB arms at 0,
  I at 19, auto stop at loop + 150 ms. Test: tools/test_loop_timing.py.
- **v0.9b HW TEST (2026-10-15, v1.97 on the card, PAD SAMPLING):** layer 1 records and loops OK; **loop 1 keeps
  playing during DUB** and the screen shows DUB (overdub-while-playing works on hw). Bugs: (1) DUB never ends by itself
  after one loop; (2) a tap during DUB ends it but the layer is lost; (3) lag = a gap between the closing tap and
  loop 1 starting. Emulator (test_v09 + build_v10, unknown stock calls 0x132880 / 0x132866 as no-ops): DUB auto-ends
  after one loop and layer 2 is kept, so the hw difference sits in stock behaviour the sim fakes. Waiting for a
  repro + trace photo from the user.
- **RE pass 2 (2026-10-15, emulator): voice slot n = mixer group n = fader n. PROVEN, with one catch.**
  - Fader poll **0x13570E**: table 0x164C42 = (ADC, strip) pairs 0/0 1/1 2/2 3/3 5/6; ADC 4 -> strip 4 (MIC/LINE) or 5
    (if 0x1364BC != 0). Strip records 0x426DDE + 0x12 * strip (+2 last raw, +4 value). Change -> 0x135806(strip, flags)
    -> 0x135882 -> function table 0x164C54 (10 B: mixer idx, idx for strip 6, fn, arg); LEVEL = entry 12 -> 0x13593E.
  - Strip -> group table **0x164C4C = 00 01 02 03 04 FF 06** (strip 5 = "pads": FF = applied to every slot in 0x43B627).
  - Groups 0-3 skip 0x11F2AE: 0x13593E reads status 0x14E83A(group) (bit 7 -> level 100, bit 0 -> fader value
    (strip +4) * 0x43B629[group] via 0x14E476, else 0), then **0x120790(group, e0 level, r1 pan)**: stores mixer
    params idx 11/12 (0x422018 + 0x2A * g + 22/24) and writes the DSP0 word from table 0x1601DE = w171 / w183 / w195 /
    w1A7 / w1B9: the channel LEVEL words of the mixer map. 0x1207D6 = a coefficient pair from 0x1601E8.
  - Emulator (fader poll with 0x11F2AE / 0x120790 / 0x1207D6 stubbed to log): ADC0 -> LVL(g0), ADC1 -> LVL(g1);
    ADC4 -> MP(g4, 11), ADC5 -> MP(g6, 0) (master).
  - **Catch: 0x43B627 = "pad plays on slot n" mask** (set by 0x14E9F4(slot) from the pad voice start at 0x14ECF4,
    cleared by 0x14E9C0 at voice stop; bits from 0x16A18A = 1/2/4/8; 0x43B628 gets the same bits). With bit n set,
    fader n is **ignored** for group n (emulator: ADC0 -> nothing) and strip 5's level goes there instead.
    Roland's own pad-level code writes group = slot, which also proves slot n's stream comes out of channel block n.
  - **v2 recipe:** (1) 0x14EC7E `jsr 0x1000A6` -> `lv_alloc` (loop pad k -> slot k); (2) 0x14ECF4 `bsr 0x14E9F4`
    (4 bytes, room for a jsr) -> `lv_mask`: stock, then for a loop slot clear its bit in 0x43B627 and call
    0x135806(k, 0x1000) so fader k applies at once. Still to check: status 0x14E83A for a pad slot (bit 0 set?),
    what 0x43B629[n] holds for pads, and the other 0x14E9F4 callers (0x14EDB0, 0x14F072, 0x14F368) re-setting the bit.
  - **Other allocator caller 0x14EEB8** = 0x14EEAA, a one-voice special start (class 0, owner 0x40, slot kept in
    0x43B652, stop 0x14EF38). Installed by 0x138438 (from 0x137EBA, flags 0x427578 bit 1 / 0x4278E2 bit 3) as the
    0x4275AA hook for pad @0x403242 (first free pad, else 15). Not identified yet (a monitor / preview voice?).
    Risk for v2: when all 4 slots are busy it steals one through 0x1002A6, so it could take a loop's slot.
- **2026-10-15, user decisions for v2:** faders = loop n pinned to the Tr.n voice (stock faders); the 4 loops = fixed
  pads in their own pad bank; loop select = simple first (an on-screen selector, maybe "move a fader to select" or
  "next loop at the wrap" later). v0.9b hw test list handed to the user (runs through the lead). RE only until the
  plan is OK'd and the hw test is in.
- **RE: where a pad gets its voice (= the pin point).** Pad note-on 0x13749E queues (bit 2 of +1, 0x150CEE) only
  when busy, else 0x137534 -> **0x14EC5E(r0l = pad, er1 = params)**. At **0x14EC7E `jsr 0x1000A6`** (flags +14) picks
  the voice slot **0-3** (only 4 stream voices for pads and tracks together):
  1. 0x100278: a slot whose class byte 0x40330A[s] & 0x70 equals flags & 0x70 (same group retriggers its slot);
  2. else the first s with 0x403302[s] == 0x96 (idle) and not in busy mask @0x40330E | @0x40330F;
  3. else 0x1002A6 steals (busy | 0x43B626 | slots with 0x40330A[s] & 3).
  Then 0x43B62D[slot] = param +2, voice setup 0x14EA28(slot), 0x43B635[pad] = slot, 0x43B631[slot] = pad + 0x10;
  a pad that owned the slot before is stopped (0x1375A8). Other 0x1000A6 caller: 0x14EEB8 (not looked at).
  **Plan:** patch that jsr to `lv_alloc`: looper bank + loop pad k -> slot k, else jmp 0x1000A6. Still to prove in
  the emulator: slot n = the mixer channel that fader n (LEVEL index 11) drives.
  **Limit:** 4 loops = all 4 voices, so no other pads / tracks while 4 loops play (8 mono = the voice hack, later).

### v1.97 (1197, 2026-10-15): MFX effects (user: per-slot TYPE; FILTER, DRIVE/LO-FI, DELAY, MOD; tested via line in)
- **DSP1 program (tools/mfxdsp.py, 0x3C..0x28F of 0x2F1):** every slot runs FILTER -> DRIVE+CRUSH -> MOD -> DELAY;
  the TYPE switches one block on, the others are transparent by coefficients (OFF = exact x1, checked).
  FILTER = Chamberlin SVF per channel (15-bit f / q, LP / BP / HP), DRIVE = 2 gain stages into saturation (to 48 dB)
  + one-pole TONE + CRUSH (sample & hold through delay RAM: write every sample, READvar at n mod 2^k), MOD = triangle
  LFO into mc0 / mc1 gains (tremolo / auto-pan / ring), DELAY = one mono line, READvar + interpolation, offset glides
  (1/128 per sample), feedback, MIX; slot LEVEL folded into the output dry / wet.
- **Host:** mfx_apply -> MVAL (31 values from tables, mfxdsp.values is the Python twin) -> mfx_write sends only the
  words whose (coef, shift) changed (MSHAD shadow; a CUTOFF step = 4 writes). TYPE change loads that type's default
  params (P_DEFAULT) and re-splits the delay RAM between the DELAY slots (mf_regt / mf_regp by mask, MREGM).
  CONTROLS: 13 targets (levels + SLOT k P j, scaled to the param's range by TYPE). UI: MFX tabs FX CHAIN, SLOT 1-3
  (rows TYPE + 3 params whose labels / displays follow the TYPE: Mac engine 'dyn' rows), CONTROLS.
- **Delay RAM rules learned (all in the model, KEYS-proven ranges):**
  - READvar offsets kept < 65536 (KEYS proved that range on hw): crush regions 8..472, dummy lines 480 / 488 / 496,
    delay lines 512..65520 split 1 / 2 / 3 ways (max 1480 / 740 / 490 ms).
  - Data written at offset w moves up one offset per sample and is overwritten by the next writer above it after
    (w_next - w) samples: a line's room is the gap to the next WRITE offset above (all three slots wrote at 512
    once -> no echo).
  - The loader can't write E fields: after our load every word's E field is cleared (stride-5 group writes) and ours
    are set; KEYS load and MFX OFF clear ours (stale groups would start transactions in the other program).
  - The delay line records in every TYPE: switching to DELAY plays what passed ~D ago (fine, like trails).
- **ESP facts found on the way:** op 0x60/0x64 input `~x & 0x7FFFFF` is 1 - x, not -x (my first offset math was off
  by -2^29); keep negative states and multiply by -128 (KEYS' -X trick). A multiply and its lo7 / mulcoeff dmac must be
  adjacent: Seq.pair() keeps them out of the 0xF1-0xFF gap.
- **Emulator:** mfxdsp selftest (all blocks), tools/test_fx.py through the firmware: LP 200 Hz 1.08 / 4 kHz 0.018,
  HP 0.16 / 1.05, param clamp, 4 writes per CUTOFF step, DRIVE clips, DELAY echo 13264 for 13272 (16-sample steps),
  split regions + WRITE bases rewritten, tremolo 0.22..1.0, bypass x1, knobs -> params, KEYS round trip clean, no odd
  accesses. **Not on hw yet:** slots 2/3 (GRAM path) and everything by ear.

### v1.96 (1196, 2026-10-15): LAB BUTTONS sees every key
- **hw v1.95:** menus OK (names back). LAB BUTTONS stayed empty: the key dispatcher 0x13F2F0 gives each key to
  its group handler first (KEYGROUP_TABLE, 16 groups) and only sends it to the screen (event 9) when the handler
  returns 0; most stock groups eat their keys. Only arrows (group 7) and EXIT / ENTER (group 11) got through.
  The test harness skipped unhooked groups (r = 0), so the BUTTONS test passed with keys hw never delivers.
- **Fix:** `bt_mask` (idle): while LAB BUTTONS is shown, KEYMASK 0x427906 = FFFF (every group skipped -> every key
  to our screen); the old mask comes back on ENTER (menu), EXIT, any other tab and the leave event (BTMASK / BTON).
  Harness: KeysSim honours KEYMASK, and `stock_eats = True` makes unhooked groups eat keys like hw.
- **hw LCD ICONS (v1.95, photo):** all 184 free 7-seg bits on -> nothing new lights. The same LCD RAM words show
  our VER / POLY digits, so the writes do reach the glass: those bits drive no segments. No hidden icons.

### v1.95 (1195, 2026-10-15): data tables word-aligned (v1.94 hw bug)
- **hw v1.94:** MFX / ROUTING pages show numbers (64, 100) but every name value is blank (ENGINE, SLOT AT, PRESET,
  FX AT). Slot select itself works.
- **Cause:** h8asm `align2` guessed the current length and counted `abs24` items (jsr / jmp to a label, 3 bytes)
  as 0. From the first such jmp on (the v1.91 trampolines) every "aligned" table landed on an odd address
  (mf_offon 0x17ECE9, rt_locn, lfo_inc, ratio_fine, arp_bpm, bit16 ... all odd).
- **Why the emulator passed:** the H8S ignores address bit 0 on word / long accesses (reads the even address, no
  address error); h8emu read the odd address exactly. On hw `mov.l @er2` from the name table built pointers like
  0x001817 -> empty strings. The same hits every word table read: LFO rates, pitch ratios, ARP tempo, bit masks.
- **Fix:** `align2` is now a layout-time item (pads by the real pc); h8emu masks bit 0 on word / long accesses like
  the chip and logs each odd one in `Emu.odd` (test_v10 prints it). v1.94 under the strict emulator reproduces
  the hw failure (row_str reads 0x001817 on the MFX page); v1.95 renders OFF / MASTER / 64 with no odd accesses.

### v1.94 (1194, 2026-10-15, emulator-tested, NOT on hw): voice modes MONO / GLIDE / UNISON
- **Validated (2026-10-15 ~03:15):** build staged in work/v194 (source 74978c7, also has the MFX pad switches and the
  boot sweep): the full test_v10 suite passes (same results as v1.91) and so do test_route / kset / padled / lfo /
  arp / voice / mfx.
- **VOICE tab** (DDS-DSP, 6th: VOICE MODE): MODE POLY / MONO / UNISON, GLIDE (OFF, 10-2000 ms), SPREAD (unison
  detune 0-15).
- Notes flow pads / MIDI -> ARP (if on) -> voice mode (vm_on / vm_off) -> keys_note_on / off, so MONO + ARP = a mono
  arp with glide.
- Every pitch write (keys_osc_note, voice_repitch) adds `pitch_off` = LFO_OFF (vibrato) + GOFF (glide) + VDET[voice]
  (unison), in 1/16 semitones; the sample's fields come from `ratio_fine` with the same offset.
- MONO: one voice (MV), a held stack (MHELD, last note wins). A new key while it sounds = legato: VKEY / VPAD move to the
  new key and GOFF = (old - new) x 16 + where the glide was; glide_tick takes GOFF linearly to 0 over GLIDE. Releasing
  the sounding key glides back to the last held one; the last release ends the note.
- UNISON: each note starts 4 voices (VDET = -3 / -1 / +1 / +3 x SPREAD / 4), half level each; POLY clears VDET.
- MODE changes release every held voice and clear the offsets (no stuck or detuned voices).
- ARP step clock now advances by exactly one step (AT += step, catch up if more than a step late): no tempo drift.
- Emulator (`tools/test_voice.py`): POLY C+E = 261.6 / 329.6 Hz; UNISON SPREAD 8 = 4 voices at 256.0 / 259.7 / 263.5 /
  267.3 Hz, level 24 each (half); MONO C then E on the same voice glides 261.6 -> 329.6 Hz in ~150 ms (GLIDE 150),
  E up glides back to C, C up releases (MV FF); GLIDE OFF jumps; MONO + ARP = one voice at a time.
- Fixed while testing v1.93: the ARP list shifts loaded the data byte into r1h while er1 was the pointer (insert /
  remove in the middle of the list wrote the wrong cell, a released key stayed and its note hung); now r2l (saved).
- Boot: a 3-pad light comet sweeps pads 1 -> 16 (30 ms a step) with the boot sound, then the stock pad LEDs come back
  (pads_take / pads_give; KEYS starting meanwhile stops it cleanly).

### v1.93 (1193, 2026-10-15, emulator-tested, NOT on hw): arpeggiator
- **ARP tab** (DDS-DSP menu, 5th: ARPEGGIATOR): MODE OFF / UP / DOWN / UP+DOWN / RANDOM, TEMPO 60-240 BPM (1/16 steps),
  GATE 25 / 50 / 75 / 100 % (100 = legato), OCTAVES 1-3.
- Pads and MIDI notes go through arp_on / arp_off: ARP off = straight to keys_note_on / off; on = a sorted held list
  (up to 8, repeats ignored). arp_tick (every KEYS pass) steps every 1/16, ends the note at GATE, plays held[i] + 12 x
  octave (above the top key: a rest). UP+DOWN turns without repeating the ends; RANDOM = 16-bit LCG.
- Changing MODE stops the arp note, empties the list and releases notes held before (no stuck voices).

### v1.92 (1192, 2026-10-15, emulator-tested, NOT on hw): DDS-DSP LFO
- **LFO tab** (DDS-DSP menu: OSCILLATORS / SAMPLE ATTACK / ENVELOPES / MODULATION): WAVE (TRIANGLE / SQUARE / SAW /
  RANDOM = sample & hold per cycle), RATE (0.2-15 Hz), PITCH (0-16 = up to a semitone, shown in cents), FILTER (0-16 =
  up to +-64 knob units on the cutoff), LEVEL (0-16 = tremolo depth), DELAY (fade-in after each note-on, 50-8000 ms).
- One global LFO on the host (no DSP words: DSP1 is full), phase from the 1 ms clock, applied at most every 15 ms:
  - vibrato: LFO_OFF (signed 1/16 semitones) is added in keys_osc_note (osc table index) and picks the sample's pitch
    fields from `ratio_fine` (61 keys x 16 steps); only sounding voices are rewritten, only when the offset changes.
  - tremolo: TREMF (1..64) scales every level write (`trem_scale`: 2 x level x TREMF / 64), so the envelopes and the
    LFO never fight over the level coefficient.
  - filter: FLFO is added after knob A + filter env in kv_env (clamped 0..126).
  - Signed math stays unsigned with u = v + 64: offset = (u x depth >> 6) - depth.
- Back to rest when every depth is 0 (offset 0, TREMF 64, FLFO 0 written once).
- Emulator (`tools/test_lfo.py`): vibrato TRIANGLE 2 Hz PITCH 16 swings the saw 246.9-276.2 Hz around C4 (one
  semitone each way), the sample's pitch fields by 1.116 (2^(2/12) = 1.12); PITCH 0 -> 261.6 Hz again; tremolo SQUARE
  4 Hz LEVEL 16 = level target 96 <-> 1; FILTER 16 SAW 2 Hz = cutoff offset +63 .. -64; DELAY 500 ms fades in.

### v1.91 (1191, 2026-10-15, emulator-tested, NOT on hw): ROUTING + LAB tiles, Mac page engine
- **Mac page engine** (build_v10 `MAC_PAGES`): one table-driven generator for every Classic Mac page (window, 3-row
  list, submode menu with full names and `>`, scroll bars for lists and menus > 3). DDS-DSP moved onto it. Item =
  (label, RAM byte, min, max, apply routine, display: number / table / OFF / name list / pan); a tab can also be a
  routine name (own body: `<name>_d` draws inside the window, `<name>_k` gets the keys, EXIT home, ENTER = menu).
  Wide values (range > 31) step with the dial's speed (1..8 per pass, KSTEP), buttons step 1.
- **ROUTING tile** (Roland's own mixer, so the stock screens agree with it; NOTES "DSP0 mixer map"):
  QUICK SETUP (PRESET: DRY / INPUT FX / LOOP FX / MASTER FX / REC FX / FX PATCH, FX AT = the 16 FX LOCATIONs,
  FX RETURN, MASTER), LEVELS (tracks A-D, input, REC BUS), PAN, FX SENDS (+ send master), AUX SENDS (+ AUX master).
  FX AT writes the stock setting (0x426DD1, bit 7 of 0x426DD0) and calls Roland's apply (0x1361CE), because the OS
  re-applies the location on pad playback (0x14E8B0 -> 0x1361FE): a bare MIXER_PARAM(7, 0, code) would not stick.
  LOOP FX = SEND/RETURN with tracks A-D sending 100, the input 0, send master 100.
- **LAB tile** (hidden hardware): ANALOG INPUTS = the 14 raw ADC bytes (0x426CBE) as live bars (40 ms), the selected
  channel inverted with its name and value (names from CONTROLS.md: 0-3 faders A-D, 4/5 fader 5/6?, 6-8 PARA-A..C,
  9/10 BEAM L/R, 11 FOOT SW; 4/5/12/13 to confirm on hw);
  BUTTONS = the last key event, its name from the factory SW CHECK table, the code, UP on release.
  LED SHOW = every LED one at a time (</> step, UP = chase every 90 ms, DOWN = stop) with its factory name and code;
  each LED's own state is put back when it is left (and on leaving the tab / page).
  LCD ICONS = the 7-segment line's 184 bits that no digit uses, one at a time (</>, with row / word / bit) or all at
  once (UP): if the glass has hidden icons they light up; the line is put back on leaving.
  PAD VU METER = the input meter (LVL_L / LVL_R 0x427838 / 0x42783E) on the pad LEDs, pads 1-8 left, 9-16 right,
  4.5 dB per pad; the stock pad LEDs are kept and put back (shared with KEYS: pads_take / pads_give).
- **KEYS: sample + oscillators**: with SAMPLE and any oscillator on (LA off, loop off) a held note no longer stops at
  the sample end: the sample is cut there (the LA cut, VLAT = VSEND) and the oscillators hold the note. (Found by the
  suite: ENV DECAY/SUSTAIN with SAW + SAMPLE ended at the 439 ms take.)
- **Validated (2026-10-15 ~02:00):** the full `test_v10.py` suite passes on the v1.91 build staged in work/v191
  (source commit 4e1cf7d): KEYS, PAD BANK, S-EDIT keys, REVERSE / LOOP, DDS OSC / LA / ENV (decay to half and holding,
  filter env), routing on enter / exit / mode keys; plus test_route / test_mfx / test_kset / test_padled.
- Tests: `tools/test_route.py` (ROUTING presets / FX AT / mixer calls / dial step, LAB bars / channel / key names).
- **S-EDIT on the Mac engine**: same rows and keys as before (RELEASE, THRU / REVERSE / LOOP with ENTER = toggle), then
  CUTOFF / RESO / ATTACK (knobs A / B / C) as read-only rows; no submode menu (engine option `menu=False`, read-only
  rows = apply 'ro'). `tools/test_kset.py` replays the old key sequences.
- **MFX tile (interface + hooks; the sound blocks wait for ears + an audio loop):** our DSP1 program
  (`tools/mfxdsp.py`, table at DSP_BASE + 0x900) serves all **three** DSP0 insert slots; each slot is a stereo LEVEL
  block for now (64 = x1, 127 = x2, 0 = silent), which is enough to prove the slots on the unit by ear.
  - FX CHAIN: ENGINE OFF/ON, SLOT 1-3 AT (OFF + the 14 insert points), SLOT 1-3 LEVEL. CONTROLS: KNOB A/B/C, BEAM L/R,
    FOOT SW -> OFF / SLOT n LEVEL (raw ADC >> 1, applied on change).
  - ON: saves the stock FX LOCATION, closes the write gate (KGATE bit 1; KEYS uses bit 0), loads our program (mute,
    load, FX_CUR = 0xFFFF, levels, unmute), routes: slot 1 the stock way (index + bit 7 + 0x1361CE, so EFFECTS off =
    slot 1 off, and the OS's re-apply on pad playback agrees), slots 2/3 straight MIXER_PARAM(7, 1/2, code).
  - OFF: gate open, slots 2/3 to code 0, the stock location back, and the stock FX patch reloaded with Roland's
    0x1081D6(0x42235E) if its algorithm word is < 20 (**unverified on hw**: 0x42235E looked like the current patch).
  - KEYS and MFX share DSP1: each load clears the other's "loaded" flag; mfx_guard (idle, our screens only) reloads
    MFX after KEYS gives DSP1 back.
  - Emulator (`tools/test_mfx.py`, DSP1 model): load through the flash table, all slots x1.0, slot 2 at 32 -> x0.5,
    knob A -> slot 3 level 100 -> x1.56, Roland's writes dropped while on, passed after OFF, KEYS round trip reloads.
  - Hw test idea: ENGINE ON, SLOT 2 AT TR.A POST-EQ, SLOT 2 LEVEL 0 -> track A (the pad voice on channel A) silent.
  - v1.94: CONTROLS row PADS 1-3 = PLAY / FX SWITCH: on the MFX page pads 1-3 bypass / enable slots 1-3 (a bypassed
    slot = x1), their LEDs show the slots that are on (pads_take / pads_give), pads 4-16 still play.

### Hidden stuff (log of finds, 2026-10-15)
- **3 FX insert slots in DSP0, Roland uses 1** (mixer group 7 index 0/1/2): slots 1/2 send on GRAM D0-D6 and return on
  64-6F; no Roland DSP1 program reads them. Our own DSP1 programs can run 3 effects at 3 mix points.
- **AUX bus** (send 1 per channel + AUX master) feeds INS AUX-OUT / the AUX jacks; **REC bus** (per channel MIX or REC).
- **Direct outs**: DSP0 writes every track's signal to GRAM g[E0]-g[EE] (+ g[88]/g[8A]); a second tap selector
  (mixer group 6 index 11) picks any of the 15 tap points for g[EA]/g[EC].
- **14 peak meters** computed in DSP0 (0x27E-0x2ED) into GRAM g[84]-g[C6].
- **Factory test mode** (power-on combo ST D + EFX D -> 0x11BDE6, see the combo table; CONTROLS.md had most of it): LCD / ENCODER / SW / LCD
  CONTRAST / FADER / POT / **BEAM CHECK (L + R sensors)** / FOOT SW / MIDI / Zip / IDE / **SCSI + DIGITAL (coax / optical)
  CHECK for an "SP808-OP1" option board** / ANALOG CHECK (Fs 44.1 / 32 kHz, LINE / PHONE, MASTER / AUX / M+A outputs,
  AUX IN) / LED CHECK / DEVICE CHECK (CPU, DRAM).
- The factory DEVICE CHECK also runs an **ESP CHECK** (0x126C02, strings 0x160B1C): PRAM / IRAM / GRAM / ERAM of both
  DSP cores, NG / OK each. The OS was built **Sep 20 1999 11:03:14** (string right after it).
- D-Beam = ADC 9 / 10 read through curve tables (0x127A66 -> 0x426D12 pointers); 0x12780E = raw ADC n + 9.
- **System parameters live in flash, not on disk** (save routine around 0x122E40): a 0x6500-byte image of the flash
  sector at 0x1F0000 is rebuilt in RAM (er6): 0x1F0000-0x1F63FF copied back as it was (unknown contents, kept), the
  33-byte system params from RAM 0x43B3D8 at +0x6400, the tag "TS25ESYSTEMPRMxxBAK" (0x1608D0) at +0x64F0; then the
  boot APIs 0x4005C4 (erase) / 0x4005D4 (program) write it back. Load (0x122F7C) checks the tag first.
  **+0x6421 .. +0x64EF (207 bytes) are free**: room to make our settings (DDS patch, ROUTING, MFX, LFO / ARP / VOICE)
  survive power-off by hooking the save after the image is built (copy our block in) and reading 0x1F6430 at boot.
  NOT done: it writes flash, so it waits for the user's OK.
- **LEDs: 65, driven by code** (the same codes as the keys: pads 10-1F, LOC 40-43, EFX 50-54, STATUS 60-67 = A-D x 2
  colours?, F4 / C4-C9 / 30-31 = LED-only). API: 0x132866(code) on, 0x132880(code) off, 0x13289A / 0x1328E0 /
  0x1328FC / 0x132934 / 0x132944 = blink variants (masks 0x4273B0 / 0x4273D0); state bits 0x427390 + 2 * (code >> 4),
  bit mask table 0x16464E[code & 15]; 0x13268C + 0x132564 push a row to the hardware. Factory list: 0x15F91E.
  Ideas: KEYS voices on the pad LEDs (done in v1.91), a VU meter on the pads, MFX slots on the EFX LEDs, a boot
  light show.
- **7-segment line = 2 rows x 12 LCD words** (row 0 at 0x40187A, row 1 at 0x401892, cleared by boot 0xA258, written
  by boot 0xA27C = API 0x4003E4). 25 digits in 4-bit groups: type 0 bits 13-10, type 1 bits 9-8 + 5-4, type 2 bits
  3-0 (types 0xA226, word offsets 0xA23F). Word 11 of both rows and bits 15-14 / 7-6 / 3-0 elsewhere are never
  written by a digit: 184 free bits = candidate icons (LAB LCD ICONS lights them on the unit).
- Mixer levels: 100 = the OS's nominal level (it writes 100 for master / input / tracks), 127 = about +6 dB over it
  (coefficient 63>>3 vs ~4.0), 64 = about -10 dB.

### v1.9 (1190, 2026-10-14): DDS-DSP tabs OSC / LA / ENV (host only, no DSP words)
- User picked LA + ENV and LFO first, DDS before Looper v2 (and will test the old looper meanwhile).
- **Tabs:** ENTER cycles OSC / LA / ENV (title row, current tab inverted), UP/DOWN pick, dial / LEFT / RIGHT change.
- **LA** (D-50 style, sampled attack + synth sustain): TIME (sample time after the note start, 0 = off), FADE (fade-out
  length), SAMPLE. With LA on a note never ends with the sample (VEND = never, no loop handoff): after TIME the
  voice's own mxs coefficient ramps SAMPLE x 4 -> 0 over FADE (host, written when the value changes); at the sample's
  end (VSEND, the old VEND) it is cut to 0 anyway, so the oscillators carry the note. VLAS per voice (1 fading, 2 out);
  la_reset restores mxs when a voice is reused (note-on, loop continuation); dds_ap0 skips voices LA owns.
- **ENV:** ATTACK (= S-EDIT knob C), DECAY (0 = off, time for a full-scale drop), SUSTAIN 0-16 (VSUS = velocity level x
  SUSTAIN / 16), RELEASE (= S-EDIT), FLT ENV 0-16 (x 8 cutoff-knob units on top of knob A), FLT DEC. Decay steps
  VTGT (and VLVL in state 2) down to VSUS every DEC_PER ms (states 2 and 6, so a loop handoff fades in to the decayed
  level; kl_prep carries VSUS). The filter is one SVF on the voice sum, so its envelope restarts on every note-on
  (paraphonic): cutoff = knob A + env, written through keys_cut_env (frequency words only) when it changes; knob A
  127 (filter off) disables it.
- Code passed 32 KB: h8asm now turns an out-of-range bsr16 / bra16 into jsr / jmp @aa:24 (same 4 bytes); the draw
  dispatcher's conditional branch to lp_draw goes through a jmp.

### v1.82 (1182, 2026-10-14): DDS-DSP labels, POLY on the 7-segment line
- User: keep the mixer (every wave its own level) and the DDS-DSP name, clearer labels: PULSE -> SQUARE, PW -> WIDTH,
  UNISON -> SAW2 (the page is a per-voice source mixer, not slots).
- 7-segment line on the KEYS / S-EDIT / DDS-DSP pages while KEYS owns DSP1: " POLY n" = voices with VSTATE != 0
  (playing, starting or releasing), live every idle pass, instead of the ROSETTA / VER / MB ticker (user: "POLY reads
  well in numeric").

### v1.81 (1181, 2026-10-14): idle oscillators frozen, 7-seg R / M
- **Confirmed on hw 2026-10-14:** "works now no back noise".
- **Hw report on v1.8:** synth notes play with the right envelope, but a background drone of the same wave sounds
  under them ("similar issue to earlier with the sample keys mode", i.e. v1.71's idle voices). The model is silent
  there. Reading: v1.72's hard mute (lvlk 0 + g 0) may have worked on hw through g = 0 alone (the sample read frozen
  = DC), so idle voices may keep a level on hw; v1.8's oscillators don't stop with g, so they drone at the last notes.
- **Fix 1:** the idle mute also writes og / og2 (phase feedback) = 0: phase = increment = constant (DC); unmute
  writes 64 back (before the voice starts, same pass).
- **Fix 2 (belt and braces):** TRI / PUL / JUNK moved 0xC0-0xC4 -> 0x9A-0x9E. No Roland DSP1 program (base + 20 FX)
  uses IRAM 0xB0-0xEF (only DSP0 does; fx18 reaches 0xAF), so that range is unproven on DSP1. Voices 4-7 still keep
  OPH1/OPH2 at 0xB0-0xBF: next suspect if the drone stays.
- Shared mulcoeffs: DSP0's program writes only mc3 / mc4, the DSP1 base and FX only mc0-mc2: Roland partitions them,
  which fits "DSP1 has no mc3" (DSP0 owns it). mc2 (our level) is safe.
- **7-segment line:** R = Γ (segments a e f) instead of the small r; "MB LEFT" -> "MMB LEFT" (M = two digits, wide
  M), the leading space dropped so 3-digit sizes still fit the 12 digits.

### v1.8 (1180, 2026-10-14): DDS-DSP, oscillators in every KEYS voice
- v1.72 confirmed on hw ("works now"; one hang once after fast chords, didn't come back). Pushed (90ab838).
- **New home tile DDS-DSP** (page P_DDS = 5, after S-EDIT; 6 tiles, the home view scrolls so the cursor stays on
  screen). KEYS stays live there (pads, MIDI, PAD BANK, knobs). Items, 2 columns x 4 rows, UP/DOWN + dial:
  SAMPLE 0-16, SAW 0-16, PULSE 0-16, PW 6-94 %, TRI 0-16, UNISON 0-16 (detuned 2nd saw), DETUNE 0-94 cents
  (1/16 semitone steps), OCT -2..+2. Levels x4 -> SH6 coefficients (16 = 1.0). SAMPLE 0 = synth only: notes hold
  while the key is held (no sample end, no loop handoffs).
- **DSP voice block 44 -> 57 words** (voices 0x100-0x2C7). Oscillator 1 = a raw 24-bit phase (the saw itself):
  increment = o2 * 32768 + o1 * 512 + o0 * 8 per sample (constants 0x400000 / 0x10000 / 0x400 with SH7), host
  table osc_tab (MIDI 12-121 in 1/16 semitones, 3 bytes). Pulse = sat(sat((saw + pw) * 15.9) * 15.9), edge
  1/252 of a cycle; triangle = 2|saw| - 1 (op 0x7C abs). Oscillator 2 = the unison saw, detuned by DETUNE steps.
  The sample interpolation moved from A to B (op30 acc_b) so A could run the oscillators; the mix is in B:
  B = sat(sample) * SAMPLE (op 0x1C store + reload) + saw + pulse + tri + unison, then SMP -> x level (mc2).
  An 'fm' word (unison saw of the last sample into osc 1's phase) is in place, coefficient 0 (FM = v2.0).
  Shared temps TRI/PUL/JUNK at 0xC0/0xC2/0xC4, OPH1/OPH2 per voice at 0xA0 + 4v. ERAM reads unchanged (rdA +17,
  rdB +23); the FC/FD latches are read at +31/+36 (any time before the next commit).
- Model: saw / pulse 50 % / pulse 75 % / triangle all at 261.6 Hz (C4 on pad 8), unison +12.5 c beats at the right
  rate, the sample path gives the same numbers as before.
- Host: keys_osc_note (note-on and loop continuations) writes both oscillators' 3 fields; dds_apN write one item to
  all 8 voices (only while KEYS owns DSP1); keys_load re-applies them after a program load.

### v1.72 (1172, 2026-10-14): PAD BANK inside KEYS, idle voices hard-muted, keys +6 dB
- **Hw v1.71:** background much lower but still there; it's "a mix of notes" looping every 1-3 s, THRU off doesn't
  change it -> not the pass-through. Roland's DSP1 base (58 words) has no ERAM access, the loader writes all 708
  words (no stale FX code). Explanation that fits: idle voices keep running at their last pitch (X drifts at 1 - r,
  the read address moves at speed r) and replay the whole ERAM ring (the take, at that pitch) every 1.5/3 s; audible
  only if their level isn't exactly 0 on hw (the model decays it to 0; cause on hw unknown).
- **Fix:** idle voices hard-muted per pass (VMUTE): 'lvlk' = 0 (L = t * 512 = 0 exactly, no smoothing residue) and
  'g' = 0 (phase held: X = REF - delta, the read address stays fixed = one word, DC). Back to lvlk 63 as soon as
  the voice is busy (note-on state 1, loop continuation state 7), before kv_tick starts it. keys_load clears VMUTE.
- Checked: Roland's coef writer 0x108936 skips writes while @0x411B65 & 3 == 3, but that is only set inside the DSP
  word read 0x1098DA (used by the DSP RAM self-test), so no dropped writes in normal play.
- **Keys +6 dB:** the level coefficient is 2 * VLVL (0..126; one voice at the default 48 = 0.375 of the sample).
- **PAD BANK (0x20 / SHIFT 0x120) on KEYS / S-EDIT** never reaches the stock: the stock opens the bank screen 0x0B
  (0x13797A -> 0x140016), our screen gets the leave event (KEYS lets go of DSP1) and the stock switches banks
  behind KEYS' back (hw: pads went back to the old bank / silent, reset needed). Now: playing -> back to picking with
  bank mode on; picking: PAD BANK = bank mode, again = next 16 banks (1-16 .. 49-64); a pad = that bank (no
  sampling), EXIT cancels; the map lights the bank's pad. Group 2 also has 0x23 = HOLD (0x1377C8), 0x21 eaten.

### v1.71 (1171, 2026-10-14): background "oscillation" on hw, pass-through per channel, THRU toggle
- **Hw report (v1.7):** keys work, but a constant background "like the sample" on the KEYS page: forever, same
  level, filter (knob A) makes no difference, gone on EXIT.
- Ruled out in the models: stuck voices (stress test: 600 random pad events with chords, loop on/off, no idle voice
  ever has a level), SVF ringing (decays to ~-110 dB even at full resonance), the 0x34 0xA5 mc-from-B form (Roland's
  fx02/fx10/fx15 use it the same way, with B computed 4 words before).
- **Found:** the v1.5+ mixer added inL AND inR into one sum and stored it to both outputs (i[13] = i[19]): each
  side got the other side's input at unity, pads/tracks became mono +6 dB. If the master feeds back into the FX
  input at -6 dB, that is a loop of gain exactly 1: everything played circulates forever at the same level.
- **Fix:** the mixer moved to the free block before the voices (0x60-0x85): VS = sum of last sample's OUT (read at
  out + 1, one sample latency), SVF on VS, F = lp * wet + VS * dry (plain semantics again: off 0/64, on 64/0),
  i[13] = F + inL * thru, i[19] = F + inR * thru (B side via MIXF 0x98). Program end now 0x260: 0x92 words free.
- **S-EDIT THRU on/off** (KTHRU, row next to RELEASE; cursor order RELEASE THRU / REVERSE LOOP): PLAY passes the
  pads/tracks through or not. Diagnostic: if the background stays with THRU off, it is not the pass-through.
- **Zombie voices (loop mode):** a key released while its voice was still at level 0 (attack start, fade-in start)
  left the voice in state 3 at level 0 forever; with LOOP on it kept handing over at level 0 and stole voices from
  held notes. The release ramp now also idles voices already at 0, and RELEASE 0 ms (period 0) drops released
  voices at once: before, the ramp skipped period 0 entirely, so with REL 0 every released voice stayed in state 3.
- Tests: the sim doesn't run the boot RAM init; test_v10 sets KTHRU = 1 like the unit (KREL stays 0 in the sim).
- Not done: idle-first voice allocation (round robin still steals the oldest voice, also for loop continuations).

### Hardware results 2026-10-14 (v1.1 / v1.2) and v1.3
- **KEYS works on the unit:** pitched across the pads, fast chords "sound great". Our own DSP1 program, on hw.
- **mc3 does not exist as a general register on the FX core (DSP1).** Odd voices used mc3 for their level
  (mc2/mc3 alternated): on hw their volume was wrong and ignored velocity, so velocity felt "opposite", staggered
  notes came and went, only struck-together chords sounded right. Roland's 20 FX programs only ever write mc0-mc2
  (mc0 88x, mc1 36x, mc2 33x); DSP0's voice engine does use mc3. v1.3 (1130): every voice on mc2. Rule: on DSP1
  use mc0-mc2 (+ mc6 = the ERAM variable-offset fraction) only. The emulator models mc3 as generic, so it can't
  catch this.
- v1.2 fixes (emulator): recapture left used voices silent/DC (g = 0 and g = 64 on the same DSP sample; start now
  waits >= 2 ms ticks); notes no longer redraw (a draw costs ms; dirty flag, redraw after the voices, max every 30 ms);
  pick screen BANK/PAD, pad hit = capture via stock bank switch 0x137B5A; SHIFT+EXIT = re-pick.

### v1.1 (build 1110, 2026-10-13, emulator-tested, NOT on hw): MIDI keyboard, velocity, release
- **Stock MIDI path found:** SCI0 is MIDI (0x1356D2 echoes RDR 0xFFFF7D to TDR = THRU). Byte parser 0x134B58:
  status -> handler pointer @0x427504 from the table at **0x164B88** (note-off 0x134D0C, note-on 0x134D46, poly AT
  ignore 0x13EFF0, CC 0x134F7A, PC 0x134FB4, ch AT / bend ignore) + data-byte counts at 0x164BA4 (2 2 0 2 1 0 0);
  data bytes land at 0x42743B (note) / 0x42743C (velocity), count @0x427439, running status @0x42743A; handler called
  with r0l = channel. Stock note -> pad: 0x134C72 (note - base note @0x43B3F8, 16 pads, pad channel @0x43B3E3 - 1),
  0x134C9C = pad note-on with the MIDI velocity, 0x134CCE = note-off, pad mask @0x427512.
- **Hook:** the two table entries now point to `m_off_tr` / `m_on_tr`: while the KEYS page is in PLAY they queue
  (key, velocity) into a 16-entry ring (RAM +0x290, MWR/MRD) and return; otherwise `jmp` to the stock handler.
  The ring is drained in `ki_voices` (main loop), so the DSP host port is never touched from the parser's context.
- **Keys:** key id 0..60 = root - 24 .. root + 36 semitones (`ratio_tab` 61 x 3 coefs); pad p = key p + 17, MIDI
  note n = key n - 36 (C4 = pad 8 = the sample's own pitch), notes outside C2..C7 are ignored.
- **Velocity:** `vel_tab` (128 bytes) -> level target 1..48 (linear), stored per voice in VLVL (+0x258) and written
  to the voice's `t` coefficient when the voice starts; pads play at 48.
- **Release:** setting KREL 0-9 = 0 / 50 / 100 / 200 / 300 / 500 / 750 / 1000 / 1500 / 2000 ms (default 200): the
  host drops a released voice's level one step every `rel_step[KREL]` ms (48 steps), the DSP's 1.5 ms one-pole
  smooths each step; 0 = cut as in v1.0. Dial / LEFT / RIGHT set it while playing ("PLAY REL 200MS"); UP / DOWN
  (and LEFT / RIGHT while idle) pick the source pad.
- Tests (`test_v10.py`): note 72 -> 2004.5 Hz, velocity 40 -> peak 0.029 (= 0.094 x 15/48), 500 ms release ->
  0.091 0.078 0.059 0.041 0.025 0.008 per 100 ms, out-of-range notes ignored, pads unchanged.
- Unknowns on hw: the MIDI parser's context (interrupt or main loop: the ring makes both safe); the pad MIDI channel
  setting is ignored while KEYS plays (any channel); the stock sequencer still gets CC/PC.
- Tests: `keysdsp.py` (model: 1 kHz recorded, ratios 1 / 1.498 / 0.5 / 1.5 -> 1002 / 1498 / 504 / 1500 Hz, detector
  fires 1 sample after onset), `test_v10.py` (firmware + model: load 46 writes, routing 7/0/12, onset, 639 ms take,
  root 1000.4 Hz, +7 1499.7 Hz, -7 664.5 Hz, release, chord, exit restores routing 1).
- Hardware unknowns: the ESP model itself (from a published bit-exact emulator of another product), the readback
  byte layout (we test the low nibble of all 4 bytes), whether the master insert really carries the pads, the
  JMP 0x2F2 cycle budget. If KEYS stays silent: check FX LOCATION / FX on, then the readback.
- Sources: gearmulator `source/ronaldo/custom_chips/esp/esp.hpp` (dsp56300/gearmulator), the A to Synth blog
  "A deepdive into the JP8000 and TC170C140 ESP" (2026-02), 39C3 talk "From Silicon to Darude Sand-storm".

## v0.9b (2026-10-13): looper fixes after the first hw test, debug trace
- **v0.9 on hw:** layer 1 fine; at the end of layer 2 it fell into Roland's SAMPLING setup (0x20),
  loop 1 stopped, "Finished." popped up, everything felt slow.
- **Cause (reproduced in the emulator once the lock was modelled):** 0x13FC0E (go to screen) is ignored
  while 0x42790E bit 1 (sampling lock) is set. Lock: 0x13F2D0 sets bit 1, 0x13F2C2 sets bits 1-2,
  0x13F2DA clears them; 0x22 event 0 locks, its leave and the r5=1 epilogue unlock. Stock forces a jump
  with 0x13FC8A (unlock, switch, relock). Our looper cancel (double tap / hold / EXIT on 0x22) used the
  plain call: the jump was dropped after our state was reset, so stock carried on.
- **Commit 0x13F9C2:** loops while current != pending (event 1 old, event 0 new), then CLS, event 5
  (0x13FBB6), event 2 (0x13F18E). A jump asked for in event 0 is followed in the same commit.
- Fixes in tools/build_v09b.py (unlock before every looper jump; layer processed on the next 0x23 idle;
  LOOPTAKE checked first; LOOP page 4 fps). ENTER on the LOOP page shows a trace (see its docstring).

## v0.9 (2026-10-13, built + emulator-tested, not on hw yet): LOOPER v1 (pad layers)
- **User chose:** layer looper; control = PAD SAMPLING (their footswitch is wired to it) + a MIDI backend
  (MIDI still to do); keyboard mode later, poly.
- **Behaviour and engine:** see the docstring of tools/build_v09.py. Emulator session test:
  `python -I tools/test_v09.py build_v09/sp808_v09.bin art/v09_emu.png` (fakes the screen engine, the pad
  table and the stock 0x22/0x23 handlers; checks trim, start phases, double tap, hold, clear).
- **Pad entry (32 bytes):** +0 start, +4 end, +8 loop point (longs, units of 16 samples = one compressed
  block: 24 bytes stereo / 12 mono; disk address -> units 0x14D584), +12 wave (table 0x4227B6, 8 bytes per
  wave: +0 flags (0x80 mono), +2 first block), +14 flags, +15 level, +16/+20 recorded start/end
  (0x13CC64 copies them at the end of a take). Only +0..+15 go to the voice (0x14EA28 -> 0x43B670 + 16 * ch).
- **Flags +14:** bits 0-1 loop OFF / ON(S-E) / ON(L-E), bits 2-3 pad play GATE 0 / TRIG 4 / DRUM 8 (DRUM
  disables the loop), bit 7 mono. Built at arm time (0x13C30E) from 0x4277CB / 0x4277CC via table 0x166012.
- **Pad play:** note-on 0x13735E -> 0x13749E -> voice 0x14EC5E (channel from 0x1000A6(flags)); note-off
  0x13743A -> 0x137448(pad, r1l): r1l 0xFF = by mode (TRIG/DRUM ignore it), 0 = stop. All off 0x1371F4
  (also kills TRIG voices via 0x1375A8). Pad state 16 x 14 bytes at 0x4275AE (+0 flags copy, +1 bit 1 voice).
- **Vtables** (+0 event, +4 note-on, +8 note-off): normal 0x1653E8, sampling 0x1662D6 (= normal + "pad press
  starts an armed take" when 0x4277D0 bit 3), take preview 0x166342, select pad 0x165FFE. 0x13704A switches
  and stops all pads when the vtable changes.
- **Take:** 0x13CAEC arms/starts (0x14F0C6 record channel @0x4032D4), 0x13CB54 stops and finalizes the take
  entry 0x4277D8 (wave @0x4277E4); waiting/empty take: 0x122C1A frees the wave, 0x122642 empties the entry.
  0x137B5A(bank) at the stop reloads pads only if the bank changed.
- **Timing:** 8-bit timer 1 at phi/64, TCORA 0xEE -> ~1 ms (0x40185E). Loop clock in 16-sample units:
  ms * 441 / 160.

## v0.8 (2026-10-13, WORKS on hw: "real awesome"): own record / take-done screens, 7-seg ticker
- **User asked:** record/result screens in our graphics (big timer, live meter, waveform); the 7-segment
  "time keeping" part of the LCD to read "Rosetta OS", the version and megs left.
- **Record screen 0x22 (stock handler 0x13C938):**
  - Events: 0 enter (arms the take), 1 leave (0x13CB54 stops it), 5 redraw, 6 idle, 9 key, 0x19 = finish.
    Return value unused; when r5 = 1 the epilogue 0x13CACA stops the take, CLS, unlocks, goes to 0x23.
  - Event 6 logic: 0x14D91E(0) == 0 (disk full) -> finish. "Waiting Signal..." text 0x166288 ->
    "Now Sampling..." 0x166298 (pointer 0x427910) when 0x4277D0 bit 2 is set and 0xFFF0DC bit 0 is clear.
  - **Level meter:** 0x13D0DE (every main-loop pass from 0x13F048) reads 14 meter channels round-robin via
    API 0x400354/0x400358 into records of 6 bytes at 0x4277FC + 6*ch: word +0 = DSP peak (high byte = level
    0-127), +2 bit 0 = dirty, +3 = peak, word +4 = peak hold (100). Input L = ch 10 (0x427838), R = ch 11
    (0x42783E). Stock draw 0x131EF0: 21-row vertical bar, level -> top row via table 0x1643A4 (128 entries,
    log). 0x13C236 places the trigger-level icon with the same table (@0xFFF0D4 = trigger level).
  - **Remaining:** free 32 KB blocks = @0x411B6E - @0x42741A - 3 (0x14D90E). 0x14D948 turns it into time:
    frames per block = 0x8000 / (24 stereo, 12 mono: 0x426E29 bit 1) * 16, / 44100 (or 32000, 0x14DB06),
    * 1000 / @0x43B326. 100 MB Zip ~ 3000 blocks ~ 24:46 stereo.
  - **Ticks:** boot ROM 8-bit timer 1 IRQ 0x93F0 (TCR1 0x0A, TCORA1 0xEE) increments the long 0x40185E
    (~1 ms) and runs 8 timer slots (12 bytes each at 0x4017FE, API 0x4002E4(r0l slot, e0 period, er1 func)).
    The OS's slot 7 (period 10) increments 0x4278B4 (10 ms) and 0x4278B6 (every 128 ticks).
- **Take-done screen 0x23 (0x13CE1C):** 0 enter (empty take -> 0x20 "Cenceled."; auto trim -> 0x24),
  2 shown ("Now Working...", writes the take into the pad, sets 0x4277D0 bit 6, CLS, redraw),
  5 "Finished." / "Disk Full." + meter, 6 meter, 9 ENTER -> 0x1F / EXIT -> 0x20 "Try Again.".
- **7-segment line** (LCD RAM rows 0-1): 25 digit positions; type and word offset per digit in the boot ROM
  tables 0xA226 / 0xA23F. Type 0 bits: row 0 a 0x2000 g 0x1000 c 0x0800 b 0x0400, row 1 f 0x2000 e 0x1000
  d 0x0800 dp 0x0400; types 1 and 2 are the same bits shifted (0xA2A0). APIs (the BOOTRAM dump is 8 bytes
  off: API X is the dump's entry X + 8): 0x4003D8 clear the line, 0x4003DC set digit (r0l), 0x4003E0 write
  pattern er0 (mask 0x3C003800), 0x4003E4 pattern er0 under mask er1, 0x4003E8 char code r0l (font 0xB3F2:
  0 blank, 1 '-', 2-11 digits, 0x0C-0x11 A-F), 0x4003EC number, 0x4003F4 two digits (r0l digit, r0h value).
  OS: 0x132480 prints ASCII (letters from table 0x163F26). Digits 0-11 = the time counter: 0x1441FE writes
  "HH-MM-SS-FF" (two-digit fields at 0, 3, 6, 9; '-' at 2, 5, 8), measure mode "MMM-BB-TT". 12-15 tempo
  (0x144244), 17-18 sample rate "44"/"32" (0x14DAE0).
- **v0.8 build (tools/build_v08.py, version 1080):** see its docstring. Our screens draw only in MPC take
  flows (SHIFT+PAD SAMPLING keeps the stock screens). ~39k instructions per 100 ms record frame.
  Emulator test: `python -I tools/test_v08.py build_v08/sp808_v08.bin art/v08_emu.png`.
  LOOP page = "coming soon"; the LCD test page and the boot ROM dump are gone.

## v0.7-v0.7f (2026-10-13): own graphics engine, pixel-exact LCD (v0.7f WORKS on hw)
- **Engine:** tools/gfxlib.py, with fonts and icons in tools/ui_gfx.py. Mockups in art/ (not in the repo) were approved.
- **Test tools:** tools/h8emu.py (small H8S emulator) and tools/test_ui.py run our draw code on the PC.
- **On hw, v0.7-v0.7e drew broken pixels:**
  - 32 px blits sheared.
  - 22/24 px blits lost every 8th pixel and left stray dots at the seams.
  - Flag 0x80 is a compressed format.
  - Stack: in on-chip RAM (SP ≈ 0xFFF914), not near our RAM.
- **v0.7e dumped the boot ROM** with Roland's own file save:
  - memcpy API 0x400224 into 0x440000, then save-file 0x10B61A(r0h 0x13, e0 0xFFFF, r0l 0, er1 = 8.3 name, stack: buffer, size).
  - Output: dump/BOOTROM.BIN (0x000000-0x0FFFFF) and dump/BOOTRAM.BIN (0x400000-0x402FFF). These are Roland data and are never committed.
  - The SP-808 wrote the directory entry and the data but not the FAT; extract them contiguously.
- **Boot ROM, LCD side:**
  - The API jump table at 0x400200 is `jmp` entries into the ROM; the blit is at 0xB074.
  - **The blit reads its source as 7 px per byte** (bits 7-1; `and.w #0x1FE` into an expand table at 0xAE34). Rows are ceil(w/7) bytes.
  - Blit flags: rows-byte bit 7 = compressed source (unpacked to 0x401BAA via 0xB2AA); y bit 6 = invert (@0x401EF8); y bit 7 = op 0xB1E6 instead of 0xB1CE.
- **LCD RAM:**
  - 0x40187A, 34 rows × 24 bytes, **6 px per byte in bits 5-0** (bit 5 = left; x tables 0xACF4 = x/6, 0xAD7C = 5 - x%6).
  - Rows 0-1 are the 7-segment / icon line. The dot rows start at @0x401EC4 = 0x4018AA, stride @0x401EBC = 24.
  - LCD init 0x9DA8; full copy 0xA046; port 0xA00000 = command/status (bit 7 busy), 0xA00001 = data.
  - The interrupt at 0x9C58 streams the whole image continuously (state machine via @0x401EAE, row counter @0x401EB6 0x80-0xA1, restart @0x401EB8).
  - So **writing the LCD RAM shows up on its own.**
- **v0.7f:**
  - gfx_flush packs the 128 px canvas (LCD x 4-131) into the LCD RAM: 22 bytes per row via nibble shift plus 3-bytes-to-4 six-bit groups; bytes 22-23 are cleared.
  - Roland-chan frames are stored pre-packed and copied in, so she no longer loses columns.
  - Boot sound: the first screen-5 idle event plays pad 16 (note-on 0x13735E, r0 = 15, r1l = 127).

## v0.6j (2026-10-13, on hw): EXIT cancels a take
- **User:** EXIT while sampling should stop, not save, and go back to the menu.
- **Stock 0x22 (record):** event 9 only handles PAD SAMPLING, and only while word bit 3 of 0x42790C is clear (it's set at enter). Event 0x19 also stops. Leave (event 1, 0x13CAB6) calls stop 0x13CB54, unlock 0x13F2DA and 0x14D1C6, then flags &= 0xFF86.
- **Our EXIT on 0x22:** MSTATE idle, then go to screen 5. The leave stops the recording, 0x23 never runs, and the take is never written to a pad.
- **Stock 0x23 EXIT:** 0x14D136 + 0x14D078 (stop the take preview, object 0x43B5A6), unlock, then go to 0x20 with the toast "Try Again." via 0x14D30E(0x16632A). The empty-take toast is "Cenceled." (0x166312, Roland's typo). Toast = message pointer 0x43B5E0, frames 0x43B5E4.
- **Our EXIT on 0x23 (was RETRY):** stop the preview, put the take pad back to its saved entry, KEEP to screen 5, "take canceled".
- The take pad's entry is now saved in start_rec for every mode.

## v0.6i (2026-10-13, WORKS on hw): encoder in our menu, CLASSIC records into the selected pad
- **v0.6h on hw:** "it seems to sample now". But ENTER in CLASSIC recorded into a pad the user couldn't see ("show what pad you selected, or say pick one"). The debug line hasn't been reported yet.
- **Encoder:**
  - Main loop 0x13F0F2: keys 0x13F2F0 → dial 0x13139A (delta → 0x427058) → param edit 0x129260 (via the current param object @0x426D3C, nothing for screen 5) → commit 0x13F9C2.
  - The commit sends event 6 (idle) to the screen on every pass without a screen change.
  - Screen 5 maps event 6 + delta to RIGHT/LEFT (HOME page: DOWN/UP).
- **MPC page rows:** Pad / Rec / Start / help.
  - Hitting a pad on the MPC page selects it (SELPAD, RAM +0x13), and stock still plays it.
  - Power-on: no pad selected. ENTER then says "hit a pad first!".
- **CLASSIC:** records straight into the selected pad S, after saving S's entry. A pad hit P on the result screen does P ← take, S ← saved entry, then SELPAD = P.
- **Pad used test:** 0x14D8AA(pad) = entry word 0 != 0xFFFF (current bank, 0x4225B4).

## v0.6h (2026-10-13, ran on hw): MPC page rework, CLASSIC = replace, pad-pick debug
- **v0.6g on hw:** the CLASSIC take stayed on the take pad T (pad 1) after hitting pad 13. "BANK FULL" after one take is real: the bank was full of old test takes.
- **Swap code checked:** the bytes match the design, and PAD_GET/SET for the current bank (@0x40323C) are plain 32-byte copies to/from 0x4225B4 + 32·pad. So either the pad hit never reached g1, or something rewrote T afterwards.
- **Key dispatcher 0x13F2F0:** it skips a group handler when the group's bit is set in the mask 0x427906 (setter 0x13F2E8), and the key then goes to the screen as event 9. 0x13AC1C sets 0x0002 (pads masked). The sampling screens don't touch the mask.
- **Screen events:** 0 = enter, 1 = leave, 2 = shown (sent once at the end of the commit, 0x13FB32 → 0x13F18E), 9 = key, 6 = idle. 0x23 event 2 writes the take into T = 0x4277C8 (bank 0x4277C7).
- **Take-preview vtable 0x166342:** a pad press plays pad 0x4277C8 (0x13735E), whichever pad you hit.
- **CLASSIC now:** T = first free pad, or pad 16 when the bank is full. T's entry is saved (RAM +0x20) before the take. On a pad hit P: P ← take, T ← saved entry. P == T means it stays.
- **Pad hits are caught in both g1 and w23 event 9.** Debug line on the MPC page: `<G|W|E> T<t0>/<t> P<p> <K|k|S|F|N|C|->`.
- **MPC page:** UP/DOWN picks the line, </> changes it, ENTER = take. SAMPLE on the MPC page = take, anywhere else = open the MPC page.
- **Guards:** our mode keys and PAD SAMPLING do nothing during our take. Before this, PAD SAMPLING on 0x22 (flags 0x0800, bit 7 clear) started a second take. PAD SAMPLING on screens 0x1F-0x24 goes to stock.

## v0.6g (2026-10-13, on the SD): CLASSIC MPC at power-on
- **v0.6f on hw:** lands on the MPC page after every take, no "RAM!", so the RAM move works.
- But the clean boot init made NEXT FREE (mode 0) the default. The old builds only started in CLASSIC because pool record #445's prev link (0x01BC) left 0x01 in SMODE.
- **Change:** the boot init and the ramcheck reset set SMODE = CLASSIC. Version 1063.
- **Stock RAM clear (OS entry 0x126616):** zeroes 0x403000..0x42BFFF, copies .data, sets 0x426CB2, calls 0x126686 and boot 0x11F0AC, then jmp 0x400200. SP is not set in the OS (the boot ROM does it).

## v0.6f (2026-10-13): our RAM moved out of the stock event pool (IMPORTANT)
- **v0.6e on hw:** still dropped to "mode select" after a take.
- **Real bug since v0.4:** our block lived at 0x42BFF0.
  - Pool 0x427A6E is 2000 × 40-byte records (init 0x143566: count 0x7D0 → 0x427A4A; per record: prev word +0, next word +2, type byte +4, 0x10 = free). It runs to 0x43B2EE.
  - The startup zero loop only goes to 0x42BFFF, which misled us.
  - Our bytes sat inside records #444/#445:
    - The OS overwrote our canary, so ramcheck reset everything to the HOME page and NEXT FREE.
    - We overwrote #445's links and type byte (corrupt free list).
- **C runtime section table at 0x12670E:**
  - .data: ROM 0x16A9E6 → RAM 0x403000, size 0x2D9.
  - .bss: 0x4032DA, size 0x38826, so it **ends at 0x43BB00**.
  - No stock code references 0x43BB00..0x43FFF7. The PRG loader starts at 0x43FFF8, and sample RAM is 0x440000+.
- **New block:** 0x43C000 (canary + 8 vars).
  - Not cleared at boot, so the boot-anim player initialises it (bootanim.patch(..., prologue)).
  - The stack location is still unknown (set by the boot ROM). If it sits just under 0x440000 it would need to be 16 KB deep to reach us; the canary is the tripwire.
- If a song acts strangely, suspect pool damage from v0.4-v0.6e and use the SD backups.

## v0.6e (2026-10-13, on the SD): second-take fix
- **v0.6d on hw:** the first CLASSIC take + pad swap worked. After that it looped through the menus and never reached the record screen.
- **Cause:** word bit 6 of 0x4277D0 ("take done", set by 0x23 event 2) stays set.
  - Screen 0x22 enter calls 0x1404F8(3) (transport mode 3 = sampling).
  - On a group change, sampling-group handler 0x141232 event 2 calls 0x13659A (enter sampling mode) only while bit 6 is clear.
  - Stock never needs the reset, because its 0x1F/0x20 screens call 0x13659A themselves.
- **Fix:** bclr #6,@0x4277D1 in start_rec and in KEEP.
- **Transport modes:** 0x1404F8(mode) moves to the mode's default state (per-idx record bytes at 0x1677B6 + 12·idx).
  - Mode 0 → state 2 (STOP); mode 3 → state 0x15.
  - On a screen change the engine clears 0x42790F, then runs hooks from 0x166C24 for every bit still clear:
    1. 0x1404DC: restore the transport mode. Screen flags bit 12 → base mode @0x42792C, else mode 4.
    2. 0x137042: normal pad vtable.
    3. 0x142EB8
    4. 0x1440FA
- **Transport state setter:** 0x140572(state); records at 0x1676BC + 10·state.
  - Leaving a group sends event 1 to that group's handler. Entering a group sends events 0 and 2.
  - A new state without flag bit 2 calls 0x136534 (leave sampling mode).

## v0.6d (built 2026-10-13): CLASSIC = real MPC flow
- `tools/build_v06d.py`, version 1060. v0.6c was never flashed.
- **CLASSIC:** PAD SAMPLING records at once into the first free pad T.
  - On the result screen, hit pad P: the entries of T and P are swapped, then KEEP. ENTER = keep on T, EXIT = retry.
- **Pad entry API** (32-byte entries; r0 = pad<<8 | bank):
  - get 0x122946(r0, er1 = dst)
  - set 0x1229C2(r0, er1 = src). Current bank: copy into 0x4225B4 + 32·pad, then 0x123070 updates 0x4221DE[bank]. Other banks go through disk buffer 0x421B80.
  - memcpy 0x1230A2(er0 = src, er1 = dst, n word on stack), done with eepmov.
- **Stock screen 0x23 writes the take at event 2:** 0x1229C2(@0x4277C8<<8 | @0x4277C7, &0x4277D8). Then 0x10B8DC(e0 = 0, r0l = 0) and 0x137BC4(1).
  - 0x137BC4 = refresh bank pads: 0x137B66, then 0x10BA9A(current bank), then 0x10AEDA.
- **0x122000 is the disk-stream cue, not the pad write.**
  - Table 0x422176 holds 20 slots of 4 bytes: 16 pads + 4 tracks.
  - Dirty masks: 0x422130 = pads, 0x422136 = tracks.
- 0x13C1E8 only stores the take's wave number in 0x4277C4.

## v0.6c (built 2026-10-13): take-flow fix + no second splash
- v0.6b confirmed on hw: Roland-chan boots. The user saw the stock Groove Sampler slide disappear.
- Bug (CLASSIC, INSTANT): hitting another pad before closing the take-result screen jams it.
- Fix (`tools/build_v06c.py`, version 1059):
  - While MSTATE == REC, pads never reach the stock handler.
    - On screen 0x22, only the stop pad acts.
    - On any other screen, a pad press = KEEP.
  - KEEP and cancel call 0x137042 (normal pad vtable). Stock 0x23 leaves the preview vtable 0x166342 active.
- Second splash 0x1487FE (called from boot 0x11F0F2):
  - Draws the compressed layout 0x1687E6 (via 0x13177C), then 8 frames of 4 tiles 24x24 from resource 7 (blit 0x400480) with 0x1480EA(87500) per frame.
  - Patched at 0x148812 to: jsr 0x11F15C; jsr 0x4003CC; jmp 0x148886 (epilogue).
- Layout bitmaps (0x16864F etc.) are compressed. Only the S-P/8/0/8 raw format is known.

## v0.6b: Roland-chan boot animation (built 2026-10-13, CONFIRMED on hw)
- `tools/build_v06b.py` = v0.6 unchanged + `tools/bootanim.py`, version 1058. SP808.PRG sha256 67A26692…
- The art is the user's Hex Wizard line drawing, converted by `tools/roland_chan.py`:
  - Option 5 conversion: lanczos + sharpen + dither.
  - Legs erased. Picture is 48 px tall: she slides up from below, scalp intact.
  - Then a blink, a closed-eye smile, "JSW OS" typed in, then "ROSETTA" (2x bold 5x7 font on a cleared box over her mouth).
  - Preview: `art/roland_chan_boot.gif`.
- Hook: 0x14874A `mov.l #0x1684BA,er1` → `jmp 0x170000`. The player ends with `jmp 0x1487F0` (stock epilogue).
- Blit API 0x400478 (from the stock usage):
  - r0h = y, r0l = x, er1 = rows, e0 = (width<<8)|rows; push.l 0 as a stack arg.
  - Rows padded to 4 bytes, MSB = left, 1 = dark. er2-er6 preserved.
  - Another caller (0x132452) uses e0 = 0x14A0: lo-byte bit 7 is probably a mode flag, so 32 rows = 0x20.
- Frames are drawn as 6 strips of 22 px at x = 2..134: the proven stock digit format, centred if the LCD is 136 wide (the stock logo spans x 3..133).
- Size and timing: 45 steps, 40 unique frames, 31 KB at 0x170000-0x177A3A.
  - Delay 0x1480EA(50000) per tick; the stock uses 62500 per frame, probably µs. 112 ticks ≈ 5.6 s.
- Risk: if the blit misbehaves at boot, recover with the boot-ROM MIDI updater (stock OS).

## v0.5b / v0.6 (built 2026-10-13, not yet on hw)
- **v0.5b:** screen-5 params = -1. The default param table 0x166B08 mapped CURSOR up/down to LCD contrast (0x403126) and the encoder to the top-bar counter.
- **v0.6** (`tools/build_v06.py`, 2.7 KB, version 1057): MPC flow modelled on VMPC2000XL SampleScreen / KeepOrRetryScreen.
  - Hooks: key groups 1 (pads), 2 (PAD SAMPLING), 8 (mode keys); screens 5, 0x22 (record), 0x23 (take done).
  - Key word 0x4278BA: +0x4000 = release, +0x0100 = SHIFT; pad index = code & 0x0F.
  - Stock record end:
    - 0x13CB54 stops the recorder, applies the pre-trigger, and calls 0x122000 / 0x1229C2, which assigns the wave to the pad.
    - Screen 0x23 = "done": ENTER → 0x1F, EXIT → discard (0x14D136 + 0x14D078) → 0x20.
  - Stop-by-pad: rewrite the key to 0x22 and return 0, so the record screen sees PAD SAMPLING (the stock stop).
  - Unknown: recording into a used pad skips stock "Overwrite?" (old wave may be orphaned; stock CLEANUP DISK).

## v0.4 CONFIRMED on hw (2026-10-13), v0.5 built
- v0.4: PAD SAMPLING one-press record into the first free pad worked on the unit.
- **LCD = 4 text rows (0-3), about 136x32 px.** v0.4's rows 5/6 were off screen.
- v0.5 (`tools/build_v05.py`, 1.7 KB, version 1055):
  - Key group 8 hook (table 0x166C04): SONG=Looper, SAMPLE=MPC, SYSTEM=Keys, SHIFT+SYSTEM=stock system menu (0x41).
  - Screen 5 page engine: HOME list / MPC / LOOPER / KEYS / SAMPLE MODES.
  - MPC sample modes: NEXT FREE (one-press) and CLASSIC (stock flow); TAP/HOLD come in v0.6 via SHIFT+pad.
- Our RAM: 0x42BFF0 canary 'JSW!' + vars at 0x42BFF4.. (end of the BSS zero range).
  - Canary 0 = init; wrong value = "RAM!" warning on HOME.
  - The tempo-map array at 0x427A6E (40-byte records) has unknown capacity. If "RAM!" ever shows, suspect it.
- Key routing: dispatcher 0x13F2F0 → key-group table 0x166BE4 (index = key>>4). A handler returns 0 → the key goes to the screen as event 9. Screens mask groups via 0x427906 (0x13F2D0 etc.).
- Boot animation is in the OS at 0x14871A:
  - It slides S-P / 8 / 0 / 8 bitmaps (0x168539, 0x1685C3, 0x168609) up for 17 frames via boot API 0x400478.
  - Bitmap format: [w][h], then rows padded to 4 bytes, MSB first.
  - 0x400470 draws the 0x1684BA image (probably the "Groove Sampler" graphic, compressed?).
  - Replaceable with Roland-chan.

## v0.3: CONFIRMED on hardware 2026-10-13
- The unit boots to "JSW LOOPER v0.3" with no meters. ENTER opens the stock sampling flow.
- Built with `tools/build_v03.py` → `build_v03/SP808.PRG`. It is v0.2 plus:
  - screen 5 page set to 0
  - redraw on event 5
- **v0.2 lesson:** a screen's *page* field (+12) is a widget layout the OS draws itself. The stock meter page drew the CH meters over our text.
  - page 0 means no widgets; screens 0-3 and 0x0E use it.
- Update flow notes:
  - The disk is usually ejected after loading SP808.PRG, so the unit asks for a Zip. Power-cycle with the SD in.
  - The update check runs from the disk/boot screens (0x147F12, via screen 1-4 handlers), not from screen 5. So replacing screen 5 keeps disk updates working.
  - To force the update: hold HOLD at power-on (0x14800C).

## v0.2: own home menu (built 2026-10-13; worked on hw, but meters drew over the text)
- `tools/build_v02.py` → `build_v02/SP808.PRG` (version 1052). Uses `tools/h8asm.py` (a mini assembler, round-trip checked with h8sdis).
- Screen 5 (the boot/home METER screen) handler → our code at 0x16B000 (216 bytes).
  - On enter: sets home=5, runs the stock meter-tap setup (0x120332, 0x11F2AE), clears the LCD, prints 3 lines.
  - ENTER → screen 0x1F (the stock PAD SAMPLING flow).
  - Key 0xF2 → AUX meter, as stock.
- The changed bytes are only: the version (3 places), the JSW string, 3 bytes of the screen 5 entry, and the new code.
- Screen handler protocol: `handler(r0.w = event)`. 0 = enter, 5/6 = refresh/tick, 9 = key (code in 0x4278BA).
- Home screen id lives at 0x403256 (initial 5); EXIT goes home via 0x13FD12.

## DSP0 mixer map (2026-10-15, emulator: tools/mixmap.py -> work/dsp/mixmap.txt)
`tools/mixmap.py` runs Roland's own mixer API 0x11F2AE(r0 = group, e0 = index, r1 = value) in the H8S emulator
(boot ROM math library + dump/BOOTRAM.BIN loaded, DSP shadows prefilled with the ROM programs) and diffs the DSP0
shadow (0x410362, 4 bytes per word: bytes 0-2 = ROM order, coef first) for values 0..127. Values land in RAM tables
0x422018 + 0x2A * group (channels), 0x4220EA (group 5), 0x4220F0 (group 6), 0x422108 (group 7).

**Channels** (groups 0-3 = Tr.A-D = the 4 stream channels, group 4 = MIC/LINE input), per channel:
| idx | what (DSP0 words for Tr.A) |
|---|---|
| 0 | input on (word 0/2 coef 0 vs 32) |
| 1 | input source: GRAM g[09]/g[0B] vs IRAM i[0F]/i[12] (rewrites the whole word) |
| 2 | stereo / mono (0 = L+R summed: cross terms 0x21/0x22) |
| 3 | stream block word 0x6E/0x8A on (0) / nop (1+) |
| 8 | stream block 0x58-0x60 / 0x74-0x7C coefficient set (interpolator? 0 = all zero) |
| 4-7, 9, 10 | no DSP write on their own (stored only; probably EQ, applied with other params) |
| 11 | **LEVEL**: word 0x171 (Tr.A), 0x183, 0x195, 0x1A7, 0x1B9 (input): exponential, 0 = off, 100 = the OS's nominal, 127 = about +6 dB, 64 = about -10 dB |
| 12 | **PAN**: L word / R word, 0 = L, 64 = both full, 127 = R |
| 13/14/15 | **send 1 (AUX)**: pre/post tap select (i[2E] vs i[2F]), level, pan (words 0x1D5/0x1D6 ...) |
| 16/17/18 | **send 2 (FX send)**: same, words 0x1E8/0x1E9 ... |
| 19 | output: 0 = MIX bus (0x1FB..), 1+ = REC bus (0x221..) |
| 20 | 1 = direct out on GRAM g[88]/g[8A]... (words 0x26C/0x26E) |

**Buses** (DSP0 0x1D5-0x237): send-1 sum -> i[13]/i[16] (= AUX OUT), send-2 sum -> i[19]/i[1B] (= FX SEND), MIX sum
(+ FX return channel group 5, + i[1E]) -> i[07]/i[0A] -> master level 0x20D (group 6 idx 0/1) -> i[08]/i[0B], REC bus
-> i[0D]/i[10] (level 0x233 = group 6 idx 2/3). Group 5 = FX RETURN channel (level 0x1CD, pan, 2 = MIX / REC).
Group 6: 0/1 master, 2/3 REC bus, 4/5 send-1 master, 6/7 send-2 master, 8/9 i[1E] channel, 10 i[1E] to MIX / REC,
11 = a second tap selector (words 0x278/0x27A -> g[EA]/g[EC], same codes as below).
DSP0 0x27E-0x2ED: 14 peak meters (abs + decay) -> GRAM g[84]...g[C6].

**FX LOCATION codes** (string table 0x164D38, 18-byte entries: name, code, channel): mixer group 7 idx 0 = code.
| code | tap | name |
|---|---|---|
| 0 | - | OFF |
| 1 | i[19] | SEND/RETURN (send-2 bus) |
| 2/3, 4/5, 6/7, 8/9 | i[2C]/i[2D], i[3E]/i[3F], i[50]/i[51], i[62]/i[63] | Tr.A..D PRE-EQ / POST-EQ |
| 0x0A/0x0B | i[70]/i[71] | MIC/LINE PRE-EQ / POST |
| 0x0C | i[07] | INS MASTER (what KEYS uses) |
| 0x0D | i[0D] | INS RECORD |
| 0x0E | i[13] | INS AUX-OUT |
An insert = the tap goes out on GRAM, the return is stored back into the same IRAM cell (words 0x252/0x254).

**THREE insert slots, Roland uses one** (group 7 idx 0/1/2, each takes the codes above):
| slot | DSP0 -> DSP1 (DSP1 reads +1) | DSP1 -> DSP0 (DSP1 writes -1) | used by |
|---|---|---|---|
| 0 | g[70]/g[74] (DSP1 reads g[71]/g[75]) | g[73]/g[77] (DSP1 writes g[72]/g[76]) | every Roland FX + KEYS |
| 1 | g[D0]/g[D2] (read g[D1]/g[D3]) | g[65]/g[6D] (write g[64]/g[6C]) | **nothing** |
| 2 | g[D4]/g[D6] (read g[D5]/g[D7]) | g[67]/g[6F] (write g[66]/g[6E]) | **nothing** |
No Roland DSP1 program touches slots 1/2 (they only use g[71]/g[75] in, g[72]/g[76]/g[78] out). A DSP1 program of our
own can run **three effects at three different mix points at once** (e.g. input FX + loop FX + master FX), each slot
placed with MIXER_PARAM(7, slot, code). Avoid g[68] (DSP0 reads g[69] as an input at word 0x16).

**Pads -> channels (for loop faders, Looper v2):** the pad note-on 0x13735E goes through the object at @0x43B300
(methods 0x13761C / 0x1375A8 / 0x13749E); a playing voice id gets its stream channel from 0x43B635[id], the
channel's owner is 0x43B631[ch] (= id + 0x10), and the pad level lands per channel at 0x43B6C0[ch] (0x14EAA4).
Pad starts do not write the mixer's channel LEVEL (index 11), so a fader on Tr.A-D (stock faders or ROUTING) keeps
working while pads play; to give each loop its own fader the looper has to pin its layers to channels.
The binding happens in 0x14ED46(r6l = voice, r6h = channel; er1 = params): 0x43B62D[voice] = param +2, voice setup
0x14EA28, then 0x43B635[ch] = voice, 0x43B631[voice] = ch + 0x10. The channel comes from its caller in the pad path
(object method 0x13749E): the place to pin a layer to Tr.A-D for Looper v2 (per-loop faders / per-loop FX slots).
0x13749E itself only queues: it sets bit 2 of byte +1 in the pad's play record (0x4275AE + 14 * pad) and calls
0x150CEE; the stream engine binds a channel later. 0x14ED46's direct callers are 0x138CAC (sample preview: channel
from @0x42769D, voice 0) and 0x13AD3C. Next step for Looper v2: find where the queued pad request gets its channel
(the 0x4275AE records' consumer) and hook it so loop layers keep fixed channels.

## Hardware buses
| addr | what |
|---|---|
| 0xC00000-0xC00BFF | DSP0 program/param RAM, 0x300 × 32-bit (shadowed in RAM at 0x410362) |
| 0xC01000-0xC01BFF | DSP1, same layout (shadow at 0x410F62) |
| 0xC02000-5 | DSP control latches (shadow at 0x411B62); 0xC00003 bit7 = busy |
| 0xE00040-47 | IDE task file (0x47 = status) |

- The DSP loader is 0x1096D2(chip, start, count, src). Program words are 3 bytes (24-bit), and each chip holds at most 0x300 = 768 words.
- **DSP0 = voice/mix engine:** 0x2F5 = **757 of 768 words**, from 0x151FE2. Mode patches are loaded at 0x126D90.
- **DSP1 = effects:** a 58-word base from 0x1528C1, then the FX algorithm is swapped in at word 0x3C (0x108274, length table at 0x157860).
- **Voice count verdict:** DSP0 is 98.6% full. More voices would mean rewriting undocumented Roland DSP microcode with almost no spare instruction budget. Changing a constant in the OS can't do it.

## Strip analysis (2026-10-13)
The disk-flash mod is CONFIRMED on hardware: the user's unit booted with "JunksmithWizard!" in the SYS menu.

### OS (H8S): no need to strip anything for space
- Code and data end at 0x16ACC3. 0x16B000-0x1BFFD9 is **all zero: 0x54FDA = ~340 KB free flash** for new code.
- So stripping OS features only matters for CPU time or RAM. Neither is measured yet.

### DSP1 (effects): one algorithm loaded at a time
- A 58-word base, plus the selected algorithm at word 0x3C (708 slots available).
- There are 20 algorithms, 155-689 words each (length table at 0x157860).
- Stripping effects frees nothing for voices; they are swapped in and out, not resident.

### DSP0 (voice / mix engine): 757 of 768 slots, the real limit
Repeat structure, found by comparing opcode bytes:

| words | shape | guess |
|---|---|---|
| 0x000-0x017 | 6 × 4 | I/O moves (ADC/DAC/serial ports?) |
| 0x018-0x053 | 5 × 12 | ? (5 channels of something: input / rec?) |
| 0x057-0x16E | **10 × 28** | **per-channel stream engine** = 280 words (37%) |
| 0x171-0x1B8 | 4 × 18 | per-track (4 tracks): EQ / level / pan? |
| 0x1B9-0x27F | mixed | buses / sends / master |
| 0x280-0x2B7 | 7 × 8 | filters (master filter / isolator?) |
| 0x2B8-0x2D7 | 4 × 8 | ? |
| 0x2D8-0x2F4 | tail | outputs |

- 10 channel blocks = probably 8 playback (4 stereo tracks) + 2 record (stereo in).
- Each channel block: 3 reads (`7exx5a`), ~7 external writes (`00xx02/06`), and **8 filler words `001837`**. All 80 `001837` in the program are inside these blocks, so they are likely memory-latency waits.
  - 3 reads per channel suggests **interpolation for VARI/PITCH (varispeed)**.
- Strip candidates for more voices, best first:
  1. **VARI/pitch interpolation.** Fixed 1:1 playback would shrink each channel block a lot. Biggest possible win, if the guess is right.
  2. **Interleave two channels** so one channel's ops fill the other's `001837` waits: saves up to 80 words.
  3. Master filter / isolator, mic FX input path, track EQ: whichever sections they turn out to be.
- Unknowns that could still block more voices:
  - the external memory bandwidth (the streaming buffer)
  - whether the OS's disk streaming can feed more channels
  - the DSP ISA itself (undocumented)
- Next: bisect on hardware. Build test PRGs that each blank one DSP0 section (assuming `000000` = NOP) and listen for what dies. **Volume low**: a blanked section could output junk.

## SD card (ZuluIDE, I:)
- Holds one image, "ZIPD 100MB empty description goes here.img". It's FAT12 with 32 KB clusters, inside an MBR partition at sector 32. It contains SONG0000.
- Backup: `sd_backup_2026-10-13/` (sha256 06e8001e…).
- 2026-10-13: SP808.PRG (test mod) was added to it, at clusters 1698-1722. It was verified that only the FAT, one root entry and previously free clusters changed. The new sha256 is 8f0ac214….
- The zululog shows a supply voltage drop warning (2999 mV).

## Tools
- `tools/h8sdis.py` is a homemade H8S disassembler. Usage: `python -I tools/h8sdis.py sp808_v1050_raw.bin 100000 START END`.
- `tools/xref.py` → `tools/xref.pkl` (calls / immediates / per-address insns).

## Function map (so far)
| addr | what |
|---|---|
| 0x100000 | header / `jmp 0x126616` |
| 0x126616 | C startup → 0x126686, 0x11F0AC (init, boot combos) |
| 0x11F1BA | SAVE SYSPROG screen (arg 0 = IMAGE, 1 = FILE) |
| 0x127544 | load SP808.PRG from disk + validate |
| 0x127670 | save SP808.PRG |
| 0x1276E2 | raw IMAGE write to LBA 0x20000 |
| 0x127770 | validate image header/trailer |
| 0x14865C | version compare + Update System prompt |
| 0x1313A6 | is-key-held(logical code) |
| 0x131198 | logical key → matrix index |
| 0x400224 / 0x400228 | memcpy / memcmp (RAM-resident, copied from .data) |
| 0x4003AC | disk sector write (LBA, count, src) |
| 0x4005BC | flash program from RAM image (RAM-resident) |

## Old: checksum hunt (superseded by the above)
- `5A126616` at +0 is probably a checksum the boot loader checks.
- None of these matched over any range tried: 8/16/32-bit sums (plain, negated, inverted), or CRC32 over +4..end.
- The end-of-transfer byte 0x23 also didn't match simple sums.
- Next steps:
  - Find the routine in the OS that writes "TS25ESYS" (backup/save code probably shares the checksum function).
  - Try CRC16 variants and word-sum-with-carry.
  - Last resort: a trial flash with a 1-byte text change, since the boot updater should survive a bad image.

## Next
1. Load raw.bin at 0x100000 in Ghidra/IDA as H8S/2xxx (big-endian).
2. Find string xrefs → menu/UI code → map the button, LCD and MIDI handlers.
3. Solve the checksum, then a harmless test mod (e.g. a boot string) to flash over MIDI.
