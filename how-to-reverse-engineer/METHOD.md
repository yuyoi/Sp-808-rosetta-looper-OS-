# Method and tools

## Tools (all in `tools/`)
| Tool | Use |
|---|---|
| `decode_upd.py` | Roland's update SMFs -> the OS image (`sp808_v1050_raw.bin`) |
| `h8sdis.py`, `xref.py`, `q.py` | disassembler; xref database; "who references this address" (`python -I tools/q.py 13F2F0`) |
| `h8asm.py` | our assembler (labels, layout-time `align2`) |
| `h8emu.py` | H8S emulator that runs our code against the real image. It logs **odd word/long accesses** (`Emu.odd`) |
| `esp.py`, `dspdump.py`, `fxcapture.py` | ESP2 decoder / disassembler / **cycle-exact** simulator; DSP programs out of the image; Roland's live FX programs captured by running its loader |
| `mixmap.py` | runs Roland's mixer API in the emulator and maps every parameter to DSP0 words |
| `build_v10.py` | the whole mod. `python -I tools/build_v10.py sp808_v1050_raw.bin work/build_v10` -> `SP808.PRG` |
| `run_all.py` | every emulator test at once, with diffs against a baseline. `--quick` skips the 40 min KEYS suite |
| `fat_add.py` | puts `SP808.PRG` into a Zip / ZuluIDE disk image |
| `sp808_midi.py` | **hardware in the loop**: MIDI remote keys, talk-back, audio capture (below) |

## How the OS was mapped (repeat this for a sibling unit, e.g. the VS-840)
1. **Decode the update** and identify it: version word at image offset `0x0E` (1050).
2. **Anchor on fixed points:**
   - the boot ROM API calls (`0x4000xx`)
   - I/O registers (`0xFFFFxx`)
   - strings (screen names, the factory switch list)
3. **Xref everything** (`xref.py`). Then follow one feature from its I/O to its UI: key dispatcher -> group table -> screen handlers (event 0 = enter, 5/6 = tick, 9 = key).
4. **Patch, don't rewrite.**
   - Hook a table entry or a `jsr` and keep the old target as the fallback.
   - Assert the original bytes before patching (`build_v10.py` does this for every hook).
5. **Emulate before hardware.**
   - The H8S emulator runs our code with stubs for the stock routines.
   - The ESP2 model runs our DSP programs sample by sample.
   - A test drives the UI like a user and compares DSP words with the model.
6. **Ask Roland's own code.** To learn what a mixer parameter does, run the stock API in the emulator and diff the DSP shadow (`mixmap.py`).

## Hardware in the loop (v1.98+)
Once the unit runs Rosetta OS, the PC can press its buttons and read its memory, so most hardware tests no longer need the user to press keys or take photos.

**Rig:** a USB audio/MIDI interface.
- interface MIDI OUT -> SP-808 MIDI IN (remote keys)
- SP-808 MIDI OUT -> interface MIDI IN (talk-back)
- SP-808 OUT -> interface input (audio capture)
- interface output -> SP-808 LINE IN (test tones)

**Remote keys** (v1.98, works on hardware):
- A note on MIDI ch 16 = a press of key code <note>. Ch 15 = 0x80 + note. Velocity 64+ = SHIFT. Note-off = release.
- `m_on_tr` / `m_off_tr` queue them into a ring.
- The dispatcher's `jsr 0x1311C6` at `0x13F2FC` now calls `rk_getkey`, which returns a queued key before the scanner's. So the key takes the **whole stock path**, like a finger press.

```
python -I tools/sp808_midi.py ports
python -I tools/sp808_midi.py key RIGHT --midi "MIDI (OCTA"
python -I tools/sp808_midi.py run "PADSMPL 120; wait 4000; PADSMPL 120" --rec out.wav --tail 3000
```
`--rec` writes out.json: every press / release with its sample index in the WAV (the device's own counter), so lags are measured, not guessed.

**Talk-back** (v1.99, emulator):
- CCs on ch 16 set registers:
  - CC 20-23: address
  - CC 24-25: length
  - CC 26-27: poke value
- CC 30 runs a command **in the main loop**: 1 = PEEK, 2 = POKE (our RAM only), 3 = PING.
- The SP-808 replies on MIDI OUT as `F0 7D 08 <cmd> ... F7`, data bytes as two nibbles each.
- PEEK covers flash, RAM and the LCD image. So `screen` gives the PC the exact LCD picture and `state` reads named variables (addresses from `build_v10.py`).

```
python -I tools/sp808_midi.py ping
python -I tools/sp808_midi.py screen shot.png        # LCD image 0x40187A -> PNG + ASCII
python -I tools/sp808_midi.py state PAGE LSTATE KSTATE
python -I tools/sp808_midi.py peek 43C000 64
```
**Why this matters:** the loop "build -> card -> user presses keys -> photo -> description" becomes "build -> card -> the PC runs the test, reads the screen and the state, records the audio". The user only installs and listens.
