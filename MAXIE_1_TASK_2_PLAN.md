# MAXIE 1 — Task 2 Plan

## Task
Real audio pipeline verification on the user's actual laptop.

## Scope
Verify microphone capture, VAD, Faster-Whisper STT, TTS/speaker playback, end-to-end voice flow, and barge-in/echo where hardware permits.

## Evidence rule
Hardware-dependent results must be PASS, FAIL, or UNVERIFIED. No hardware result is inferred from source inspection or unit tests.

## Exclusions
No wake-word implementation, storage optimization, model replacement, architecture refactor, or unrelated cleanup in this task.

## Protocol
Run the supplied hardware verification commands on the target laptop and preserve exact output. Record dependency availability, audio devices, VAD, STT, TTS, end-to-end, and barge-in results separately.

## Acceptance
Task 2 is complete only when available hardware checks have evidence. Unsupported or unavailable components remain UNVERIFIED rather than being marked PASS.
