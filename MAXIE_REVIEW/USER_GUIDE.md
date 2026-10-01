# MAXIE — User Guide

A Jarvis-style personal AI assistant with a calm, confident **female** voice
(inspired by FRIDAY). It lives on your Windows laptop, runs your commands by
voice or typing, and you can drive it from your phone over Wi-Fi.

This guide is for people installing MAXIE for the first time.

---

## 1. What MAXIE can do

| Category       | Say…                                                            | MAXIE does                                  |
|----------------|-----------------------------------------------------------------|---------------------------------------------|
| Basics         | "what time is it" / "what is the date"                          | tells time / date                           |
| Weather        | "weather"                                                       | current weather for your city (open-meteo)  |
| Math           | "what is 12 times 8", "50 percent of 200", "square root of 144" | answers with local calculator               |
| Apps           | "open chrome", "open notepad", "open youtube"                   | launches the app/site                       |
| Apps           | "close notepad"                                                 | quits the app                               |
| YouTube        | "open youtube and search funny cats", "play <song name>"        | opens YouTube search results                |
| Music / media  | "next song", "previous track", "pause", "resume", "stop music"  | controls playback (Windows media keys)      |
| Volume         | "set volume to 40", "add volume", "raise it", "mute"            | controls system volume                      |
| Calls          | "answer the call", "reject the call"                            | answers/rejects Android calls over ADB      |
| Web search     | "search for python"                                             | searches the web (DuckDuckGo)               |
| System         | "system info", "battery", "take a screenshot"                   | CPU/RAM/battery info, screen capture        |
| To-do list     | "add buy milk to my list", "show my todo", "mark task 1 done", "remove walk the dog", "clear my todo" | personal task list          |
| Memory         | "remember that I like cyber security", "what do I like"         | remembers and recalls things                |
| Recommender    | "give me a match", "recommend a movie / series / song"          | curated offline pick for you                |
| Chat           | "hello", "help", "who are you"                                  | chats via a local AI model (Ollama)         |
| Power          | "shut down the laptop" (then confirm "yes")                     | shuts down / restarts after confirmation    |
| Quit           | "exit", "goodbye"                                               | closes MAXIE                                |

You can also interrupt MAXIE while it is speaking: say **"stop"**.

---

## 2. Requirements

- **Windows 10/11** (primary) or **Linux**. Python **3.10 or newer**.
- The core app only needs a few small libraries. The heavy speech/AI
  packages are **optional** — without them MAXIE runs in text mode with
  clear messages.

Install everything:

```bash
pip install -r requirements.txt
```

### Optional add-ons for full voice + AI

| Feature     | Needs | Great experience |
|-------------|-------|------------------|
| Voice mode (mic)  | sounddevice, torch, silero-vad, faster-whisper | female voice out of the box (Windows SAPI) |
| Chat/AI     | Ollama running locally (`ollama serve`), default `llama3.2:3b` | smarter, context-aware replies |
| Media keys  | nothing on Windows; on Linux `sudo apt install playerctl` | next/previous/play-pause |
| Phone calls | `adb` on PATH + your Android phone paired (USB or wireless) | answer/reject calls from the laptop |

On Linux for TTS: `python Installers/setup_tts.py` (or `sudo apt install
espeak-ng` for the automatic robotic fallback). **Never settle for the
robot voice — run the installer once; the neural voice is cached
offline afterwards.**

---

## 3. First launch

```bash
python run.py        # or: python main.py
```

On first run MAXIE auto-creates its configuration files under `Config/`:

- `Config/system_config.json` — assistant name, user name, weather city,
  AI model, remote access, wake word.
- `Config/personality.json` — voice style (FRIDAY), gender (female), rate.
- `Config/audio_config.json` — mic, speech model, barge-in settings.

If a microphone + the optional speech packages are installed you get
**voice mode**; otherwise **text mode** (type commands). Either way,
commands work identically.

### Wake word (optional)

By default MAXIE listens continuously. To require a wake word first, set
`wake_word_enabled: true` in `Config/system_config.json` (default wake
phrase `hey maxie`). The wake word today is a lightweight text gate; a
true always-on spotting model is future work.

### Desktop GUI (control panel)

```bash
python run.py --gui            # open the MAXIE window
python run.py --gui --minimized # start hidden (used for auto-start)
python run.py --console        # force the old text-only console
```

The GUI shows the live conversation log and MAXIE's status
(Idle / Listening / Speaking). From it you can:

- type commands (Send / Enter),
- press **🎤 Talk** for a one-shot push-to-talk capture,
- toggle **Auto-listen** for hands-free continuous voice,
- toggle **Start at login** (auto-start, see below),
- use the quick chips: Time, Todo, Next, Call, Help, Exit.

Every command goes through the same brain as voice/phone, so behaviour
is identical everywhere.

### Start at login (auto-start)

```bash
python Installers/set_autostart.py enable    # MAXIE starts with your login
python Installers/set_autostart.py status
python Installers/set_autostart.py disable
python Installers/set_autostart.py test      # shows the exact command used
```

- Windows: registry Run key, launches `pythonw run.py --gui --minimized`.
- Linux: `~/.config/autostart/maxie.desktop`.
- You can also use the **Start at login** checkbox in the GUI.

---

## 5. Using MAXIE from your phone (Remote access)

1. Edit `Config/system_config.json`:

   ```json
   "remote_server": {
     "enabled": true,
     "host": "127.0.0.1",
     "port": 8778,
     "token": "your-secret-token"
   }
   ```

2. **For access from your phone (LAN), set a token.** Without a token,
   MAXIE refuses to bind to anything but the laptop itself (loopback).

3. Run MAXIE, then open a browser or the free "HTTP Request" app on your
   phone and call the endpoint:

   ```
   POST http://<laptop-ip>:8778/command
   Headers: X-MAXIE-Token: your-secret-token
   Body (JSON): { "text": "what time is it" }
   ```

   Health check: `GET http://<laptop-ip>:8778/health`

   On Windows find your laptop IP with `ipconfig`, on Linux `ip addr`.

4. Useful phone/CLI one-liner:

   ```bash
   curl -X POST http://127.0.0.1:8778/command \
     -H "X-MAXIE-Token: your-secret-token" \
     -H "Content-Type: application/json" \
     -d '{"text": "open youtube"}'
   ```

Remote commands are answered in under a second. If MAXIE is idle it will
also speak the reply out loud.

### Mobile web UI (open in your phone browser)

With the remote server running, open:

```
http://<laptop-ip>:8778/ui
```

You get a dark FRIDAY-style page with a **hold-to-talk** mic button
(Web Speech API), a text box, quick chips (Time, Weather, Todo, Next,
Answer call, Help), and a **Voice** toggle so MAXIE speaks its replies
back through the phone. Enter your access token once — it is remembered
on the phone.

### Phone voice endpoint

```
POST http://<laptop-ip>:8778/voice
Headers: X-MAXIE-Token: your-secret-token, Content-Type: audio/wav
Body: raw WAV bytes
→ { "ok": true, "transcript": "...", "response": "..." }
```

The laptop transcribes the audio with its Whisper model and returns
MAXIE's reply. The Android app uses this under the hood (see §12).

---

## 6. Answering and rejecting calls (Android)

MAXIE talks to your phone through Android Debug Bridge (`adb`):

1. Install `adb` and add it to PATH (Windows: `winget install --id Google.PlatformTools`).
2. Connect your phone — easiest is **wireless debugging**:
   ```
   adb pair <ip>:<port>      # enter the code shown in Settings
   adb connect <ip>:<port>
   adb devices               # your phone must be listed
   ```
3. Now **"answer the call"** and **"reject the call"** work from the
   laptop, the CLI, or the phone endpoint.

On Windows without a paired phone, "answer the call" falls back to the
system answer key (best effort for softphone/Bluetooth rings). Rejecting
requires the ADB device.

> Safety: keep your phone within this Wi-Fi; MAXIE never listens to or
> records your calls — it only presses the answer/hang-up button.

---

## 7. Shutdown / restart (read this)

Power commands are dangerous, so MAXIE **always asks first**:

```
You : shut down the laptop
MAXIE : I won't shut down without your explicit confirmation.
        Say 'confirm shutdown' to confirm.
```

You have to reply with something like **"yes, shut down"** or
**"confirm shutdown"**. Only then does it power off (Windows: `shutdown /s`).

On a Linux machine MAXIE refuses by default to protect it during
development — set `allow_local_power_control: true` in
`Config/system_config.json` to enable it there.

---

## 8. Configuration summary

All files are under `Config/` and are created automatically on first run.

| Key | File | Meaning |
|-----|------|---------|
| `assistant_name` / `user_name` | system_config | who MAXIE is and calls you |
| `weather.city` | system_config | city for the weather skill |
| `ai.model`, `ai.url` | system_config | Ollama model + server URL |
| `remote_server` | system_config | phone remote + token |
| `style` / `voice_gender` | personality.json | FRIDAY persona, female voice |
| `speech_rate` / `volume` | personality.json | TTS tuning |
| `microphone_index` | audio_config | pick a specific mic |
| `whisper_model` | audio_config | transcription model (`base.en` is a good default) |
| `wake_word_enabled` | system_config | require "hey maxie" first |

---

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| "No microphone found — text mode" | install optional packages: `pip install sounddevice torch silero-vad faster-whisper` |
| Phone endpoint says "took too long" | ensure Ollama isn't the one slow-response for that query, or disable remote TTS by lowering `response_length` |
| Chat says "can't reach Ollama" | start it: `ollama serve`, then run `ollama pull llama3.2:3b` once |
| Media keys do nothing (Linux) | `sudo apt install playerctl` |
| Can't answer calls | run `adb devices`; re-pair wireless debugging |
| Remote refuses to bind | set a non-empty `token` in system_config before enabling LAN |
| Voice garbled / echo | lower audio `vad_threshold`, set `microphone_index`, check `echo_cooldown_seconds` |
| MAXIE doesn't quit | press Ctrl+C twice, or say "exit" |

---

## 10. Running the tests (developers)

```bash
python Tests/run_tests.py      # 126 headless-safe unit tests
python -m compileall -q .      # compile check
```

Voice hardware (mic/speaker/TTS) can only be validated on a real laptop —
tests cover the logic.

---

## 11. Privacy & security notes

- Your AI chat runs **locally** (Ollama). Your voice is transcribed
  locally (faster-whisper). Nothing is sent to the cloud.
- LLM output is never executed as a command; only built-in skills run.
- Tokens live in config files, never in the code.
- Add this folder to your own personal setup and don't share
  `Config/*.json` with others.

Enjoy your own Jarvis. — MAXIE

---

## 12. Android phone app (Siri-style, works with the screen off)

A real Android client lives in `Android/` — a Kotlin/Gradle project that
keeps listening while your phone is locked. It hears with an offline
**energy wake trigger**, and when it hears you it records the phrase and
uploads it to the laptop's `/voice` endpoint; MAXIE transcribes, replies,
and the phone **speaks the answer**, even with the screen off.

Build it in Android Studio (open the `Android/` folder — see
`Android/README.md`).

Highlights:

- **Foreground mic service** + partial wake lock → hears with screen off.
- Pluggable `WakeTrigger` — the built-in energy gate works anywhere; drop
  in a real wake-word model (OpenWakeWord / Porcupine / Vosk) for
  "Hey MAXIE" if you want.
- Needs the laptop's `POST /voice` → requires `faster-whisper` installed.
- Source only: there is no Android SDK in the MAXIE dev environment, so
  compile it in Android Studio following `Android/README.md`.

---

## 13. Continuous learning & memory

MAXIE **keeps learning on its own** — no "remember" required:

- Say things like *"i like dark roast coffee"*, *"i love mangoes"*,
  *"my favorite movie is interstellar"*, *"i am learning netball"* and
  MAXIE quietly saves them.
- Later ask *"what do i like"*, *"what am i studying"*, or *"what do i
  enjoy"* — synonym recall finds the answer.
- Everything is stored in `Memory/maxie_memory.db` (SQLite), so it
  survives restarts and reboots. Enable auto-start (§4) and MAXIE simply
  is there with your memory intact every day.

Memory commands: "remember that …", "what do I like", "forget/to delete"
\`delete <fact>\`.