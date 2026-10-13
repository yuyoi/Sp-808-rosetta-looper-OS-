# SP-808 OS v1.05 menu map (for the guitar-looper conversion)

## How the UI works
- **Key event:** word at RAM `0x4278BA`.
  - Low byte = logical key code (see NOTES.md table).
  - `+0x100` = with SHIFT; `0x4000` bit = release / second action.
- **Key-group handlers:** 0x13F44E (SONG/SYS/SAMP), 0x13F4AA (TRIM/LEVEL/REGIO/MARK), 0x13F504 (TO->/SCRUB), 0x13F552 (EXIT/ENTER), 0x13F5C4 (pad-side keys 0x20-0x23), 0x13F65E (transport 0x30-0x35), 0x13F6FE (INFO/S.MOD/ROW/ONOFF).
- **Change screen:** `0x13FC0E(screen)` writes the pending screen to `0x4278FE`. The main loop (0x13F9C2) commits it to the current screen at `0x4278FC`, then copies the 22-byte table entry into RAM `0x4278E0`.
- **Screen table:** `0x166D74`, 0x6C entries × 22 bytes: `[flags:4][handler:4][param table:4][page/strings:4][?:4][parent screen:2]` (parent 0xFFFE/0xFFFF = none).
- **Popups / dialogs:** object pointer at `0x42791E`; event handler at `@(10,obj)`; set up via `0x140016`.

### Key → screen bindings (found so far)
| key | screen |
|---|---|
| SONG | 0x0A Song Edit Menu |
| SYS | 0x41 System Edit Menu (now "JunksmithWizard!") |
| SAMP | 0x52 Sample Edit Menu |
| SHIFT+TRIM | 0x57 TIME STRETCH |
| SHIFT+LEVEL | 0x58 CHANGE PITCH |
| REGIO / MARK | 0x09 PLAY LIST |
| SCRUB | 0x36 |
| SHIFT+ENTER | 0x2F SAVE menu |
| TRIM / LEVEL | 0x13AB98 (inline edit) |

## Screens by area
Strip = groove/sequencer UI, which can go. Keep = sampler / looper-relevant. **Careful:** the 4 tracks are *played by* the song sequencer engine, so remove the groove **screens**, not the engine underneath, until we know what the looper needs.

### Groove / song / sequencer (STRIP candidates)
| id | title | handler |
|---|---|---|
| 07 | MEAS / bar display | 13D3D4 |
| 09 | PLAY LIST | 13EAEC |
| 0A | Song Edit Menu (Select Song?, Set Song Param? ...) | 13FDAE |
| 0B | SONG PARAMETER (Tr.VoiceReserve, Sync, MTC...) | 129F3E |
| 0C | T-MAP (tempo map) | 12A4A4 |
| 0D | LOCATOR | 12AB3A |
| 0E | (song sub) | 12ABA0 |
| 0F-10 | CREATE NEW SONG | 12AE6E / 12AEFE |
| 11 | TURN SONG PROTECTION | 12A19C |
| 12-16 | PASTE / MOVE / ERASE / DELETE / INSERT | 12B616.. |
| 17-19 | ADJUST TIMING | 12BA94.. |
| 1A-1B | Quantize / Start | 146FC2 / 1471B2 |
| 1C | (rec sub) | 1472A0 |
| 1D | Select Track / NewPhrase (Audio REC / Event REC) | 14A1F4 |
| 1E | STEP REC | 14A018 |
| 2C-2E | STEP MOD | 149274.. |
| 2F-33 | Save song (Overwrite / Save As New) | 13FDAE.. |
| 34-35 | SELECT SONG / DELETE SONG | 13357C / 133742 |

### Sampler (KEEP)
| id | title | handler |
|---|---|---|
| 1F-24 | SAMPLING (Select Pad, Pad Play / Loop / Auto Trim, "Waiting Signal...", Remain) | 13C488.. |
| 4D | BANK PARAM | 12890E |
| 4E-51 | Bank COPY / ERASE / RENUMBER / PROTECT | 128448.. |
| 52 | Sample Edit Menu | 12C2F0 |
| 53 | SAMPLE PARAM (PadPlay, LoopMode START-END / LOOP-END, LoopPoint) | 139BD8 |
| 54-55 | DIVIDE / DELETE | 1385D2 / 13850C |
| 56 | CREATE REVERSAL | 13B0A0 |
| 57 | TIME STRETCH | 13B57A |
| 58 | CHANGE PITCH | 13AF1C |

### Mixer (keep, probably simplify)
| id | title | handler |
|---|---|---|
| 05-06 | METER CH / AUX | 13D224 / 13D294 |
| 08 | INFORMATION | 13D306 |
| 25-27 | Merge-L&R / Balance ... | 14AE8C.. |
| 28-2A | MIX COMMON (Master, FX-Signal, AUX In&Out) | 14B3B0.. |
| 2B | A B C D (track select) | 136284 |

### Effects (keep)
| id | title | handler |
|---|---|---|
| 5A-5B | FX SW. | 12DA2C / 12C3E6 |
| 5C, 61-62 | FX INFO | 12C470 / 12D4AE |
| 5D | FX LOCATION | 12D654 |
| 5F-60 | FX CTRL | 12C740 / 12CA7E |
| 63-66 | FILTER / ISOLATOR | 12D4AE / 12DECE |
| 67 | CTRL SYS FX | 12CD7E |
| 68 | SAVE EFFECTS PATCH | 12E2A8 |
| 37-38, 47 | COPY FX ONLY | 12EE5A / 12EFDC / 130474 |

### System / disk (keep)
| id | title | handler |
|---|---|---|
| 41 | System Edit Menu | 12C25C |
| 42 | SYSTEM COMMON | 14A692 |
| 43 | MIDI | 13EFF0 |
| 44 | FILTER/ISOLATOR keep setting | 12E416 |
| 45 | INIT SYS-PARAM | 14A8F2 |
| 46 | D BEAM SETUP | 13EFF0 |
| 48-49 | CLEANUP / FORMAT DISK | 14A97E / 14AA0A |
| 4A-4C | LOAD EXT SONG / SAMPLE, COPY DISK | 1301B0.. |
| 04 | disk check ("Not SP-808 Disk") | 14839E |

### Hidden factory / test screens (free to repurpose: Doom lives here?)
| id | title | handler |
|---|---|---|
| 39-3B | SEQ TEST 1-3 | 1462DA.. |
| 3C, 6B | TEST | 14E492 / 136F7A |
| 3D-3E | MMC TEST | 136E82 |
| 3F | ESP TEST | 14E5CE |
| 40 | VOICE TEST (FadeTime, cnt) | 14F5BE |
| 69 | A/D JIG TEST | 1310E4 |
| 6A | BEAM PULSE (D-Beam) | 136FA0 |

## Looper spec (user, 2026-10-13)
- Pads and tracks share one voice pool. Target: **8 poly = 8 stackable layers**, each with its own mix level.
- **Assignable record button** for sampling and looping. Control comes from the user's own footswitch mod, plus MIDI.
- v1: **overdub + undo, auto start on signal, save loops to disk, tempo / click (count-in, bar-locked length)**.
- 8 layers is only realistic if **mono** layers (guitar is mono) take 1 DSP channel each.
  - DSP0 has 10 channel blocks, which looks like 8 playback + 2 record.
  - Needs a stock-hardware test: 8 mono pad samples triggered at once. How many sound?

## Looper-relevant existing pieces
- **Sampling** already has auto-start ("Waiting Signal..."), Auto Trim and loop playback per pad (LoopMode, LoopPoint).
- **Tracks** have Audio REC, AutoPunch and Pre-Punch Monitor.
- **FootSwAssign** exists, so the footswitch jack can drive looper actions.
- **D-Beam** exists.
