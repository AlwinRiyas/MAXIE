# MAXIE — Code Review Package

Complete, runnable source snapshot of the **MAXIE** personal AI assistant,
prepared for external code review.

**Start here:** [`REVIEW_REPORT.md`](REVIEW_REPORT.md)

## Contents

| File | Purpose |
|---|---|
| `REVIEW_REPORT.md` | The main review report — architecture, features, partials, bugs, tests, phase, remaining work, dependencies, entry points, design decisions, security review |
| `FILE_TREE.txt` | Complete file tree with per-file sizes; 0-byte placeholders are flagged `(EMPTY)` |
| `EXCLUSIONS.md` | Exactly what was excluded and why, including one deliberate deviation (`Installers/`) |
| `AGENTS.md` | Project conventions, architecture map, security rules (authoritative) |
| `DEVELOPMENT_STATUS.md` | Author's status summary (note: stale, claims 90 tests — actual 138) |
| `README.md`, `USER_GUIDE.md`, `CHANGELOG.md` | Project documentation |
| `Docs/` | `MAXIE_PRINCIPLES.md` has content; 5 other docs are 0-byte placeholders |
| `AI/ Automation/ Brain/ Config/ Conversation/ Core/ Interface/ Installers/ Logs/ Memory/ Security/ Skills/ Tests/ Ui/ Voice/ Weather/ WakeWord/ Models/ Plugins/ Resourses/ Vision/` | Source code, verbatim |
| `requirements.txt`, `.gitignore`, `Skills/app_database.json`, `Config/*.json` | Configuration needed to understand the architecture |

## Quick facts

- **Python 3.10+** (verified on 3.14.7); Windows primary, Linux dev
- **126 source files**, ~8,170 Python LOC (~1,450 tests)
- **138 tests — 137 pass, 0 fail, 1 skip** (`requires sounddevice`)
- `python -m compileall -q .` → **PASS**
- No mic/speaker hardware was available; voice-hardware paths are unverified
- Commits at `0a97dab` "MAXIE MVP voice baseline"

## Verify this package yourself

```bash
python -m compileall -q .      # expect: clean, exit 0
python Tests/run_tests.py      # expect: Ran 138 tests ... OK (skipped=1)
python run.py --console        # optional: interactive console
```

Both commands run **fully headless** — no microphone, speaker, GPU, or Ollama
required. Optional native dependencies are lazily imported and fenced by
design.

## Top review targets

1. **`AI/ai_engine.py:82-84`** — `_is_offline_message()` matches only
   connection errors, so timeout/error replies get written into the
   conversation context as if they were real answers (bug B1, reproduced in
   the report).
2. **`Interface/remote_server.py:37-43`** — LAN binding fails closed without a
   token: the security model works as documented.
3. **`Security/permissions.py`** — the 30-intent allowlist; LLM output is
   never executed.
4. **`Skills/calculator.py`** — AST allowlist, no `eval`/`exec` anywhere.
5. **Cleanup targets** — `WakeWord/` (4 empty files), 5 empty `Docs/*.md`,
   empty `Voice/Core/`, empty `Config/voice_config.py`.
