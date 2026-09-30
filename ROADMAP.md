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
- **3.3** Energy fallback with calibrated SNR semantics — **DONE 2026-09-29** (TD-05, `vad_noise_ratio` default 1.8)
- **3.4** Production caller for `reset_noise()` — **DONE** (`AudioRecorder.record()`)
- **3.5** Hangover / padding — **MISSING**
- **3.6** Test the `noise_floor` branch — **DONE** (`Tests/vad_test.py`, TD-05 visible to the suite)

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
- **5.5** Graceful degradation driven by STT availability, not `sounddevice` — **DONE 2026-09-29** (TD-06, `Transcriber.available`)
- **5.6** Recoverable load: latch only on success, retry with backoff — **DONE 2026-09-29** (TD-06)
- **5.7** Word-level timestamps for skills — **MISSING**
- **5.8** Whisper model cached process-wide, not per `/voice` request — **DONE 2026-09-29** (SEC-01, `Transcriber.shared()`)

## Phase 6 — Barge-in / interrupt · **PARTIAL**

- **6.1** `BargeInListener` exists — **DONE**
- **6.2** No duplicate commands — **DONE** — preserve
- **6.3** Preserve genuine long interrupts (drop the blanket `>2.2 s` reject) — **DONE 2026-09-29** (TD-30)
- **6.4** Do not destroy an interrupt arriving in the final window — **DONE 2026-09-29** (TD-30, drain window)
- **6.5** Single source of truth for stop phrases — **DONE 2026-09-29** (TD-30, `VoiceCommands`)
- **6.6** Release `BargeInListener` on the exception path — **DONE 2026-09-29** (TD-28, try/finally)
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
- **8.3** Clarification on low confidence — **DONE 2026-09-29** (placeholder/unresolved-verb phrases ask; bare verbs route to the skill)
- **8.4** Multi-intent handling — **DONE 2026-09-29** (safe `and`/`,` split, only independently-classifiable skill clauses)
- **8.5** Unified intent registry with declared capabilities — **PARTIAL**
- **8.6** LLM output never executed — **DONE** — preserve and test it
- **8.7** Argument schema validation — **DONE 2026-09-29** (`ARG_REQUIRED`, `_has_argument`, per-intent prompts)

## Phase 9 — AI provider · **PARTIAL**

- **9.1** `LLMProvider` interface — **DONE 2026-09-29** (`AI/llm_provider.py`: `ask`/`is_available` ABC; `OllamaClient(LLMProvider)`; `from_config` override hook) — TD-34
- **9.2** Ollama adapter — **DONE** (`Tests/ollama_client_test.py`: 12 headless tests via patched requests)
- **9.3** Availability probe actually called — **DONE 2026-09-29** (`AIEngine.ask` probes `client.is_available()` up-front, TTL-cached via `availability_ttl_seconds`; `AIEngine.is_available()` delegates) — TD-34
- **9.4** Additional providers (llama.cpp, OpenAI-compatible) — **MISSING** (interface is ready; adapt new backend at the boundary)
- **9.5** Streaming responses — **MISSING** (`stream: False` today; TTS prefers final text)
- **9.6** Token/word budget — **DONE 2026-09-29** (`context_turns` caps turns; `_apply_budget` in `AIEngine` caps total chars and single-row length via `max_context_chars`/`max_context_row_chars`)
- **9.7** Retry with backoff — **DONE 2026-09-29** (ConnectionError/Timeout/429/5xx retry `retries` times with linear `retry_delay_seconds`; permanent errors fail fast)
- **9.8** **Classify all four failure modes; never persist an error as context** — **DONE** (B1 fixes + `test_all_four_failure_modes_never_persist` + `test_offline_failure_not_persisted`)
- **9.9** Never leak the internal URL to the user — **DONE 2026-09-29** (docstring contract + `test_failure_messages_never_leak_internal_url`) — SEC-05 (provider half)

## Phase 10 — Memory system · **PARTIAL**

- **10.1** Working memory (conversation table) — **DONE**
- **10.2** Long-term facts — **DONE**
- **10.3** Preference learning — **DONE 2026-09-29** (negation guard: `_auto_learn` skips phrases with negation before the marker; tests for "don't like", downgraded possession, mixed positive/negative)
- **10.4** Semantic retrieval with IDF + stopwords + minimum score — **DONE 2026-09-29** (TD-19)
- **10.5** Cross-session persistence — **DONE**
- **10.6** **Concurrency safety** (probed: 86% loss under 4 threads) — **MISSING**
- **10.7** **Bounded context**; `get_context(0)` must not return everything — **DONE 2026-09-29** (TD-11, `prune_context`)
- **10.8** Retention sweep for the `conversation` table — **DONE 2026-09-29** (TD-11, `conversation_cap`)
- **10.9** Fix `migrate_json` storing `"True"`; one-shot migration marker — **DONE 2026-09-29** (TD-12)
- **10.10** Collision-free fact keying (no first-5-words truncation) — **DONE 2026-09-29** (TD-41, sha1 suffix)
- **10.11** Escape `LIKE` metacharacters in `search()` — **DONE 2026-09-29** (TD-18)
- **10.12** `update()` must preserve `kind` — **DONE 2026-09-29** (TD-40)
- **10.13** Named user profiles — **MISSING**
- **10.14** Summarisation / compaction — **MISSING**

## Phase 11 — Skill system · **PARTIAL**

- **11.1** `SkillManager` registry — **DONE**
- **11.2** **Capability-based, default-deny permissions** — **DONE 2026-09-29** (`Permissions.DESTRUCTIVE` frozenset; `requires_confirmation(intent)` capability-keyed gate in the router — a new destructive intent cannot bypass by omission) — SEC-07
- **11.3** JSON tool schema per skill — **MISSING**
- **11.4** Argument binding + validation — **PARTIAL**
- **11.5** Plugin discovery via `entry_points` — **MISSING** (from OpenVoiceOS)
- **11.6** `Skills/skills/` plugin folder — **MISSING**
- **11.7** Async execution — **MISSING**
- **11.8** Per-skill timeout and cancellation — **MISSING**
- **11.9** Error isolation — **PARTIAL**
- **11.10** Hot reload — **MISSING**
- **11.11** Confirm-before-destructive — **DONE 2026-09-29** — capability-keyed; bulk memory wipe additionally gated + audited (SEC-08)
- **11.12** AST-safe calculator — **DONE** — preserve
- **11.13** Guarded bulk memory delete + test — **DONE 2026-09-29** (SEC-08: `Permissions.BULK_DELETE_WORDS` gate, confirmation + audit line, unguarded single deletes; `TestBulkDeleteConfirmationTest`)
- **11.14** **Close the auto-learn prompt-injection channel** — **DONE 2026-09-29** (SEC-06: quoted-speech guard on the raw transcript, per-session cap `auto_learn_session_cap`, negation guard; `AutoLearnInjectionTest`)

## Phase 12 — Agent capabilities · **PARTIAL** (schema layer + smart mode)

- **12.1** Controlled / smart / agent routing modes — **PARTIAL** (from Leon) —
  `controlled` (default) and `smart` ship as `ai.routing_mode`; `agent` is
  rejected by config and by the router until 12.2 exists
- **12.2** `LLMPlanner` — **MISSING**
- **12.3** `AgentExecutor` — **MISSING**
- **12.4** Plan → execute → verify loop — **MISSING**
- **12.5** Loop detection + hard iteration cap — **MISSING**
- **12.6** Permission enforcement *inside* the loop — **MISSING** (the loop
  does not exist; the pre-loop allowlist + destructive refusal does)
- **12.7** Structured tool-calling wired to skill schemas — **DONE** —
  `Skills/skill_schema.py` is the single contract: the validator and the
  Ollama tool definition are rendered from the same declaration
- **12.8** `SkillResult` with success/failure/partial — **MISSING**
- **12.9** Undo/rollback surface for remote actions — **MISSING**
- **12.10** Conversation summary injected on turn N — **MISSING**

Order matters here: the tool-schema layer and the routing modes came first
and the bounded loop did not, because a loop with no argument contract and
no explicit autonomy setting is just an unbounded way to run the wrong
skill. 12.2-12.6 build on what is now in place.

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
- **17.12** Gate `/ui` behind auth — **DONE by deviation** (SEC-10) — the tap-to-talk page stays public, every command stays token-checked, so a locked screen cannot be bricked
- **17.13** Per-command action + rollback — **MISSING**
- **17.14** Conversation history view — **MISSING**
- **17.15** Enable/disable skills from the phone — **MISSING**
- **17.16** Richer diagnostics endpoint — **PARTIAL**
- **17.17** Thread-safe start/stop; join the server thread — **DONE** (TD-24) — lock-guarded, `shutdown()` + `server_close()` + bounded join
- **17.18** Stop must resolve queued futures — **DONE** (TD-10) — queued futures resolve with a shutdown error instead of hanging the caller
- **17.19** Request-id correlation (`X-MAXIE-Request-Id`) — **DONE** (SEC-11)
- **17.20** Two-step confirmation for destructive commands — **DONE** (SEC-11) — separate confirm turn, client-bound, `confirm_ttl_seconds` expiry
- **17.21** Bounded live request threads — **DONE** (TD-07) — `max_connections`, 503 beyond the ceiling

## Phase 18 — Quality attributes · **MOSTLY MISSING**

### 18.1 Testing · **PARTIAL**
- Adversarial/negative tests — **PARTIAL** (barge-in, SEC-06 injection, SEC-08 bulk-delete, availability probe, budget — all headless-negative)
- **"One bad command must not end the session"** — **DONE 2026-09-29** (TD-22: teardown steps are error-isolated; one failing step no longer orphans the others — `Tests/shutdown_test.py`)
- Concurrency tests (memory, capture, playback) — **MINIMAL** (`Tests/logger_test.py` TD-16 race)
- Resource-lifecycle tests (no leaked threads/streams) — **PARTIAL** (`Tests/shutdown_test.py`; remote thread join is TD-24)
- Remove vacuous tests (`learning_test.py:68`) — **TODO**
- **Stop the suite mutating real config** — **DONE** (2026-09-28). `Tests/tts_test.py`
  now redirects `Config.FILES` to a temp dir; a new guard test asserts the live
  `Config/audio_config.json` is byte-identical after a run. Proven to fail
  without the isolation. Baseline is now **326 tests, 2 skipped**.
- Removing the dead `Core/state_manager.py` and pointing tests at the live
  machine — **DONE 2026-09-29** (`Tests/state_test.py` now covers
  `VoiceStateMachine`; the dead module is deleted).
- Deterministic suite — **DONE 2026-09-29**: the 22:00-time-dependent greeting
  assertion is gone; `Tests/learning_test.py` mocks the Ollama client; the
  GUI-loop tests tear down their daemon threads, so the interpreter exits
  cleanly.
- Hardware smoke test suite for the laptop — **BLOCKED**

### 18.2 Observability · **PARTIAL**
- Structured logging; remove the 3× plaintext utterance logging — **DONE 2026-09-30** (TD-17: `Logger.utterance()` logs `<N chars #digest>` at the router/barge-in/auto-learn sites; plaintext only behind `logging.log_utterances`)
- Log retention sweep — **DONE 2026-09-30** (TD-17: `Logger.sweep()` prunes rotated `maxie.log.N` past `logging.retention_days`, run once per `Maxie` start)
- Secret/PII redaction — **PARTIAL** (utterances redacted; config values and model names still land in the log)
- **Lifecycle hygiene** — **DONE 2026-09-29**: `Logger.instance()` is race-free (TD-16), has `shutdown()`/flush (TD-47); `Maxie.shutdown()` is thread-safe with an atomic flag (TD-25), error-isolated per step (TD-22), and the signal handler defers blocking cleanup to the main thread (TD-23); `Config.set_audio` re-syncs memory↔disk (TD-26)
- `Logs/` and `Memory/` permissions `0600` — **DONE for the log** (TD-17: chmod on every `Logger` construction); `Memory/` still untouched
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
- Global error boundary so a failed turn never ends the session — **PARTIAL** (shutdown teardown is error-isolated; a mid-turn failure is still per-call try/except)
- `contextlib.suppress` + per-step logging in `Maxie.shutdown()` — **DONE 2026-09-30** (TD-22)
- Thread-safe, idempotent shutdown — **DONE 2026-09-30** (TD-25, `_shutdown_lock`)
- Config schema validation with friendly errors — **DONE 2026-09-30** (TD-27: `Config.SCHEMA` + `ConfigError` + exit code 2 from `run.py`)
- Non-blocking signal handling — **DONE 2026-09-30** (TD-23: handler logs and defers cleanup to the main thread)
- Malformed config must not destroy user settings — **DONE** (TD-09, `bfb49cb`: backup to `.bak`, defaults restored)

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
