# Pitfalls (each one cost a hardware round or a long debug)

| Symptom | Cause | Rule |
|---|---|---|
| v1.94: every menu value blank on hardware, fine in the emulator | a word table landed on an odd address; the H8S ignores bit 0 | layout-time `align2` before word tables; the emulator now masks bit 0 and logs `Emu.odd`; run_all fails on any odd access |
| LAB BUTTONS showed nothing | the stock key-group handlers eat most keys before the screen | mask all groups (KEYMASK `0x427906`) while the page shows, restore on leave |
| KEYS notes froze after 0.74 s | phase stored scaled, overflowed | store the raw DSP phase |
| idle voices droned quietly | idle voices still read delay RAM / ran oscillators | hard-mute idle voices, freeze their oscillators |
| MFX DELAY: no echo | all slots wrote at the same delay-RAM offset | data written at offset w moves up 1 per sample and dies at the next WRITE offset above: give every slot its own line |
| DELAY offset way off | `~x & 0x7FFFFF` is 1 - x, not -x | keep the state negative, fix the sign in the coefficients |
| a DSP pair broke after a reschedule | `dmac` must directly follow its multiply; words 0xF1-0xFF must stay nop | `Seq.pair`, the scheduler checks both |
| MPC page cursor jumped after visiting MFX | a later `MCUR = ...` silently redefined the MPC cursor | one name per RAM byte; per-lane RAM blocks (`LANE_RAM`) |
| synth needed a pad hit before any sound | KEYS only started voices after a sample capture | SAMPLE 0 = synth only, no pick step (v1.98) |
| remote MIDI: stray key releases after a script | `midiOutReset` sends note-offs on every channel = key releases on ch 15/16 | close the port without a reset |
| PC recording all zeros on the OCTA-CAPTURE | its WDM inputs deliver digital silence (Octa routing) | probe every input for 1 s first; a Focusrite / ASIO path works |
| (rule) hooks must not change stock behaviour | registers the caller needs were changed | write down each hook's register contract and keep it |
| (rule) a hardware fault | theories cost hours | bisect: one change at a time, photo of the exact screen first |
