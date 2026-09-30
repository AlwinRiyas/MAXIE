# MAXIE — TECHNICAL DEBT REGISTER

**Verified:** 2026-09-28, against the working tree. Every entry carries a
`file:line` reference. Severity is impact on a real user, not code aesthetics.

Totals: **47 items** — 7 critical, 10 high, 16 medium, 14 low/dead.

**Status update (2026-09-29):** TD-01, TD-02 and TD-03 are **CLOSED** (commits
`030c9e2`, `7dc99b4`); TD-04, TD-15 and TD-32 are **CLOSED in the live,
uncommitted state-machine WIP**; TD-31 is partially closed. Test count moved
from 139 to **208**. The counts below retain the original register numbering —
closed items are annotated, not renumbered, so line references stay stable.

**Status update (2026-09-30):** TD-16, TD-22, TD-23, TD-25, TD-26, TD-27 and
TD-47 and TD-17 are **CLOSED** (utterances redacted to length+digest at INFO
behind `logging.log_utterances`, log file owner-only, retention sweep added);
TD-07/SEC-05 (unbounded bodies, threads and error-body detail) is **CLOSED** in
the remote boundary. The suite sits at **450 tests, 2 skipped**. The register
numbering is still preserved.

Severity note: TD-08 was initially rated CRITICAL as "live token committed".
That was **overstated** — verification showed the `remote_server.token` value in
the worktree is empty and the HEAD blob is 0 bytes, so nothing leaks today. It
is downgraded to HIGH as a *prospective* risk. The three CRITICAL voice defects
(TD-01, TD-02, TD-03) and the remote DoS (TD-07) are the real headline items.

---

## S1 — Critical

**Resolved:** TD-01, TD-02, TD-03 (see `TEST_STATUS.md`). Remaining critical
items are the remote DoS, capability spreads, and process launch.

### TD-01 Cancelled TTS keeps synthesising and then plays into an open mic
`Voice/voice_engine.py:225-243`, `:517-547`
Synthesis ran in a `subprocess.run` (`:227`) that was never assigned to
`self.process`; `stop()` could only kill the player. No cancel flag between
`:234` and `:235`.

**Status: CLOSED** (commit `030c9e2`).
Synthesis now runs through `_run_synthesis` with the handle on
`self._synth_process`, `_cancel` is an `Event`, `_play_audio` refuses after a
cancel, and Piper only plays when synthesis completed (the success path was
briefly dropped and is now covered by a regression test). Covered by 10 tests in
`Tests/tts_cancel_test.py`.
*Impact:* user says "stop" during the 1–5 s piper synthesis window; the loop
reopens the mic; synthesis completes; MAXIE speaks at full volume, transcribes
itself, and routes the echo. Affects both recommended engines on every platform.
*Fix:* hold the synth handle on the instance, add a `threading.Event` cancelled
between synth and play, and check it before `_play_audio`.

### TD-02 `_speaking` latches `True` on any TTS failure
`Voice/voice_engine.py:246`, `:282` (set) vs `:408`, `:482`, `:521` (clear)
All clears were downstream of a successful synthesis plus a real player process.

**Status: CLOSED** (commit `030c9e2`).
Piper and Edge workers now `finally`-clear `_speaking` on every path.
*Impact:* a missing piper binary or an offline Edge engine turns every
subsequent reply into a 40-second stall, forever, with no self-heal.
*Fix:* `try/finally` around the whole speak path; clear the flag in the handler.

### TD-03 Recorder can hang forever if capture stops mid-utterance
`Voice/audio_recorder.py:172-176`, `:211-215`
`total_blocks` only advances on dequeue; there is no wall-clock deadline, and
`speech_wait_timeout` only bounds the pre-speech wait.

**Status: CLOSED** (commit `7dc99b4`).
`_listen_loop` now takes a `max_total_seconds` absolute deadline, checked on
every iteration (including `queue.Empty`), derived from Config via
`_total_budget`. Covered by 5 tests in `Tests/recorder_deadline_test.py`.
*Impact:* unplugging a USB headset mid-sentence leaves the conversation thread
dead permanently; GUI auto-listen repeats it forever.
*Fix:* absolute deadline derived from `Config`, checked in the loop.

### TD-04 GUI auto-listen transcribes MAXIE's own speech
`Ui/gui.py:185-191` vs `Conversation/conversation_engine.py:175-182`
Speaking was gated during LISTENING; nothing gated *listening* during SPEAKING.
`_auto_loop` never took `_talk_lock` (which `_on_talk` does hold).

**Status: CLOSED in the live state machine (uncommitted WIP at this write).**
`VoiceStateMachine` owns capture and playback as mutually exclusive atomic
reservations; the old check-then-act `_can_remote_speak` was removed. The GUI's
`_auto_loop` and `_on_talk` share `_talk_lock`, `_auto_loop` no longer touches
tkinter from the worker and sleeps between empty listens. Coverage:
`Tests/state_test.py`, `Tests/gui_loop_test.py`, `Tests/conversation_state_test.py`.

**Remaining watch item:** the Pipper/Edge workers still clear `_speaking` in a
`finally` while `_play_audio` itself dispatches an async player; the success
path has a test, but real playback timing must be confirmed on hardware.
*Impact:* a mutating remote command re-executes itself once per reply, silently,
scaled by response length. The `echo_cooldown` sleep on another thread cannot
help.
*Fix:* route all capture through one lock; make the GUI observe the shared
`VoiceState` instead of polling independently.

### TD-05 Energy-VAD fallback deadlocks in quiet rooms
`Voice/vad_engine.py:109` + `Voice/audio_recorder.py:185-187`
The gate demands speech > 3× ambient RMS; real rooms show 1.5–2×. `reset_noise()`
has no production caller, so the floor never recovers.
*Impact:* on any install without the optional ML stack (this dev box included),
ambient ≥ 0.004 RMS causes every utterance to be dropped after a 20 s timeout.
*Fix:* calibrated absolute floor, a bounded adaptive multiplier, and a
production caller for `reset_noise()`.

### TD-06 One-shot load latch disables STT permanently on first failure
`Voice/transcriber.py:37-39`, `Voice/vad_engine.py:52-62`
Both set the "attempted" flag *before* trying. `speech_pipeline.py:14-16` gates
on `sounddevice`, not on the transcriber.
*Impact:* one download timeout or OOM permanently disables transcription while
the UI still reports "VOICE MODE".
*Fix:* only latch on success; expose `available` as a real property; add
exponential-backoff retry.

### TD-07 Remote server accepts unbounded bodies and unbounded threads
`Interface/remote_server.py:234-238`, `:268-275`, `:100`, `:107`
`Content-Length` is read straight into memory; `ThreadingHTTPServer` with
`daemon_threads = True` is unbounded. `core_manager.py:75` reloads Whisper per
`/voice` request.
*Impact:* trivial memory-exhaustion DoS; amplified by per-request model load.
*Fix:* body cap, token-bucket rate limit, bounded pool, cached transcriber.

### TD-08 `Config/system_config.json` is git-tracked and holds a user-editable token field
`Config/system_config.json` (tracked; `.gitignore` only has `Config/tts_models/`)
Worktree file is 607 bytes of live configuration against a 0-byte HEAD blob.
*Impact:* the current `remote_server.token` value is **empty** (verified), so no
secret is exposed today. The risk is prospective — the first real token anyone
sets is one `git commit -a` from publication, and personal state (user name,
mic choice, TTS engine) leaks into every commit. `AGENTS.md`'s claim that
tokens live in gitignored files is currently false.
*Fix:* add `Config/*.json` to `.gitignore`, `git rm --cached` the three files,
ship a `.example.json`, and add a pre-commit check for a non-empty token.

---

## S2 — High

### TD-09 Config read rewrites the file; malformed config silently destroys settings
`Config/config.py:155-156`, `:152-153`
An 18-byte config grows to 603 bytes on a mere read. `{ this is not json ]]`
becomes `data = {}` and defaults are written over the user's file with no log
and no backup. `Config.load()` runs at import time (`:288`).
*Fix:* write only when the file is missing; back up before overwriting; log
loudly on parse failure.

### TD-10 `stop()` orphans queued futures
`Conversation/conversation_engine.py:90-95`, `:111`
`running` is cleared before the `None` sentinel is enqueued, and the loop checks
`while self.running.is_set()` first, so the sentinel is usually never consumed.
*Impact:* `RemoteServer:83` blocks the full `DEFAULT_TIMEOUT=20`; the GUI's
`add_done_callback` never fires; replies are silently lost.
*Fix:* drain and resolve every queued future with
`set_exception(RuntimeError("MAXIE is shutting down"))`, then `join(timeout=…)`.

### TD-11 `get_context(max_turns=0)` returns the whole table
`Memory/memory_database.py:194`
The guard is falsy-based. The `conversation` table is never pruned in production
and no query uses `created_at`.
*Fix:* `if max_turns is not None:` plus a retention sweep.

### TD-12 `migrate_json` stores the literal string `"True"`
`Memory/memory_database.py:226-228`
Booleans are stringified, so the value is lost; the live DB has four such rows,
and `recall_any("the")` will speak `"True"` back.
Runs on every `MemoryEngine.__init__` (`memory_engine.py:21`).
*Fix:* store the key as the value for bool entries; gate behind a one-shot
migration marker.

### TD-13 Dead `StateManager` prints on every transition
`Core/state_manager.py:18-20`
Zero production references, yet `Tests/state_test.py` instantiates it, so
`[STATE] …` pollutes stdout after the unittest summary. The tested class is not
the live one.
*Fix:* delete the class and `state_test.py`, and test the real `VoiceState`.

### TD-14 Dead `EventBus` has a callback-mutation hazard
`Core/event_bus.py:21-22`
`publish` iterates the live list, so a callback that subscribes skips later
callbacks; a raising callback aborts the rest. No unsubscribe, no dedup, no
lock. Zero production subscribers.
*Fix:* delete, or fix (copy list, isolate errors, add unsubscribe + lock) and
actually wire the GUI's 200 ms poll to it.

### TD-15 GUI `_auto_loop`: off-thread tkinter, 100% CPU spin, no mic lock
`Ui/gui.py:185-191`
`winfo_exists()` from a worker thread; `continue` with no sleep; no
`_talk_lock`. Zero test coverage.
**Status: CLOSED in the live GUI (uncommitted WIP at this write).** The loop
reads a plain `_alive` flag instead of `root.winfo_exists()`, sleeps 0.3 s
between empty listens, and shares `_talk_lock` with `_on_talk`. Covered by 11
tests in `Tests/gui_loop_test.py`.
*Fix:* sleep 0.2–0.5 s on empty, share the capture lock, drop the tk call from
the worker.

### TD-16 `Logger.instance()` check-then-set race
`Logs/logger.py:46-51`, `:20`
`setLevel` also runs before the handler guard at `:22`. Handlers execute on the
caller's thread, so a slow disk serialises the voice loop.
*Fix:* double-checked lock; move `setLevel` after the guard; consider a
`QueueHandler`.

**Status: CLOSED (2026-09-30, Phase 18 batch).** `Logger.instance()` now uses a
module-level `_instance_lock` with double-checked locking; a 10-thread
first-call barrier test proves exactly one instance (`Tests/logger_test.py`).

### TD-17 Full user utterances logged three times, files are `0777`
`Brain/brain_router.py:44`, `Conversation/conversation_engine.py:149`, `:218`
235 utterances confirmed in `Logs/maxie.log`; the same text is persisted forever
in SQLite and pushed to the phone. `ls -la Logs/` shows `-rwxrwxrwx`.
*Fix:* hash/length at INFO, content at DEBUG behind a flag, `chmod 0600`, add a
retention sweep.

**Status: CLOSED (2026-09-30).** All three parts:
1. `0600` on every `Logger` construction (owner-only; the dev share ignores
   POSIX modes so that check self-skips there).
2. `Logger.utterance()` replaces plaintext with `<N chars #digest>` at the
   three log sites (`Brain/brain_router.py` router/auto-learn/clarify lines,
   `Voice/barge_in_listener.py` barge-in lines); plaintext only when
   `logging.log_utterances: true` is set explicitly for debugging.
3. `Logger.sweep()` deletes rotated `maxie.log.N` files older than
   `logging.retention_days` (default 7) and runs once per `Maxie` start.

Note the pre-existing `Logs/maxie.log` still holds the historical plaintext;
rotate or delete it once. Covered by `Tests/logger_test.py` (11 new cases) and
`Tests/system_test.py::LogRedactionTest`, fail-first verified against the
pre-fix router line.

---

## S3 — Medium

### TD-18 `search()` LIKE metacharacters unescaped
`Memory/memory_database.py:150` — `search("%")` and `search("_")` return every
row. Escape and add `ESCAPE '\'`.

### TD-19 `any_recall` produces confident wrong answers
`Memory/memory_database.py:113`, `:104`; `Memory/memory_engine.py:36-38`
Substring scoring with `len(w) > 2` admits `"the"`. Probe:
`any_recall("tell me about the institute")` → `{"key": "college", "value":
"Loyola Institute of Technology", "score": 1}`, matched on the stopword alone.
*Fix:* word-boundary regex, stopword list, IDF weighting, minimum score.

### TD-20 Non-timing-safe token comparison
`Interface/remote_server.py:61` — use `hmac.compare_digest`.

### TD-21 Internal exception strings disclosed to clients
`Interface/remote_server.py:75`, `:296`, `:304`; `AI/ollama_client.py:74`
Errors are echoed to the caller, `ollama_client` leaks the internal URL, and
`/voice` returns HTTP **200** with `ok: True` spliced next to `{"error": ...}`.
*Fix:* generic client message, full detail to the log, correct status codes.

### TD-22 `Maxie.shutdown()` has no error handling
`Core/core_manager.py:114-128` — one raise orphans every remaining resource.
Wrap each step with `contextlib.suppress` and per-step logging.

**Status: CLOSED (2026-09-30, Phase 18 batch).** Teardown is a named-step loop
with per-step `try/except` + logging; one failing subsystem no longer orphans
the rest (`Tests/shutdown_test.py`).

### TD-23 Blocking network I/O inside a signal handler
`Core/core_manager.py:95-98` → `Interface/remote_server.py:122`
`self._server.shutdown()` blocks on the `serve_forever` thread: deadlock risk and
not async-signal-safe. `raise SystemExit(0)` is already redundant
(`run.py:42-44`).
*Fix:* set a flag or write to a self-pipe and let the main loop exit.

**Status: CLOSED (2026-09-30, Phase 18 batch).** `_handle_signal` now logs and
`raise SystemExit(0)`; cleanup runs on the main thread via the `start()`/`run.py`
`finally`. Verified fail-first — the old direct-call handler failed the new
deferral test (`Tests/shutdown_test.py`).

### TD-24 `RemoteServer.start()`/`stop()` unsynchronised, thread never joined
`Interface/remote_server.py:95`, `:127-128`
Fields are cleared without a lock or `join()`; concurrent start/stop can
double-bind or leak the `serve_forever` thread. `MAXIE-RemoteTTS` /
`MAXIE-TTS` threads are never tracked (`conversation_engine.py:160`, `:315`).

### TD-25 `shutdown()` is not thread-safe
`Core/core_manager.py:115-117` — non-atomic check-then-set; two shutdown paths
can both proceed.

**Status: CLOSED (2026-09-30, Phase 18 batch).** A `_shutdown_lock` guards the
`shutting_down` flag and a single teardown pass; double `shutdown()` calls are
idempotent (`Tests/shutdown_test.py`).

### TD-26 `Config.set_audio` duplicates the write path and skips re-sync
`Config/config.py:219-228` inlines `json.dump(..., default=str)` (missing
`ensure_ascii=False`) and, unlike `set()` (`:199`), never calls `load(force=True)`,
leaving `cls.data` and disk divergent.

**Status: CLOSED (2026-09-30, Phase 18 batch).** `set_audio` now uses the shared
`_save_file` write path (`ensure_ascii=False`) followed by `cls.load(force=True)`;
`Tests/config_test.py::ConfigWriteSyncTest` proves disk↔memory stay in sync and
unicode survives a round-trip.

### TD-27 No schema validation anywhere
`Config/config.py:167-179`; `Core/core_manager.py:56`
A bad `port` surfaces as a raw `ValueError` outside any `try` in `run.py:35`, so
the user gets a traceback instead of the intended friendly message.

**Status: CLOSED (2026-09-30).** `Config.SCHEMA` declares type + bounds for
every hand-editable tunable; `Config.validate()` coerces unambiguous
wrong-type values (`"8778"` → `8778`) and raises `ConfigError` naming the exact
setting for anything out of range or uncoercible. `load()` calls it, and
`run.py` turns it into one readable line plus exit code 2. Covered by
`Tests/config_test.py::ConfigValidationTest` and `Tests/launcher_test.py`; the
launcher cases fail against the old traceback path.

### TD-28 `BargeInListener` leaked on the exception path
`Conversation/conversation_engine.py:366-372`
`_cleanup_voice` sits after the `while` loop and is unreachable from any failing
iteration.

### TD-29 `MAXIE_REVIEW/` is a stale full duplicate of the codebase
Repo-root `MAXIE_REVIEW/` mirrors every source file, including its own `Tests/`.
It doubles the search surface, guarantees drift, and `Tests/run_tests.py`
discovery may pick up both copies. **This is the one item here that is a
deliverable rather than a bug — it was requested. Flagged so the audit trail is
complete.**

### TD-30 Barge-in drops legitimate interrupts
`Voice/barge_in_listener.py:197-200`; `Conversation/conversation_engine.py:294-306`
The `>2.2 s` echo guard rejects *any* longer utterance, so "stop, actually what
time is it" never interrupts. The `while is_speaking()` check at `:294` precedes
`was_interrupted()` at `:298`, and the `finally` at `:304-306` unconditionally
kills the listener, destroying an interrupt arriving in the final 30 ms. Two
divergent stop-phrase sets (`:29-41` vs `Voice/voice_commands.py:13-28`)
contradict the "single source of truth" claim in `voice_commands.py:1-7`.

### TD-31 `voice.wav` CWD collision and leaked PortAudio streams
`Voice/speech_pipeline.py:19` writes a **relative** path and never deletes it,
violating `AGENTS.md`'s own path convention. `Ui/gui.py:150` vs `:185-191` can
open two `InputStream`s on one device. `audio_recorder.py:110-113` leaks a handle
whenever `start()` fails.
**Partially CLOSED:** `audio_recorder.py` now closes the stream when `start()`
fails (commit `7dc99b4`, covered by `Tests/recorder_deadline_test.py`). The GUI
double-stream half is closed by the shared-lock work in TD-04. The relative
`voice.wav` path is **still open**.

### TD-32 `VoiceState.PROCESSING` latches; the state machine is not a machine
`Voice/voice_manager.py:29`; `Core/state_manager.py` (dead)
No transition table, no guard, lock-free attribute written by three threads.
Any empty listen leaves the GUI showing "Thinking…" forever.
**Status: CLOSED in the live WIP.** The dead `Core/state_manager.py` was
removed; `VoiceStateMachine` validates every transition with two-way
capture/playback exclusion; `ConversationEngine` closes every turn in a
`finally` with `end_turn()`, which refuses to clobber a live capture. Covered by
`Tests/state_test.py` and `Tests/conversation_state_test.py`.

### TD-33 TTS/thread lifetime problems
`Voice/voice_engine.py:441-448`, `:474-484`, `:414-458`, `:523-524`
`_stop_signal` is set and never read, so the pyttsx3 worker is unkillable
(`:447` is unreachable); `done.wait()` at `:480` has no timeout, leaking a
thread per speak; `_ensure_pytts` is unsynchronised around non-thread-safe
`pyttsx3.init()`; `shutdown()` joins nothing. `_detect_engine:61-64` also
bypasses readiness, so a forced-but-missing engine reports itself available —
**which is the live on-disk state** (`"tts_engine": "piper"`,
`"piper_voice": "xyz"`).

---

## S4 — Low / dead code

| ID | Location | Issue |
|---|---|---|
| TD-34 | `AI/ollama_client.py:28-33` | `is_available()` has zero callers — the only health check is dead. |
| TD-35 | `Config/config.py:106` | `LOGGER = None`, never read. |
| TD-36 | `Memory/memory_database.py:234-235` | `get_database()` has zero callers; speculative re-export. |
| TD-37 | `Config/config.py:283-285` | `Config.which` is a bare `shutil.which` passthrough, used 20×. |
| TD-38 | `Interface/remote_server.py:20` | `"" in LOOPBACK_HOSTS` is unreachable. |
| TD-39 | `Interface/remote_server.py:315-328` | `_ui_cache` is a class attribute with a racy double-read. |
| TD-40 | `Memory/memory_engine.py:30-31`; `memory_database.py:80-81` | `update` silently drops `kind`, reclassifying notes as facts. |
| TD-41 | `Memory/memory_engine.py:71-73` | First-5-words key derivation collides; last-write-wins with no audit. |
| TD-42 | `Config/config.py:155`, `:169` | `dict(defaults)` shallow copy aliases nested class attributes; `set_audio:222-223` mutates them. |
| TD-43 | `Interface/remote_server.py:283-284`, `:320` | `os`/`tempfile` imported inside methods. |
| TD-44 | `Ui/gui.py:12-17` | `_load_autostart` uses `exec_module` on every construction, bypassing the import cache. |
| TD-45 | `Conversation/conversation_engine.py:131-143` vs `:249-261` | Exit logic duplicated and already drifted. |
| TD-46 | `remote_server.py:21`; `conversation_engine.py:287,293,303`; `gui.py:135,185,241` | Magic numbers not in `Config` while every other tunable is. |
| TD-47 | `Logs/logger.py` | No `shutdown()`/`flush()`; `RotatingFileHandler` never closed. **CLOSED (2026-09-30):** `Logger.shutdown()` flushes, closes handlers and clears the singleton; `instance()` self-heals (`Tests/logger_test.py`). |

---

## Vacuous / weak tests found during the audit

These are test-side debt, not code debt, but they hid real bugs:

- `Tests/learning_test.py:68` — `assertGreaterEqual(x is not None, True)` is
  `assertGreaterEqual(True, True)`; it passes whether or not recall works.
- `Tests/config_test.py:29-32` — hardcodes `Config.ASSISTANT_NAME == "Maxie"`
  and `USER_NAME == "Alwin"`, duplicating `DEFAULT_SYSTEM` and breaking on any
  legitimate rename.
- `Tests/state_test.py` — tests the dead `StateManager` and *enshrines* the
  stray `print` as acceptable.
- `Tests/ui_test.py` — 8 tests, **0** for `MaxieGUI`; `test_import_gui_is_safe`
  is literally `import Ui.gui  # noqa: F401`.
- `Tests/tts_test.py:87-107` — piper path is fully mocked end-to-end and never
  touches real synthesis or playback.
- `Tests/tts_test.py:150-160` — this test **writes** `"piper_voice": "xyz"` and
  `"tts_engine": "piper"` into the live `Config/audio_config.json`, i.e. the
  suite mutates the developer's real configuration.
