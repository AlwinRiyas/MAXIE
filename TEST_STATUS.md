# MAXIE — TEST STATUS

**Baseline recorded:** 2026-09-28, headless Linux dev box, Python 3.14.7.
**Updated:** 2026-09-29 (Wave 1 — TTS, recorder, state machine).

---

## 1. Baseline result

```
$ python -m compileall -q .
(exit 0)

$ python Tests/run_tests.py
Ran 208 tests in 12.7s
OK (skipped=1)
```

| Metric | Value |
|---|---|
| Tests discovered | 208 |
| Passed | 207 |
| Failed | 0 |
| Skipped | 1 |
| Errors | 0 |
| Wall time | ~13 s |
| Suites | 24 files under `Tests/` |

**Skipped:** `Tests/audio_stream_test.AudioStreamTest.test_stream_start_stop` —
`@unittest.skipUnless(AudioManager.is_available(), "requires sounddevice")`.
`sounddevice` is not installed here.

### Correction to previous claims

`DEVELOPMENT_STATUS.md` previously stated **90 tests**. The real count is **208**.
The stale figure has been corrected.

---

## 1a. Changes to the baseline (2026-09-28 .. 2026-09-29)

| Change | Before | After |
|---|---|---|
| Test count | 139 | **208** |
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
instant (~13 s total).

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

Legend: **A** = substantive coverage · **B** = smoke only · **C** = no coverage

| Module | Suite | Grade | Real coverage of the risk that matters |
|---|---|---|---|
| `Voice/vad_engine.py` | `vad_test.py` | **B** | Silence/loud/sub-512 paths only. **The `noise_floor * 3.0` branch (`:109`) — the TD-05 deadlock — is never meaningfully exercised.** |
| `Voice/audio_recorder.py` | — | **C** | The entire capture path: no test reaches `record()` or `_listen_loop`. |
| `Voice/voice_engine.py` | `tts_test.py` | **B** | Best-covered code in `Voice/`: player selection, engine detection, no-TTS paths. But synthesis is **fully mocked**, and `stop()`, `is_speaking()`, `_watch_process`, and every `_speaking` transition are untested. |
| `Voice/barge_in_listener.py` | — | **C** | 306 lines, **zero tests**. |
| `Voice/transcriber.py` | — | **C** | Zero tests; the one-shot `_loaded` latch (TD-06) is invisible. |
| `Voice/voice_manager.py`, `voice_state.py` | — | **C** | Zero tests. `Tests/state_test.py` covers the *dead* `Core/state_manager.py`. |
| `Voice/speech_pipeline.py` | — | **C** | Zero tests. |
| `AI/ollama_client.py` | — | **C** | **0% direct coverage.** No mocked `requests` for `ask`, `ask_generate`, timeouts, or `raise_for_status`. |
| `AI/ai_engine.py` | `ai_test.py` | **B** | 6 tests, all against a fake client that **never raises** and a fake memory that always returns `[]` — the fake *encodes the dead memory-injection path as correct*. `_is_offline_message` is never called by any test. |
| `Memory/memory_database.py` | `memory_test.py` | **B** | Single-threaded happy path. Concurrency (probed: 86% data loss), `get_context(0)`, `migrate_json`, `_best_match`, `any_recall`, `recall_for`, `search` metacharacters all untested. |
| `Brain/brain_router.py` | `learning_test.py` | **B** | 7 tests; one is **vacuous** (see §5). No false-positive, negation, boundary, or bulk-delete coverage. |
| `Interface/remote_server.py` | `remote_server_test.py` | **B** | 10 loopback tests. **`Authorization: Bearer` never exercised; CORS, body caps, rate limits, malformed bodies, concurrency, and stop-during-request all untested.** |
| `Ui/gui.py` | `ui_test.py` | **C** | 8 tests, **0 for `MaxieGUI`**. `test_import_gui_is_safe` is `import Ui.gui`. |
| `Config/config.py` | `config_test.py` | **B** | 6 `assertIn` smoke checks. `_deep_merge`, `set`, `set_audio`, `save`, malformed JSON, read-without-write, and the token-not-tracked question all untested. |
| `Core/event_bus.py` | `event_test.py` | **B** | 4 happy-path tests; a raising listener and a re-subscribing listener are untested. Module is dead anyway. |
| `Core/state_manager.py` | `state_test.py` | **B** | 3 tests on a dead class; **enshrines the stray `print`** and pollutes stdout after the summary. |
| `Core/core_manager.py` | — | **C** | **No test file exists.** Construction, fail-closed bind, `start`, `shutdown` idempotency, signal handlers, per-request `Transcriber` — all uncovered. |
| `Conversation/conversation_engine.py` | — | **C** | **No test file exists.** `submit_text`, the remote worker crash path, `stop()`'s orphaned futures, the 40 s deadline, echo cooldown — all uncovered. |
| `Logs/logger.py` | — | **C** | No test file. Rotation, redaction, file permissions unverified. |
| `Skills/calculator.py` | via `system_test`/`brain` | **B** | AST allowlist behaves; adversarial expressions untested. |
| `Security/permissions.py` | indirect | **B** | Confirmation round-trip works; no test that a *new* intent is default-denied. |

---

## 4. The single most important missing test

> **No test asserts that the assistant survives a failing turn.**

"One bad command must not end the session" is the core reliability property of
the product, and there is no test for it in any file. Every bug in
`TECHNICAL_DEBT.md` ships through a green suite because the suite is happy-path
only: no negative, adversarial, concurrency, or resource-lifecycle tests exist
anywhere in the project.

---

## 5. Weak or vacuous tests

| Test | Problem |
|---|---|
| `Tests/learning_test.py:68` | `assertGreaterEqual(engine.recall_any(...) is not None, True)` reduces to `assertGreaterEqual(True, True)` — **passes whether or not recall works.** |
| `Tests/config_test.py:29-32` | Hardcodes `ASSISTANT_NAME == "Maxie"` / `USER_NAME == "Alwin"`, duplicating `DEFAULT_SYSTEM`; breaks on a legitimate rename and hides an accidental one. |
| `Tests/state_test.py` | Tests a dead class, and its five `set_state` calls print `[STATE] …` into stdout **after** `Ran 138 tests / OK`. |
| `Tests/ui_test.py:133-134` | `import Ui.gui  # noqa: F401` — presented as GUI coverage. |
| `Tests/tts_test.py:87-107` | Piper synth + play fully mocked; never touches real synthesis or playback. |
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
| Barge-in / echo cancellation | **UNVERIFIED** — zero tests, and the structural mic-closed property is violated by the GUI path |
| Physical wake-word spotting | **MISSING** — `WakeWord/` is empty; live gate is a 4-line substring match |
| LAN remote access | **PARTIAL** — loopback tested; LAN binding exercised only for the fail-closed case |
| Ollama round trip | **UNVERIFIED** by tests — the service was started locally, but no test covers the real client |

Hardware results must be filled in from the actual laptop, not inferred.

---

## 7. Priority test work

Ordered by the bugs each test would have caught:

1. `test_speak_cancelled_during_synthesis_never_plays` — TD-01/R1.
2. `test_tts_failure_clears_speaking_flag` — TD-02/R2.
3. `test_record_returns_when_capture_stalls` — TD-03/R3.
4. `test_voice_body_rejected_above_cap` + `test_cors_not_wildcard` — SEC-01, SEC-03.
5. `test_token_not_git_tracked` (`git ls-files`) — SEC-02.
6. `test_offline_strings_never_persist` for all four failure strings — the B1 defect.
7. `test_assistant_survives_failing_turn` — §4.
8. `test_memory_concurrent_writes` (4 threads) — probed 86% loss.
9. `test_migrate_bool_preserves_sentence` — TD-12.
10. `test_any_recall_ignores_stopwords` — TD-19.
11. `test_config_read_does_not_rewrite_file`; `test_malformed_config_is_backed_up` — TD-09.
12. `test_stop_resolves_queued_futures` — TD-10.
13. `test_gui_auto_loop_respects_capture_lock` — TD-04.
14. `test_bearer_auth_path` — currently zero coverage of a live code path.
15. `test_tests_do_not_mutate_config` — §5.
