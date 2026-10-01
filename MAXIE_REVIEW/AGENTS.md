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
- No secrets in code. Tokens live in `Config/*.json` (gitignored where
  sensitive), never committed.

## Architecture (current)

```
main.py / run.py
 └── Core/core_manager.Maxie
     ├── VoiceEngine            TTS (piper neural offline -> edge online -> SAPI/espeak fallback)
     ├── VoiceManager           state machine + listen()
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