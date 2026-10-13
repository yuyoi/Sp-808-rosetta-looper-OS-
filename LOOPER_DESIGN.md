# Looper mode design (ideas from BOSS RC-30 / RC-505)

**Decided (user, 2026-10-13):**
- REC→DUB→PLAY order.
- Layers = tracks A-D.
- Control = 1 analog footswitch (tap = REC/DUB/PLAY, double tap = stop, hold = undo/clear) + MIDI foot controllers for the rest.

Sources:
- RC-30 feature list: [Andy's Music](https://www.andysmusic.com/products/boss-rc-30-loop-station-dual-track-looper-pedal), [Music Store](https://musicstore.de/en_DE/EUR/Boss-RC-30-Loop-Station-UK-/art-GIT0021040-900)
- RC-505mk2 parameter guide: [Roland PDF](https://static.roland.com/assets/media/pdf/RC-505mk2_Parameter_eng02_W.pdf)
- RC-505mk2 review: [Sound On Sound](https://www.soundonsound.com/reviews/boss-rc-505-mkii?amp)

## BOSS ideas worth stealing
| BOSS feature | what it does |
|---|---|
| REC/DUB/PLAY on one switch | Press cycles states. "Rec action" order is either REC→DUB→PLAY or REC→PLAY→DUB (RC-30). |
| STOP | Stop mode: IMMEDIATE / FADE / LOOP (play to loop end, then stop). A second press during the wind-down stops at once (RC-505). |
| UNDO / REDO | Removes the last overdub; redo brings it back (RC-30). |
| Auto Rec | Recording starts when you start playing (RC-30). |
| Count-in + rhythm guide | 1 bar of click before recording; tempo by knob or tap (RC-30). |
| Per-track fader + select | Each track has its own volume and select button (RC-30). |
| One-shot | The phrase plays once instead of looping (RC-30/505). |
| Reverse, start/stop fades | Per track (RC-505). |

## How it maps onto the SP-808
**Engine: tracks A-D are the layers.**
- The SP-808's song/track engine already plays the 4 tracks phase-locked on one timeline. It already has punch-in/out (AutoPunch) and a metronome ("Metro."), so overdubs stay in sync without new DSP work.
- Each overdub = a new phrase on the next track. It is not mixed into one buffer (the DSP can't do that), so every layer stays separately mixable ("stack and mix").
- 4 layers to start: 4 stereo voices. 8 mono layers if the voice hack happens later.

| control | looper action |
|---|---|
| Analog footswitch (ADC ch 11): tap | REC → DUB → PLAY → DUB ... |
| Analog footswitch: double tap | STOP (mode IMMEDIATE / FADE / LOOP-END) |
| Analog footswitch: hold 2 s | while playing: UNDO last layer (mute it), again = REDO; while stopped: CLEAR (confirm) |
| MIDI foot controller (CC/notes, mappable) | REC/DUB/PLAY, STOP, UNDO, REDO, CLEAR, layer mutes, tap tempo |
| REC / STOP / UNDO buttons | the same actions on the panel |
| Faders A-D | layer volumes (stock) |
| STATUS A-D | mute/unmute a layer (stock) |
| EFFECTS A-D | that layer's FX send (stock FX untouched) |
| Start setting | INSTANT / WAIT SIGNAL (Auto Rec, hardware LEV1-8) / COUNT-IN (1 bar click) |
| Loop length | Set by the first take. Optional QUANTIZE snaps it to whole bars at the tempo. |
| Save | Stock song save, so loops live on the Zip / SD image. |

### Screen (4 rows)
```
LOOPER  L1 L2 L3 L4      <- layer status: REC/DUB/PLAY/MUTE
PLAY   bar 3/4  120bpm
Next: DUB on footsw
Start:WAIT  Stop:FADE
```

## RE findings (2026-10-13, pass 1)
**Song engine has no loop.**
- No song loop, cycle or repeat-play exists.
- The SONG PARAMETER list is Name, Tr.VoiceReserve, SyncSource, Out, MTC Type, Error Level, Offset, MMC Mode.
- "Repeat Times" exists only as a phrase PASTE edit.
- Looping tracks would mean either paste-repeat edits or locate jumps (a gap at every wrap).

**Transport** (key group 0x13F65E):

| key | action |
|---|---|
| PLAY | 0x1406FE |
| STOP | 0x140726 |
| REC | 0x1406B8(5), with bit 4 of 0x4277D0 set |
| SHIFT+REC | screen 0x1B |
| SHIFT+PLAY | screen 0x1A |
| SHIFT+STOP | screen 0x1D (Audio/Event REC track select) |

- These all feed one state machine: @0x427928 → state record {byte idx, byte, word flags, long handler(event)}.
- Events: 3 = PLAY, 4 = STOP, 5 = REC.
- Flags bit 0 means the state handles PLAY itself (otherwise 0x141B1E); bit 1 the same for STOP (otherwise 0x141BB0).
- State records are near 0x167766 (10 bytes each). The per-idx table is at 0x1677BE (12 bytes each).

**MMC (MIDI Machine Control):**
- A song parameter "MMC Mode" exists, and test mode has "MMC TEST (Recordable)": 1 STOP, 2 PLAY, 3 REC, 5 REW, 6 FF.
- So a MIDI controller that sends MMC can probably drive the transport with no new code.

**FootSwAssign** is a BANK PARAM (per pad bank, next to BeamAsgn), not a transport assign. Our looper reads ADC ch 11 itself.

**Pad playback:**
- Pad player vtable pointer @0x40323E. Normal play vtable 0x1653E8:
  - +0 mode/event 0x1370A2
  - +4 note-on 0x13735E (r0 = pad 0-15, r1l = velocity) → 0x137374 → 0x13749E (voice start)
  - +8 note-off 0x13743A(pad)
- Null vtable: 0x1653DC. Sampling vtable: 0x1662D6.
- Switch vtables with 0x13704A(er0 = vtable). 0x137042 restores normal play.
- 0x1371F4 = all pads off.
- Pad state: 16 × 14 bytes at 0x4275AE (+1 bit 0 = playing).
- Pad table: 0x4225B4 + 32·pad (+0 wave word, 0xFFFF = empty; +14 = play flags, loop etc.).

**Sampling stops all pads.** Screen 0x22 enter (0x13C97C) does:
1. Switches the pad vtable to sampling (0x1662D6).
2. Calls 0x1371F4 (all pads off) at 0x13C9D6.
3. Starts the take (0x13CAEC).

Overdub over a looping pad needs this patched (skip the pads-off call, keep the play vtable), plus a hardware test that the DSP can play pads while recording.

## Engine choice (open, user to decide)
| | pad layers | track layers |
|---|---|---|
| record | our MPC record path (works on hw) | stock Audio REC + AutoPunch (sync for free) |
| loop playback | stock pad Loop (seamless) | none: paste-repeat edits or locate jumps |
| mix | we map faders (ADC 0-3) to pad levels | faders A-D native |
| sync | start/stop the take on the loop wrap, trim to exact length | punch in/out at the loop boundaries |
| new RE needed | pads-off patch, voice position or timer | phrase paste/repeat API, punch API, track undo |

## Unknowns to reverse-engineer before building
1. The track Audio REC API (start/stop record on track N, punch in/out at the loop boundaries).
2. Song loop playback (loop region = locator pair?) and the transport start/stop calls.
3. Footswitch in normal operation (ADC ch 11 threshold) and the stock FootSwAssign.
4. MIDI input handling, for mappable MIDI footswitch messages.
5. Metronome / count-in hooks.
6. Fades: track level automation, or the DSP volume write.
