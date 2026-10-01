# MAXIE — DEVELOPMENT STATUS

Last updated: 2026-09-23 · Status: **COMPLETE**

## What MAXIE is

A Jarvis-style personal AI assistant with a calm, confident FEMALE voice
(FRIDAY-inspired). Cross-platform: Windows (primary), Linux (dev), phone
via HTTP. Python 3.10+ (3.14 verified).

## Current architecture

```
run.py / main.py
 └── Core.core_manager.Maxie
     ├── VoiceEngine            TTS, female voice (SAPI / pyttsx3 / espeak)
     ├── VoiceManager           state machine + listen()
     ├── AudioManager           mic discovery/selection (config-aware)
     ├── AudioRecorder          streaming VAD recorder (Silero + energy fallback)
     ├── SpeechPipeline         recorder -> Transcriber
     ├── Transcriber            faster-whisper (configurable)
     ├── BargeInListener        echo-aware STOP detection while speaking
     ├── BrainRouter            skills vs memory vs AI routing
     │   ├── IntentEngine
     │   ├── CommandCorrector
     │   ├── MemoryEngine       SQLite (long-term) + context (short-term)
     │   └── AIEngine -> OllamaClient (provider abstraction)
     ├── SkillManager           allowlisted skills only (Security.permissions)
     ├── ConversationEngine     main loop + stop/exit + remote worker thread
     └── Interface.RemoteServer HTTP endpoint for phone/CLI (token-gated)
```

## Feature status

| Area            | Status | Notes                                         |
|-----------------|--------|-----------------------------------------------|
| Foundation      | DONE   | config auto-defaults, logging, paths, launcher|
| Brain/AI        | DONE   | router, intents, corrector, Ollama + context  |
| Memory          | DONE   | SQLite CRUD + free-form notes + context        |
| Skills          | DONE   | calc, weather, search, volume, open/close app, system, screenshot, memory |
| Voice pipeline  | DONE   | streaming VAD recorder, transcriber, adaptive gain |
| TTS / barge-in  | DONE   | echo protection, circular duplicates removed  |
| Remote access   | DONE   | stdlib HTTP server, token auth, fail-closed LAN |
| Wake word       | PARTIAL| lightweight text gate (true spotting is future) |
| Tests           | DONE   | 90 headless unittest cases + runner           |
| Persona         | DONE   | FRIDAY female voice, Jarvis-style system prompt + greeting |
| GUI             | PARTIAL| optional, guarded import                       |

## Verification (headless dev box)

- `python -m compileall -q .` — PASS
- `python Tests/run_tests.py` — **90 tests, OK** (1 skip: sounddevice HW)
- `python run.py` (no mic) — boots, text mode works:
  time, date, weather, calculator, memory save/recall, app open, help, exit
- Phone flow (remote enabled + token) — instant responses over HTTP,
  including memory, greeting, and math; exit works.

## Notes & known limitations

- Voice hardware cannot be verified on a headless dev box; run on the
  actual laptop to validate mic/speaker/TTS.
- Predictive/always-on wake word spotting is future work.
- Barge-in reliability depends on laptop mic quality (adaptive threshold +
  short-stop-phrase decoding + state gating in place).
- Electron/GUI remains optional; core is fully usable via voice/text/phone.