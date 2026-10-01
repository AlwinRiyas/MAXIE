# MAXIE

Neuroxon's AI Assistant — a Jarvis-style personal voice assistant with a
calm, confident **female** voice (inspired by FRIDAY).

Cross-platform: Windows (primary) / Linux (dev) / phone access via a local
HTTP endpoint. Written in Python 3.10+.

## What MAXIE can do

- **Listen & talk** — streaming, VAD-driven speech recognition
  (Silero VAD + faster-whisper, energy fallback that works headless) and
  female neural TTS (offline **piper** by default → Microsoft edge →
  Windows SAPI → pyttsx3/espeak).
- **Interrupt** — say **"stop"** while MAXIE is speaking; echo-protected
  barge-in, with **"exit"** / **"goodbye"** to shut down.
- **Commands** (spoken or typed):

  | You say…                    | MAXIE does                       |
  |-----------------------------|----------------------------------|
  | "what time is it"           | time                             |
  | "what is the date"          | date                             |
  | "weather"                   | weather (open-meteo)             |
  | "open chrome"               | launch app (Windows/Linux)       |
  | "close notepad"             | quit app                         |
  | "what is 12 times 8"        | math (spoken math supported)     |
  | "search for python"         | web search (DuckDuckGo)          |
  | "set volume to 40"          | volume control                   |
  | "system info"               | CPU/RAM/battery/info             |
  | "take a screenshot"         | screenshot                       |
  | "remember that I like X"    | save to SQLite memory            |
  | "what do I like"            | recall memory                    |
  | "forget my gym"             | delete memory                    |
  | "add buy milk to my list"   | to-do list (add)                 |
  | "show my todo list"         | to-do list (show)                |
  | "mark task 1 as done"       | to-do list (complete)            |
  | "next song" / "skip"        | media next track                 |
  | "pause / resume music"      | play-pause (Windows keys / playerctl) |
  | "answer call" / "reject call" | answer/reject Android calls via ADB |
  | "open youtube and search X" | open YouTube search results      |
  | "play <song name>"          | search it on YouTube             |
  | "give me a match"           | movie/series/music/game recommendation |
  | "recommend a movie"         | curated recommendation (offline) |
  | "shut down the laptop"      | requires "yes/confirm", then powers off (Windows; Linux gated) |
  | "restart the laptop"        | same confirmation flow           |
  | "hello", "help", "who are you" | chat (local LLM via Ollama)   |

- **Remember** — SQLite long-term memory + short-term conversation context
  so follow-ups like "who created you?" resolve correctly.
- **Continuous learning** — MAXIE quietly saves "i like X", "my favorite
  movie is Y", "i am learning Z" and recalls them via synonyms
  ("what do i enjoy?"), surviving reboots.
- **Desktop GUI** — `python run.py --gui` for a tkinter control panel with
  push-to-talk, status, and an autostart toggle.
- **Phone access** — drive MAXIE from your phone over HTTP: `GET /ui`
  (tap-to-talk web page) and `POST /voice` (upload a WAV; Whisper replies).
  An always-on Android client skeleton lives in `Android/`.
- **Auto-start** — `Installers/set_autostart.py enable` starts MAXIE
  (hidden GUI) at login on Windows and Linux.

## Quick start

> Full installation, configuration, phone setup, and usage for new users:
> see **`USER_GUIDE.md`**.

```bash
# 1. Install core deps (voice deps are optional and lazy-loaded)
pip install -r requirements.txt

# 2. Configure (auto-created on first run)
#    Config/system_config.json    -> name, AI model, weather, remote
#    Config/personality.json      -> style (FRIDAY), voice_gender (female)

# 3. Run
python run.py            # or: python main.py
```

Without a microphone/Ollama MAXIE degrades gracefully: text mode + clear
warnings. With a working mic it uses voice mode.

## Phone / remote access

```json
// Config/system_config.json -> "remote_server"
{
  "enabled": true,
  "host": "127.0.0.1",   // LAN access REQUIRES a token below
  "port": 8778,
  "token": "your-secret"
}
```

Endpoints (all require `X-MAXIE-Token: <token>` when a token is set):

- `GET  /health` — liveness
- `GET  /`       — API info
- `POST /command` — body `{"text": "what time is it"}` → `{"ok": true, "response": "..."}`

Remote commands are answered instantly by a dedicated worker thread, and
MAXIE will speak the reply aloud when it is idle. Binding to a
non-loopback address without a token is refused (fail-closed).

Example from a phone/CLI:

```bash
curl -X POST http://127.0.0.1:8778/command \
  -H "X-MAXIE-Token: your-secret" \
  -H "Content-Type: application/json" \
  -d '{"text": "open youtube"}'
```

## Security

- LLM output is **never** executed; actions run only through allowlisted
  skills (`Security/permissions.py`).
- Destructive actions (shutdown/restart) run only after an explicit
  "yes/confirm"; on Linux the dev machine is additionally protected by
  `allow_local_power_control: false` in `Config/system_config.json`.
- Remote server binds loopback by default; LAN requires an explicit token.

## Phone call control (Android)

MAXIE answers/rejects calls through `adb` (Android Debug Bridge). Connect
your phone once over wireless ADB (`adb pair`) or USB debugging:

```bash
adb devices   # should list your phone
```

Then "answer the call" / "reject the call" works from the laptop, the CLI,
or the phone HTTP endpoint. On Windows without an ADB device, ANSWER falls
back to the system media key (best effort for softphone/Bluetooth rings).

## Media keys & playerctl

- Windows: uses standard media keys (no extra installs needed).
- Linux: install `playerctl` (`sudo apt install playerctl`) for next/
  previous/play-pause, plus `pactl` (usually present) for volume.

## Tests

```bash
python Tests/run_tests.py      # 126 headless-safe unittest cases
python -m compileall -q .      # compile check
```

Voice hardware (mic/speaker/TTS) cannot be verified on a headless box —
run `python run.py` on the actual laptop to validate.

## Wake word

Optional lightweight text-gate (`wake_word_enabled` in config). A true
always-on spotting model is future work.

## Tech

- Python stdlib + numpy/scipy/requests/psutil (core)
- Optional: sounddevice, torch, silero-vad, faster-whisper, piper-tts
  (natural voice), edge-tts, pyttsx3. Skip them and MAXIE still runs —
  you just get text mode / the automatic fallback voice. For the
  human-sounding voice, run `python Installers/setup_tts.py` once.
- AI: Ollama (default `llama3.2:3b` @ `127.0.0.1:11434`, configurable)

Developed by Alwin Riyas.