# How to reverse engineer the Roland SP-808 OS (for AI models and humans)

This folder briefs any AI model or person who continues the SP-808 Rosetta OS. It covers what is known, how it was found, which tools exist, the rules, and the mistakes that already cost hardware test rounds. Read it before you touch code.

## Read in this order
| File | What |
|---|---|
| `PROMPT.md` | paste this into a new AI session to start it right |
| `RULES.md` | legal, safety and workflow rules (non-negotiable) |
| `PLATFORM.md` | the hardware: H8S CPU, memory map, LCD, keys, MIDI, the two ESP2 DSPs |
| `METHOD.md` | decode, disassemble, xref, patch, emulate, test, card. Plus **hardware in the loop**: MIDI remote keys, MIDI talk-back, audio capture |
| `ROSETTA.md` | how the mod is built: hooks, our RAM, the page engine, DSP programs, parallel lanes |
| `PITFALLS.md` | every bug that already happened and the rule it taught |

The big references are in the repo root:
- `NOTES.md`: the full log, newest version first.
- `tools/build_v10.py`: the whole mod, one patch script.
- `tools/keysdsp.py` and `tools/mfxdsp.py`: our DSP programs.

## Status words used everywhere
- **verified**: read from the traced code, or the emulator agrees with it.
- **emulator**: passes `tools/run_all.py` (H8S emulator + cycle-exact ESP2 model), not yet on hardware.
- **hardware**: the user confirmed it on the real unit. Only the user can promote something to this.
- **hypothesis**: plausible, not confirmed. Say so in docs and commits.

## Where things stand (2026-10-21)
- **Works on hardware:** custom OS v1.98 on a SP-808EX running the non-EX OS 1.05:
  - boot animation, menus, MPC sampling
  - KEYS sampler + DDS-DSP synth, our own programs in the FX DSP
  - MFX effects in slot 1
  - LAB pages
  - MIDI remote keys (the PC presses the SP-808's buttons)
- **Emulator only (v1.99):**
  - menus in the D-70 / HR-GP5 style
  - CHORUS / FLANGER / PHASER under MOD
  - MIDI talk-back (the SP-808 sends memory / its screen to the PC)
- **Open:** FX slot 2 makes no difference on hardware; the looper (v0.9b) has lag and loses overdubs (Looper v2 in progress).
