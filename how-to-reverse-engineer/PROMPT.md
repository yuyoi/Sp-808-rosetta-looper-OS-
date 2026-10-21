# Starter prompt for a new AI session

Copy everything between the lines into the first message of a new session (Claude Code or similar) with this repo attached. Edit the TASK line.

---
You are continuing the SP-808 Rosetta OS: a custom OS for the Roland SP-808 groove sampler (H8S/2xxx CPU, two Roland/Toshiba ESP2 DSPs), built as a patch over Roland's own OS 1.05.

Before doing anything:
1. **Read** `how-to-reverse-engineer/README.md`, `RULES.md`, `PLATFORM.md` and `PITFALLS.md`. Then read the file for your task: `ROSETTA.md` for features, `METHOD.md` for reverse engineering or hardware tests. `NOTES.md` in the root is the log.
2. **Never commit Roland data:** the decoded image, .PRG builds, .MID updates, dumps, disk images, programs.json. The .gitignore is a whitelist; keep it that way. The user supplies their own `SP808v1050.zip`.
3. **Every change:**
   - build (`python -I tools/build_v10.py sp808_v1050_raw.bin work/build_v10`)
   - run `python -I tools/run_all.py --quick` and read the diffs against the baseline
   - add a test for the new behaviour
   - odd word/long accesses must be 0
   - DSP changes are proven in the cycle-exact model first
4. **Hardware:**
   - Only the user puts builds on the card.
   - Never send MIDI keys that erase, delete or save without the user's OK.
   - For a vague hardware report, get a photo of the exact screen first.
5. **Talking to the user:** keep answers short, with a TL;DR at the top and the bottom. Ask before big design changes. Every menu gets as many rows as it needs and scrolls ("the Rosetta way").

TASK: <describe the task here>
---

Tip: one task per session. The docs carry the context between sessions.
