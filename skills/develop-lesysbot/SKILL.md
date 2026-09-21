---
name: develop-lesysbot
description: Maintain and extend the LeSysBot codebase — dev environment setup, architecture map (what lives where, which files to touch for which change), running tests and lint, adding a messaging adapter or config setting, install-script rules, docs conventions, and the PR checklist. Use when asked to "fix a bug in lesysbot", "add a feature", "add a Discord adapter", "run the tests", or "contribute to lesysbot".
---

# Develop LeSysBot (maintainers & contributors)

## Dev environment

```bash
git clone https://github.com/<you>/lesysbot.git && cd lesysbot
git checkout -b my-change
pip install -e ".[dev]"        # editable + pytest + ruff

# CRITICAL: verify the editable install won. A stale NON-editable build in
# site-packages silently shadows the repo — edits appear to do nothing:
python -c "import lesysbot; print(lesysbot.__file__)"   # must print a path in THIS clone
# if not: pip install -e .

pytest                # whole suite, seconds, no LLM/network needed
ruff check lesysbot/    # lint
```

Live run: `lesysbot --provider cli` (`-v` for DEBUG on screen). Slash commands
and tool testing need **no model**; only LLM chat needs Ollama. A dev checkout
loads the repo's `tools/` and reads `./config.yaml` if present
(`cp config/default.yaml config.yaml`).

## Architecture in one screen

Three independent layers wired by `Agent` (`lesysbot/core/agent.py`):

```
MessagingAdapter → Agent.handle(user_id, text) → LLMClient → ToolRegistry → reply
```

Text starting with `/` dispatches straight to the tool registry — the LLM is
never called. Otherwise the message joins the per-user history, goes to the
LLM with all tool schemas, and returned `tool_calls` are executed (parallel via
`asyncio.gather`, sequential when any tool has `confirm=`) in a loop capped by
`agent.max_tool_calls`.

That LLM loop holds a **per-user `asyncio.Lock`** (`Agent._turn_lock`), so a
message arriving mid-turn queues instead of starting a second `handle()` over
the same history — adapters dispatch updates concurrently (Telegram requires
`concurrent_updates(True)` for confirmations to work), and two loops sharing one
`ConversationHistory` made the model re-run tools it had already run and reply
twice. Keep it **per user, not global**, and keep the `/` path outside it: slash
commands never touch the history, and `/cancel_shutdown` must stay answerable
while the turn that scheduled the reboot is still running.

```
lesysbot/
├─ __main__.py     entry point: flags, logging setup, adapter wiring (if/elif)
├─ core/           Agent (tool-calling loop), config (pydantic Settings),
│                  paths (~/.lesysbot anchoring), trace.py, sysinfo.py
├─ llm/            single AsyncOpenAI client, configurable base_url (all backends)
├─ mcp/            registry (discovery/hot-reload/gating), @tool decorator,
│                  CLITool, platform gating, `lesysbot tools` CLI
├─ messaging/      base interface + CLI / Telegram / Discord adapters,
│                  startup notice
└─ install/        `lesysbot tools install` engine (zipball fetch, lockfile)
tools/             bundled tool packages (the seeded catalog)
tests/             hermetic pytest suite — no network, no LLM, temp dirs
scripts/           install/uninstall bootstrap (bash), logo generator
config/            default.yaml — the documented default config
monitoring/        the Prometheus + Grafana stack `lesysbot setup` seeds
docs/              user & contributor guides
```

### Where to change what

| I want to… | Touch |
|---|---|
| Add a capability (new tool) | a new folder in `tools/` — no core code (see [write-tool](../write-tool/SKILL.md)) |
| Support a new chat platform | new file in `lesysbot/messaging/` + one `elif` in `lesysbot/__main__.py` |
| Support a new LLM backend | usually nothing — set `llm.base_url` |
| Change tool-calling loop / history / confirmations | `lesysbot/core/agent.py` |
| Change tool discovery / gating / hot reload | `lesysbot/mcp/registry.py` |
| Add a config setting | `lesysbot/core/config.py` + `config/default.yaml` + `docs/configuration.md` |
| Change the install wizard | `lesysbot/setup/` — `scripts/install.sh` only bootstraps into it |

## Tests

```bash
pytest                               # all
pytest tests/test_agent.py           # one file
pytest tests/test_agent.py::test_x   # one test
```

Conventions (keep new tests the same):

- **Hermetic**: registries/agents built over temp tool dirs; `LESYSBOT_HOME`
  monkeypatched for the `~/.lesysbot` fallback; GitHub faked via
  `tests/install_utils.py` (`make_github_zip` builds GitHub-shaped zipballs,
  `FakeFetcher` serves them and records requested URLs). No network, no LLM.
- `asyncio_mode = "auto"` (pyproject) — `async def` tests need no decorator.
- Core changes: write a failing test first.

## Adding a messaging adapter

1. Subclass `MessagingAdapter` (`lesysbot/messaging/base.py`) in
   `lesysbot/messaging/<platform>.py`; implement `start(handler)` (call
   `await handler(user_id, text)` per incoming message, `send()` the reply)
   and `send(user_id, text)`. Override `confirm(user_id, tool_name, prompt,
   args) -> bool` if the platform can show yes/no UI (default auto-approves).
2. Wire an `elif` in the provider block of `lesysbot/__main__.py`, keeping the
   import **inside** the branch (adapters load lazily so optional deps don't
   break other providers), and ensure `agent.set_confirm_fn(adapter.confirm)`.
3. Add a config model for its credentials in `lesysbot/core/config.py` +
   `config/default.yaml`.
4. Document: a setup section in `docs/adapters.md` (create bot → tokens →
   configure → run → troubleshoot) + the `docs/configuration.md` reference
   block. Adapters are hard to unit-test live — exercise confirm/deny at
   minimum and describe the manual test in the PR.

## Install-script rules

`scripts/install.sh` and `scripts/uninstall.sh` are **bootstrap only** — Python
check, pip install, hand off to `lesysbot setup`. Keep logic in the Python
wizard. `install.sh` runs under `set -euo pipefail`: use `i=$((i+1))`, never
`((i++))` (exit status 1 on zero result aborts the script). CI runs
`shellcheck --severity=error` on them.

## Docs conventions

Top-down (overview → detail), step-by-step, one job per page. Each fact has
**one home** — cross-link rather than repeat. New pages slot into
`docs/README.md`'s reading order and the root README's documentation table.
Behaviour changes update the guide that documents them (and `CLAUDE.md` for
architecture changes; the `skills/` folder mirrors the docs — update the
matching skill too).

## PR checklist

- [ ] `pytest` passes; `ruff check lesysbot/` clean
- [ ] New behaviour covered by a test (core) or a live `/help` + invocation check (tools)
- [ ] Docs updated (the page documenting what changed; `docs/README.md` if a page was added)
- [ ] Destructive tools set `confirm=`
- [ ] Commit style: `feat(registry): …`, `fix(installer): …`, `docs: …`

Isolated end-to-end verification without touching a real `~/.lesysbot`:
see the scratch-environment recipe in
[troubleshoot-lesysbot](../troubleshoot-lesysbot/SKILL.md).

Finer-grained internals (module edge cases, loader details) live in the repo's
`CLAUDE.md` and `docs/architecture.md` — this skill is the self-contained
summary; those files are the deep end.
