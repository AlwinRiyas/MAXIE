# MAXIE 1 — Current Priority Queue

Updated from the current repository state after Task 1.

1. **Task 2 — Real audio pipeline verification**: verify microphone, VAD, STT, TTS, end-to-end voice, and barge-in on the actual target hardware. Hardware evidence is required; source/tests alone cannot mark these PASS.
2. **Task 3 — Real wake-word implementation**: replace the current transcription/string gate with a pluggable audio wake-word provider and hardware verification.
3. **Task 4 — Remaining reliability/security gaps**: address only after Tasks 2–3, based on fresh audit evidence.
4. **Task 5 — Performance measurement**: record real startup, memory, STT, TTS, and response latency before optimization.
5. **Task 6 — Resource/storage optimization**: only after functionality and quality are verified; do not reduce model quality or capabilities.

## Rule

One task at a time. No unrelated cleanup or optimization is bundled into a task. Hardware-dependent claims require hardware evidence.
