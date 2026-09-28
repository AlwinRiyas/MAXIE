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

- `Core/state_manager.py` — 6-value `StateManager`, superseded by
  `Voice.VoiceState`. `Tests/state_test.py` tests *this*, not the live machine.
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

`Voice/voice_state.py` defines exactly four states:

```
IDLE -> LISTENING -> PROCESSING -> SPEAKING -> IDLE
```

There is **no transition table, no guard, and no validation**.
`VoiceManager.set_state()` exists but is never called; every transition is a
direct attribute write. `Conversation/conversation_engine.py:178-180` also
writes the attribute directly.

`VoiceManager.listen()` (`voice_manager.py:29`) enters `PROCESSING` and does not
return to `IDLE`, so a completed turn leaves the machine parked in
`PROCESSING` — the GUI then renders "Thinking…" indefinitely.

### 3.2 Capture

`Voice/audio_recorder.py` opens an `InputStream` and pushes frames onto a
`queue.Queue`; a worker drains it, sums energy, and feeds `VADEngine`.

- Termination relies **entirely** on `queue.Empty`. There is no wall-clock
  deadline on the loop (`audio_recorder.py:172-176`, `:211-215`).
- `speech_wait_timeout` is gated on `speech_started_at is None`, so it only
  bounds the *pre-speech* wait, never the total utterance.
- `stream.close()` is skipped when `InputStream()` succeeds but `start()`
  fails (`audio_recorder.py:110-113`), leaking a handle.

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

`Voice/voice_engine.py` runs synthesis in a local `subprocess.run` (`:227`) that
is **never stored on `self.process`**. `stop()` (`:517-547`) can only terminate
the *player* process. There is no cancel flag between synthesis (`:234`) and
playback (`:235`).

Consequence: a "stop" issued during the 1–5 s synthesis window lets synthesis
complete, the conversation loop reopens the microphone, and then playback begins
— MAXIE speaks into an open mic, transcribes itself, and feeds the echo to the
router.

`_speaking` is set at `:246`/`:282` and only cleared at `:408`/`:482`/`:521`,
all downstream of a *successful* synthesis plus a real player. Any TTS failure
latches the flag permanently.

### 3.6 Echo control

The property that makes the console loop safe is structural: the mic is closed
during TTS (`audio_recorder.py:121-126`). That property holds **only** for the
single-threaded console path. It is violated by:

- `Ui/gui.py:185-191` — `_auto_loop` calls `listen_once()` with no
  coordination against the concurrent `MAXIE-RemoteTTS` thread.
- Concurrent TTS — the state attribute is lock-free and written by three
  threads.
- The cancellation path in 3.5, where TTS starts *after* the mic reopened.

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
12. `AIEngine.ask` fallback

Consequences:

- There is **no planning layer** and **no agent loop**. The LLM is a terminal
  fallback; its output is never re-parsed and never dispatched to a skill.
- `_auto_learn` runs on essentially every utterance (`:52`) and writes to
  persistent storage, so spoken text is an unvalidated write path.
- Only one intent is extracted; multi-intent requests silently drop the tail.

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

`Core/state_manager.py:18-20` prints on every transition. That class is dead,
but the test suite instantiates it, so `[STATE] …` lines leak into stdout after
the unittest summary.

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
