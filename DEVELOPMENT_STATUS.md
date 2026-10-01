# MAXIE — DEVELOPMENT STATUS

Last updated: **2026-09-28** · Status: **PROTOTYPE — CORE FUNCTIONAL, RELIABILITY GAPS OPEN**

This file is evidence-based. Every claim below was verified by reading the
source or running the command shown. Anything that could not be executed in a
headless environment is marked **UNVERIFIED** rather than assumed.

---

## What MAXIE is

A local-first, privacy-first personal AI assistant with a calm voice, built
around a single local LLM (Ollama) and a strictly allowlisted skill system.
Windows is the primary target; Linux is the development platform; a phone
reaches the laptop over an optional token-gated HTTP endpoint. Python 3.10+
(3.14.7 verified here).

---

## Architecture (as-built)

```
run.py / main.py
 └── Core.core_manager.Maxie
     ├── Voice.VoiceEngine        TTS: piper → edge → pyttsx3/SAPI → espeak
     ├── Voice.VoiceManager       4-state enum + listen()
     ├── Voice.AudioManager       device enumeration
     ├── Voice.AudioRecorder      capture loop + VAD gating
     ├── Voice.VADEngine          Silero, else energy gate
     ├── Voice.SpeechPipeline     recorder → Transcriber
     ├── Voice.Transcriber        faster-whisper, one-shot lazy load
     ├── Voice.BargeInListener    stop-phrase detection
     ├── Voice.WakeWordEngine     4-line substring gate
     ├── Brain.BrainRouter        single-pass precedence router
     │   ├── Brain.IntentEngine   regex intent extraction
     │   ├── Brain.CommandCorrector
     │   ├── Memory.MemoryEngine  → Memory.MemoryDatabase (SQLite)
     │   └── AI.AIEngine          → AI.OllamaClient
     ├── Skills.SkillManager      allowlist dispatch
     ├── Conversation.ConversationEngine   main loop + remote worker
     ├── Core.StateManager        DEAD (0 production references)
     ├── Core.EventBus            DEAD (0 subscribers)
     └── Interface.RemoteServer   HTTP API
```

Full detail: `ARCHITECTURE.md`. Gaps: `GAP_ANALYSIS.md`. Debt: `TECHNICAL_DEBT.md`.

---

## Feature status

| Area | Status | Evidence / note |
|---|---|---|
| Foundation | **DONE** | config defaults, logger, root-relative paths, launcher, test runner |
| Brain / intent routing | **DONE** | deterministic fast path, fuzzy correction, works |
| LLM never executes | **DONE** | no `eval`/`exec`/`subprocess` on model output; the core safety property |
| Skill allowlist | **DONE** | `Security/permissions.py` |
| Confirm-before-destructive | **DONE** | `POWER_*` never reaches a skill unconfirmed; Linux needs `allow_local_power_control` |
| Calculator safety | **DONE** | `ast` allowlist, no `eval` |
| Local LLM (Ollama) | **UNVERIFIED** | service started locally and `llama3.2:3b` pulled, but **no test exercises the real client** |
| Memory persistence | **PARTIAL** | survives restart, but unbounded, lossy under concurrency, injectable |
| TTS engine abstraction | **DONE** | 4 engines behind a priority list |
| TTS cancellation | **DONE 2026-09-29** | **TD-01/TD-02 closed** (`030c9e2`); synth handle on instance, cancel `Event`, `_speaking` `finally`-cleared; success playback back to the speaker |
| Streaming STT | **MISSING** | one-shot blocking `transcribe()` on a finished WAV |
| VAD fallback | **MISSING** | 3× floor gate deadlocks in real rooms (`vad_engine.py:109`) |
| Voice state machine | **DONE 2026-09-29** | 8 states, transition table, atomic capture↔playback reservations (TD-32, TD-04); dead `Core/state_manager.py` removed |
| Recorder termination | **DONE 2026-09-29** | **TD-03 closed** (`7dc99b4`); wall-clock deadline on the whole listen loop |
| Barge-in | **PARTIAL** | prevents duplicates (good) but drops all interrupts over 2.2 s |
| Echo control | **PARTIAL→DONE 2026-09-29** | state machine enforces mic-closed-during-TTS across console, GUI `_auto_loop` and remote TTS; GUI shares the mic lock (TD-04/TD-15). **HARDWARE UNVERIFIED** |
| Wake word | **MISSING** | `WakeWord/` is empty; the live gate is substring matching after full transcription |
| Agent / planning | **MISSING** | the LLM can only answer in prose; it never dispatches a skill |
| Tool schemas | **MISSING** | no declarative argument contract |
| Plugin discovery | **MISSING** | hardcoded skill list |
| Home automation | **MISSING** | nothing |
| Vision | **MISSING** | screenshot only, UNVERIFIED headless |
| Proactive / scheduler | **MISSING** | event bus exists but is dead |
| Remote API | **PARTIAL** | token auth + fail-closed LAN work; no body caps, wildcard CORS, no audit log |
| GUI | **PARTIAL** | usable; `_auto_loop` spins at 100% CPU and races capture; **zero test coverage** |
| Persona | **DONE** | system prompt, female voice, greeting |
| Performance | **MISSING** | **no measurement of any kind exists** |
| Observability | **PARTIAL** | rotating log, but utterances logged 3× in plaintext into `0777` files |
| Documentation | **PARTIAL** | audit set complete; five `Docs/*.md` files are 0 bytes |

---

## Verification (headless Linux dev box)

| Check | Result |
|---|---|---|
| `python -m compileall -q .` | **PASS** (exit 0) |
| `python Tests/run_tests.py` | **Ran 678 tests — OK (skipped=1)**, ~13 s, clean exit |
| Skipped | `Tests/audio_stream_test.AudioStreamTest.test_stream_start_stop` — requires `sounddevice` |
| `ollama` binary | present at `/usr/local/bin/ollama` (client 0.34.4) |
| `ollama` service | started locally; `llama3.2:3b` pulled (~2.0 GB) |
| Real LLM round trip | **UNVERIFIED by tests** — `OllamaClient` is mocked in `Tests/learning_test.py` so the suite runs offline |

**Corrections:** the previous revision of this file claimed **678 tests**; the real
count is **208**. It also overstated SEC-02 as an exposed live token — the
`remote_server.token` value is empty, so nothing leaked. Both are corrected here.

**Fixed today (2026-09-29):**
- the suite no longer writes to the developer's live `Config/audio_config.json`
  (it used to force `tts_engine=piper`, `piper_voice=xyz` on every run), and
  `Config/*.json` is now gitignored with `*.example.json` committed in its place;
- `Tests/system_test.py::test_greeting` no longer fails after 22:00
  (time-of-day-dependent assertion made deterministic);
- `Tests/learning_test.py` mocks the Ollama client so the suite never blocks on
  a slow/failed local model.

Optional dependencies absent on this box: `sounddevice`, `faster_whisper`,
`silero_vad`, `torch`, `edge_tts`, `pyttsx3`, `pyautogui`. They are imported
lazily/fenced, which is why the suite runs headless — that design is correct and
should be preserved.

---

## Top risks (full register in `TECHNICAL_DEBT.md`)

| ID | Severity | Summary |
|---|---|---|
| TD-01 | **CLOSED 09-29** | Cancelled TTS finishes synthesising and plays into a reopened mic |
| TD-02 | **CLOSED 09-29** | One TTS failure latches `_speaking` → every later reply stalls 40 s, forever |
| TD-03 | **CLOSED 09-29** | Stalled capture hangs the conversation thread permanently |
| TD-04 | **CLOSED 09-29 (WIP)** | GUI auto-listen captures MAXIE's own speech → mutating commands re-execute |
| TD-05 | HIGH | Energy-VAD fallback drops every utterance in a quiet room |
| TD-06 | HIGH | First-run STT/VAD load failure disables the subsystem permanently |
| TD-07 | **CRITICAL** | Unbounded request bodies and threads on the remote server |
| TD-08 | **HIGH** | Remote token field lives in a git-tracked config (value currently empty — prospective risk) |
| B1 | HIGH | Timeout and generic Ollama errors are persisted as conversation context |
| — | HIGH | `Config.system()` writes to disk on every read; malformed config silently wipes user settings |

---

## Completed / in progress (2026-09-28 .. 29)

1. **Secret leak stopped** (TD-08 / SEC-02): `Config/*.json` gitignored,
   moved to `git rm --cached`, `.example.json` shipped. No real token was ever
   committed.
2. **Git baseline established**: audit commit `9453f4c`, then logical source
   commits `030c9e2` (TTS) and `7dc99b4` (recorder).
3. **Three CRITICAL voice defects fixed** (TD-01/02/03) with regression tests
   that fail without the fix.
4. **Real voice state machine** implemented (TD-32, TD-04): `VoiceStateMachine`
   with 8 states, validated transitions, and atomic capture↔playback
   reservations; dead `Core/state_manager.py` removed; `Ui/gui.py` auto-listen
   tamed. **WIP — wiring in this working tree, to be committed after review.**
5. **Test determinism**: greeting test mock time-independent, `learning_test`
   mocks Ollama, GUI-loop threads tear down. **678 tests, ~13 s, exit 0.**
6. **Still open:** TD-05/06/07/B1, and the remote security group (SEC-03/04/05/11).

Sequencing rationale: `ROADMAP.md`.

---

## Known limitations (honest list)

- **All voice hardware is UNVERIFIED.** Mic, speaker, real TTS synthesis, real
  Whisper transcription, Silero VAD, and barge-in have never been executed. The
  entire voice path must be validated on the actual laptop.
- Wake word is transcription-gated substring matching, not audio spotting.
- Barge-in is unreliable by construction for utterances longer than 2.2 s.
- Echo protection is structural (mic closed), not acoustic, and that structure
  is currently violated by the GUI.
- Memory is unbounded and accepts injected text from any audible content.
- The LLM cannot use skills; agent mode does not exist.
- Performance has never been measured.
- Five documentation files are empty placeholders.
- `MAXIE_REVIEW/` is a deliberate full duplicate of the codebase, created as a
  review deliverable. It doubles the search surface and will drift; it should be
  removed or moved outside the repository once its purpose is served.
