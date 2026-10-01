# MAXIE — SECURITY AUDIT

**Date:** 2026-09-28 · **Auditor pass:** full source read, plus runnable probes
for every finding marked *probed*.
**Scope:** local-first single-user assistant, Windows primary / Linux dev, with
an opt-in LAN HTTP endpoint.

---

## 1. Threat model

MAXIE is a **local-first, single-user** assistant. The realistic adversaries are:

| Adversary | Capability | In scope |
|---|---|---|
| Anyone on the LAN, once the user opts in | reach `http://<laptop-ip>:8778` | yes |
| A malicious/wrongly-phrased utterance picked up by the mic | drive the router | yes |
| Prompt injection via web/YouTube/search content fed to the LLM | influence the model | yes |
| Another local process/user on the machine | read `Config/`, `Memory/`, `Logs/` | yes |
| A crash or malformed request | availability | yes |

Explicitly **out of scope**: physical access with root, kernel compromise,
supply-chain compromise of `pip` packages, and attacks on Ollama's own HTTP API
(bind it to loopback).

---

## 2. Controls that are correct and must be preserved

These are genuine, load-bearing, and verified in source:

1. **LLM output is never executed.** Model text is returned to the user; it is
   not `eval`'d, not shelled, and never re-fed into skill dispatch.
2. **Skills are an explicit allowlist** (`Security/permissions.py`).
3. **Destructive actions require explicit confirmation.** `POWER_*` and friends
   never reach a skill without a user yes/confirm round-trip. Linux dev boxes
   additionally require `allow_local_power_control: true`, default `False`.
4. **Calculator uses an `ast` allowlist**, not `eval`/`exec`.
5. **Remote binding fails closed.** A non-loopback bind without a token raises
   at construction (`Interface/remote_server.py:39-43`); a whitespace-only token
   normalises to empty and is therefore refused.
6. **Secrets are not in code.**

---

## 3. Findings

Severity: **CRITICAL** = remote or unauthenticated impact; **HIGH** = local-user
or integrity impact; **MEDIUM** = hardening; **LOW** = hygiene.

### SEC-01 — CRITICAL — Unbounded request body on `/voice` and `/command`
`Interface/remote_server.py:234-238`, `:268-275`

`Content-Length` is trusted and passed directly to `rfile.read(length)`.

```python
length = int(self.headers.get("Content-Length") or 0)
data = self.rfile.read(length)      # attacker controls `length`
```

Combined with TD-07 (`ThreadingHTTPServer`, `daemon_threads = True`) and
`core_manager.py:75` constructing a new `Transcriber` per request, a handful of
concurrent requests with large `Content-Length` headers is a cheap memory
exhaustion / CPU exhaustion DoS.

**Fix:** reject `Content-Length` above a hard cap (e.g. 10 MB for `/voice`,
64 KB for `/command`) *before* reading; wrap the read so a client that lies
about length cannot stream indefinitely; add a token-bucket rate limiter keyed
on token; cache one `Transcriber` process-wide instead of per request.

### SEC-02 — CRITICAL — Live remote token is committed to Git
`Config/system_config.json` (git-tracked), `.gitignore`

`git ls-files Config/` lists `system_config.json`; `.gitignore` contains only
`Config/tts_models/`. The worktree file is 607 bytes of live configuration
including a `remote_server.token` field, against a 0-byte blob in HEAD.

**Impact, stated precisely:** the value of `remote_server.token` in the current
worktree is **empty** (verified: length 0), and the HEAD blob is 0 bytes, so **no
live secret is exposed today**. The risk is prospective, not realised: the first
real token anyone sets is one `git commit -a` away from publication, and any
clone of this repository carries whatever the config held at commit time. The
config also leaks non-secret personal state (user name, mic choice, TTS engine).
`AGENTS.md`'s claim that tokens live in gitignored files is false today.

**Status: CLOSED 2026-09-28, hardened 2026-10-01.** Steps 1, 2 and 4 are
done: `Config/*.json` is ignored with `!Config/*.example.json`, the three live
files are untracked, and the three example files are committed. No token needs
rotating (the value was empty throughout).

**What the first pass missed.** The fix was a snapshot of one afternoon, and
step 5 was never done — nothing stopped a later `git add -f
Config/system_config.json` or an edited `.gitignore` from reintroducing it. Two
things were found while closing that gap:

1. **`Memory/memory.json` was tracked in three commits while an ignore rule for
   it sat in `.gitignore` the whole time.** `.gitignore` does not untrack
   anything already committed. The file carried real user facts
   (`"gym": "6 PM"`, a college name). It is now untracked, but it remains in
   history — rewriting that is a force-push and the owner's call.
2. Key material and the SQLite store had no ignore rules at all.

`Tests/repo_hygiene_test.py` (14 tests) now asks git directly, so the exposure
fails on the commit that reintroduces it:

- no live `Config/*.json` tracked, while the three `*.example.json` stay tracked;
- every named live config is `git check-ignore`-confirmed;
- **no file that `.gitignore` lists is still tracked** — the generic check that
   would have caught `Memory/memory.json` on day one;
- committed examples contain no credential-shaped value and no private address;
- no tracked file contains a `remote_token` literal;
- `*.pem`/`*.key`/`id_rsa`/`.env` and `Memory/*.db` are ignored.

**Still open (owner's decision, not code):** `Memory/memory.json` is in history.
Purging it needs `git filter-repo` plus a force-push and a re-clone by anyone who
already has the repo. The content is three gym/college facts, not a credential.

### SEC-03 — HIGH — Wildcard CORS on a token-gated API
`Interface/remote_server.py:163-168`

`Access-Control-Allow-Origin: *` is emitted on every response, including 401s.

**Impact:** any web page in any browser the user has open can issue cross-origin
requests to `http://127.0.0.1:8778`. Loopback is not a security boundary against
a browser — this is the classic DNS-rebinding/CSRF-to-localhost pattern. Combined
with the token check the attacker still needs the token, but the wildcard
removes the last line of defence against a leaked token and makes `/health` and
`/ui` freely readable by any site.

**Fix:** default to no CORS header. Allow an explicit origin allowlist from
config (`remote_server.allowed_origins`), defaulting to empty; handle `OPTIONS`
with `Access-Control-Allow-Methods` only for matched origins.

### SEC-04 — HIGH — Non-constant-time token comparison
`Interface/remote_server.py:61`

```python
supplied.strip() == self.token
```

**Fix:** `hmac.compare_digest(supplied.encode(), self.token.encode())`.
Note this also removes the incidental `.strip()` normalisation — do that
explicitly first, and re-verify the whitespace-only-token fail-closed case.

### SEC-05 — HIGH — Internal detail disclosed to remote clients
`Interface/remote_server.py:75`, `:296`, `:304`; `AI/ollama_client.py:74`

- `/command` returns `f"Command failed: {error}"` — arbitrary exception text,
  including stack fragments and paths.
- `/voice` returns `{"error": str(error)}` as **HTTP 200** with `ok: True`
  spliced in.
- `OllamaClient` embeds the internal URL in the message returned to the user
  (`ollama_client.py:74`), so a misconfigured or proxied address is spoken aloud
  and pushed to the phone.

**Fix:** generic client-facing text, unique request id for correlation, full
detail to the log at WARNING. Return correct HTTP status codes
(400/401/404/413/429/500) and stop splicing `ok: True` into error bodies.

**Status: CLOSED (2026-09-30).** Remote half: `/command` and `/voice` return
only generic text (`"Command could not be started."`, `"Voice processing
failed."`, `"MAXIE took too long to respond."`) with correct status codes; the
raw exception goes to `logger.error` only. Provider half: `OllamaClient` returns
the constant `GENERIC_ERROR_MESSAGE` and never embeds the internal URL, and
`AIEngine._is_offline_message` stops all four failure strings from reaching
memory. Asserted in `Tests/remote_server_test.py`
(`test_error_body_does_not_disclose_internal_detail`,
`test_voice_error_uses_status_500_and_no_internal_detail`) and
`Tests/ai_test.py` / `Tests/ollama_client_test.py`.

### SEC-06 — HIGH — Unvalidated persistent write path from free-form speech
`Brain/brain_router.py` `_auto_learn()`; `Memory/memory_engine.py:71-73`

`_auto_learn` runs on nearly every utterance (`:52`) and persists a
substring-derived fact. Its markers (`"i like "`, `"i love "`, `"i study "`,
`"my favorite"`) match inside longer utterances, so `"i don't like waiting"`
stores `don't like waiting`. Keys are the first five non-stopword words, so
distinct facts collide and last-write-wins silently overwrites.

**Security impact:** any audible content — a podcast, a video, a YouTube
result, a prompt-injected web page read aloud — becomes durable memory that is
re-injected into every future system prompt. This is a **persistent prompt
injection** channel, and it survives reboot.

**Fix:** a dedicated non-LLM parser with negation/quoted-speech handling; an
explicit confirmation for anything persisting; a cap on facts per session;
stopword/verb-list based keying instead of positional truncation; and never let
auto-learned text reach a privileged position in the system prompt.

### SEC-07 — MEDIUM — CLOSED 2026-10-01 — Capabilities, not a known-bad list
`Security/permissions.py`; `Brain/brain_router.py` confirmation gate

*The finding:* the gate matched intent **names** in a hand-maintained
`DESTRUCTIVE` set, so a new destructive intent ran ungated if whoever added it
forgot to touch that second list. The docstring claimed the opposite.

*What it is now.* Every allowlisted intent declares its capabilities
(`CAPABILITIES`: `power.system`, `memory.irreversible`, `device.unlock`, …) and
the gate checks `DESTRUCTIVE_CAPABILITIES` instead of a list of names.
`DESTRUCTIVE` is **derived** at import, so it cannot drift from
`CAPABILITIES`. Both directions of developer error are now safe:

- forgetting to declare an intent's capability → gated (fail-closed),
- declaring a benign capability → deliberate, and visible as a diff here.

An allowlisted-but-undeclared intent is gated. An intent that is neither
classified nor allowlisted (the router's `UNKNOWN`) is not gated, because it
cannot execute either — `can_execute` already refuses it, and a refusal is not
a confirmation prompt.

`can_execute` remains default-deny: only `ALLOWED` can run, so no capability
declaration ever widens what MAXIE may do.

Covered by `Tests/permissions_test.py::CapabilityDeclarationTest` (7 tests).
Verified in both directions — reverting `permissions.py` fails them.

### SEC-08 — MEDIUM — Bulk memory delete is untested and unguarded
`Brain/brain_router.py` `DELETE_MEMORY` with `"all"` / `"everything"`

A spoken "delete all memories" path with no test, no audit trail, and no
confirmation distinct from ordinary deletion.

**Fix:** require explicit confirmation, log the wipe, and add a test.

### SEC-09 — MEDIUM — Secret and full-text leakage into logs and memory
`Brain/brain_router.py:44`; `Conversation/conversation_engine.py:149`, `:218`;
`Logs/` mode `0777`

User utterances are logged in plaintext three times, persisted forever in
SQLite, and pushed to the phone. Log files are world-readable and writable.

**Fix:** `chmod 0600` on `Logs/` and `Memory/`; content at DEBUG behind a config
flag with a hash at INFO; retention sweep; a redaction pass for anything
resembling a token; document that the phone is a trusted endpoint.

### SEC-10 — MEDIUM — `/health` and `/ui` are unauthenticated
`Interface/remote_server.py` `/health`, `/ui`

`/health` is low-risk but is a useful LAN fingerprint (confirms MAXIE exists,
its version surface, and its uptime). `/ui` is a functional mobile control page
whose *commands* are token-checked but whose presence and content are not.

**Fix:** make `/health` return a minimal payload with no version; gate `/ui`
behind the token as well (the mobile page can carry the token in the URL hash or
a cookie), or accept it as an explicit documented trade-off.

### SEC-11 — MEDIUM — No rate limiting or audit log for remote commands
`Interface/remote_server.py`

No limit on command rate; no record of *who* issued a command beyond the shared
token. A leaked token grants full, unlogged, unlimited remote control including
shutdown.

**Fix:** per-token rate limit; append-only audit log of timestamped commands with
a source address; consider a second factor (a rotating nonce) for destructive
commands.

**Status: CLOSED (2026-09-30).** All four parts are in place:
1. Per-client token-bucket rate limiting (429 past the bucket), plus
   `remote_server.max_connections` capping live request threads (TD-07).
2. Append-only audit log that records **accepted** commands as well as
   rejected ones, with client address, outcome, request id, and the
   command text redacted to a length + digest (TD-17).
3. Request-id correlation: every response carries `X-MAXIE-Request-Id`
   (8 hex chars), echoed in the audit entry and in the error-log lines, so
   a user can quote the id of a failed command.
4. Second factor for destructive commands: a destructive action can no
   longer be asked for and confirmed in the same utterance. "yes shut down"
   is refused and re-prompted; only a bare confirmation ("yes") in a later
   turn executes the held action, which expires after
   `confirm_ttl_seconds` (default 60) and is bound to the client that
   raised it, so one device cannot confirm another device's prompt.

A rotating nonce was considered and rejected: a nonce stops replay, not a
live attacker who holds the token, so it would add ceremony without
changing the threat. The two-step confirmation is the control that
actually limits the blast radius of a leaked token.

### SEC-12 — MEDIUM — Blocking network I/O in a signal handler
`Core/core_manager.py:95-98` → `Interface/remote_server.py:122`

`_handle_signal` calls `self._server.shutdown()`, which blocks on the
`serve_forever` thread. Deadlock risk during shutdown, and signal handlers must
not do blocking I/O.

**Fix:** set a flag or write a byte to a self-pipe; let the main loop notice and
shut down cleanly.

### SEC-13 — LOW — Loopback check normalisation edge cases
`Interface/remote_server.py:20`, `:29-31`

`"" in LOOPBACK_HOSTS` is unreachable because `__init__` normalises the host
first. Behaviour is correct; the constant is misleading. Add a test asserting
that a whitespace-only token refuses a LAN bind.

### SEC-14 — LOW — `exec_module` on an installer from the GUI constructor
`Ui/gui.py:12-17`

`Installers/set_autostart.py` is re-executed on every GUI construction, bypassing
the import cache. Not a vulnerability today (the file is ours), but it is
unnecessary dynamic code execution in a startup path.

**Fix:** import it normally behind `try/except ImportError`.

---

### SEC-15 — MEDIUM — A model that can chain skills amplifies every other finding
`AI/llm_planner.py`, `Skills/agent_executor.py`, `Brain/brain_router.py:_run_plan`

Shipping a bounded agent loop (Phase 12.2-12.6) turns any weakness in a single
skill into a repeatable multi-step capability: a prompt-injected utterance can
now aim several allowlisted skills at one goal instead of one. The loop itself
is the finding — it is a new privilege boundary, not a new bug.

**Status: CLOSED by design (2026-09-30), with one accepted gap.** The controls,
each with a test that fails if it is removed (`Tests/agent_test.py`, verified by
mutation):

1. **Two switches, not one.** `ai.routing_mode: "agent"` alone is refused at
   config load; `ai.agent_enabled: true` is required as well, and the router
   falls back to `controlled` if a value is poked into memory. Nothing is
   autonomous in the shipped config.
2. **Nothing destructive is reachable.** Destructive intents are never in the
   planner's tool list, `parse_plan` refuses a plan naming one, and the executor
   re-checks `Permissions.requires_confirmation` at dispatch time. A model
   cannot obtain or consume a SEC-11 confirmation.
3. **Whole-plan validation.** One failing step discards the entire plan, so a
   rejected plan cannot execute its safe half and leave evidence of having got
   partway.
4. **Ceilings.** `ai.agent_max_iterations` / `ai.agent_max_steps` (1-10, bounded
   by `Config.SCHEMA`) cap a single goal.
5. **Loop detection.** A repeated `(skill, arguments)` stops the run at plan
   time and again at dispatch time.
6. **Rollback is honest.** Only steps whose skill declared a compensating action
   are reverted, in reverse order, and a failure is reported as partial rather
   than as a clean undo.

**Accepted gap:** no skill declares a compensating action yet, so the rollback
surface is implemented but unused (ROADMAP 12.9 stays PARTIAL). Also note the
loop inherits SEC-06's prompt-injection exposure in full — `_auto_learn`'s
quoted-speech guard protects the transcript, not the planner's goal string, so a
`plan` is still built from the user's own utterance only. Any future source of
planner input (a calendar, an email, a web page) must be re-reviewed before it
is allowed near `plan_prompt`.

**Related, and the reason 12.10 is off by default:** the running conversation
summary is model-written text that is re-injected into every later prompt, so
it is an injection channel with a long reach — anything the model once read
aloud could be compressed into it. Three properties keep it inert rather than
useful (`Tests/context_summary_test.py`):
1. it is stored with the `assistant` role and injected with an
   `Earlier in this conversation:` marker, so it cannot arrive as a fresh
   instruction from the user;
2. it only ever summarises rows the user themselves produced in this
   conversation — no external text is folded in;
3. it is disabled unless `ai.summarise_after_turns` is set, and a failed
   summary leaves the rows in place rather than substituting model text for
   the user's own words.

---

## 4. What was probed vs. inferred

| Finding | Evidence |
|---|---|
| SEC-01 unbounded body | source read |
| SEC-02 token tracked | `git ls-files Config/`, `.gitignore` |
| SEC-03 wildcard CORS | source read |
| SEC-04 timing-unsafe compare | source read |
| SEC-05 detail disclosure | source read |
| SEC-06 auto-learn injection | source read; `i don't like waiting` traced by hand |
| SEC-08 bulk delete | source read; no test exists |
| TD-12 `"True"` rows | **probed** against the live DB — 4 rows |
| TD-18 `search("%")` returns all rows | **probed** |
| TD-19 stopword false positive | **probed** — `any_recall("tell me about the institute")` → college |
| TD-11 `get_context(0)` returns 100 rows | **probed** |
| TD-09 18-byte config → 603 bytes on read | **probed** |
| Concurrency data loss in memory (7 `InterfaceError`s, 86% loss) | **probed** with a 4-thread pool |
| Voice pipeline R1–R3 | **probed** where possible; mic/player hardware absent, so end-to-end confirmation needs the laptop |
| SEC-15 agent loop gates | **probed by mutation** — each of the six gates was removed in turn and the corresponding test failed; a real Ollama was not consulted for plan quality |

## 5. Remediation order

1. ~~**SEC-02** — stop the token leak before any commit. Rotate it.~~ **CLOSED** 2026-09-28; test-enforced since 2026-10-01. `Memory/memory.json` still in history (owner call).
2. **SEC-01** — body caps and rate limit. Cheap, removes a DoS.
3. **SEC-05**, **SEC-04**, **SEC-03** — remote boundary hygiene.
4. **SEC-06** — close the persistent prompt-injection channel.
5. ~~**SEC-07** — invert the permission model to default-deny capabilities.~~
   **CLOSED 2026-10-01.**
6. **SEC-09**, **SEC-10**, **SEC-11**, **SEC-12** — hardening and auditability.

Everything above is compatible with the existing design philosophy: MAXIE is
local-first, and the LLM-never-executes rule is exactly the property that makes
prompt injection survivable. The work is to stop *persisting* injected text, not
to abandon the philosophy.
