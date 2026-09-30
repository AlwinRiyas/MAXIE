# MAXIE — ARCHITECTURE (as-built)

**Status:** verified against source on 2026-09-28. This document describes the
system that exists, not the system that is planned. For the target design see
`ROADMAP.md`; for the gap between the two see `GAP_ANALYSIS.md`.

**Notation:** every line reference below was read directly from the working
tree. Claims marked `[UNVERIFIED]` were not executable on this headless Linux
box and are inferred from code only.

---

## 1. Process and entry points

| Entry point | Role |
|---|---|
| `run.py` | Real launcher. Argparse (`--gui`, `--minimized`, `--console`), builds `Maxie`, installs signal handlers, drives the conversation loop or GUI. |
| `main.py` | Thin shim delegating to `Core.core_manager.Maxie`. |
| `Ui/gui.py` | Optional tkinter control panel; constructed by `run.py --gui`. |
| `Interface/remote_server.py` | Background `ThreadingHTTPServer` bound to `127.0.0.1:8778`. |
| `Installers/set_autostart.py` | Windows Run-key / Linux XDG autostart management. |

`Maxie` (`Core/core_manager.py`) is the composition root. It constructs every
subsystem, owns the `RemoteServer`, and is responsible for shutdown.

---

## 2. Component map

```
run.py
 └── Core.core_manager.Maxie
     ├── Voice.VoiceEngine         TTS: piper -> edge -> pyttsx3/SAPI -> espeak
     ├── Voice.VoiceManager        state enum + listen() orchestration
     ├── Voice.AudioManager        device enumeration/selection
     ├── Voice.AudioRecorder       blocking capture loop with VAD gating
     ├── Voice.VADEngine           Silero if importable, else energy gate
     ├── Voice.SpeechPipeline      recorder -> Transcriber -> str
     ├── Voice.Transcriber         faster-whisper, one-shot lazy load
     ├── Voice.BargeInListener     stop-phrase detection while speaking
     ├── Voice.WakeWordEngine      4-line substring gate
     ├── Brain.BrainRouter         single-pass precedence router
     │   ├── Brain.IntentEngine    regex intent extraction
     │   ├── Brain.CommandCorrector fuzzy normalisation
     │   ├── Memory.MemoryEngine   -> Memory.MemoryDatabase (SQLite)
     │   └── AI.AIEngine           -> AI.OllamaClient
     ├── Skills.SkillManager       allowlist dispatch
     ├── Conversation.ConversationEngine  main loop + remote worker thread
     ├── Core.StateManager         DEAD — zero production references
     ├── Core.EventBus             DEAD — zero production subscribers
     └── Interface.RemoteServer    HTTP API
```

### Dead / placeholder modules

These exist on disk and are **not** on any live code path:

- `Core/state_manager.py` — **REMOVED 2026-09-29** (dead 6-value manager).
  `Tests/state_test.py` now covers `VoiceStateMachine`, the live machine.
- `Core/event_bus.py` — no subscribers.
- `Voice/Core/` — empty directory.
- `Voice/microphone.py`, `Voice/voice_config.py` — unreferenced.
- `WakeWord/` — all files 0 bytes.
- `Config/voice_config.py` — 0 bytes, duplicate of the live
  `Voice/voice_config.py`.
- `Models/`, `Plugins/`, `Resourses/`, `Vision/` — empty scaffolds.

---

## 3. Voice pipeline (as-built)

### 3.1 State

`Voice/voice_state.py` + `Voice/voice_state_machine.py` (new 2026-09-29) define
eight states and a validated transition table:

```
IDLE -> (WAKING ->) LISTENING -> THINKING -> ACTING -> SPEAKING -> COOLDOWN
   \                                                          ~> LISTENING (barge-in)
   all states -> IDLE | ERROR
```

`VoiceStateMachine` is the single owner: every `transition()` is checked against
`VALID_TRANSITIONS` under an `RLock`, and capture/playback are **mutually
exclusive atomic reservations** (`reserve_capture`/`reserve_playback`). Speech
is never legal from a capturing state (the STRUCTURAL echo guard — TD-04), and a
reply is reserved before its thread starts, closing the old check-then-act race.

`VoiceManager.listen()` leaves the machine in `THINKING` for a real utterance
(ginger closed), `IDLE` for an empty or refused capture. `ConversationEngine`
closes every turn with `end_turn()` in a `finally`; `end_turn()` refuses to
clobber a capture the GUI auto-loop holds.

### 3.2 Capture

`Voice/audio_recorder.py` opens an `InputStream` and pushes frames onto a
`queue.Queue`; a worker drains it, sums energy, and feeds `VADEngine`.

- A wall-clock deadline (`max_total_seconds`, from `_total_budget`) now bounds
  the whole loop, including `queue.Empty` iterations (TD-03, commit `7dc99b4`).
- `stream.close()` runs when `start()` fails (TD-31).

### 3.3 VAD

`Voice/vad_engine.py` prefers Silero; falls back to an energy gate. The fallback
requires speech energy > `max(absolute_floor, noise_floor * 3.0)` (`:109`).
`observe_noise()` adapts the floor, but `reset_noise()` has **no production
caller** — a floor learned during a noisy moment is never cleared, so the
fallback can lock itself into a state where normal speech is classified as noise.

`Tests/vad_test.py` never exercises the `noise_floor * 3.0` branch meaningfully,
so this path is unverified.

### 3.4 Transcription

`Voice/transcriber.py` lazily loads faster-whisper once and caches `self._loaded`
at `:37-39` **before** attempting the load. A single failure (download timeout,
OOM, ctranslate2 mismatch) permanently disables STT for the process lifetime with
one log line. `speech_pipeline.py:14-16` gates on `AudioManager.is_available()`
(i.e. `sounddevice`), not on the transcriber, so the system can announce
"VOICE MODE" and transcribe nothing.

### 3.5 Synthesis and cancellation

**Updated 2026-09-29 (commit `030c9e2`).** `Voice/voice_engine.py` now runs
synthesis through `_run_synthesis` with the subprocess handle on
`self._synth_process` and a `threading.Event` cancel flag (`self._cancel`).
`stop()` terminates the synthesis process itself, `_play_audio` refuses after a
cancel, and 10 tests in `Tests/tts_cancel_test.py` cover cancel-during-synthesis,
the `_speaking` latch, and — for Piper — that a *successful* synthesis actually
reaches the speaker.

Consequence of the old design (for the record): a "stop" issued during the
1–5 s synthesis window let synthesis complete, the conversation loop reopened
the microphone, and playback began — MAXIE spoke into an open mic, transcribed
itself, and fed the echo to the router.

`_speaking` was set at `:246`/`:282` and only cleared downstream of a
successful synthesis; it is now cleared in a `finally` on every worker path.

**HARDWARE-UNVERIFIED point:** the workers clear `_speaking` when playback is
*dispatched*, not when the speaker finishes; on real hardware confirm
`is_speaking()` stays true for the whole audible reply.

### 3.6 Echo control

The property that makes the console loop safe is structural: the mic is closed
during TTS (`audio_recorder.py:121-126`). **Updated 2026-09-29:** the shared
`VoiceStateMachine` now enforces capture↔playback exclusion with atomic
reservations across all three surfaces (console, GUI auto-listen, remote TTS):
- `VoiceManager.listen()` claims the mic atomically and refuses while speaking;
- `ConversationEngine._maybe_speak_remote()` atomically reserves the speaker
  before spawning the reply thread (no check-then-act);
- `Ui/gui.py` `_auto_loop` shares `_talk_lock` with `_on_talk` and no longer
  calls tkinter from the worker thread (TD-15), so a second `InputStream` can
  never be opened on the device.

Coverage: `Tests/state_test.py`, `Tests/conversation_state_test.py`,
`Tests/gui_loop_test.py`.

---

## 4. Brain and routing

`Brain/brain_router.py` `process()` is a single precedence chain, evaluated in
order:

1. empty-input guard
2. `CommandCorrector` normalise
3. `IntentEngine` extract intent
4. `_auto_learn()` — persist preference phrases to SQLite
5. append conversation context
6. memory-extraction of the user utterance
7. destructive-action confirmation gate
8. direct skill match
9. skills-list query
10. memory recall
11. greeting / help
12. smart-mode skill proposal (`ai.routing_mode == "smart"` only)
13. `AIEngine.ask` fallback

Consequences:

- There is **no planning layer** and **no agent loop**. The LLM is a terminal
  fallback; its output is never re-parsed into an instruction.
- In `smart` mode the model may *propose* a skill. The proposal still has to
  clear four filters before anything runs: allowlist, a declared schema,
  the schema validator, and the destructive refusal. It never reaches
  `Permissions.confirmation_for` as a confirmation.
- `_auto_learn` runs on essentially every utterance (`:52`) and writes to
  persistent storage, so spoken text is an unvalidated write path.
- Only one intent is extracted; multi-intent requests silently drop the tail.

### 4.0 Skill argument contracts

`Skills/skill_schema.py` holds one `SkillSchema` per allowlisted intent: the
argument names, types, required-ness, enums, bounds, and which one is the
primary value the existing single-string skill interface wants. It is the
only place that knowledge exists, rendered two ways:

- `SkillManager.execute_args(intent, arguments)` validates a dict against it
  and dispatches the primary argument;
- `SkillSchema.to_ollama_tool()` renders the same declaration as an Ollama
  tool definition for `smart` mode.

Unknown argument names are rejected rather than forwarded, so a model cannot
smuggle a field past a skill that reads one. `tool_schemas()` filters twice:
allowlisted intents only, and destructive intents never (the router would
refuse them anyway, so advertising them only invites a wasted turn).

### 4.1 AI

`AI/ai_engine.py` builds a system prompt, appends `memory.recall_for(query)`,
calls `AI/ollama_client.py`, and persists the result.

`OllamaClient.ask` distinguishes four failure modes but `AIEngine` filters only
one (`ai_engine.py:82-84`):

| Ollama outcome | Message | Filtered? | Consequence |
|---|---|---|---|
| connection refused | "I can't reach Ollama right now…" | yes | correct |
| timeout | "Ollama took too long to respond." | **no** | persisted as assistant context |
| other error | "I hit an error talking to the model: …" | **no** | persisted, and leaks the internal URL |
| empty completion | "I couldn't come up with an answer right now." | **no** | persisted |

Once persisted, these strings are re-injected on every subsequent turn via
`get_context()`.

`OllamaClient.is_available()` (`:28-33`) has zero callers — the only health check
is dead.

### 4.2 Memory

`Memory/memory_database.py` is a single SQLite file with `facts`,
`conversation`, and (derived) synonym clusters. Notable as-built properties:

- `get_context(max_turns=0)` returns the **entire** table — the falsy-zero guard
  is `if max_turns:` (`:194`).
- The `conversation` table is never pruned; `clear_context()` has no production
  caller.
- `search()` interpolates the term into a `LIKE` pattern unescaped (`:150`).
- `any_recall()` scores by substring containment with `len(w) > 2` (`:104-113`),
  so stopwords match; `MemoryEngine.recall_any` returns the result as a spoken
  answer with no confidence floor.
- `migrate_json` (`:226-228`) stores `str(value)`, so a JSON boolean persists as
  the literal string `"True"` and is later spoken back. The live database
  contains four such rows.
- `remember_sentence` derives keys from the first five non-stopword words
  (`memory_engine.py:71-73`), so distinct facts collide and last-write-wins
  silently overwrites.

---

## 5. Skills and security model

The security posture rests on three correct properties:

1. **LLM output is never executed.** Text from the model is returned to the user
   verbatim; it is not `eval`'d, shelled, or fed back into the router.
2. **Skills are an explicit allowlist** enforced by `Security/permissions.py`.
3. **Destructive intents require an explicit confirmation** round-trip before a
   skill is invoked; `POWER_*` never reaches a skill unconfirmed.

Those properties are real and load-bearing. Weaknesses around them:

- `Skills/calculator.py` uses an `ast` allowlist with no `eval`/`exec` — correct,
  and worth preserving under any rewrite.
- `_auto_learn` is a persistent, unvalidated write path fed by free-form speech.
- The confirmation gate is keyed on intent strings, not on a capability, so new
  skills must be added to the permission table by hand.
- Non-timing-safe token comparison and unbounded request bodies weaken the remote
  boundary; see `SECURITY_AUDIT.md`.

---

## 6. Interfaces

### 6.1 Remote HTTP API

`Interface/remote_server.py`, `ThreadingHTTPServer`, default `127.0.0.1:8778`.

| Route | Method | Auth | Notes |
|---|---|---|---|
| `/health` | GET | no | liveness only; reveals version surface |
| `/ui` | GET | no | public mobile tap-to-talk page |
| `/command` | GET, POST | token | text command -> router |
| `/voice` | POST | token | WAV body -> Transcriber -> reply |

Fails closed: a non-loopback bind without a token raises at construction
(`remote_server.py:39-43`), and a whitespace-only token is normalised to empty
and therefore refused.

Weaknesses: wildcard CORS (`:163-168`), no `Content-Length` cap (`:234-238`,
`:268-275`), `hmac.compare_digest` not used (`:61`), class-level `_ui_cache`
(`:315`), unbounded `daemon_threads`.

`Maxie._handle_voice` constructs a **new** `Transcriber` per request
(`core_manager.py:75`), so an unauthenticated-ish cheap request reloads Whisper.

### 6.2 GUI

`Ui/gui.py` is optional and import-guarded. It provides log/status panes,
push-to-talk, auto-listen, quick chips, and an autostart toggle, talking to the
same `ConversationEngine` as the console.

Known structural problems: `_auto_loop` spins with no sleep (`:189`), calls
tkinter from a worker thread (`:186`), and never takes `_talk_lock`, so it races
`_on_talk` on the same capture device. The `MaxieGUI(assistant=...)` injection
seam exists but is never used, and the class is never instantiated by any test.

---

## 7. Configuration

`Config/config.py` loads `Config/system_config.json`, `personality.json`, and
`audio_config.json` at **import time** (`:288`).

- `Config.system()` **writes to disk on every read** (`:155-156`).
- A malformed file is caught by `except (OSError, ValueError): data = {}`
  (`:152-153`) and then overwritten with defaults — no log, no backup.
- `_deep_merge(dict(defaults), data)` shallow-copies only the top level (`:155`,
  `:169`), so an un-overridden nested dict is shared with the class attribute
  and can be mutated in place by callers.
- No schema validation anywhere; a bad `port` surfaces as a raw `ValueError` at
  `core_manager.py:56`.

---

## 8. Error handling and observability

`Logs/logger.py` provides a rotating file logger. Full user utterances are
written **three times in plaintext** — `brain_router.py:44`,
`conversation_engine.py:149`, `conversation_engine.py:218` — and also persisted
forever in SQLite and pushed to the phone. `Logs/` files are mode `0777`.

`Logger.instance()` has a check-then-set race (`:46-51`); `setLevel` runs before
the handler guard (`:20`); there is no `flush()`/`shutdown()`, so a hard exit
can lose the last line.

`Core/state_manager.py` was dead and printed `[STATE] …` on every transition;
it was **removed 2026-09-29** and its tests replaced by `Tests/state_test.py`,
which now covers the real `VoiceStateMachine`.

---

## 9. What the current design gets right

Worth preserving through any refactor, because these are the parts that make
MAXIE defensible:

- Allowlisted skills with an explicit destructive-action confirmation gate.
- LLM output is never executed.
- `ast`-based calculator instead of `eval`.
- Fail-closed remote binding.
- Lazy/fenced imports so the app and the entire test suite run headless.
- SQLite persistence that genuinely survives process restart.
- A daemon-thread + watchdog pattern for TTS so a broken audio stack cannot
  wedge the process.
