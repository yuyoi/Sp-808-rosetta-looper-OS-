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
