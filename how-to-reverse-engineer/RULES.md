# Rules

## Legal
- Roland's code stays Roland's. The repo holds only our tools, our patch scripts and our docs.
- Never commit any of these:
  - the decoded OS image (`sp808_v1050_raw.bin`) or builds (`*.bin`, `SP808.PRG`)
  - Roland's update files (`upd/`, `*.MID`)
  - dumps (`dump/`, `BOOTROM.BIN`)
  - captured DSP programs (`work/dsp/programs.json`)
  - disk / card images
- The `.gitignore` is a whitelist: everything is ignored unless listed. Check `git status` before every commit.
- Each user decodes their own copy of Roland's free `SP808v1050.zip`.

## Safety (the unit and the user's data)
- **The card:**
  - Only the user (or the lead session, on the user's "sd in") writes the ZuluIDE card.
  - Find the card by its contents (`zuluide.ini`), never by drive letter: letters move.
  - Always start from a **fresh copy of the card's image**. The user records takes onto it.
  - Keep the pre-install image as a backup and verify the card byte for byte after writing.
- **Recovery:** the boot ROM can always re-flash the stock OS. Hold [STATUS] + [EFFECTS] above fader A at power-on. The OS can't break that.
- **MIDI remote / talk-back:**
  - Only sequences the user OK'd, with the user present.
  - Never press keys that erase, delete, format or save.
  - POKE is limited to our own RAM (0x43C000-0x43DFFF).
- One session drives the unit at a time. Two sessions on one device must agree first.

## Workflow
- Builds are byte-reproducible. A tested `.bin` is compared (`cmp`) with the one that goes on the card.
- Versions: `VERSION` / `VER_TXT` in `build_v10.py` (1199 = v1.99). Only the lead bumps them, at merge time.
- Status words: verified / emulator / hardware / hypothesis (see README). Only the user says "hardware".
- "X can be used" from the user is a note for the future, not a build order. Finish work in progress before starting new features.
