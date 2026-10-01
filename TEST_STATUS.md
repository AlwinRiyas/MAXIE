# MAXIE — TEST STATUS

**Baseline recorded:** 2026-09-28, headless Linux dev box, Python 3.14.7.
**Updated:** 2026-10-01 (home automation, dead-code removal, TD-28, SEC-07).

**Current:** **678 tests across 39 files, OK (skipped=2)**, ~44 s, clean exit.
Numbers below that predate this update are marked with the date they were
recorded; do not read them as current.

---

## 1. Baseline result

```
$ python -m compileall -q .
(exit 0)

$ python Tests/run_tests.py
Ran 678 tests in 44.1s
OK (skipped=2)
(exit 0)
```

| Metric | Value |
|---|---|
| Tests discovered | **678** |
| Passed | 676 |
| Failed | 0 |
| Skipped | 2 |
| Errors | 0 |
| Wall time | ~40 s |
| Suites | 39 files under `Tests/` |

**Skipped (2)**, both environment guards rather than missing tests:

- `Tests/audio_stream_test.AudioStreamTest.test_stream_start_stop` —
  `requires sounddevice`, which is not installed on this box.
- `Tests/logger_test.LoggerLifecycleTest.test_log_file_is_owner_only` —
  `filesystem does not honour POSIX permissions` (the mount here is exFAT/NTFS,
  so `chmod 0600` cannot be asserted).

### Correction to previous claims

`DEVELOPMENT_STATUS.md` previously stated **90 tests**. The real count at the
time was **208**; it is **678** now. The stale figure has been corrected, and
all four status documents now agree on one number.

---

## 1a. Changes to the baseline (2026-09-28 .. 2026-10-01)

| Change | Before | After |
|---|---|---|
| Test count | 139 | **678** |
| `Config/audio_config.json` after a suite run | **mutated** — `tts_engine` forced to `piper`, `piper_voice` to `xyz` | **untouched** |

`Tests/tts_test.py::InstallerConfigTest` now redirects `Config.FILES` to a
temporary directory for its duration, and
`test_set_audio_does_not_touch_live_config` asserts the live config file is
byte-identical before and after `Config.set_audio`.

**Both directions verified.** Simulating the pre-fix test (no path isolation)
made the new guard **fail** and mutated the live file; with the fix in place the
suite leaves the live config unchanged.

### Wave 1 additions (2026-09-29, commits `030c9e2`, `7dc99b4`)

| Suite | Tests | Guards |
|---|---|---|
| `Tests/tts_cancel_test.py` | 10 | TD-01 (cancel during synth), TD-02 (`_speaking` latch), **Piper success-path playback** |
| `Tests/recorder_deadline_test.py` | 5 | TD-03 wall-clock deadline, failed-`start()` stream close |
| `Tests/state_test.py` (replaces dead `Core/state_manager` tests) | 34 | transition table, capture↔playback exclusion, atomic reservation |
| `Tests/conversation_state_test.py` | 12 | turn→IDLE, THINKING mid-route, live-capture vs `end_turn()`, remote reservation |
| `Tests/gui_loop_test.py` | 11 | TD-15 (no spin, no off-thread tkinter), TD-04 shared mic lock |

**Regression directions verified:** the six TTS cancellation tests and the five
recorder deadline tests fail against the reconstructed pre-fix source; the Piper
success-playback test fails when the `_play_audio` call is removed; the state
tests fail against the old four-value `VoiceState` (no `THINKING`, no
`reserve_*`, always-IDLE `listen()`).

**Determinism fixes:** `Tests/system_test.py::test_greeting` no longer asserts
`startswith("Good")` (it failed every evening after 22:00); `Tests/learning_test.py`
now mocks the Ollama client so the suite never blocks on a slow local model;
the GUI-loop tests tear down their daemon threads so interpreter shutdown is
instant.

### Wave 2 additions (2026-09-30 .. 2026-10-01)

| Suite | Tests | Guards |
|---|---|---|
| `Tests/remote_server_test.py` | 33 | TD-07/SEC-05 body caps, generic error bodies, `X-MAXIE-Request-Id`, thread ceiling, `/voice` wiring |
| `Tests/smart_mode_test.py` | 20 | SEC-07 model-proposal gate, schema validation, routing modes |
| `Tests/agent_test.py` | 57 | 12.2-12.5 planning, iteration/steps ceiling, loop detection, rollback |
| `Tests/skill_schema_test.py` | 32 | 12.7 schemas, `execute_args`, tool rendering, destructive tools withheld |
| `Tests/config_test.py` | 30 | TD-27 `Config.SCHEMA` validation, write-on-missing, malformed backup, deep-merge |
| `Tests/context_summary_test.py` | 30 | running summary, non-destructive summarisation, `assistant`-role summary row |
| `Tests/home_test.py` | 96 | registry, HA/Hue adapters, router intent ordering, confirmation gate, compensating action, capability gate |
| `Tests/shutdown_test.py` | 6 | TD-16/22/23 idempotent `Maxie.shutdown()`, signal deferral |
| `Tests/transcriber_test.py` | 4 | TD-06 retry-not-latch, shared cached model |
| `Tests/vad_test.py` | 8 | TD-05 ratio calibration against the config-derived threshold |
| `Tests/ollama_client_test.py` | 19 | real client paths: timeouts, `raise_for_status`, offline classification |
| `Tests/barge_in_test.py`, `Tests/microphone_capture_test.py` | 18 | echo gate, echo cooldown, capture↔playback exclusion |
| `Tests/tts_test.py`, `Tests/tts_cancel_test.py` | 23 | TD-01/TD-02 cancellation and `_speaking` latch |
| `Tests/state_test.py` | 34 | live `VoiceStateMachine` (the dead `Core/state_manager` tests are gone) |
| `Tests/conversation_state_test.py` | 18 | TD-28 text-mode listener leak, TD-32 turn lifecycle |
| `Tests/permissions_test.py` | 14 | SEC-07 capability declaration and the fail-closed default |
| `Tests/repo_hygiene_test.py` | 14 | SEC-02 durability: nothing live, secret-shaped or ignored-but-tracked is committed |
| `Tests/logger_test.py` | 15 | TD-17 `0600` log, `<N chars #digest>` utterance redaction, rotation sweep |

**Removed:** `Tests/event_test.py` (4 tests) with `Core/event_bus.py`, along
with `Tests/state_test.py`'s 3 dead-class tests. Net coverage still rose
(208 -> 678) because the deleted tests guarded code that had no production
caller; keeping them would have meant keeping the modules alive.

## 2. Environment and optional dependencies

| Dependency | State here | Effect |
|---|---|---|
| `requests`, `numpy`, `psutil`, `tkinter`, `PIL` | present | full test surface available |
| `sounddevice` | **absent** | audio stream tests skipped; live mic/speaker UNVERIFIED |
| `faster_whisper` | **absent** | transcriber exercised only through fakes |
| `silero_vad`, `torch` | **absent** | VAD tested on the energy fallback path only |
| `edge_tts` | **absent** | Edge TTS never synthesises |
| `pyttsx3` | **absent** | pyttsx3 worker logic untestable here |
| `pyautogui` | **absent** | desktop skills untested |
| `ollama` | installed (`/usr/local/bin/ollama`, client 0.34.4); server was started locally and `llama3.2:3b` pulled | LLM tests still use fakes; **no test exercises the real client** |

Optional deps are imported lazily/fenced, which is why the suite runs headless.
That is a genuine strength and should be preserved.

---

## 3. Coverage matrix

Re-derived from source and suite names on 2026-10-01. The previous version of
this table predated roughly 470 of the 678 tests and described modules that
have since been deleted.

Legend: **A** = substantive coverage · **B** = partial · **C** = no coverage

| Module | Suite | Grade | Real coverage of the risk that matters |
|---|---|---|---|
| `Voice/vad_engine.py` | `vad_test.py` | **B** | 8 tests: silence/loud/short-clip/512-block gate, noise-floor calibration, a real-room speech ratio, and the config-derived default. TD-05 is now covered; Silero itself still is not. |
| `Voice/audio_recorder.py` | `microphone_capture_test.py`, `recorder_deadline_test.py` | **B** | 18 tests: backend-open failure, stream closed when `start()` fails, block reading and dry-out, gain clamping, `record()` to WAV, and the TD-03 wall-clock deadline. Real hardware untested. |
| `Voice/microphone_capture.py` | `microphone_capture_test.py` | **B** | Stream close ordering, `recover()` re-open and exhaustion, gain boost. Backend is mocked. |
| `Voice/voice_engine.py` | `tts_test.py`, `tts_cancel_test.py` | **B** | 23 tests: engine selection, TD-01 cancel-during-synthesis never plays, TD-02 `_speaking` latch cleared on every failure path, daemon watchdog. Synthesis is fully mocked. |
| `Voice/barge_in_listener.py` | `barge_in_test.py` | **B** | 6 tests: stop-phrase single source of truth, long-utterance rules, mid-sentence stop ignored, safe after a start failure. Echo behaviour itself is unverified on hardware. |
| `Voice/transcriber.py` | `transcriber_test.py` | **B** | 4 tests: TD-06 retry-not-latch, `available` reflects the loaded model, shared instance caching. `faster_whisper` is not installed. |
| `Voice/speech_pipeline.py` | `speech_pipeline_test.py` | **B** | 1 test: temp WAV is written and removed. **Thin — one test for the whole module.** |
| `Voice/voice_manager.py`, `voice_state.py` | `state_test.py`, `conversation_state_test.py` | **A** | 52 tests: full transition table, capture↔playback exclusion, atomic reservations, turn→IDLE, live-capture vs `end_turn()`, remote reply refused while capturing. |
| `AI/ollama_client.py` | `ollama_client_test.py` | **A** | 19 tests against mocked `requests`: JSON mode, fence stripping, retry/backoff on 503, timeout, generic-error collapse, `is_available`, and that failure messages never leak the internal URL. |
| `AI/ai_engine.py` | `ai_test.py`, `context_summary_test.py` | **A** | 49 tests: context assembly, summarisation, and `_is_offline_message` for all four failure strings (the B1 defect). |
| `Memory/memory_database.py` | `memory_test.py`, `context_summary_test.py` | **B** | 44 tests: LIKE escaping, IDF recall, `get_context(0)`, bool migration, summary rows, `kind` preservation, sha1 content hash. **Concurrency still untested** (probed 86% loss). |
| `Brain/brain_router.py` | `learning_test.py`, `system_test.py`, `smart_mode_test.py`, `home_test.py` | **A** | 177 tests across router intents, auto-learn isolation, bulk-wipe confirmation, smart-mode proposal gate, and home dispatch. One vacuous assertion remains (§5). |
| `Interface/remote_server.py` | `remote_server_test.py`, `ui_test.py` | **A** | 42 tests: body caps, generic error bodies, `X-MAXIE-Request-Id`, thread ceiling, `/voice`, mobile tap-to-talk page. LAN binding is exercised only for the fail-closed case. |
| `Ui/gui.py` | `gui_loop_test.py`, `ui_test.py` | **B** | 20 tests: 11 real `MaxieGUI` methods (no spin, no off-thread tkinter, shared mic lock), autostart helper. Tkinter needs a display for the rest. |
| `Config/config.py` | `config_test.py`, `launcher_test.py` | **A** | 33 tests: TD-27 `SCHEMA` bounds validation, write-only-when-missing, malformed backup, `deep_merge`, `set_audio` isolation, bad setting exits 2. |
| `Core/core_manager.py` | `shutdown_test.py`, `system_test.py` | **B** | 6 lifecycle tests: idempotent `shutdown()`, one teardown failure does not orphan the rest, signal handler defers to the main thread. |
| `Conversation/conversation_engine.py` | `conversation_state_test.py` | **B** | 18 tests: turn lifecycle, remote worker, `stop()` during an in-flight command, TD-28 text-mode listener leak. |
| `Logs/logger.py` | `logger_test.py` | **A** | 15 tests: race-free `instance()`, `shutdown()`/flush, TD-17 `0600` file, `<N chars #digest>` redaction, plaintext only when opted in, retention sweep. |
| `Security/permissions.py` | `permissions_test.py` | **A** | 14 tests: SEC-07 capability declaration, derived `DESTRUCTIVE`, fail-closed on an undeclared allowlisted intent, confirmation text that never claims to have executed. |
| `Skills/skill_schema.py` | `skill_schema_test.py`, `agent_test.py` | **A** | 89 tests: schema validation, `execute_args`, tool rendering, destructive tools withheld, 12.2-12.5 planning with rollback. |
| `Home/*` | `home_test.py` | **A** | 96 tests: registry longest-match, HA/Hue adapters, live toggle, lock gate, compensating action, structured dispatch. **All backends are fakes.** |
| `Skills/*` (device control) | `device_skills_test.py`, `calculator_test.py`, `web_search_test.py` | **B** | 28 tests. Adversarial calculator expressions remain untested. |
| ~~`Core/event_bus.py`~~ | — | — | **DELETED 2026-10-01** (TD-14) with its test file: it had zero production subscribers. |
| ~~`Core/state_manager.py`~~ | — | — | **DELETED 2026-09-29**; `Tests/state_test.py` now covers the live `VoiceStateMachine`. |

**Still C (no suite):** the real Piper/Edge `piper` binary invocation, Silero VAD
(only the energy fallback is tested), and `pyttsx3` (not installed here).

---

## 4. The most important remaining gap

**Partly closed.** This section used to say that no test asserted the
assistant survives a failing turn. That is no longer true:

- `Tests/conversation_state_test.py::HandleCommandTurnTest` asserts a raising
  skill still closes the turn (state returns to IDLE) instead of stranding the
  GUI on "Thinking..." — TD-32.
- `Tests/conversation_state_test.py::TextModeCleanupTest` asserts a raising
  text-mode command does not leak the barge-in listener — TD-28.
- `Tests/gui_loop_test.py::test_auto_loop_survives_listen_errors` asserts a
  failing mic read is surfaced in the log and the auto-listen thread does not
  die.
- `Tests/shutdown_test.py::test_one_teardown_failure_does_not_orphan_the_rest`
  asserts one broken teardown step does not prevent the others.

**What is still missing.** Those tests prove the *loops* survive; none drives a
full `Maxie` process through a failing turn and then a good one, with the real
router and real skills. The gap is an end-to-end reliability test, not a unit
test, and it is the thing I would write next.

Second structural gap, now **closed for the database**: TD-48 found 70% row loss
under four threads, which is now fixed by an `_synchronized`/`RLock` wrapper on
every `MemoryDatabase` method and covered by
`test_concurrent_writes_do_not_lose_rows`. Still no concurrency test for
`RemoteServer.start()`/`stop()` (TD-24), and `add_context` + auto-learn still
have no mixed read/write stress.

---

## 5. Weak or vacuous tests

| Test | Problem |
|---|---|
| `Tests/learning_test.py:158` | `assertGreaterEqual(engine.recall_any(...) is not None, True)` reduces to `assertGreaterEqual(True, True)` — **still passes whether or not recall works.** Not yet fixed. |
| `Tests/config_test.py:35-36` | Hardcodes `ASSISTANT_NAME == "Maxie"` / `USER_NAME == "Alwin"`, duplicating `DEFAULT_SYSTEM`; breaks on a legitimate rename and hides an accidental one. Still open. |
| ~~`Tests/state_test.py`~~ | **FIXED.** Was 3 tests on the dead `Core/state_manager`; it now covers the live `VoiceStateMachine` (34 tests) and the stray `[STATE] …` print went with the deleted class. |
| `Tests/ui_test.py` | `test_import_gui_is_safe` is still literally `import Ui.gui  # noqa: F401`, but it is no longer the only GUI coverage — `Tests/gui_loop_test.py` exercises 11 real `MaxieGUI` methods. |
| `Tests/tts_test.py:87-107` | Piper synth + play fully mocked; never touches real synthesis or playback. |
| `Memory/memory.json` was tracked | **FIXED 2026-10-01.** It was in `.gitignore` from the start and committed anyway in three commits, carrying real facts. `.gitignore` does not untrack. Now untracked, with `repo_hygiene_test.py::test_no_ignored_file_is_still_tracked` preventing a repeat. Still in history — purging needs a force-push (owner's call). |
| `Tests/tts_test.py:150-160` | **FIXED 2026-09-28.** It mutated the developer's live config, writing `"tts_engine": "piper"` and `"piper_voice": "xyz"` into `Config/audio_config.json`. `InstallerConfigTest` now isolates `Config.FILES` to a temp dir and a guard test asserts the live file is unchanged. |

---

## 6. Hardware verification status

| Capability | Status |
|---|---|
| Microphone capture | **HARDWARE UNVERIFIED** — no `sounddevice` on this box |
| Speaker playback | **HARDWARE UNVERIFIED** |
| Piper / Edge TTS real synthesis | **HARDWARE UNVERIFIED** — mocked only |
| faster-whisper real transcription | **UNVERIFIED** — client not installed |
| Silero VAD | **UNVERIFIED** — only the energy fallback is tested |
| Barge-in / echo cancellation | **UNVERIFIED** — 6 logic tests (`barge_in_test.py`) cover stop-phrase decoding; **no acoustic test and no real mic** |
| Physical wake-word spotting | **MISSING** — `WakeWord/wake_word_engine.py` is a 1-line substring test (`"hey maxie" in text.lower()`) applied *after* transcription. 3 tests cover that string match, not spotting. |
| LAN remote access | **PARTIAL** — loopback tested; LAN binding exercised only for the fail-closed case |
| Ollama round trip | **UNVERIFIED** by tests — 19 tests mock `requests`; no test drives a live local server |
| Home Assistant / Hue hubs | **HARDWARE UNVERIFIED** — 96 tests use fake backends. `Installers/check_home.py` exists to exercise a real hub but has never been run against one. |

Hardware results must be filled in from the actual laptop, not inferred.

---

## 7. Priority test work

Re-checked against the suite on 2026-10-01. Most of the original list is now
done; the entries below are the ones with **no equivalent test**, checked by
name and by searching for the behaviour under other names.

**Done since the original list** (kept for the record, with the test that
replaced each item):

| Original item | Now covered by |
|---|---|
| 1. TTS cancel never plays | `tts_cancel_test.py::test_play_audio_refuses_when_cancelled` |
| 2. TTS failure clears `_speaking` | `tts_cancel_test.py::test_piper_cancel_clears_speaking_flag`, `test_edge_failure_clears_speaking_flag` |
| 3. Recorder returns on stall | `recorder_deadline_test.py::test_deadline_derived_from_config_not_hardcoded` |
| 4. Voice body cap + CORS | `remote_server_test.py::test_voice_body_rejected…`, `test_cors_wildcard_never_emitted` |
| 6. Offline strings never persist | `ai_test.py::test_offline_failure_not_persisted` |
| 9. Bool migration preserved | `memory_test.py::test_migrate_json_bool_entries_store_value_not_True` |
| 10. Recall ignores stopwords | `memory_test.py::test_stopword_only_query_returns_none` |
| 11. Read does not rewrite / malformed backed up | `config_test.py::test_read_does_not_rewrite_a_valid_file`, `test_malformed_config_is_not_silently_destroyed` |
| 12. `stop()` resolves queued futures | `conversation_state_test.py` (in-flight remote command) |
| 13. GUI auto-loop respects the capture lock | `gui_loop_test.py::test_auto_loop_refuses_to_capture_while_lock_held` |
| 14. Bearer auth | `ui_test.py::test_bearer_auth_accepted`, `test_the_session_sends_the_token_as_a_bearer_header` |
| 15. Tests do not mutate config | `config_test.py::InstallerConfigTest` + the byte-identical guard |

**Still genuinely missing, in the order I would write them:**

**Done 2026-10-01:**

| Item | Now covered by |
|---|---|
| 1. `test_token_not_git_tracked` | `Tests/repo_hygiene_test.py` (14 tests). It also caught `Memory/memory.json` being tracked in three commits despite an ignore rule — see §5. |
| 2. `test_memory_concurrent_writes` | `memory_test.py::test_concurrent_writes_do_not_lose_rows`. The probe found **70% loss**, not the 86% the register estimated, so it became TD-48 and was fixed. |

**Still missing, in the order I would write them:**

1. **`test_assistant_survives_failing_turn`** — end-to-end: real `Maxie`, real
   router, one failing skill, then a good command. The loop-level survival is
   covered (§4); the process-level version is not.
2. **Adversarial calculator expressions** — `calculator_test.py` covers the AST
   allowlist's happy path, not `__import__`, attribute chains, or walrus.
3. **`RemoteServer.start()`/`stop()` concurrency** — TD-24 is still open and has
   no test; a double-bind or a leaked `serve_forever` thread would pass the suite.
4. **A real `pyttsx3` / `piper` subprocess test** — blocked on this box; these
   belong in the hardware pass, not the headless suite.
5. **Fix the two vacuous/fragile tests in §5** rather than add new ones.
