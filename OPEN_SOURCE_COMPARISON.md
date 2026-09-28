# MAXIE — OPEN SOURCE COMPARISON

**Date:** 2026-09-28. References are to the upstream projects as of this date.
Used to decide what MAXIE should **borrow** — not to redesign MAXIE around
someone else's stack.

Projects studied:

| Project | URL | Licence | Maturity signal |
|---|---|---|---|
| **Leon** | https://github.com/leon-ai/leon | MIT | **active**; core release tags are old, server/client are versioned separately |
| **OpenVoiceOS** | https://github.com/OpenVoiceOS/OpenVoiceOS | Apache-2.0 (core) | **active**, large install base, modular micro-services |
| **Rhasspy 2.x** | https://github.com/rhasspy/rhasspy | Apache-2.0 | **archived 2025-04-22**; last release v2.5.11 in 2021 |
| **Rhasspy 3 / Wyoming** | https://github.com/rhasspy/rhasspy3 | Apache-2.0 | early; the designated successor direction |

---

## 1. What each project actually does

### Leon — the closest philosophical match

A privacy-first personal assistant, TypeScript throughout, structured as:

```
Skills → Actions → Tools → Functions → Binaries
```

- **Skills** group user-facing capabilities; **Actions** are the runtime units
  the NLU resolves to; **Tools** are the granular operations inside an action;
  **Functions** wrap external binaries; **Binaries** are the executables
  themselves. This five-level chain is the single most useful idea in the
  comparison: it keeps "what the user asked for" distinct from "what program ran".
- **Schemas everywhere** (TypeBox) — every action, tool, and utterance has a
  declared schema that is validated at the boundary.
- **Three routing modes** with an explicit cost/safety ladder:
  - `agent` — full autonomous planning.
  - `smart` — planner proposes, skills validate.
  - `controlled` — deterministic skills only, LLM used narrowly.
  This maps almost exactly onto the "controlled / smart / agent" mode split
  MAXIE needs, and MAXIE currently has only the tail of it.
- **Voice**: openWakeWord + `Hey_Leon.onnx`, streaming STT, per-utterance
  TTS pipelines, a TCP voice-server boundary so the client (web/desktop) and the
  server are separable processes.
- **Memory**: QMD (a lightweight local index) for semantic retrieval plus SQLite
  for structured facts; Markdown "context files" the user can read and edit.
- **TTS**: YourTTS on-device by default.

### OpenVoiceOS — the best modular voice stack

- `ovos-core` is a **message bus**: utterance intents, TTS requests, and
  skill responses are broadcast as messages, decoupled from any transport.
- `ovos-dinkum-listener` handles wake word + VAD + STT as a swappable
  "listener" plugin (legacy `ovos-ww-plugin-precise-lite`, `ovos-standalone`
  Silero, `ovos-odroid`).
- **Intent pipelines** are declarative: a skill declares a pipeline of stages
  (stt → intent → skill → tts) and the bus routes between them.
- **Skills are Python packages registered via `entry_points`**, discovered at
  runtime — genuine plugin discovery, which MAXIE lacks.
- **Personas** and an optional **agentic loop** in `ovos-agent`/`ovos-core`.
- **No authentication on the message bus** by default. Correct for a local
  single-user install, wrong for anything networked.

### Rhasspy / Rhasspy3 — the cautionary tale

- Rhasspy 2.x: MQTT/Hermes-based, `rhasspy-silence` implements WebRTC VAD with
  an energy fallback, satellite-style architecture.
- **Archived in April 2025.** Widely deployed, quietly dead, and a large
  installed base still runs it.
- The successor direction is **Wyoming** (protocol-first, small components:
  `wyoming-satellite`, `wyoming-asr`, `wyoming-pipeline`, `wyoming-tts`),
  spoken over **gRPC/Unix sockets**, not MQTT.
- **No authentication by default.**

---

## 2. Feature matrix

| Capability | MAXIE | Leon | OpenVoiceOS | Rhasspy 2.x |
|---|---|---|---|---|
| Local-first / offline | yes | yes | yes | yes |
| Wake word | substring gate | openWakeWord | plugin (Precise, Silero) | precise + Porcupine |
| Streaming VAD | energy/Silero | yes | yes | WebRTC (`rhasspy-silence`) |
| Streaming STT | one-shot, **no** | yes | yes | yes |
| TTS abstraction | **yes** (4 engines) | yes (YourTTS + others) | yes (plugin) | yes (plugin) |
| Barge-in / interrupt | partial, **drops long interrupts** | supported | supported | limited |
| AEC / echo cancellation | structural (mic closed), **violated by GUI** | pipeline-level | pipeline-level | limited |
| Deterministic intent routing | **yes** | yes | yes | yes |
| Autonomous planning | **no** | yes (agent mode) | yes (agentic loop) | no |
| Skill plugin discovery | hardcoded | structured TS modules | **`entry_points`** | plugin packages |
| Tool schemas / validation | **no** | TypeBox | pipeline schemas | intents |
| Memory | SQLite + substring recall | QMD + SQLite + context files | skill-provided | intent/sentence history |
| Home automation | **no** | skill layer | skill layer | limited |
| Vision | screenshot only | yes (skills) | limited | no |
| Proactive / scheduler | **no** | cron-like | timers | timers |
| GUI | tkinter | full web/desktop client | ovos-web / CLI | web (Hass-style) |
| Remote API | token HTTP | TCP/WS voice server | message bus | HTTP + MQTT |
| Remote auth | **token, fails closed** | client/server pairing | **none by default** | **none by default** |
| Language | **Python** | TypeScript | Python | Python |
| Licence | private | MIT | Apache-2.0 | Apache-2.0 |
| Project health | active | active | active | **archived** |

---

## 3. What MAXIE should adopt

Ordered by value-to-effort. Each is concrete and small relative to its payoff.

### 3.1 A validation layer for tool calls — from Leon's schemas, without TypeBox
Leon validates every action and tool against a schema at the boundary. MAXIE
needs the *property*, not the language. Add a declarative schema per skill
(argument names, types, required-ness, enums) validated before dispatch. This
closes the current gap where every skill hand-rolls argument extraction, and it
becomes the contract an LLM tool-calling layer can rely on.

### 3.2 Three explicit routing modes — from Leon
Adopt `controlled` / `smart` / `agent` as first-class config:

- **controlled** (default): deterministic skills only. LLM may answer
  conversationally but may not select a skill. This is MAXIE's current
  behaviour, minus the auto-learn injection hole.
- **smart**: the LLM may choose a skill, but the call is schema-validated and
  destructive capabilities still require confirmation.
- **agent**: bounded plan → execute → verify loop with an iteration cap and
  loop detection.

Making this explicit means the user chooses how much autonomy they grant, which
is exactly the property MAXIE's security model is built around.

### 3.3 Capability-based permissions — inverted from Leon/OVOS
Neither competitor has this. MAXIE's allowlist is currently keyed on intent
strings, which fails open as intents are added. Invert it: every skill declares
a capability set (`read`, `mutate`, `destructive`, `network`), and the gate
checks capabilities. Default-deny is strictly better than both competitors and
costs nothing to adopt.

### 3.4 Real plugin discovery — from OVOS `entry_points`
`Skills/` is a hardcoded list. Move to `importlib.metadata.entry_points` under
a `maxie.skills` group so a skill is a distributable package. This also makes
hot-reload and the GUI's "enable/disable skill" feature possible later.

### 3.5 Pipeline-shaped skills — from OVOS
`ovos` models a skill as a declared pipeline (stt → intent → skill → tts).
MAXIE's routing is already close to this shape. Formalising it makes skills
composable and makes barge-in/echo a property of the pipeline rather than of
each skill.

### 3.6 A bounded event bus — from the shape Leon/OVOS both assume
MAXIE already has `Core/event_bus.py`; it is dead and has a
callback-during-iteration bug. Either delete it or fix it properly and wire the
GUI's 200 ms poll to it. A working bus is the foundation for the scheduler
(proactive intelligence) and for cheap cross-module status instead of polling.

### 3.7 Resumable on-disk transcripts — from Leon's context files
Leon keeps user-editable Markdown context. MAXIE has an unbounded SQLite
`conversation` table that is never pruned. A simple bounded recent-turn file
plus a summarisation step gives the same benefit with a fraction of the
infrastructure.

### 3.8 Streaming ASR with cancellation — from all three
Every mature project streams and can abort. MAXIE's one-shot blocking
`transcribe()` is the outlier, and it is why the GUI race (TD-04) and the
cancellation path (TD-01) are so destructive.

---

## 4. What MAXIE should NOT copy

| Pattern | Why not |
|---|---|
| **Rhasspy 2.x as a dependency** | Archived April 2025. Depending on a dead project is how a personal assistant stops being maintained. Take the *lessons* (WebRTC VAD energy fallback, satellite separation), not the dependency. |
| **MQTT/Hermes as the internal bus** | Heavy operational surface for a single-user local assistant. If a protocol-style bus is wanted, follow Wyoming (gRPC/Unix sockets) — but only if the process-separation is actually needed. |
| **Unauthenticated message bus (OVOS, Rhasspy)** | Fine for loopback, unacceptable for MAXIE's opt-in LAN mode. MAXIE's token + fail-closed bind is **better** than both. Keep it, and add the missing caps/audit. |
| **Full TypeScript rewrite (Leon)** | MAXIE is Python, and the existing audio/ML stack (`faster-whisper`, `silero-vad`, `piper`) is Python-native. A rewrite would throw away working, tested code for stylistic parity. |
| **Client/server process split by default (Leon, Wyoming)** | Real benefit, high cost. MAXIE is single-process today. Only adopt if the remote story or a mobile client justifies it. |
| **A large skill marketplace ecosystem** | MAXIE's skill count is ~12. Plugin *mechanism* is worth having at ~5 skills; a marketplace is not. |

---

## 5. Bottom line

MAXIE is **not behind** Leon or OpenVoiceOS on features it claims to have — the
voice abstraction, allowlist model, confirm-before-destructive gate, and
LLM-never-executes rule put it ahead of both on safety. It is behind on
**reliability engineering** (state machines, cancellation, negative tests) and
on **agent capability** (planning, tool schemas, multi-step execution).

The comparison says the right order is: reliability first (a state machine and
cancellable subsystems), then the plugin/tool-schema layer, then a bounded agent
loop. Do not start with a process split, a protocol bus, or a language rewrite.
