# Platform (SP-808 / SP-808EX, OS 1.05)

## CPU and memory
- **CPU:** Hitachi H8S/2xxx, advanced mode (24-bit addresses), big-endian.
- **Odd addresses:** **word and long accesses ignore address bit 0.** There is no address error: a word table at an odd address silently reads the wrong bytes (this was the v1.94 blank-menu bug).
- **OS image:** `0x100000-0x1BFFFF` (768 KB, flash).
  - Our host code: blob at `0x16B000` (about 115 KB used, room up to `0x1A0000`).
  - Boot animation: `0x1A0000`.
  - Our DSP program tables: `0x1B8000` (KEYS) and `0x1B8900` (MFX).
- **SP808.PRG:** an 8-byte header `00100000 001C0000` plus the image. The boot ROM installs it from the disk / card.
- **Boot ROM:** `0x000000`, with APIs at `0x4000xx`: blit `0x400478`, memcpy `0x400224`, get key `0x40048C`, flash erase / program `0x4005C4` / `0x4005D4`.
- **RAM:**
  - OS variables end at `0x43BAFE`.
  - **Ours: `0x43C000-0x43DFFF`** (vars), framebuffer `0x43E000` (512 B).
  - PRG loader `0x43FFF8`, sample RAM `0x440000+`.
  - The stack is in on-chip RAM (about `0xFFF914`).

## LCD
- **Graphic area:** 128 x 32 dots plus 2 rows of 7-segment digits and icons.
- **The boot ROM's LCD image is at `0x40187A`:** 34 rows x 24 bytes, 6 pixels per byte in bits 5-0 (bit 5 = left).
  - Rows 0-1 are the 7-seg line, rows 2-33 the dots.
  - Our canvas is LCD x 4..131.
  - An interrupt streams it to the panel (port `0xA00000` / `0xA00001`).
- **Our framebuffer** (gfxlib): 4 strips x 32 rows x 4 bytes. `gfx_flush` packs it into the LCD image.

## Keys
- **Dispatcher:** `0x13F2F0` (main loop).
  1. It gets the next raw key from `0x1311C6`: the scanner, via boot ROM `0x40048C`.
  2. `KEY_EVENT 0x4278BA` = (raw & 0x4100) | code. 0x4000 = release, 0x0100 = SHIFT.
  3. The group (high nibble of the code) goes through `KEYGROUP_TABLE 0x166BE4`. `KEYMASK 0x427906`: a set bit skips the group handler.
  4. A handler returning 0 passes the key to the screen as event 9.
- **Key codes = LED codes:**
  - pads `0x10-0x1F`, PAD BANK `0x20`, PAD SAMPLING `0x22`
  - LOC 1-4 `0x40-0x43`
  - UP / DOWN / LEFT / RIGHT `0x70-0x73`
  - SONG / SYSTEM / SAMPLE `0x80-0x82`
  - EXIT / ENTER `0xB0` / `0xB1`
  - PLAY `0x31`, STOP `0x32`

## MIDI
- **Port:** SCI0, at 31250 baud.
  - RX ISR `0x1356C0` echoes every byte to TDR (soft THRU). TX = wait SSR (`0xFFFF7C`) bit 7, write TDR (`0xFFFF7B`), clear bit 7.
- **Byte parser:** `0x134B58`.
  - Handlers come from the table `0x164B88`: note-off `0x134D0C`, note-on `0x134D46`, poly AT `0x13EFF0`, CC `0x134F7A`, PC `0x134FB4`, then ch-AT and bend (both ignored).
  - A handler is called with r0l = channel. Data bytes land at `0x42743B` / `0x42743C`.

## DSPs (Roland / Toshiba ESP2, two cores)
- **DSP0:** the voice engine (4 disk voices) plus Roland's mixer.
  - The mixer API `0x11F2AE` (r0 = group, e0 = index, r1 = value) writes its words (`tools/mixmap.py`).
  - **Three FX insert slots** (group 7, index 0/1/2). Roland uses only slot 0.
- **DSP1:** the effects core. Roland's FX, or **our** programs (KEYS sampler / MFX).
  - 768 steps per sample, 128K words of delay RAM.
  - The rules (read latency 3, ERAM spacing, dmac adjacency, `~x` = 1 - x) are in NOTES "The chip".
- **The hand-over between the cores goes through GRAM:** the reader sees the writer's address + 1. Slot 0 uses `g[70]/g[74]` in and `g[72]/g[76]` back.
