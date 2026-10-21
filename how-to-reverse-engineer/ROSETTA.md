# How the Rosetta mod is built (`tools/build_v10.py`)

## Hooks into Roland's OS (each asserts the original bytes first)
- **Key groups:** `KEYGROUP_TABLE` entries -> `g1` (pads), `g2` (PAD BANK / PAD SAMPLING: looper), `g8` (SONG / SYSTEM / SAMPLE).
- **Screens:** our home menu and pages replace stock screen handlers (event 0 = enter, 6 = tick, 9 = key). `PAGE` picks the page.
- **DSP write gates:** `GATES` (Roland's DSP1 writers check `KGATE` first) keep Roland's FX code from writing into our programs.
- **MIDI:** handler table `0x164B88`.
  - note-on / off -> `m_on_tr` / `m_off_tr`: KEYS notes, plus remote keys on ch 15/16.
  - CC -> `m_cc_tr`: talk-back on ch 16.
- **Key dispatcher:** `jsr 0x1311C6` -> `rk_getkey`. It runs pending talk-back commands, then returns remote keys before the scanner's.

## Our RAM (`0x43C000` + offset)
- **`0x000-0x7FF`:** the existing variables. Edited only by the lead.
- **Lane blocks:**
  - lead `0x800-0xBFF`
  - MFX `0xC00-0xFFF`
  - LOOP `0x1000-0x17FF`
  - spare `0x1800-0x1FFF`
- Power-on values and strings go in per-lane lists (`INIT_*`, `STRS_*`) so merges don't collide.

## Pages: the Rosetta menu engine (`MAC_PAGES`)
- **Each page:** a list of tabs. A tab is rows of (label, var, lo, hi, apply routine, display).
- **Displays:** numbers, units from a table, names, `dyn` = the label or display depends on a TYPE / MODE variable.
- **Look (v1.99, D-70 / HR-GP5 style):**
  - a black title tab with the tab name, page name right
  - full-width 8 px rows, an inverted selection bar
  - a boxed scroll bar
- **The Rosetta way:** a menu gets as many rows as it needs and scrolls. Never squeeze or hard-wire parameters.

## DSP programs
- **KEYS** (`keysdsp.py`): 8 sampler voices + DDS oscillators in DSP1.
- **MFX** (`mfxdsp.py`): FILTER -> DRIVE + CRUSH -> MOD (incl. chorus / flanger / phaser) -> DELAY, per slot, list-scheduled.
- Both have a Python model that the firmware tests compare against word for word.

## Parallel sessions (`PARALLEL.md`, local)
- **Lead:** merges, versions, card installs, KEYS / synth, tools.
- **Lanes (MFX, LOOP):** each works in its own worktree and branch, inside its RAM block and code sections.
- **Merge request:** sha + run_all summary + space used + the hardware checks for the user.
