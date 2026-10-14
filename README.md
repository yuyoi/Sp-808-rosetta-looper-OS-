<p align="center"><img src="assets/roland_chan_boot.gif" width="560" alt="Roland-chan boot animation"></p>

# SP-808 Rosetta Looper OS

> **Runs on real hardware.** Custom firmware boots on a real Roland SP-808(EX) and installs straight from a Zip or
> ZuluIDE SD card: Roland-chan boot animation, own home menu, MPC-style pad sampling, and **KEYS: an 8-voice pitched
> sampler running as our own program in the FX DSP**, on top of the 4 stock voices. See [Status](#status-2026-10-14).

> **Preview, parked October 2026.** This is published as-is so people can see the menus, the tooling and how far the
> reverse engineering got, and expand it if they want. KEYS (v1.72) is confirmed on a real unit; the looper (v0.9b)
> is built and emulator-tested but was never flashed. The code is working-state, not cleaned up: one patch script
> per version, long notes, no packaging. Start with [Use](#use), `NOTES.md` and `tools/build_v10.py`.
> The disk side (takes to/from WAV, R-DAC codec, ZuluIDE tool) lives in
> [sp-808-disk-studio](https://github.com/yuyoi/sp-808-disk-studio).

Goal: turn the Roland SP-808 Groove Sampler into a **guitar looper / MPC-style sampler**. The groove/song UI comes
out, the sampler stays, and three modes get their own buttons: **MPC** (pad sampling), **Looper** (layers, overdub,
footswitch + MIDI) and **Keyboard** (one sound pitched across the 16 pads and a MIDI keyboard). Stretch goal: Doom.

Part of the Rosetta family, after [Rosetta ROM](https://github.com/yuyoi/Rompler-RosettaRom) (D-110 sample swap and OS mod).

## What works

- **Decode Roland's update** (`SP808v1050.zip`, 8 SMF files of SysEx) into the plain OS image: 7-bit packed data,
  no compression, no encryption. `decode_upd.py` is bit-exact.
- **Install from disk:** the OS updates itself from `SP808.PRG` on a FAT12/16 Zip disk. The only checks are a magic
  byte, a tag and a header copy, **no checksum**. `fat_add.py` puts the file on a Zip / ZuluIDE disk image.
- **Reverse-engineered H8S OS:** homemade disassembler, xref builder and a small label assembler. UI engine (screen
  table, key groups), LCD/boot-ROM API, buttons, faders, knobs, D-Beam and footswitch ADC channels are mapped in the docs.
- **Roland-chan boot animation** (replaces the S-P-8-0-8 slide and the second Groove Sampler splash): she slides up,
  blinks, smiles, then "JSW OS" and "ROSETTA" type in.
- **Own home menu** (SAMPLE = MPC, SONG = Looper, SYSTEM = Keyboard, SHIFT+SYSTEM = stock system menu). The VALUE
  dial and the cursor keys both work in it.
- **MPC mode** (MPC page: Pad / Rec / Start):
  - **CLASSIC (default), like a real MPC:** hit a pad to select it (the page shows its number and whether it's used),
    then ENTER, SAMPLE or PAD SAMPLING records into it.
  - Any pad stops the take.
  - On the result screen: ENTER keeps the take, another pad moves it there (the selected pad goes back to how it was).
  - Other modes: NEXT FREE (first empty pad), TAP / HOLD (SHIFT+pad records into that pad). Start INSTANT or WAIT
    SIGNAL.
- **KEYS mode (v1.72, works on hardware):** hit any pad from any bank (PAD BANK or the dial picks the bank) and it is
  captured into the FX DSP's delay RAM, then played pitched across the 16 pads and a MIDI keyboard:
  - 8 voices of our own DSP1 program **plus** the 4 stock disk voices: pads and tracks keep playing through KEYS.
  - Live pitch per note: each voice reads the RAM with its own fractional phase and interpolates (`keysdsp.py`).
  - MIDI keyboard C2-C7 (C4 = pad 8), velocity, release on the dial, SHIFT+EXIT or PAD BANK = pick another sample.
  - **S-EDIT** page: resonant low-pass (knob A cutoff, B resonance), attack (knob C), release, reverse, loop
    (sustain while held, crossfaded voice handoff), THRU on/off.

## State in one look

| part | state |
|---|---|
| decode Roland's update, build, install from disk, recovery | works on hardware |
| Roland-chan boot, home menu, MPC page, record / take-done screens, 7-seg ticker (v0.8) | works on hardware |
| KEYS: 8 + 4 voices, MIDI keyboard, velocity, S-EDIT filter / attack / release / reverse / loop, PAD BANK (v1.72) | works on hardware |
| looper: pad layers, overdub, undo / clear on PAD SAMPLING (v0.9b) | built, emulator-tested, **not flashed** |
| H8S disassembler / xref / assembler / emulator, ESP2 DSP decoder and simulator | work, used for all of the above |

Open points for whoever picks it up:
- **Looper engine:** the song engine has no loop/cycle play at all. Pads loop seamlessly, so layers = looping pads
  (stock sampling stops all pads; that call is hooked out). Notes: `LOOPER_DESIGN.md`.
- **KEYS:** one rare hang seen once after fast chords (gone after that). Stock FX stay silent after KEYS until an FX is
  loaded again. Samples up to ~1.4 s. Resampling the keys' output isn't done.
- Voices: DSP0 (the voice engine) is full, so the 4 disk voices stay 4; extra voices live in **DSP1, the effects
  core** (Roland/Toshiba ESP2, instruction set public since The Usual Suspects' JP-8000 work). Its 128K-word
  delay RAM is ~3 s of audio: short samples only.
- Recording into a used pad skips the stock "Overwrite?", so the old wave may be orphaned (stock CLEANUP DISK).
- LCD width: 132 or 136 px (the stock logo is centred on 136).

## Use

You must supply Roland's **own update file** (`SP808v1050.zip`, SP-808 OS v1.05). It is Roland's copyrighted code
and is not in this repo. Unzip `SP808#1.MID` .. `SP808#8.MID` into `upd/`, then:

```
pip install numpy pillow
python -I tools/decode_upd.py upd sp808_v1050_raw.bin                  # Roland update -> OS image
python -I tools/build_v10.py sp808_v1050_raw.bin build_v10             # -> build_v10/SP808.PRG
python -I tools/fat_add.py disk.img build_v10/SP808.PRG --replace      # put it on your Zip / ZuluIDE image
```

On the SP-808: power on with the disk in, answer **YES** to "Update System?", then power-cycle when it asks for
the Zip. Hold **HOLD** at power-on to force the prompt. **Back up your disk image first.**

**Recovery** (built into the boot ROM, the OS can't break it): power on holding [STATUS] + [EFFECTS] above fader A,
then play Roland's `SP808#1-8.MID` into MIDI IN.

**Legal:** this repo contains no Roland code. The build scripts patch **your own** decoded image. Please don't share
the built `SP808.PRG`: share this repo instead.

Note: the builds are based on the SP-808 (non-EX) OS v1.05. Installing one on an SP-808EX turns it into a non-EX.

## Files

| File | |
|---|---|
| `tools/decode_upd.py` | Roland SMF update -> OS image |
| `tools/h8sdis.py`, `tools/xref.py`, `tools/q.py` | H8S disassembler, xref builder (`xref.py image.bin tools/xref.pkl`), "who references this address" |
| `tools/h8asm.py` | small H8S assembler with labels (only the instructions the patches use) |
| `tools/make_prg.py` | SP808.PRG format + header checks (first trial mod) |
| `tools/build_v02.py` .. `tools/build_v10.py` | each firmware version as a patch script (`build_v10.py` = current, builds v1.72; v0.7b-e are LCD diagnostics) |
| `tools/esp.py`, `tools/dspdump.py`, `tools/fxcapture.py` | ESP2 DSP decoder / disassembler / cycle simulator; DSP programs out of the image; live FX programs captured by running the stock loader in the emulator |
| `tools/keysdsp.py`, `tools/test_v10.py` | our DSP1 sampler program (+ model test) and the KEYS end-to-end test |
| `tools/gfxlib.py`, `tools/ui_gfx.py` | graphics engine (framebuffer, fonts, icons, LCD packing) and the mockup renderer |
| `tools/h8emu.py`, `tools/test_ui.py`, `tools/test_v08.py`, `tools/test_v09.py` | small H8S emulator that runs our code on the PC; screen and looper-session tests |
| `tools/bootanim.py` | boot animation player + hook; frames from `assets/roland_chan_frames.npz` |
| `tools/roland_chan.py` | turns the line art into LCD frames (needs the drawing, not included) |
| `tools/fat_add.py`, `tools/inject_prg.py` | put SP808.PRG on a FAT12/16 disk image (bare volume or MBR) |
| `NOTES.md` | working notes: update format, flashing, boot combos, function map, every version |
| `MENU_MAP.md`, `CONTROLS.md` | screen table / key routing map, all buttons, ADC channels, LCD and boot-ROM API |
| `LOOPER_DESIGN.md` | looper design (BOSS RC-style) and the engine findings |

## Credits and legal

- **Made by JunkSmithWizard (JSW) together with Claude (Anthropic's AI).**
- Roland-chan is JSW's own drawing (from the Hex Wizard project).
- Roland, SP-808 and Groove Sampler are trademarks of Roland Corporation. This project is not affiliated with Roland.
  No Roland code or data is distributed here.
- MIT licensed (see `LICENSE`).

## Status (2026-10-14)

Confirmed on a real SP-808EX with a ZuluIDE (Zip drive emulator):
- Disk install of a modified OS.
- Own home menu (v0.3).
- One-press PAD SAMPLING (v0.4).
- Roland-chan boot animation (v0.6b), with the second splash removed (v0.6c).
- MPC mode with the select-pad flow and the VALUE dial in the menu (v0.6i).

Also fixed on the way: since v0.4 our RAM sat inside the stock 2000-record event pool, and v0.6f moved it.

- **v0.7f: our own graphics engine, pixel-exact on the LCD.**
  - Icon home screen; MPC page with a 4×4 pad map and pop-ups.
  - Roland-chan in full detail, plus a boot sound (pad 16).
  - Everything is drawn into the boot ROM's LCD RAM (6 px per byte, streamed by interrupt). The details came from a dump of the boot ROM taken on the unit with Roland's own file-save routine. See `NOTES.md`.
- **v0.8: own record and take-done screens, 7-segment ticker.**
  - Record: big MM:SS.T timer, dB level meter with peak hold, remaining time, WAIT / REC.
  - Take done: length, pad and the take's level envelope.
  - The time-counter digits cycle "ROSETTA OS", the version and the MB left on the disk.

- **v1.0-v1.72 KEYS, confirmed on the unit 2026-10-14** ("works now"): the FX DSP (DSP1) runs our own sampler
  program (`tools/keysdsp.py`), Roland's DSP1 writes are gated while it owns the chip, the master runs through it
  so pads/tracks and 8 KEYS voices play together. MIDI keyboard through the stock MIDI parser's handler table.
  Hardware fixes on the way: no general mc3 on DSP1 (all voices on mc2), phase stored raw (notes froze after 0.74 s),
  per-channel pass-through, idle voices hard-muted (they replayed the delay RAM quietly), PAD BANK handled inside KEYS.

Built and emulator-tested only (never on the unit):
- **v0.9b looper:** PAD SAMPLING tap = REC / PLAY / DUB, double tap = stop, hold = undo / clear; layers are pads.

## TODO

- [x] Record / result screens in the new graphics (live level meter, timer, take waveform) - v0.8.
- [x] 7-segment line: "ROSETTA OS", version, MB left - v0.8.
- [ ] Assignable record button (sampling and looper).
- [x] Looper v1 (v0.9/v0.9b, hw test pending): pad layers, overdub + undo/clear, all on PAD SAMPLING (footswitch).
- [ ] Looper next: MIDI control, the footswitch jack (ADC ch 11), tempo/click, save loops to disk.
- [x] Keyboard mode (v1.0-v1.72, works on hw): 8 + 4 voices, MIDI keyboard, velocity, S-EDIT filter / attack /
  release / reverse / loop / THRU, PAD BANK.
- [ ] Keyboard next: resample the keys' output, stock FX back after KEYS, longer samples, MIDI channel setting.
- [ ] Strip the groove/song screens.
- [ ] Doom.
