# Contributing to LeSysBot

Thanks for wanting to improve LeSysBot! This guide walks you through a
contribution **step by step** — from picking what to build, through setting up
a dev environment, to opening a pull request. If you haven't yet, skim
[docs/architecture.md](docs/architecture.md) first: it explains how the pieces
fit and exactly which files each kind of change touches.

---

## 1. Pick your kind of contribution

Different contributions have very different footprints — most don't touch the
core at all:

| You want to… | What you'll write | Core code changed? | Start here |
|---|---|---|---|
| Give LeSysBot a new ability | A tool package in `tools/` | No | [§4](#4-contributing-a-tool) |
| Share a tool under your own GitHub account | Your own tool repo (no PR needed here!) | No | [docs/sharing-tools.md](docs/sharing-tools.md) |
| Support a new chat platform | An adapter in `lesysbot/messaging/` | One `elif` | [§5](#5-contributing-a-messaging-adapter) |
| Fix a bug / add a core feature | Code in `lesysbot/` + a test | Yes | [§6](#6-contributing-a-core-change) |
| Improve the docs | Markdown in `docs/` or the root | No | [§7](#7-contributing-documentation) |

> **Tools don't have to live in this repo.** Anyone can share tools from
> a plain GitHub repo and users install it with `lesysbot tools install you/repo`
> — no PR, no review, no waiting. Contribute a tool *here* when it's broadly
> useful enough to belong in the bundled catalog.

---

## 2. Set up your development environment

**Step 1 — Fork and clone.**

```bash
git clone https://github.com/<your-username>/lesysbot.git
cd lesysbot
git checkout -b my-change
```

**Step 2 — Install in editable mode with dev extras** (adds `pytest` + `ruff`
on top of `[all]`, so Telegram and Discord are both importable):

```bash
pip install -e ".[dev]"
```

**Step 3 — Verify the editable install actually won.** A stale *non-editable*
build in site-packages can shadow the repo, making your edits silently do
nothing:

```bash
python -c "import lesysbot; print(lesysbot.__file__)"
# → must print a path inside YOUR clone. If not, re-run: pip install -e .
```

**Step 4 — Confirm the toolchain runs clean before you change anything:**

```bash
pytest              # the whole suite runs in seconds, no LLM/network needed
ruff check lesysbot/  # lint
```

**Step 5 (optional) — Run the bot** to try things live. You'll need
[Ollama](https://ollama.com) with a model pulled for LLM chat, but slash
commands (and therefore most tool testing) work with no model at all:

```bash
lesysbot --provider cli          # chat + /commands
lesysbot --provider cli -v       # with DEBUG logging on screen
```

A dev checkout loads tools from the repo's `tools/` and reads `./config.yaml`
if you create one (`cp config/default.yaml config.yaml`).

---

## 3. Know your way around

```
lesysbot/            the package
├─ __main__.py       entry point: flags, logging, adapter wiring
├─ core/             Agent (the tool-calling loop), config, paths, tracing
├─ llm/              the OpenAI-compatible client (all backends)
├─ mcp/              tool registry, @tool decorator, CLITool, platform gating
├─ messaging/        CLI / Telegram / Discord adapters + the base interface
└─ install/          `lesysbot tools install` — fetch tool packages from GitHub
tools/             bundled tool packages (the catalog users get seeded with)
tests/             pytest suite — hermetic: no network, no LLM, temp dirs
docs/              user & contributor guides (see docs/README.md for the map)
scripts/           install/uninstall wizards (bash + PowerShell), exe build
config/            default.yaml — the documented default config
packaging/         PyInstaller spec for the Windows .exe
```

The full walkthrough of how these interact is
[docs/architecture.md](docs/architecture.md) — including a
[table of which files to touch for which change](docs/architecture.md#11-where-to-change-what).

---

## 4. Contributing a tool

**Step 1 — Scaffold a folder package** (the shareable form — a loose `.py` is
fine for private local tools, but bundled tools are packages):

```
tools/my-tool/
├─ README.md          # frontmatter: name, description, platforms, requires
└─ tool.py            # @tool functions and/or CLITool instances
```

Follow [docs/writing-tools.md](docs/writing-tools.md) for everything that goes
in `tool.py` — type hints (they become the LLM-facing schema), `confirm=` for
anything destructive, `platforms=`/`requires=` when it isn't universal.

**Step 2 — Test it live.** Run `lesysbot --provider cli`, then:

- check it appears in `/help` with the right signature;
- call it directly: `/my_tool arg=value` (works without an LLM);
- if you have a model running, ask for it in natural language too.

Hot reload means you can edit → save → retry without restarting.

**Step 3 — Update the catalog.** Add a row to
[tools/README.md](tools/README.md) so people browsing the repo can find it
(bundled packages install via `lesysbot tools install lesysbot/lesysbot/tools/<name>`).

**Step 4 — Lint, then open the PR** ([§8](#8-open-the-pull-request)). Tool
packages don't require unit tests, but the tool must load cleanly (step 2) and
`ruff check` must pass.

> Using Claude Code? The `.claude/skills/add-tool` project skill scaffolds all
> of this in one step.

---

## 5. Contributing a messaging adapter

**Step 1 — Subclass `MessagingAdapter`** in a new
`lesysbot/messaging/<platform>.py`, implementing `start()` and `send()`, and
override `confirm()` if the platform can show a yes/no UI. The annotated
template is in [docs/adapters.md §4](docs/adapters.md#4-building-a-custom-adapter).

**Step 2 — Wire it up:** add an `elif` to the provider block in
[lesysbot/__main__.py](lesysbot/__main__.py) (keep the import *inside* the branch —
adapters are imported lazily so optional deps don't break other providers) and
add a config model for its credentials in
[lesysbot/core/config.py](lesysbot/core/config.py) + [config/default.yaml](config/default.yaml).

**Step 3 — Offer the tools as native commands** *(if the platform has a command
menu)*: take the registry as an optional second constructor argument and build
the menu from [lesysbot/messaging/commands.py](lesysbot/messaging/commands.py) —
`all_commands(registry)` for the specs, `to_slash_text()` to render an
invocation back into `/name key=value` so it re-enters `Agent._handle_slash`
rather than becoming a second dispatch path. Register once at startup and treat
failure as non-fatal; see the Telegram and Discord adapters.

**Step 4 — Document it:** a setup section in
[docs/adapters.md](docs/adapters.md) following the Telegram/Discord pattern
(create the bot → get tokens → configure → run → troubleshoot), and a mention
in [docs/configuration.md](docs/configuration.md)'s reference block.

**Step 5 — Test:** adapters are hard to unit-test against a live platform, so
at minimum exercise the confirm/deny path and describe your manual test in the
PR. `tests/test_discord.py` shows the pattern: stub the client's connect call so
the registered handlers can be driven directly, no network needed.

---

## 6. Contributing a core change

**Step 1 — Write a failing test first** in `tests/`. The suite is hermetic —
tests build registries/agents over temp dirs, monkeypatch `LESYSBOT_HOME`, and
fake GitHub with `tests/install_utils.py` — keep yours the same (no network, no
real LLM). `asyncio_mode = "auto"` is set, so `async def` tests need no
decorator.

**Step 2 — Make the change.** Match the surrounding code's style; comments
only for constraints the code can't express.

**Step 3 — Run the checks:**

```bash
pytest                              # all
pytest tests/test_agent.py          # one file
pytest tests/test_agent.py::test_x  # one test
ruff check lesysbot/
```

**Step 4 — Update whatever the change makes stale:** `config/default.yaml` and
[docs/configuration.md](docs/configuration.md) for new settings,
[CLAUDE.md](CLAUDE.md) for architecture changes, the relevant guide in
`docs/` for behaviour changes.

**A note on the install scripts:** `scripts/install.sh` and
`scripts/install.ps1` are the same wizard twice and must stay in sync — change
both. The PowerShell one can't run in CI, so verify it by careful inspection
(and say so in the PR). In `install.sh`, mind `set -euo pipefail`: use
`i=$((i+1))`, never `((i++))` (which aborts the script when the result is 0).

---

## 7. Contributing documentation

The docs are written **user-first**: someone who just wants the thing to work
should be able to read the top of a page, run the commands, and stop. When
editing:

- **Lead with the shortest path that works.** The plain-language answer and a
  copy-pasteable command come before any explanation of why.
- **Push internals into a `<details>` block.** If a reader who only wants it
  working doesn't need a paragraph, wrap it:

  ```markdown
  <details>
  <summary><b>Under the hood — how X works</b></summary>

  … the technical detail …

  </details>
  ```

  Keep the blank line after `</summary>` — that's what lets the markdown inside
  render, both on GitHub and on the docs site. Two or three of these at the end
  of a page is normal; a page that needs ten probably wants splitting.
- **Don't number headings** on the user-facing pages (`getting-started`,
  `usage`, `configuration`, `writing-tools`, `installing-tools`, `service`,
  `management-ui`, `troubleshooting`) — make them the question the reader is
  asking. The reference pages (`adapters`, `architecture`, `building-windows-exe`)
  keep their numbering, and cross-links to them use those anchors.
- **Symptoms and fixes go in [troubleshooting.md](docs/troubleshooting.md)**,
  not in a per-page table. Link to it instead.
- **Cross-link rather than repeat** — each fact should have exactly one home.
- **New page?** Add it to [docs/README.md](docs/README.md), the root README's
  "What next?" table, and the docs site (`content/<version>/nav.json` plus the
  `GUIDES` map in `scripts/import-docs.js`) — the site imports guide markdown
  straight from `docs/`, so a page missing from that map never appears.

---

## 8. Open the pull request

**Step 1 — Final check:**

- [ ] `pytest` passes
- [ ] `ruff check lesysbot/` is clean
- [ ] New behaviour is covered by a test (core changes) or a live `/help` +
      invocation check (tools)
- [ ] Docs updated (the page that documents what you changed, plus
      [docs/README.md](docs/README.md) if you added a page)
- [ ] Destructive tools set `confirm=`

**Step 2 — Commit** using the conventional style you'll see in `git log`:

```
feat(registry): support nested tool packages
fix(installer): stop arrow-key menu ghosting when labels wrap
docs: explain trace file rotation
```

**Step 3 — Push and open the PR.** Explain *what* and *why*, note anything you
couldn't test automatically (PowerShell, a live platform), and link related
issues. Small focused PRs get reviewed fastest.

---

## Questions?

Open a GitHub issue — including for "is this a good idea?" questions before
you build something large. For understanding the code, start with
[docs/architecture.md](docs/architecture.md); the finer-grained internals live
in [CLAUDE.md](CLAUDE.md).
