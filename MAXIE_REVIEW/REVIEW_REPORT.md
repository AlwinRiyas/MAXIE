# MAXIE — CODE REVIEW REPORT

**Generated:** 2026-09-28 14:59 UTC
**Purpose:** Complete source-code review package for another engineer.
**Reviewer note:** every claim below was verified by running the code in a
throwaway copy of this package on a headless Linux box (Python 3.14.7). No
hardware (mic/speaker) was available, so voice-hardware paths are unverified
by design — see *Verification* below.

---

## 1. Project identity

| | |
|---|---|
| Name | MAXIE |
| Description | Jarvis-style personal AI assistant, calm female "FRIDAY" persona |
| Language | Python 3.10+ (verified on 3.14.7) |
| Target platforms | Windows (primary / production), Linux (dev), Android phone client (HTTP) |
| Size | 126 source files, ~8,170 Python LOC (~1,450 of it tests) |
| Package size | ~340 KB of source, zipped well under 200 KB |
| Entry point | `run.py` (or `main.py` → same core) |
| External service | Ollama (local LLM, HTTP on `127.0.0.1:11434`) |

---

## 2. Architecture

### 2.1 Layer map

```
run.py / main.py                       ← CLI entry, arg parsing, graceful shutdown
 └── Core.core_manager.Maxie           ← composition root; owns every subsystem
     ├── VoiceEngine                   ← TTS (piper → edge → SAPI/pyttsx3/espeak → none)
     ├── VoiceManager                  ← voice state machine + listen()
     ├── AudioManager                  ← mic enumeration/selection (config-aware)
     ├── AudioRecorder                 ← streaming VAD recorder (Silero, energy fallback)
     ├── SpeechPipeline                ← recorder → Transcriber
     ├── Transcriber                   ← faster-whisper (configurable model/device)
     ├── BargeInListener               ← echo-aware STOP detection while speaking
     ├── BrainRouter                   ← routes: skills vs memory vs AI vs refusal
     │   ├── IntentEngine              ← utterance → intent
     │   ├── CommandCorrector          ← STT repair (whisper mishears app names)
     │   ├── CommandEngine / Parser    ← legacy command path
     │   ├── MemoryEngine              ← SQLite long-term + short-term context
     │   └── AIEngine → OllamaClient   ← provider abstraction + prompt building
     ├── SkillManager                  ← allowlisted skills only (Security.Permissions)
     ├── ConversationEngine            ← main loop, stop/exit, remote worker thread
     ├── RemoteServer                  ← stdlib HTTP endpoint (token-gated)
     └── Gui (Ui/gui.py)               ← tkinter panel, shares ConversationEngine
```

### 2.2 Data flow (one turn)

```
audio → AudioRecorder (VAD) → Transcriber (whisper) → text
  → CommandCorrector → IntentEngine → intent
  → BrainRouter:
       ├─ allowlisted intent + confirm gate → SkillManager → skill → reply
       ├─ memory intent                     → MemoryEngine (SQLite) → reply
       └─ everything else                   → AIEngine → OllamaClient → Ollama → reply
  → VoiceEngine.speak(reply)  (daemon thread + watchdog)
```

### 2.3 Module inventory (non-empty packages only)

| Package | Files | LOC | Role |
|---|---|---|---|
| `Voice/` | 15 | 1721 | recording, VAD, STT, TTS, barge-in |
| `Skills/` | 18 | 1577 | allowlisted device/app/user actions |
| `Brain/` | 8 | 692 | intent detection, correction, routing |
| `Conversation/` | 2 | 371 | main loop, remote worker |
| `Memory/` | 3 | 342 | SQLite CRUD, context, synonym recall |
| `Interface/` | 3 | 329 | HTTP server + mobile HTML UI |
| `Installers/` | 2 | 306 | TTS setup, autostart (Win registry / XDG) |
| `Config/` | 3 | 287 | JSON config loader w/ defaults |
| `Ui/` | 2 | 254 | tkinter control panel |
| `Core/` | 7 | 238 | composition root, state, event bus, time/date, greeting |
| `AI/` | 4 | 220 | Ollama client, prompts, AI engine |
| `Weather/` | 3 | 129 | weather (cached, offline-safe) |
| `Tests/` | 22 | 1447 | unittest suite + runner |
| `Automation/` | 3 | 85 | app discovery, system info |
| `Logs/` | 2 | 83 | logger |
| `Security/` | 1 | 37 | permissions allowlist |
| `WakeWord/`, `Models/`, `Plugins/`, `Resourses/`, `Vision/` | — | 0 | **empty placeholders** (see §5) |

---

## 3. Entry points

| Command | What it does |
|---|---|
| `python run.py` | Normal boot: voice loop + optional remote server |
| `python run.py --console` | Force console (skip GUI) |
| `python run.py --gui [--minimized]` | tkinter control panel (`--minimized` used by autostart) |
| `python main.py` | Thin alias → same `Maxie` core |
| `python Tests/run_tests.py [-v]` | Full test suite (138 tests) |
| `python Tests/run_tests.py Tests/vad_test.py` | Single file |
| `python Installers/setup_tts.py [--engine piper\|edge\|espeak] [--test]` | Install/configure TTS |
| `python Installers/set_autostart.py enable\|disable\|status\|test` | Autostart (Windows Run key / XDG `.desktop`) |
| `python -m compileall -q .` | Byte-compile check (PASS) |

### External surfaces

- **HTTP (phone/CLI):** `GET /health`, `GET /ui` (public page; commands still
  token-checked), `GET /` (capabilities), `POST /command` `{"text": ...}`,
  `POST /voice` (raw `audio/wav` body → laptop STT → reply). Default bind
  `127.0.0.1:8778`; LAN bind **fails closed** without a token.
- **Android client** (`Android/`, Kotlin/Gradle): *not present in this repo*;
  documented in `AGENTS.md` but not compiled here.

---

## 4. Implemented features (verified)

**Voice in**
- Streaming VAD recorder with Silero VAD + adaptive energy fallback, pre-roll,
  min-silence/max-duration gating (`Voice/audio_recorder.py`, `Voice/vad_engine.py`).
- faster-whisper transcription; model/device/compute-type all configurable
  (`Voice/transcriber.py`).
- Echo-aware barge-in: state gating + short-stop-phrase-only decoding +
  adaptive RMS threshold (`Voice/barge_in_listener.py`).
- Wake-word text gate: `"hey maxie" in text.lower()` (`Voice/wake_word_engine.py`).

**Voice out**
- TTS engine cascade: piper (offline neural) → edge-tts (online neural) →
  Windows SAPI / pyttsx3 / espeak → disabled no-op. Per-platform player
  selection (paplay/pw-play/aplay/ffplay/mpv/vlc; `SoundPlayer` + PowerShell
  on Windows). Daemon thread + watchdog timeout so audio can never block exit
  (`Voice/voice_engine.py`).

**Brain / routing**
- Intent detection across time, date, weather, math, apps, media, phone calls,
  power, YouTube, to-dos, memory, system info, search, recommendations
  (`Brain/intent_engine.py`, 692→10 KB).
- Whisper-error correction: misspelled app aliases, math-symbol preservation,
  time/date/weather phrase repair (`Brain/command_corrector.py`).
- Router precedence: destructive-confirm gate → skill → memory → AI
  (`Brain/brain_router.py`).

**Memory / learning**
- SQLite long-term store (CRUD + `LIKE` search), bounded short-term context
  (`context_turns`, default 6) (`Memory/memory_database.py`).
- Silent continuous learning: preference phrases ("i like/love/prefer",
  "my favorite", "i am learning/studying") auto-persisted; reverse-mapped
  `SYNONYMS` clusters let "what do i enjoy?" recall the same fact
  (`Brain/brain_router.py::_auto_learn`, `Memory/memory_database.py`).
- Persists across reboots.

**Skills (allowlisted — `Security/permissions.py`)**
`TIME, DATE, WEATHER, OPEN_APP, CLOSE_APP, CALCULATE, SEARCH, VOLUME,
SYSTEM_INFO, SAVE_MEMORY, RECALL_MEMORY, DELETE_MEMORY, GREETING, HELP,
SCREENSHOT, AI_CHAT, TODO_ADD, TODO_LIST, TODO_DONE, TODO_REMOVE, TODO_CLEAR,
MEDIA_NEXT, MEDIA_PREVIOUS, MEDIA_PLAY_PAUSE, CALL_ANSWER, CALL_REJECT,
YOUTUBE_SEARCH, RECOMMEND, SHUTDOWN, RESTART`

Concrete skills: calculator (AST-allowlisted, no `eval`/`exec`), weather,
web search (DuckDuckGo HTML scrape + URL cleaner), volume, open/close app
(Start-Menu-derived `app_database.json`), system info/screenshot, to-do list
(JSON), media keys (Win `ctypes` / `playerctl`), Android call answer/reject
(ADB), power (confirm-gated), YouTube search (URL builder), offline
recommendations, memory.

**Surfaces**
- Console loop with stop/exit phrases and remote worker thread.
- HTTP remote server (stdlib only), token auth, fail-closed LAN.
- Public mobile tap-to-talk page at `/ui` (`Interface/mobile_ui.html`).
- tkinter GUI sharing the same `ConversationEngine` (log, push-to-talk,
  auto-listen, quick chips, autostart toggle).
- Autostart on Windows (Run key) and Linux (XDG `.desktop`).
- 138-test headless suite.

---

## 5. Partially implemented features

| Area | State | Gap |
|---|---|---|
| **Wake word** | Text gate only — `Voice/wake_word_engine.py` is 4 lines doing a substring check on the *transcribed text* | Not an audio spotter. Requires the user to already be transcribed; no always-on listening, no false-accept control. AGENTS.md concedes this. |
| **GUI** | Functional tkinter panel | Guarded import, optional. Not packaged as a build; no icon/branding; unverified visually here. |
| **Vision** | `Vision/__init__.py` is **0 bytes** | Placeholder only. No implementation. |
| **Models / Plugins / Resourses** | `__init__.py` only (0 bytes) | Scaffolding. Note `Resourses/` is a misspelling of "Resources". |
| **Phone control** | ADB answer/reject only | No SMS/call-log/contact actions. Requires ADB + USB debugging. |
| **Remote server** | Text + WAV upload | No streaming audio, no push, no per-user auth (single shared token), no rate limiting, no request-size cap. |
| **`WakeWord/` package** | 4 files, **all 0 bytes** | Dead duplicate of the real `Voice/wake_word_engine.py`. Confusing; should be deleted. |
| **Weather** | Cached fetch, offline-safe | Single provider, no location geocoding beyond config lat/long. |

---

## 6. Known bugs (all reproduced/verified)

**B1 — Timeout & error replies pollute short-term context.** `AI/ai_engine.py:82-84`
`_is_offline_message()` only matches strings containing **both** "ollama" *and*
"running". `AI/ollama_client.py` returns three distinct failure strings; only
the connection-refused one matches. A timeout or generic error is therefore
written into the conversation context as if it were a real MAXIE answer, and
is then replayed to the model on subsequent turns.

Reproduced:
```
conn    filtered: True
timeout filtered: False     ← "Ollama took too long to respond."
error   filtered: False     ← "I hit an error talking to the model: boom"
context polluted on timeout:
  [('user', 'what is the weather'),
   ('assistant', 'Ollama took too long to respond. Please try again.')]
```
Fix: return a typed failure from `OllamaClient.ask` (or check
`client.last_error`) instead of pattern-matching English prose.

**B2 — Test suite hard-depends on `Installers/`.** `Tests/ui_test.py:116`
loads `Installers/set_autostart.py` via `importlib`. Removing that directory
breaks the suite. Proven: with `Installers/` excluded, the run is
`FAILED (errors=1)` with
`FileNotFoundError: .../Installers/set_autostart.py`.
This is why `Installers/` **is included** in this package despite the
"exclude installers" instruction — see `EXCLUSIONS.md`.

**B3 — Dead code: `OllamaClient.is_available()`.** `AI/ollama_client.py:28`
has **zero callers** anywhere in the project (all other `is_available` hits
are `AudioManager`/`SpeechPipeline`/`Transcriber`). Nothing ever reports AI
health, so an unreachable Ollama is only discovered by talking to MAXIE.

**B4 — Dead statement + wasted query: `AI/ai_engine.py:71`.**
`memories = self.memory.recall_for("", top=0)` is assigned and never used;
the very next line does the real `recall_for("")`. Pure waste plus a
pointless DB round-trip on every AI turn.

**B5 — `RemoteServer._ui_cache` is a class attribute.** `Interface/remote_server.py:315`
caches the mobile HTML on the *class*, not the instance. A second
`RemoteServer` (or a test) inherits the first one's HTML, and the failure
string `"<h1>MAXIE</h1><p>UI file missing.</p>"` is cached too, so a
transient read error is permanent for the process.

**B6 — Non-constant-time token comparison.** `Interface/remote_server.py:61`
uses `supplied.strip() == self.token`. A timing side channel on a network
auth check. Use `hmac.compare_digest`.

**B7 — `/voice` has no request-size limit.** `Interface/remote_server.py:275`
`self.rfile.read(length)` with an attacker-controlled `Content-Length` allows
unbounded memory allocation. (Requires a valid token, so severity is limited.)

**B8 — CORS `*` on a token-authenticated API.** `Interface/remote_server.py:163-168`
sends `Access-Control-Allow-Origin: *`, so any web page can attempt requests.
The token check still applies, so this is defense-in-depth rather than a
direct hole, but the wildcard origin is unnecessary.

**B9 — Config loader writes on read.** `Config/config.py:156` `_load_file()`
calls `_save_file()` on every load. Merely importing `Config` rewrites three
JSON files on disk. Idempotent in practice (verified byte-identical after a
full test run), but it means a read has a write side effect and can clobber
concurrent edits.

**B10 — Documentation is largely empty.** Five of seven `Docs/*.md` are
**0 bytes**: `API_REFERENCE.md`, `ARCHITECTURE.md`, `CHANGELOG.md`,
`CODING_STANDARDS.md`, `ROADMAP.md`. Only `MAXIE_PRINCIPLES.md` has content
(2,144 B). `Docs/CHANGELOG.md` is empty while a populated top-level
`CHANGELOG.md` also exists — a real duplication/confusion.

**B11 — Stray empty directory `Voice/Core/`.** Empty, unreferenced.

**B12 — `DEVELOPMENT_STATUS.md` is stale.** Claims "90 headless unittest
cases"; the suite actually contains **138** tests. The top-level
`CHANGELOG.md` (v6.1) correctly says 138.

**B13 — `Config/voice_config.py` is 0 bytes**, yet `Voice/voice_config.py`
(186 B) is the live one. A second, empty config module is confusing.

---

## 7. Tests

### 7.1 Result (clean package copy, headless, Python 3.14.7)

```
$ python -m compileall -q .
(exit 0, no output — PASS)

$ python Tests/run_tests.py
Ran 138 tests in 12.778s
OK (skipped=1)
```

**138 tests — 137 passed, 0 failed, 1 skipped.**

### 7.2 Per-module

| Tests | Count |
|---|---|
| `Tests/device_skills_test.py` | 17 |
| `Tests/system_test.py` | 13 |
| `Tests/tts_test.py` | 12 |
| `Tests/remote_server_test.py` | 10 |
| `Tests/intent_test.py` | 9 |
| `Tests/learning_test.py` | 7 |
| `Tests/memory_test.py` | 7 |
| `Tests/calculator_test.py` | 7 |
| `Tests/ai_test.py` | 6 |
| `Tests/config_test.py` | 6 |
| `Tests/corrector_test.py` | 6 |
| `Tests/vad_test.py` | 5 |
| `Tests/voice_commands_test.py` | 5 |
| `Tests/event_test.py` | 4 |
| `Tests/web_search_test.py` | 4 |
| `Tests/permissions_test.py` | 3 |
| `Tests/state_test.py` | 3 |
| `Tests/wakeword_test.py` | 3 |
| `Tests/audio_stream_test.py` | 2 |
| `Tests/ui_test.py` | 9 |
| **Total** | **138** |

### 7.3 Failed tests

**None.** With the package as shipped: 0 failures.

One failure appears only if `Installers/` is stripped (bug **B2**):
`Tests.ui_test.UiModuleTest.test_autostart_targets_run_py` →
`FileNotFoundError: Installers/set_autostart.py`.

### 7.4 Skipped tests

| Test | Reason |
|---|---|
| `Tests.audio_stream_test.AudioStreamTest.test_stream_start_stop` | `@unittest.skipUnless(AudioManager.is_available(), "requires sounddevice")` — no audio hardware in this container. |

That is the **only** skip. Graceful-degradation tests for the missing stack
(`silero_vad`, `piper`, faster-whisper, sounddevice) do run, because optional
imports are fenced — they emit `WARNING` lines and still assert correct
fallback behaviour.

### 7.5 What is NOT covered (gaps a reviewer should note)

- No test exercises a real microphone, speaker, or TTS synthesis.
- No test for `OllamaClient` network paths — `AI/ai_engine.py` is always
  tested with a stub client, so the B1 class of bug was invisible to the suite.
- No test for `Voice/voice_engine.py`'s actual audio output (only engine
  *selection* logic is tested).
- No concurrency test for the remote worker thread / barge-in.
- No lint/type-check gate in CI (no CI config exists in the repo).
- Optional deps absent in this environment: `sounddevice`, `torch`,
  `faster_whisper`, `silero_vad`, `edge_tts`, `pyttsx3`, `pyautogui`.
  Present: `requests`, `numpy`, `psutil`, `tkinter`, `PIL`.

---

## 8. Current phase / subphase

**Phase: MVP complete → hardening/review phase.**

- The functional MVP ("MAXIE MVP voice baseline", HEAD `0a97dab`) is done and
  test-covered: 138 tests green, `compileall` clean.
- Sub-phase the author is in: **environment bring-up on the real machine** —
  getting the voice pipeline validated on hardware and the LLM reachable. Two
  concrete environment blockers were found and resolved during packaging prep
  (see §11).
- Remaining engineering focus is **consolidation, not new features**: the
  empty docs, the dead `WakeWord/` package, the stale status file, and the
  untested network/AI paths above.

`CHANGELOG.md` v6.1 ("Natural voice") is the last named release.

---

## 9. Remaining work

**Must-fix (small, high value)**
1. Fix **B1** — typed error from `OllamaClient` instead of prose matching.
2. Fix **B2** — make `ui_test` degrade (or move autostart logic out of
   `Installers/` into a testable module).
3. Remove dead code **B3**, **B4**, **B5**.
4. Delete the empty `WakeWord/` package and empty `Voice/Core/` (**B11**).
5. Write the five empty `Docs/*.md`, or delete them and keep the top-level
   `CHANGELOG.md` (**B10**).

**Should-fix**
6. `hmac.compare_digest` for the token (**B6**); cap `/voice` body size
   (**B7**); narrow CORS origin (**B8**).
7. Add a real `OllamaClient` test with a stub HTTP layer (would have caught B1).
8. Call `is_available()` at boot and surface AI health in the GUI/status
   (turns B3 into a feature).
9. Refresh `DEVELOPMENT_STATUS.md` to 138 tests (**B12**); remove empty
   `Config/voice_config.py` (**B13**).

**Future (documented in `AGENTS.md`/DEVELOPMENT_STATUS)**
10. True always-on wake-word spotting (audio model, not a text gate).
11. On-hardware validation of mic/speaker/TTS/barge-in — impossible headless.
12. Android client build; streaming audio to/from the phone.
13. `Vision/` and `Plugins/` either implement or remove.
14. Add CI (compileall + test runner + a linter).

---

## 10. Dependencies

### Required (core boot)
| Package | Version | Use |
|---|---|---|
| numpy | >=1.26 | audio buffers, VAD math |
| scipy | >=1.11 | signal helpers |
| requests | >=2.28 | Ollama HTTP, web search |
| psutil | >=5.9 | system-info skill |

### Optional (lazy/fenced — app runs without them)
| Package | Version | Use |
|---|---|---|
| sounddevice | >=0.4.6 | mic + speaker I/O |
| torch | >=2.0 | Silero VAD |
| silero-vad | >=0.5.1 | neural VAD |
| faster-whisper | >=1.0.0 | speech-to-text |
| piper-tts | — | offline neural TTS (via `setup_tts.py`) |
| edge-tts | — | online neural TTS (via `setup_tts.py`) |
| pyttsx3 | >=2.90 | Linux TTS fallback |
| webrtcvad | >=2.0.10 | optional Windows energy VAD |
| tkinter | stdlib | GUI (present in most distros) |

### External services / binaries
- **Ollama** at `127.0.0.1:11434` (config `ai.url`; model `llama3.2:3b`).
- **ADB** (Android) for phone call control.
- **playerctl** (Linux) / media keys (Windows) for media control.
- `paplay`/`pw-play`/`aplay`/`ffplay`/`mpv`/`vlc` for audio playback.
- DuckDuckGo HTML endpoint for web search (no API key).
- YouTube search URL construction (no API key).

### Secret handling
No secrets in code. The only credential is `remote_server.token` in
`Config/system_config.json`, which is **not** in `.gitignore` — see the
security note below.

---

## 11. Security review

**Solid**
- LLM output is **never executed**. All actions funnel through
  `SkillManager` + `Security.Permissions.ALLOWED` (30 intents).
- Destructive actions (`SHUTDOWN`, `RESTART`, `DELETE_MEMORY`) require an
  explicit spoken confirmation; `FORMAT` is refused outright.
- Linux dev boxes additionally need `allow_local_power_control: true`
  (default `False`).
- Remote server binds `127.0.0.1` by default and **fails closed** — binding a
  non-loopback address without a token raises `ValueError`
  (`Interface/remote_server.py:37-43`).
- Calculator uses an **AST allowlist**; no `eval`/`exec` anywhere in the
  codebase (verified by grep). Only numeric literals, 9 operators, 8 named
  functions, and `pi`/`e`.
- `/voice` validates the `RIFF` magic and deletes its temp file in a
  `finally` block.
- `/ui` HTML is public, but every command it issues is still token-checked.

**Weaknesses**
- **B6** non-constant-time token compare; **B7** no request-size cap;
  **B8** wildcard CORS.
- Token auth is a single shared secret with no expiry, no rate limiting, and
  no lockout; compared with plain `==`.
- `Config/system_config.json` holds the token in plaintext and is **not
  gitignored** (only `Memory/*` and `Config/tts_models/` are). A token
  written on a dev box would be committed by accident. Recommend adding it
  to `.gitignore` and shipping a `system_config.example.json`.
- `/voice` hands an arbitrary uploaded WAV to the transcriber; no size/duration
  limits beyond the request cap above.
- `Skills/web_search.py` and `Skills/youtube_skill.py` perform outbound
  requests with user text — no SSRF surface (fixed endpoints), but they do
  leak user queries to third parties.
- Power control relies on OS-level commands executed via `subprocess`; the
  allowlist + confirmation gate is the only thing standing between the LLM's
  text and a reboot.

---

## 12. Important design decisions

1. **Composition root in `Core.core_manager.Maxie`.** Every subsystem is
   constructed and owned in one place; `run.py`, the GUI, and the remote
   server all drive the *same* `ConversationEngine` instance. Consequence:
   adding a surface requires no new wiring.
2. **Optional native deps are lazily imported and fenced.** `sounddevice`,
   `torch`, `silero-vad`, `faster-whisper`, `pyttsx3` are imported inside
   functions with `is_available()` guards, so the app **and the tests** run
   headless. This is why 138 tests pass in a container with no audio stack.
3. **Config as auto-healing JSON.** `Config` deep-merges user files over
   defaults and writes the result back, so a missing or partial config file
   self-repairs, and new keys never break older installs. Paths derive from
   the project root, never hardcoded — cross-platform by construction.
4. **Skills are the only execution surface; the LLM is never trusted.** The
   router classifies into an allowlisted intent, `Permissions` gates it, and
   `SkillManager` dispatches. Confusing intent ≠ action.
5. **Confirmation is a second, explicit step for destructive ops.** The
   router answers with an instruction ("Say 'confirm shutdown'"), so `POWER_*`
   never reaches a skill unconfirmed.
6. **Remote server is stdlib-only** (`http.server` + `ThreadingHTTPServer`) —
   no Flask, keeping the dependency surface tiny and the install trivial.
7. **Fail closed, always.** No token + non-loopback bind = refuse to start.
   No audio tool = `speak()` returns `False` and MAXIE continues. Broken
   anything optional degrades to a warning, never to a crash. TTS runs on a
   daemon thread with a watchdog so audio can never block a phone reply or
   process exit.
8. **Echo-aware barge-in without a dedicated model.** Achieved with
   combination of state gating + decoding *only* short stop phrases while
   speaking + an adaptive RMS threshold — cheap and CPU-only, at some cost in
   reliability on a noisy mic.
9. **TTS cascade, never a hard failure.** piper (offline neural) → edge
   (online neural) → platform SAPI/pyttsx3/espeak → silent no-op. `auto`
   genuinely probes each engine instead of assuming.
10. **Synonym-cluster memory recall.** `MemoryDatabase.SYNONYMS` is reverse
    mapped, so a stored "I love X" is recallable via "what do i enjoy?" and
    friends — cheap semantic search with zero extra dependencies (no
    embeddings, no vector DB).
11. **One class per module, noun class names, absolute imports from the
    project root** (`from Brain...`). Enforced by convention in `AGENTS.md`;
    the test runner injects the project root onto `sys.path` so `Tests/` works
    from any CWD.
12. **PEP-668 aware installers.** `setup_tts.py` falls back from `pip` to
    `pipx` when the OS blocks system pip, rather than telling the user to pass
    `--break-system-packages`.

---

## 13. Environment status (Linux dev box, during packaging)

Two blockers were found and fixed on the dev machine while preparing this
package. **Neither is a code defect** — both are environment setup, recorded
here because they affect reproducibility:

1. **Ollama was installed but not running.** `/usr/local/bin/ollama`
   (client 0.34.4) existed, but no `ollama serve` process and nothing
   listening on `127.0.0.1:11434`, so `ai.url` pointed at a dead port.
   Fixed by starting `ollama serve`.
2. **No model present.** The running server reported `{"models":[]}`, so even
   a reachable server could not answer. Fixed with
   `ollama pull llama3.2:3b` (2.0 GB, verified present).

The default `ai.url = http://127.0.0.1:11434` assumes Ollama on the same
machine. Since the author's other Ollama is on Windows, reaching it from Linux
requires either a local install (done) or pointing `ai.url` at the Windows
host's LAN address — which additionally needs `OLLAMA_HOST=0.0.0.0` on Windows
and Windows Firewall access. No code change is required for either, as
`OllamaClient` already takes its base URL from config.

---

## 14. How to review this package

```bash
# 1. Verify it compiles
python -m compileall -q .

# 2. Run the suite (no hardware, no network, no Ollama needed)
python Tests/run_tests.py        # expect: Ran 138 tests ... OK (skipped=1)

# 3. Read in this order
#    AGENTS.md            conventions, architecture, security rules
#    Core/core_manager.py composition root
#    Brain/brain_router.py routing
#    Interface/remote_server.py + Security/permissions.py  trust boundary
#    AI/ai_engine.py      the B1 bug
#    Tests/system_test.py how the router is meant to behave

# 4. Optional: run the console interface
python run.py --console
```

Starting points for a reviewer, by interest:
- **Security** → `Security/permissions.py`, `Interface/remote_server.py:37-61`,
  `Skills/calculator.py`, `Skills/power_skill.py`.
- **Voice pipeline** → `Voice/audio_recorder.py`, `Voice/vad_engine.py`,
  `Voice/barge_in_listener.py`, `Voice/voice_engine.py` (largest file, 18 KB).
- **AI quality** → `AI/ai_engine.py`, `AI/ollama_client.py`, `AI/prompts.py`.
- **Cleanup targets** → `WakeWord/` (empty), `Docs/*.md` (5 empty),
  `Voice/Core/` (empty), `Config/voice_config.py` (empty).
