# MAXIE — GAP ANALYSIS

**Date:** 2026-09-28. Compares the current verified system against the target
architecture for a production-quality local-first personal AI assistant.

Status vocabulary: **DONE** · **PARTIAL** · **MISSING** · **UNVERIFIED** ·
**BLOCKED**

---

## Summary

| Dimension | Current verdict |
|---|---|
| Overall maturity | **Prototype with production instincts** |
| Voice pipeline reliability | **MISSING** — three CRITICAL defects make it unreliable in normal use |
| Architecture | **PARTIAL** — no state machine, no provider interfaces, no agent loop, two dead state systems |
| Memory | **PARTIAL** — works, but unbounded, unvalidated, and injectible |
| Security model | **PARTIAL** — the philosophy is right, the enforcement and the secret hygiene are not |
| Remote API | **PARTIAL** — fails closed, but no caps, wildcard CORS, no audit log |
| Testing | **PARTIAL** — 138 green tests, almost all happy-path; the most important property is untested |
| Performance | **MISSING** — no measurement exists; per-request model load and unbounded tables |
| Hardware verification | **UNVERIFIED** — the entire audio path |

**Headline:** MAXIE is not "feature-incomplete" so much as **reliability-incomplete**.
The feature list is genuinely good. What is missing is the layer that makes a
feature list trustworthy — state machines, provider boundaries, negative tests,
measurement, and honest status.

---

## 1. Microphone capture

| Target | Current | Status |
|---|---|---|
| Isolated `MicrophoneCapture` | Logic lives inside `Voice/audio_recorder.py:60-224`, tangled with VAD and file writing | **PARTIAL** |
| Pluggable device backend | `AudioManager` enumerates sounddevice devices | **PARTIAL** — no non-sounddevice backend |
| Device hot-plug recovery | None | **MISSING** |
| Adaptive AGC / gain | RMS sum is O(n²) over a growing buffer; no true AGC | **MISSING** |
| Bounded buffering with wall-clock deadline | No deadline; capture can hang forever (`audio_recorder.py:172-176`) | **MISSING** — TD-03 |
| Explicit stream lifecycle | `stream.close()` skipped when `start()` fails (`:110-113`) | **MISSING** — TD-31 |

Gap: the capture loop has no termination condition other than PortAudio calling
back. Everything above it depends on this one component being reliable, and it
is the least reliable part of the system.

## 2. Wake word

| Target | Current | Status |
|---|---|---|
| Pluggable `WakeWordProvider` (Porcupine, openWakeWord, Picovoice, whisper) | Single 4-line substring gate, `Voice/wake_word_engine.py` | **PARTIAL** |
| Hard real-time loop | The gate runs on the STT transcript, i.e. *after* full transcription | **PARTIAL** |
| Hotword learning | None | **MISSING** |
| Phoneme/fuzzy matching | Exact substring | **MISSING** |
| `WakeWord/` package | All files 0 bytes | **MISSING** |
| Always-on power cost profile | No measurement | **MISSING** |

Gap: MAXIE transcribes everything and then string-matches. That is a
*transcription-gated* wake word, not a wake word.

## 3. VAD

| Target | Current | Status |
|---|---|---|
| Pluggable `VADEngine` (Silero, WebRTC) | Silero if importable, else energy | **PARTIAL** |
| Graceful fallback | Present | **DONE** |
| SNR-driven adaptive VAD | 3× floor gate that real rooms cannot satisfy (`vad_engine.py:109`) | **MISSING** — TD-05 |
| Hangover / padding | None | **MISSING** |
| Speech-segment callback design | Blocking loop + sentinel | **PARTIAL** |
| `reset_noise` reachable in production | **No caller** | **MISSING** |

Gap: the fallback that most installs will actually use is the one that
deadlocks. `Tests/vad_test.py` cannot catch it.

## 4. Streaming ASR (STT)

| Target | Current | Status |
|---|---|---|
| Pluggable `STTProvider` | `Transcriber` hardcodes faster-whisper | **PARTIAL** |
| Real streaming decode | Blocking one-shot `transcribe()` on a finished WAV | **MISSING** |
| Partial results | None | **MISSING** |
| Cancellation mid-utterance | None | **MISSING** |
| Graceful degradation | `speech_pipeline.py:14-16` gates on `sounddevice`, not on the STT | **MISSING** — TD-06 |
| One-shot load latch that can recover | Latched before the attempt (`transcriber.py:37-39`) | **MISSING** |
| Word-level timestamps for skills | None | **MISSING** |
| Offline / local-only default | Local by default | **DONE** |

Gap: `speech_pipeline.py:19` writes a **relative** `voice.wav` and never deletes
it, which also violates `AGENTS.md`'s own path convention and creates a
collision point with the GUI.

## 5. TTS engine abstraction

| Target | Current | Status |
|---|---|---|
| Pluggable `TTSProvider` (Piper, Edge, SAPI, espeak, pyttsx3) | Present as an if/elif chain | **DONE** |
| Priority list from config | Present | **DONE** |
| Availability probe before selection | `_detect_engine:61-64` bypasses readiness | **PARTIAL** — TD-33 |
| Cancellable synthesis | **Broken** — synth handle never stored (`voice_engine.py:225-243`) | **MISSING** — TD-01 |
| Voice/speed/emotion parameters | Voice selectable | **PARTIAL** — no speed/pitch control |
| Caching | None | **MISSING** |
| Non-blocking interface | Daemon thread + watchdog | **DONE** — genuinely good |

Gap: the abstraction is present but the most important property of a TTS layer —
**you can stop it** — is broken on both recommended engines.

## 6. Barge-in / interrupt

| Target | Current | Status |
|---|---|---|
| Interrupt while speaking | `BargeInListener` exists | **DONE** |
| No duplicate commands | Achieved | **DONE** |
| Genuine interruptions preserved | `>2.2 s` guard rejects all longer utterances | **MISSING** — TD-30 |
| Single stop-phrase source of truth | Two divergent lists (`barge_in_listener.py:29-41` vs `voice_commands.py:13-28`) | **MISSING** |
| Final-window interrupt | Destroyed by the unconditional `finally` (`conversation_engine.py:304-306`) | **MISSING** |
| Cancellation safety (no speech after cancel) | Broken (TD-01) | **MISSING** |

Gap: barge-in currently optimises for "never duplicate a command" at the cost of
"never lose a legitimate interrupt", and does not prevent the worst outcome —
speaking after being told to stop.

## 7. Echo control

| Target | Current | Status |
|---|---|---|
| Half-duplex discipline | Mic is closed during TTS in the console loop only | **PARTIAL** |
| Reference-cancellation | None | **MISSING** |
| AEC via WebRTC/pipeline | None | **MISSING** |
| Echo-aware thresholds | Adaptive RMS + short-stop-phrase-only decoding | **DONE** |
| Cross-thread enforcement | State attribute is lock-free | **MISSING** — TD-04 |

Gap: MAXIE's echo strategy is *structural* (close the mic), and that structure
is violated by the GUI and by the cancellation path. Structural strategies are
fine — but they must be enforced by the state machine, and there isn't one.

## 8. Command router / intent recognition

| Target | Current | Status |
|---|---|---|
| Deterministic fast path | Yes, regex `IntentEngine` | **DONE** |
| Fuzzy fallback | `CommandCorrector` | **DONE** |
| Clarification on low confidence | None | **MISSING** |
| Multi-intent handling | First match only; tail silently dropped | **MISSING** |
| Unified registry of intents | Partial | **PARTIAL** |
| LLM never executes | Enforced | **DONE** — the single most important property |
| Argument schema / validation | Per-skill ad hoc | **PARTIAL** |

Gap: routing is deterministic and safe, but shallow. It cannot do "do X, then
Y", and it never asks for clarification.

## 9. AI provider

| Target | Current | Status |
|---|---|---|
| `LLMProvider` interface | Single concrete `OllamaClient` | **MISSING** — TD-34 |
| Ollama / llama.cpp / OpenAI / cloud switch | Config URL only | **PARTIAL** |
| Availability probe | `is_available()` exists with **zero callers** | **MISSING** |
| Per-provider profiles | No | **MISSING** |
| Streaming | Blocking `requests.post` | **MISSING** |
| Token/word budget | None | **MISSING** |
| Retry with backoff | None | **MISSING** |
| Correct failure classification | 1 of 4 messages filtered (`ai_engine.py:82-84`) | **MISSING** — the other three persist as context |
| Timeouts | Present | **DONE** |

Gap: the only provider works, but every failure mode except "Ollama is not
running" is silently written into long-term conversation history and re-injected
forever.

## 10. Memory system

| Target | Current | Status |
|---|---|---|
| Working memory | `conversation` table | **PARTIAL** |
| Short-term session memory | Implicit via `get_context` | **PARTIAL** |
| Long-term facts | `facts` table | **DONE** |
| Preference learning | `_auto_learn` | **PARTIAL** — matches inside negations |
| Semantic retrieval | Substring scoring with stopwords | **PARTIAL** — TD-19 |
| Cross-session persistence | SQLite | **DONE** |
| Named user profiles | None | **MISSING** |
| Memory summarisation | None | **MISSING** |
| Bounded context | `get_context(0)` returns everything; table never pruned | **MISSING** — TD-11 |
| Concurrency safety | **Probed: 7 `InterfaceError`s, 86% data loss under 4 threads** | **MISSING** |
| Memory CRUD skill | Present | **DONE** |
| Forgotten/negative memories | None | **MISSING** |

Gap: memory works and survives restart, which is the hard part. It is
unbounded, lossy under concurrency, and it accepts injected text.

## 11. Skill system

| Target | Current | Status |
|---|---|---|
| Plugin discovery / `entry_points` | Hardcoded `SkillManager` | **PARTIAL** |
| JSON tool schema | None | **MISSING** |
| Registry with explicit capabilities | `Security/permissions.py` allowlist | **PARTIAL** — string-keyed, not capability-based |
| Arg binding / validation | Ad hoc per skill | **PARTIAL** |
| Async execution | None | **MISSING** |
| Skill timeout / cancellation | None | **MISSING** |
| Skill error isolation | Partial | **PARTIAL** |
| Hot reload | None | **MISSING** |
| `Skills/skills/` plugin folder | Not present | **MISSING** |
| Destructive-action confirmation | Present and working | **DONE** |
| AST-safe calculator | `ast` allowlist, no `eval` | **DONE** — preserve this |

Gap: the allowlist is the right idea; it just needs to be a capability model
rather than a growing list of intent strings, and it needs a tool schema so the
LLM can *call* skills rather than only answer in prose.

## 12. Agent capabilities

| Target | Current | Status |
|---|---|---|
| Agent mode | None | **MISSING** — `agent` is refused by config and by the router, not silently downgraded |
| Routing modes | `ai.routing_mode`: `controlled` (default) / `smart` | **PARTIAL** — the third mode needs the planner |
| Plan → execute → verify loop | None | **MISSING** |
| `LLMPlanner` | None | **MISSING** |
| `AgentExecutor` | None | **MISSING** |
| Loop detection / max iterations | None | **MISSING** |
| Permission enforcement inside the loop | N/A | **MISSING** (pre-loop allowlist + destructive refusal do exist) |
| Tool schemas | `Skills/skill_schema.py`, one per allowlisted intent | **DONE** |
| Structured tool-calling | `OllamaClient.ask_with_tools` -> allowlist -> schema -> dispatch | **DONE** |
| Optional LLM fallback for unclear commands | Always the fallback | **PARTIAL** — no plan-first mode |

Gap: this is the largest single functional gap. MAXIE's LLM can only ever
answer in prose. It cannot compose two skills, verify a result, or ask for
clarification. Structured tool-calling plus a bounded agent loop is the change
that converts MAXIE from "voice front-end for regex" into an assistant.

## 13. Home automation

| Target | Current | Status |
|---|---|---|
| Device/entity registry | None | **MISSING** |
| LLM → tool mapping | None | **MISSING** |
| State tracking | None | **MISSING** |
| Confirm-before-act | Present for destructive actions | **DONE** |
| Discovery (Home Assistant, Hue) | None | **MISSING** |

Gap: nothing here exists. The permission model is the only reusable asset.

## 14. User profile / personalisation

| Target | Current | Status |
|---|---|---|
| Name, timezone, locale | `Config` | **DONE** |
| Preferences | Auto-learn | **PARTIAL** |
| Multiple profiles | None | **MISSING** |
| Learned routines | None | **MISSING** |
| Time-aware behaviour | None | **MISSING** |

Gap: static config plus free-text auto-learn. No profile switch, no time
awareness.

## 15. Vision / screen understanding

| Target | Current | Status |
|---|---|---|
| Screen capture | `Skills/screenshot.py` (OS-dependent) | **PARTIAL** — `[UNVERIFIED]` headless |
| Vision provider interface | None | **MISSING** |
| Local VLM | None | **MISSING** |
| OCR | None | **MISSING** |
| GUI grounding | None | **MISSING** |
| `Vision/` package | Empty | **MISSING** |

Gap: a screenshot skill exists; there is no vision stack.

## 16. Proactive intelligence

| Target | Current | Status |
|---|---|---|
| Reminder / task skill | `Skills/todo_skill.py` | **PARTIAL** — JSON list, no scheduling |
| Calendar | None | **MISSING** |
| Scheduler / background jobs | None | **MISSING** |
| Event triggers | `Core/event_bus.py` exists but is **dead** (0 subscribers) | **MISSING** |
| Daily briefing | None | **MISSING** |
| Quiet hours | None | **MISSING** |
| Onboarding | None | **MISSING** |

Gap: the event bus is the right seed and is currently unused. A scheduler plus
a properly wired bus is the cheapest path to the "assistant" feeling.

## 17. Remote / phone interface

| Target | Current | Status |
|---|---|---|
| Authenticated HTTP API | Token via header or query | **DONE** |
| Fail-closed LAN binding | Verified | **DONE** |
| Mobile tap-to-talk UI | `GET /ui` | **DONE** — unauthenticated (SEC-10) |
| PUSH / voice reply | `POST /voice` | **DONE** |
| PTT stream | Partial | **PARTIAL** |
| Per-command action + rollback | None | **MISSING** |
| Conversation history view | None | **MISSING** |
| Skill enable/disable from remote | None | **MISSING** |
| Diagnostics from phone | `/health` only | **PARTIAL** |
| PTT push-to-HTTPS | None | **MISSING** |
| Body caps / rate limit / audit log | None | **MISSING** — SEC-01, SEC-11 |

Gap: the API exists and fails closed, which is the hard part. It is missing the
operational controls that make it safe to expose to a LAN.

## 18. Quality attributes

### Testing
Green suite, near-zero adversarial coverage. **PARTIAL.** The single most
important property — "one bad command must not end the session" — has no test.
See `TEST_STATUS.md`.

### Observability
Rotating file logger, but utterances logged three times in plaintext into
world-writable files, no redaction, no metrics, no tracing, dead stdout prints
in a dead class. **MISSING.**

### Performance
**No measurement exists at all.** Known pathologies: new `Transcriber` per
`/voice` request, O(n²) energy sum in the recorder, unbounded `conversation`
table, no TTS cache, per-request model load, 1 s GUI status poll. **MISSING.**

### Documentation
Five `Docs/*.md` files are **0 bytes**. `DEVELOPMENT_STATUS.md` was wrong about
the test count. `AGENTS.md` was wrong about token gitignoring. The audit set
written today fixes this. **PARTIAL.**

### Security posture
Philosophy correct (never execute LLM output, allowlist skills, confirm
destructive actions, fail-closed LAN). Enforcement and hygiene not: the remote
token lives in a git-tracked file (value currently empty, so prospective rather
than realised), no body caps, wildcard CORS, persistent prompt-injection via
auto-learn, plaintext logs. **PARTIAL** — see `SECURITY_AUDIT.md`.

### Error handling
Largely per-component, mostly without a global policy. A single raise in
`Maxie.shutdown()` orphans every remaining resource. **PARTIAL.**

### Concurrency
Several unsynchronised, lock-free shared attributes and an unsynchronised
SQLite writer. **PARTIAL** — with a probed 86% data-loss result.

### Resource cleanup
Leaks identified: PortAudio handles on failed `start()`, a thread per pyttsx3
speak, `BargeInListener` on the exception path, unjoined `serve_forever` and
TTS threads, `voice.wav` never deleted. **MISSING.**

### Configuration
Single JSON files, auto-created, written on read, no schema, no validation, no
profiles, secrets not gitignored. **PARTIAL.**

### Documentation/UX
CLI and tkinter GUI exist and are usable; no onboarding, no help inside the GUI,
no in-app diagnostics. **PARTIAL.**

---

## The three highest-value changes

If only three things get done, these are they — each unlocks or de-risks many
others:

1. **Make TTS cancellable and the recorder deadline-bounded** (TD-01, TD-02,
   TD-03). These are the three defects that make the product unusable rather
   than merely imperfect, and they are all in the voice path that the entire
   product rests on.
2. **Introduce a real, guarded voice state machine and route every capture and
   playback through it** (TD-04, TD-32). Echo control, barge-in, and GUI safety
   all follow from one enforced state variable instead of three threads writing
   an attribute.
3. **Add structured tool-calling plus a bounded agent loop** (§12). This is what
   makes MAXIE an assistant instead of a voice front-end — and it is the only
   large new capability that the existing allowlist can safely host.
