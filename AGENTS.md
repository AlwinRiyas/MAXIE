# AGENTS.md — MAXIE

Personal AI voice assistant. Cross-platform (Windows primary, Linux dev,
phone access via HTTP endpoint). Written in Python.

## Conventions

- Python 3.10+ (3.14 verified).
- Imports use absolute package names from project root (e.g. `from Brain...`).
- One class per module. Class names are nouns (`VoiceEngine`, `BrainRouter`).
- No `__init__` logic in `__init__.py` beyond docstring/`__all__`.
- Optional native/ML deps (sounddevice, torch, faster-whisper, silero-vad,
  pyttsx3) are imported lazily/fenced so the app and tests run headless.
- Every module that touches the platform (Windows vs Linux) branches explicitly.
- No secrets in code. Tokens live in `Config/*.json` and must never be committed.
  **Fixed 2026-09-28:** `.gitignore` now excludes `Config/*.json` (with
  `!Config/*.example.json`), and the three live config files were untracked via
  `git rm --cached`; example files are committed instead. The old
  `remote_server.token` value was empty, so nothing leaked, but the exposure was
  one `git commit -a` away.
- Tests must not mutate real user state. This was violated by
  `Tests/tts_test.py` and was **fixed 2026-09-28** (path isolation + a guard test);
  keep it that way when adding tests.
- Reading configuration must never write to disk. `Config/config.py:155-156`
  currently does, and a malformed file is silently overwritten with defaults.

## Architecture (current)

```
main.py / run.py
 └── Core/core_manager.Maxie
     ├── VoiceEngine            TTS (piper neural offline -> edge online -> SAPI/espeak fallback)
     ├── VoiceManager           live state facade over VoiceStateMachine
     ├── VoiceStateMachine      8 states, validated transitions, atomic capture↔playback reservations
     ├── AudioManager           microphone listing/selection (config-aware)
     ├── AudioRecorder          streaming VAD recorder (Silero, energy fallback)
     ├── SpeechPipeline         recorder -> Transcriber
     ├── Transcriber            faster-whisper (configurable model)
     ├── BargeInListener        STOP detection while speaking (echo-aware)
     ├── BrainRouter            routing: skills vs memory vs AI
     │   ├── IntentEngine
     │   ├── CommandCorrector
     │   ├── MemoryEngine (SQLite)
     │   └── AIEngine -> OllamaClient (provider abstraction + context)
├── SkillManager            registry of skills (allowed actions only)
     ├── ConversationEngine     main loop + stop/exit + remote worker thread
     └── RemoteServer           HTTP endpoint for phone/CLI control
```

`Core/event_bus.py` is **dead code** with zero production references. The old
`Core/state_manager.py` was **removed 2026-09-29**; `Tests/state_test.py` now
tests the live `VoiceStateMachine`. Do not treat `event_bus.py` as the real
event system.

Continuous learning: `BrainRouter._auto_learn()` silently persists
preference phrases ("i like/love/prefer", "my favorite", "i am
learning/studying") into SQLite; `MemoryDatabase.SYNONYMS` (reverse
mapped synonym clusters) lets "what do i enjoy / like?" recall the same
fact. Context persists across reboots (survives restart — no re-learning
needed after power off).

Device-control skills: `Skills/todo_skill.py` (JSON to-do list),
`Skills/media_controller.py` (play/pause/next/prev; Windows media keys via
ctypes, Linux playerctl), `Skills/phone_controller.py` (answer/reject
Android calls via ADB), `Skills/power_skill.py` (shutdown/restart after
explicit confirm), `Skills/youtube_skill.py` (YouTube search),
`Skills/recommendation_skill.py` (offline curated picks).

Desktop/remote surfaces:

- `Ui/gui.py` — tkinter control panel (`run.py --gui`): log/status,
  push-to-talk + auto-listen, quick chips, autostart toggle. It talks to
  the same `ConversationEngine` (log_callback, submit_text, listen_once)
  as the console and phone.
- `Installers/set_autostart.py` — enable/disable/status/test autostart
  (Windows registry Run key, Linux XDG autostart); targets
  `run.py --gui --minimized`.
- RemoteServer endpoints: `GET /ui` (public mobile tap-to-talk page,
  commands still token-checked), `GET/POST /command`,
  `POST /voice` (WAV -> laptop Transcriber -> reply; wired via
  `Maxie._handle_voice`).
- `Android/` — Siri-style Kotlin/Gradle client: foreground mic service
  with screen off, energy `WakeTrigger` (pluggable wake-word), WAV
  upload to `/voice`, TTS replies. Not compiled in this repo.

## Key commands

- Start MAXIE: `python run.py` (also `python main.py`).
- Desktop GUI: `python run.py --gui [--minimized]`; console `--console`.
- Auto-start: `python Installers/set_autostart.py enable|disable|status|test`.
- Natural voice: `python Installers/setup_tts.py [--engine piper|edge|espeak]`
  (PEP-668 OSes fall back to pipx automatically; models cache in
  `Config/tts_models/`, gitignored).
- Run test suite: `python Tests/run_tests.py`.
- Compile check: `python -m compileall -q .`
- Unit tests use `unittest`; the runner injects project root onto sys.path.

## Configuration

- `Config/config.py` -> loads `Config/system_config.json`, `Config/personality.json`,
  `Config/audio_config.json`; MISSING files are auto-created with defaults.
- Paths are computed from the project root, not hardcoded. Windows-specific
  app paths live in `Skills/app_database.json` (scanned from Start Menu on
  Windows; Linux uses `xdg-open`/PATH lookup).

## Security rules (critical)

- LLM output is NEVER executed. Execution only happens through allowlisted
  skills in `SkillManager` / `Security.permissions`.
- Remote server binds `127.0.0.1` by default; enabling LAN access requires an
  explicit token in config. Never bind to `0.0.0.0` without a token.
- Destructive actions (shutdown, restart) execute only after an explicit
  yes/confirm in the router; `POWER_*` never reach skills unconfirmed.
  Linux dev boxes additionally need `allow_local_power_control: true` in
  `Config/system_config.json` (default False). Delete/format stay
  confirm-or-refuse.
- TTS runs through a daemon thread with a watchdog timeout so a broken
  audio stack can never block phone replies or process exit.

## Known limitations

- Voice hardware cannot be verified on a headless dev box; `Tests/run_tests.py`
  covers logic-level tests. Run `python run.py` on the actual laptop to
  validate mic/speaker/TTS.
- Phone access: phone reaches laptop via `http://<laptop-ip>:8778`
  (see README, Remote Access section).
- Wake word is a lightweight text-gate; a true always-on spotting model is
  future work.
- Barge-in reliability depends on laptop mic quality; echo protection uses
  state gating + short-stop-phrase-only decoding + adaptive threshold.

## Audit documents (2026-09-28)

Read these before changing anything structural. All are at the repo root.

| Document | Contents |
|---|---|
| `ARCHITECTURE.md` | As-built system, verified against source |
| `GAP_ANALYSIS.md` | Target architecture vs current, stage by stage |
| `TECHNICAL_DEBT.md` | 47-item register with `file:line` and severity |
| `SECURITY_AUDIT.md` | Threat model, 14 findings, remediation order |
| `TEST_STATUS.md` | 208-test baseline, coverage matrix, hardware status |
| `OPEN_SOURCE_COMPARISON.md` | Leon / OpenVoiceOS / Rhasspy, what to adopt and reject |
| `ROADMAP.md` | 19 phases with subphases, in priority order |
| `DEVELOPMENT_STATUS.md` | Honest current state |
| `FINAL_AUDIT.md` | Not yet written — written only at completion |

`Docs/` contains several **0-byte placeholder** files (`ARCHITECTURE.md`,
`ROADMAP.md`, `API_REFERENCE.md`, `CHANGELOG.md`, `CODING_STANDARDS.md`). Do not
edit them; the canonical documents are at the root.

## Highest-risk known defects

Fix in this order; each is `file:line` referenced in `TECHNICAL_DEBT.md`.

**CLOSED 2026-09-29 — see `TECHNICAL_DEBT.md` / `TEST_STATUS.md` for the
commit and test evidence:**
- **TD-01 / TD-02** TTS cancellation + `_speaking` latch (commit `030c9e2`).
- **TD-03** recorder wall-clock deadline (commit `7dc99b4`).
- **TD-04 / TD-15 / TD-32** state machine, atomic capture↔playback
  reservations, and the GUI auto-listen lock (committed in the `bfb49cb` /
  `a4d7bf9` hardening batch; `git status` no longer shows them as WIP).
- **TD-16 / TD-22 / TD-23 / TD-25 / TD-26 / TD-47** lifecycle batch (Phase 18,
  2026-09-30): race-free `Logger.instance()` + `shutdown()`/flush; error-isolated,
  lock-guarded, idempotent `Maxie.shutdown()`; signal handler defers cleanup to
  the main thread; `set_audio` re-syncs disk↔memory. **TD-17 partial**: log file
  now owner-only `0600`; the 3× utterance logging remains.
- **B1** Ollama failure-string persistence (commit `bf7d978`): `_is_offline_message`
  classifies all four failure sources (connection/timeout/generic/empty) and
  nothing reaches stored context (`Tests/ai_test.py::OfflineFilteringTest`).
- **TD-07 / SEC-05** remote boundary (2026-09-30): all error bodies are generic
  with correct status codes, provider messages never leak the internal URL, and
  `_BoundedThreadingHTTPServer` caps live request threads
  (`remote_server.max_connections`, default 16).

- **TD-27** config schema validation — **CLOSED 2026-09-30**: `Config.SCHEMA`
  (type + bounds per tunable) is enforced by `Config.validate()` inside
  `load()`; a bad setting prints one line and exits 2 (`Tests/launcher_test.py`).
- **B1** Ollama failure-string persistence — **CLOSED** (`bf7d978`).

Still open, in priority order:
- **TD-08** / SEC-02 — `Config/*.json` is gitignored and untracked; the token
  field is empty today. The next real token must go only into the ignored
  file, never an example.
- **TD-17 remainder** — 3× plaintext utterance logging + retention sweep.
- **SEC-11 remainder** — request-id correlation and any second factor for
  destructive remote commands (rate limit + audit log are in).
- **TD-23 note** — signal-handler deferral is closed, but `run.py` still
  relies on the interpreter reaching its `finally`; a hard `SIGKILL` skips
  cleanup (accepted risk).

## Working rules for changes

- A bug fix ships with a test that **fails without the fix**. Verify both
  directions before claiming it is done.
- Never reduce the test count. Baseline is 341 passing, 2 skipped.
- `python Tests/run_tests.py` and `python -m compileall -q .` must both stay
  clean at the end of every change.
- Mark hardware-dependent results **HARDWARE UNVERIFIED** until run on the real
  laptop. Do not infer hardware behaviour from headless runs.
- All new tunables go in `Config`, not inline as magic numbers.
- Do not add a direct dependency without adding it to the lazy/fenced import
  pattern; the suite must keep running headless.
- When adding a skill, declare its capabilities and confirm that the
  confirmation gate covers destructive ones.
- Report files changed in full, with the real current content, and state the
  test evidence for each claim.