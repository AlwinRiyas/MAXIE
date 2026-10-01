# MAXIE Changelog

## v6.1 — Natural voice (permanently de-roboting MAXIE)

MAXIE's voice is no longer the robotic espeak/SAPI default on any
platform:

- **Piper neural voice (offline, default).** `python Installers/setup_tts.py`
  installs `piper-tts` (falls back through `pipx` automatically on
  PEP-668 / externally-managed systems), pulls the `en_US-lessac-medium`
  model (~60 MB) from Hugging Face into `Config/tts_models/` (gitignored)
  and writes `tts_engine: "piper"` + `piper_voice` into
  `Config/audio_config.json`.
- **Engine detection & fallback.** `tts_engine: auto` (the default) picks,
  in order: piper (model present + binary) → edge (Microsoft neural,
  online) → Windows SAPI / pyttsx / espeak — and degrades to a disabled
  no-op rather than robotic speech. `auto` now *actually detects* on the
  supported engines instead of always skipping to the system voice.
- **Independent player selection.** WAV files prefer `paplay`→`pw-play`→
  `aplay`, with `ffplay` last; other formats prefer `mpv`→`ffplay`→`vlc`.
  On Windows `SoundPlayer` for WAV, and any supported player for MP3.
  No audio toolkit, no player, no model → `.speak()` returns False and
  MAXIE keeps going (never a command blocker).
- `Config/audio_config.json` gained `tts_engine`, `piper_voice`,
  `edge_voice`, and a `tts_models/` gitignored dir. New config keys do
  not break older installations (safe defaults).
- 12 `tts_test.py` tests: silence/empty → graceful False, hear-through
  detection (piper+model/edge/espeak), Windows SoundPlayer + PowerShell,
  player menu selection per file type, and forced-piper-without-model
  never calls the synth. Full suite now **138 tests, 1 headless skip**.

---

# MAXIE Changelog (older)

## v1.0
- Project initialized

## v2.0
- Core Manager
- Conversation Engine
- Voice Engine
- Application Discovery

## v3.0
- Offline Speech Recognition
- Application Registry

## v4.0 — Refactor + feature-complete pipeline
- Streaming, VAD-driven audio recorder (Silero VAD with adaptive energy fallback)
- Transcribe via faster-whisper (configurable model / device / compute type)
- Echo-protected barge-in listener (stop phrase detection while speaking)
- Cross-platform TTS (Windows SAPI female voice, Linux pyttsx3/espeak female)
- Brain router: command corrector -> intent engine -> skills -> memory -> AI
- Intent engine + command corrector with app aliases and whisper corrections
- Ollama provider abstraction with configurable URL/model + short-term context
- Memory: SQLite (save/recall/search/delete/update + free-form notes + context)
- Skills: calculator, weather (configurable location), web search, volume,
  open-app / close-app (cross-platform), system info, screenshot, memory
- Security/permissions allowlist; destructive actions require confirmation
- Config system auto-creates JSON defaults from project root
- `run.py` unified entry point + `main.py` alias

## v5.0 — Completed assistant (Jarvis-style, female voice)
- Fixed startup blocker: `Brain/voice_commands.py` (stop/exit phrase gate)
- Remote mobile/CLI access: `Interface/remote_server.py` (stdlib HTTP,
  token auth, LAN binding fails closed) with instant-response worker thread
- Spoken math natural-language handling (percents, square roots, powers)
- Intent fixes: "12 times 8" no longer seen as time; "weather today" as weather
- FRIDAY/Jarvis persona: poised FEMALE system prompt + time-aware greeting
- Full `unittest` suite + `Tests/run_tests.py` runner (headless-safe, 90 cases)
- Cleanup: removed duplicate barge-in module and webrtcvad legacy file

## v5.1 — Device control & personal productivity
- To-do list skill (add/show/mark done/remove/clear) — text, voice, and phone
- Media control: play/pause/resume/stop, next & previous song (Windows media
  keys via ctypes; Linux playerctl)
- Phone calls over ADB: answer/reject from laptop (Android, USB/wireless);
  Windows best-effort answer key fallback
- Shutdown/restart now execute after an explicit yes/confirm; Linux dev
  machine protected by `allow_local_power_control` (default False)
- YouTube: "open youtube and search X", "play <song>" opens search results
- Recommendations: "give me a match" / movies / series / music / games
  (offline curated, no API key)
- Call/media/todo/recommendation intents + routing + allowlist (110 tests)
- Remote worker answers instantly even if TTS is slow; TTS guarded by a
  timeout watchdog so a broken audio stack can never block replies or exit

## v6.0 — Always on, continuous learning, GUI, and a Siri-style phone app
- **Continuous learning**: preference phrases ("i like", "i love", "my
  favorite", "i am learning"…) are captured silently and stay stored in
  SQLite, so MAXIE remembers you across reboots — no "remember that" needed
- Memory recall now uses synonym clusters ("enjoy/prefer/like",
  "study/learning", "watch/movie/series") so "what do i like?" finds
  "i love X"
- **tkinter desktop GUI** (`python run.py --gui`): live log, status readout,
  push-to-talk mic, auto-listen toggle, quick action chips, and an
  autostart checkbox; `--minimized` for login start
- **Auto-start installer** (`Installers/set_autostart.py`): enable/disable/
  status/test — Windows registry Run key, Linux XDG autostart
- **Mobile web UI** `GET /ui`: public tap-to-talk page (Web Speech API +
  speechSynthesis) that drives MAXIE from any phone browser with a token
- **Phone voice endpoint** `POST /voice`: upload a WAV (e.g. from the
  Android app), transcribed by the laptop's Whisper model, reply returned
- **Android "Siri-style" app skeleton** (`Android/`): Kotlin/Gradle project
  with a foreground mic service that hears with the screen off, energy
  wake gate (pluggable `WakeTrigger` for a real wake-word model), WAV
  upload to `/voice`, and TTS replies over LAN
- Tests for learning/recall, `/ui`, `/voice`, autostart and run.py flags
  (126 tests, 1 headless skip)