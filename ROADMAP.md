# MAXIE — ROADMAP

**Date:** 2026-09-28. Derived from `GAP_ANALYSIS.md` and `TECHNICAL_DEBT.md`.
Status vocabulary: **DONE** · **PARTIAL** · **MISSING** · **UNVERIFIED** ·
**BLOCKED** · **TODO**

Every phase lists **subphases** so progress is measurable. Each phase closes only
when its tests pass, `python Tests/run_tests.py` stays green, and
`python -m compileall -q .` is clean.

---

## Prioritised order (the plan)

The order below is deliberate and differs from the document order.

**Wave 0 — do first, small, blocking:**
1. Stop the secret leak (SEC-02). Untrack the config files and gitignore them.
   *(Verified: the current token value is empty, so nothing leaks until someone
   sets a real one — but that is one `git commit -a` away.)*
2. Establish a real git baseline.

**Wave 1 — the product is currently unreliable; fix that before adding anything:**
3. Phase 4: make TTS cancellable and stop latching.
4. Phase 3: bound the recorder with a wall-clock deadline.
5. Phase 2: real voice state machine with a transition table and guards.
6. Phase 7: enforce echo control through that state machine (fixes the GUI race).

**Wave 2 — correctness and safety:**
7. Phase 5: barge-in that preserves genuine interrupts.
8. Phase 1/8: fail-close on STT/VAD load, fix the VAD fallback deadlock.
9. Phase 9/10/11: provider boundary, memory bounds, capability permissions.
10. Phase 17: remote API caps, CORS, rate limit, audit log.

**Wave 3 — the capabilities that make it an assistant:**
11. Phase 12/13: tool schemas, plugin discovery, agent loop, routing modes.
12. Phase 14/16/15: profiles, scheduler, event bus, vision.

**Wave 4 — quality attributes:**
13. Phases 6, 18: performance measurement, observability, documentation, test depth.

Reasoning: Wave 1 items are three CRITICAL defects that make MAXIE *unusable*
(TTS that speaks after you say stop, TTS failure that stalls every reply
forever, and a recorder that can hang permanently). Adding an agent loop on top
of that foundation would multiply every defect.

---

## Phase 0 — Foundation & baseline · **DONE (with exceptions)**

- **0.1** Config auto-defaults — **DONE**
- **0.2** Rotating logger — **DONE** (see Phase 18 for redaction)
- **0.3** Path computation from project root — **DONE** (one violation: `speech_pipeline.py:19`)
- **0.4** Launcher `run.py` / `main.py` — **DONE**
- **0.5** Test runner — **DONE**
- **0.6** **`git` baseline + secret hygiene** — **TODO** → Wave 0
  - `Config/system_config.json` is git-tracked and holds a user-editable
    `remote_server.token` field (currently **empty** — no live leak, but
    prospective).
  - Working tree has 100+ pre-existing modifications from before this audit.
  - **Action:** add `Config/*.json` to `.gitignore`, `git rm --cached`, ship a
    `.example.json`, then commit an honest baseline and work in small commits.

## Phase 1 — Microphone capture · **PARTIAL**

- **1.1** Isolated `MicrophoneCapture` — **DONE 2026-09-29** (new `Voice/microphone_capture.py`; stream lifecycle, queue, stall tracking)
- **1.2** Pluggable device backend — **DONE** (`SoundDeviceStream` backend protocol; fake backend in tests)
- **1.3** Device hot-plug recovery — **DONE** (`MicrophoneCapture.recover()` reopens a stalled stream, bounded retries)
- **1.4** Adaptive AGC / gain — **DONE** (`_apply_agc`, slow-attack toward `agc_target_rms`, caps at `agc_max_gain`; O(n²) running sum replaced with a running counter)
- **1.5** Bounded buffering + wall-clock deadline — **DONE 2026-09-29** (TD-03, commit `7dc99b4`)
- **1.6** Explicit stream lifecycle (close on `start()` failure) — **DONE 2026-09-29** (TD-31, commit `7dc99b4`)
- **1.7** Absolute `voice.wav` path in `Config/temp_path()` + delete after use — **DONE** (TD-31, `SpeechPipeline` tempdir + removal)
- **1.8** Hardware verification — **BLOCKED** (no mic on dev box)

## Phase 2 — Voice state machine · **DONE in live WIP 2026-09-29**

- **2.1** Expand `VoiceState` to `IDLE / WAKING / LISTENING / THINKING / ACTING / SPEAKING / COOLDOWN / ERROR` — **DONE**
- **2.2** Central `VoiceStateMachine` with a validated transition table — **DONE** (TD-32)
- **2.3** Delete dead `Core/state_manager.py`; point `Tests/state_test.py` at the live machine — **DONE** (TD-13)
- **2.4** One lock, one owner: every capture and playback goes through the machine — **DONE** (TD-04, atomic reservations)
- **2.5** Observable state changes emitted to subscribers — **DONE** (`subscribe(callback(prev, cur))`)
- **2.6** Turn always returns to `IDLE`, including empty input — **DONE** (`ConversationEngine.end_turn()`)

**Status note:** implemented and test-green (208 tests) in the working tree;
awaiting review/commit.

## Phase 3 — VAD · **PARTIAL**

- **3.1** `VADEngine` interface — **DONE**
- **3.2** Silero backend — **DONE** (`[UNVERIFIED]`, not installed here)
- **3.3** Energy fallback with calibrated SNR semantics — **MISSING** (TD-05: 3× floor deadlocks real rooms)
- **3.4** Production caller for `reset_noise()` — **MISSING**
- **3.5** Hangover / padding — **MISSING**
- **3.6** Test the `noise_floor * 3.0` branch — **MISSING** (TD-05 is invisible to the suite)

## Phase 4 — TTS engine abstraction · **DONE except lifecycle and cache**

- **4.1** `TTSProvider` interface + Piper — **DONE**
- **4.2** Edge TTS — **DONE** (`[UNVERIFIED]`)
- **4.3** SAPI / pyttsx3 — **PARTIAL** (thread-lifecycle bugs, TD-33)
- **4.4** espeak fallback — **DONE**
- **4.5** Availability probe consulted by selection — **MISSING** (TD-33)
- **4.6** **Cancellable synthesis** — **DONE 2026-09-29** (TD-01, `030c9e2`)
- **4.7** `_speaking` cleared in `finally` on every path — **DONE 2026-09-29** (TD-02, `030c9e2`)
- **4.8** Non-blocking interface with watchdog — **DONE** — keep this
- **4.9** Voice/speed parameters — **PARTIAL**
- **4.10** Response cache — **MISSING**
- **4.11** Fix the live config left by the test suite (`tts_engine: piper`, `piper_voice: xyz`) — **TODO**
- **4.12** Unkillable pyttsx3 worker, `done.wait()` with no timeout — **MISSING** (TD-33)

## Phase 5 — Streaming STT / ASR · **PARTIAL**

- **5.1** `STTProvider` interface — **MISSING**
- **5.2** faster-whisper adapter — **DONE** (`[UNVERIFIED]`)
- **5.3** Real streaming decode with partials — **MISSING**
- **5.4** Cancellation mid-utterance — **MISSING**
- **5.5** Graceful degradation driven by STT availability, not `sounddevice` — **MISSING** (TD-06)
- **5.6** Recoverable load: latch only on success, retry with backoff — **MISSING** (TD-06)
- **5.7** Word-level timestamps for skills — **MISSING**
- **5.8** Whisper model cached process-wide, not per `/voice` request — **MISSING** (SEC-01)

## Phase 6 — Barge-in / interrupt · **PARTIAL**

- **6.1** `BargeInListener` exists — **DONE**
- **6.2** No duplicate commands — **DONE** — preserve
- **6.3** Preserve genuine long interrupts (drop the blanket `>2.2 s` reject) — **MISSING** (TD-30)
- **6.4** Do not destroy an interrupt arriving in the final window — **MISSING** (TD-30)
- **6.5** Single source of truth for stop phrases — **MISSING** (TD-30)
- **6.6** Release `BargeInListener` on the exception path — **MISSING** (TD-28)
- **6.7** Hardware verification — **BLOCKED**

## Phase 7 — Echo control · **DONE in live WIP except AEC**

- **7.1** Half-duplex: mic closed during TTS — **DONE in console only** → **DONE across all surfaces 09-29**
- **7.2** **Enforced by the state machine so the GUI cannot violate it** — **DONE 2026-09-29** (TD-04; atomic capture↔playback reservations)
- **7.3** Echo-aware thresholds — **DONE**
- **7.4** Reference-cancellation / WebRTC AEC — **MISSING** (documented limitation)
- **7.5** Cooldown owned by the state machine, not a `sleep` on a side thread — **PARTIAL**
- **7.6** Regression test: GUI auto-listen must never capture MAXIE's own speech — **DONE** (`Tests/gui_loop_test.py`, `Tests/conversation_state_test.py`)

## Phase 8 — Command router / intent recognition · **PARTIAL**

- **8.1** Deterministic fast path — **DONE**
- **8.2** Fuzzy correction — **DONE**
- **8.3** Clarification on low confidence — **MISSING**
- **8.4** Multi-intent handling — **MISSING**
- **8.5** Unified intent registry with declared capabilities — **PARTIAL**
- **8.6** LLM output never executed — **DONE** — preserve and test it
- **8.7** Argument schema validation — **MISSING**

## Phase 9 — AI provider · **PARTIAL**

- **9.1** `LLMProvider` interface — **MISSING** (TD-34)
- **9.2** Ollama adapter — **DONE** (`[UNVERIFIED]`, no test)
- **9.3** Availability probe actually called — **MISSING** (TD-34)
- **9.4** Additional providers (llama.cpp, OpenAI-compatible) — **MISSING**
- **9.5** Streaming responses — **MISSING**
- **9.6** Token/word budget — **MISSING**
- **9.7** Retry with backoff — **MISSING**
- **9.8** **Classify all four failure modes; never persist an error as context** — **MISSING** (B1 defect, TD under `SECURITY_AUDIT` §3)
- **9.9** Never leak the internal URL to the user — **MISSING** (SEC-05)

## Phase 10 — Memory system · **PARTIAL**

- **10.1** Working memory (conversation table) — **DONE**
- **10.2** Long-term facts — **DONE**
- **10.3** Preference learning — **PARTIAL** (matches inside negations)
- **10.4** Semantic retrieval with IDF + stopwords + minimum score — **MISSING** (TD-19)
- **10.5** Cross-session persistence — **DONE**
- **10.6** **Concurrency safety** (probed: 86% loss under 4 threads) — **MISSING**
- **10.7** **Bounded context**; `get_context(0)` must not return everything — **MISSING** (TD-11)
- **10.8** Retention sweep for the `conversation` table — **MISSING**
- **10.9** Fix `migrate_json` storing `"True"`; one-shot migration marker — **MISSING** (TD-12)
- **10.10** Collision-free fact keying (no first-5-words truncation) — **MISSING** (TD-41)
- **10.11** Escape `LIKE` metacharacters in `search()` — **MISSING** (TD-18)
- **10.12** `update()` must preserve `kind` — **MISSING** (TD-40)
- **10.13** Named user profiles — **MISSING**
- **10.14** Summarisation / compaction — **MISSING**

## Phase 11 — Skill system · **PARTIAL**

- **11.1** `SkillManager` registry — **DONE**
- **11.2** **Capability-based, default-deny permissions** — **MISSING** (SEC-07)
- **11.3** JSON tool schema per skill — **MISSING**
- **11.4** Argument binding + validation — **PARTIAL**
- **11.5** Plugin discovery via `entry_points` — **MISSING** (from OpenVoiceOS)
- **11.6** `Skills/skills/` plugin folder — **MISSING**
- **11.7** Async execution — **MISSING**
- **11.8** Per-skill timeout and cancellation — **MISSING**
- **11.9** Error isolation — **PARTIAL**
- **11.10** Hot reload — **MISSING**
- **11.11** Confirm-before-destructive — **DONE** — preserve
- **11.12** AST-safe calculator — **DONE** — preserve
- **11.13** Guarded bulk memory delete + test — **MISSING** (SEC-08)
- **11.14** **Close the auto-learn prompt-injection channel** — **MISSING** (SEC-06)

## Phase 12 — Agent capabilities · **MISSING**

- **12.1** Controlled / smart / agent routing modes — **MISSING** (from Leon)
- **12.2** `LLMPlanner` — **MISSING**
- **12.3** `AgentExecutor` — **MISSING**
- **12.4** Plan → execute → verify loop — **MISSING**
- **12.5** Loop detection + hard iteration cap — **MISSING**
- **12.6** Permission enforcement *inside* the loop — **MISSING**
- **12.7** Structured tool-calling wired to skill schemas — **MISSING**
- **12.8** `SkillResult` with success/failure/partial — **MISSING**
- **12.9** Undo/rollback surface for remote actions — **MISSING**
- **12.10** Conversation summary injected on turn N — **MISSING**

## Phase 13 — Home automation · **MISSING**

- **13.1** Device/entity registry — **MISSING**
- **13.2** LLM → tool mapping — **MISSING**
- **13.3** State tracking — **MISSING**
- **13.4** Confirm-before-act — **DONE** (reuse Phase 11)
- **13.5** Discovery adapters (Home Assistant, Hue) — **MISSING**

## Phase 14 — User profile / personalisation · **PARTIAL**

- **14.1** Name, timezone, locale from config — **DONE**
- **14.2** Preferences from auto-learn — **PARTIAL**
- **14.3** Multiple profiles — **MISSING**
- **14.4** Learned routines — **MISSING**
- **14.5** Time-aware behaviour — **MISSING**
- **14.6** Safe user-name derivation — **PARTIAL** (`_safe_user` untested)

## Phase 15 — Vision / screen understanding · **MISSING**

- **15.1** Screenshot capability — **PARTIAL** (`[UNVERIFIED]`)
- **15.2** `VisionProvider` interface — **MISSING**
- **15.3** Local VLM adapter — **MISSING**
- **15.4** OCR — **MISSING**
- **15.5** GUI grounding — **MISSING**
- **15.6** Populate or delete the empty `Vision/` package — **TODO**

## Phase 16 — Proactive intelligence · **MISSING**

- **16.1** Reminder / task skill — **PARTIAL** (JSON list, no scheduling)
- **16.2** Calendar integration — **MISSING**
- **16.3** Scheduler / background jobs — **MISSING**
- **16.4** **Fix or delete `Core/event_bus.py`; wire the GUI to it** — **MISSING** (TD-14)
- **16.5** Daily briefing — **MISSING**
- **16.6** Quiet hours — **MISSING**
- **16.7** Onboarding flow — **MISSING**

## Phase 17 — Remote / phone interface · **PARTIAL**

- **17.1** Token-authenticated HTTP API — **DONE**
- **17.2** Fail-closed LAN binding — **DONE** — preserve
- **17.3** Mobile tap-to-talk UI — **DONE**
- **17.4** `POST /voice` WAV upload — **DONE**
- **17.5** Push-to-talk stream — **PARTIAL**
- **17.6** **Body size caps** — **MISSING** (SEC-01)
- **17.7** **Rate limiting** — **MISSING** (SEC-01, SEC-11)
- **17.8** **Correct CORS (no wildcard)** — **MISSING** (SEC-03)
- **17.9** **`hmac.compare_digest` token compare** — **MISSING** (SEC-04)
- **17.10** **No internal detail in error bodies; correct status codes** — **MISSING** (SEC-05)
- **17.11** **Command audit log** — **MISSING** (SEC-11)
- **17.12** Gate `/ui` behind auth — **MISSING** (SEC-10)
- **17.13** Per-command action + rollback — **MISSING**
- **17.14** Conversation history view — **MISSING**
- **17.15** Enable/disable skills from the phone — **MISSING**
- **17.16** Richer diagnostics endpoint — **PARTIAL**
- **17.17** Thread-safe start/stop; join the server thread — **MISSING** (TD-24)
- **17.18** Stop must resolve queued futures — **MISSING** (TD-10)

## Phase 18 — Quality attributes · **MOSTLY MISSING**

### 18.1 Testing · **PARTIAL**
- Adversarial/negative tests — **MISSING**
- **"One bad command must not end the session"** — **MISSING** (the core property)
- Concurrency tests (memory, capture, playback) — **MISSING**
- Resource-lifecycle tests (no leaked threads/streams) — **MISSING**
- Remove vacuous tests (`learning_test.py:68`) — **TODO**
- **Stop the suite mutating real config** — **DONE** (2026-09-28). `Tests/tts_test.py`
  now redirects `Config.FILES` to a temp dir; a new guard test asserts the live
  `Config/audio_config.json` is byte-identical after a run. Proven to fail
  without the isolation. Baseline is now **208 tests, 1 skipped** (~13 s).
- Removing the dead `Core/state_manager.py` and pointing tests at the live
  machine — **DONE 2026-09-29** (`Tests/state_test.py` now covers
  `VoiceStateMachine`; the dead module is deleted).
- Deterministic suite — **DONE 2026-09-29**: the 22:00-time-dependent greeting
  assertion is gone; `Tests/learning_test.py` mocks the Ollama client; the
  GUI-loop tests tear down their daemon threads, so the interpreter exits
  cleanly.
- Hardware smoke test suite for the laptop — **BLOCKED**

### 18.2 Observability · **MISSING**
- Structured logging; remove the 3× plaintext utterance logging — **MISSING** (TD-17)
- Secret/PII redaction — **MISSING**
- `Logs/` and `Memory/` permissions `0600` — **MISSING** (TD-17)
- Metrics: latency, TTS/STT timing, route distribution — **MISSING**
- Delete unguarded `print` in dead code — **TODO** (TD-13)
- Fix `Logger.instance()` race; add `flush()`/`shutdown()` — **MISSING** (TD-16, TD-47)

### 18.3 Performance · **MISSING** (no measurement exists)
- Baseline: cold start, wake-to-listen, STT latency, TTS latency, full turn — **TODO**
- Cache the Whisper model process-wide — **TODO** (SEC-01)
- Fix the O(n²) energy sum in the recorder — **TODO** (TD-01 §1.4)
- Bound the `conversation` table — **TODO** (TD-11)
- TTS response cache — **MISSING**
- Replace the 1 s GUI status poll with the event bus — **MISSING** (TD-14)

### 18.4 Documentation · **PARTIAL → improving**
- Audit set written 2026-09-28 (`ARCHITECTURE`, `GAP_ANALYSIS`, `TECHNICAL_DEBT`, `SECURITY_AUDIT`, `TEST_STATUS`, `OPEN_SOURCE_COMPARISON`, `ROADMAP`, `DEVELOPMENT_STATUS`) — **DONE**
- `AGENTS.md` refreshed — **DONE**
- Five empty `Docs/*.md` placeholders — **TODO** (remove or populate)
- `CHANGELOG.md` maintained per release — **TODO**

### 18.5 Error handling · **PARTIAL**
- Global error boundary so a failed turn never ends the session — **MISSING**
- `contextlib.suppress` + per-step logging in `Maxie.shutdown()` — **MISSING** (TD-22)
- Thread-safe, idempotent shutdown — **MISSING** (TD-25)
- Config schema validation with friendly errors — **MISSING** (TD-27)
- Non-blocking signal handling — **MISSING** (TD-23)
- Malformed config must not destroy user settings — **MISSING** (TD-09)

### 18.6 Concurrency · **PARTIAL**
- One capture lock; one playback lock — **MISSING**
- Thread-safe memory writes — **MISSING** (probed 86% loss)
- Lock-free `VoiceState` — **MISSING** (TD-32)
- GUI `_auto_loop` must take the capture lock and sleep — **MISSING** (TD-15)

### 18.7 Resource cleanup · **MISSING**
- Close PortAudio streams on `start()` failure — **MISSING** (TD-31)
- No thread per pyttsx3 speak; bounded wait — **MISSING** (TD-33)
- Release `BargeInListener` on exceptions — **MISSING** (TD-28)
- Join `serve_forever` and TTS threads — **MISSING** (TD-24)
- Delete `voice.wav` after transcription — **MISSING** (TD-31)

### 18.8 Configuration · **PARTIAL**
- **Never write on read** — **MISSING** (TD-09)
- Back up before overwriting; log parse failures — **MISSING** (TD-09)
- Fix the shallow-copy aliasing of nested defaults — **MISSING** (TD-42)
- `set_audio` must use the same write path and re-sync — **MISSING** (TD-26)
- Schema validation — **MISSING** (TD-27)
- Move all magic numbers into `Config` — **TODO** (TD-46)
- **Secrets gitignored + rotated** — **BLOCKED → Wave 0** (SEC-02)

### 18.9 UX / documentation surfaces · **PARTIAL**
- tkinter control panel — **DONE**
- `MaxieGUI(assistant=...)` injection used by tests — **MISSING**
- GUI test coverage (0 today) — **MISSING**
- In-app help — **MISSING**
- Onboarding — **MISSING**
- Runtime diagnostics view — **MISSING**

---

## Definition of done for a phase

- [ ] Every subphase marked DONE or explicitly waived with a reason
- [ ] `python -m compileall -q .` clean
- [ ] `python Tests/run_tests.py` green, with **no reduction** in test count
- [ ] New tests cover the defect being fixed, and **fail without the fix**
- [ ] No new secret, model, or audio committed
- [ ] `TECHNICAL_DEBT.md` and `DEVELOPMENT_STATUS.md` updated
- [ ] Hardware-dependent items marked **HARDWARE UNVERIFIED** until run on the laptop
- [ ] Committed in a logical, single-purpose commit

## Final gate

The project is production-ready when:

1. `FINAL_AUDIT.md` exists and records a passing re-audit.
2. All S1 (critical) and S2 (high) debt items are closed.
3. The test suite covers negative, adversarial, and concurrent paths, and
   includes the "survives a failing turn" property.
4. The remote API has body caps, rate limiting, correct CORS, constant-time
   token comparison, and an audit log.
5. Hardware verification has been performed on the real laptop and recorded.
6. No secret is tracked by git.
