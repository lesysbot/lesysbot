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
> a plain GitHub repo and users install it with `lesysbot install you/repo`
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
lesysbot chat          # chat + /commands
lesysbot chat -v       # with DEBUG logging on screen
```

A dev checkout loads tools from the repo's `tools/` and reads `./config.yaml`
if you create one (`cp config/default.yaml config.yaml`).

---

## 3. Know your way around

```
lesysbot/            the package
├─ __main__.py       entry point: flags, logging, adapter wiring
├─ cli/              `lesysbot install|update|search|doctor|dashboard|…`
├─ core/             Agent (the tool-calling loop), config, paths, grafana, tracing
├─ llm/              the OpenAI-compatible client (all backends)
├─ mcp/              tool registry, @tool decorator, CLITool, requirement gating
├─ messaging/        CLI / Telegram / Discord adapters + the base interface
├─ management/       the loopback panel on :8700 (stdlib http.server, no deps)
├─ artifacts/        fetch tool AND dashboard packages from GitHub; lock; catalog
├─ prereq/           what a package needs, whether this machine has it, the fix
└─ dashboards/       render installed dashboard packages for Grafana
tools/             bundled tool packages
dashboards/        bundled dashboard packages (System Overview)
dashboard/         the Prometheus + Grafana stack (compose, scripts, provisioning)
catalog.json       the marketplace index — metadata pointing at GitHub links
hatch_build.py     copies the four above into the wheel, minus local state
tests/             pytest suite — hermetic: no network, no LLM, temp dirs
docs/              user & contributor guides (see docs/README.md for the map)
scripts/           install/uninstall bootstrap (bash), logo generator
config/            default.yaml — the documented default config
dashboard/         the Prometheus + Grafana stack `lesysbot setup` seeds
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
├─ README.md          # frontmatter: name, description, requires
└─ tool.py            # @tool functions and/or CLITool instances
```

Follow [docs/writing-tools.md](docs/writing-tools.md) for everything that goes
in `tool.py` — type hints (they become the LLM-facing schema), `confirm=` for
anything destructive, `requires=` for every program it shells out to.

**Step 2 — Test it live.** Run `lesysbot chat`, then:

- check it appears in `/help` with the right signature;
- call it directly: `/my_tool arg=value` (works without an LLM);
- if you have a model running, ask for it in natural language too.

Hot reload means you can edit → save → retry without restarting.

**Step 3 — Update the catalog.** Add a row to
[tools/README.md](tools/README.md) so people browsing the repo can find it
(bundled packages install via `lesysbot install lesysbot/lesysbot/tools/<name>`).

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

**A note on the shell scripts:** `scripts/install.sh` is **POSIX `sh`**, not
bash: the documented install command pipes it into `sh`, which is dash on Debian
and Ubuntu, so `[[ ]]`, arrays, `BASH_SOURCE` and a bare `set -o pipefail` all
break there. Every *other* script is bash.
`tests/test_shell_portability.py` enforces that split, and CI additionally runs
`shellcheck --shell=sh --severity=warning scripts/install.sh` — bashisms are
SC3xxx *warnings*, so the error-only pass misses all of them.

**Testing either installer against a scratch directory:** always set
`LESYSBOT_SKIP_SERVICE=1`. `LESYSBOT_HOME` and `--prefix` do not relocate the
LaunchAgent / systemd unit / scheduled task, so without it a test run replaces
the service on your own machine.

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
  asking. The reference pages (`adapters`, `architecture`) keep their
  numbering, and cross-links to them use those anchors.
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
couldn't test automatically (a live Telegram/Discord bot, for instance), and
link related issues. Small focused PRs get reviewed fastest.

CI runs automatically on the PR. What has to be green before it can merge is
[§9](#9-how-main-is-protected).

---

## 9. How `main` is protected

You can't push to `main` directly — every change lands through a pull request.
Two things gate the merge button:

- **`CI OK` must be green.** That's a single check that turns green only when
  the whole matrix, the base-install job and both script linters have passed.
- **Your branch must be up to date with `main`.** If `main` moved while you
  worked, merge it in (`git merge origin/main`) and push again; GitHub will
  re-run CI on the result.

Nothing else blocks you — reviews are set to **0 required approvals**, so a
maintainer can merge their own PR once CI is green.

<details>
<summary><b>Why one <code>CI OK</code> check instead of the five real ones</b></summary>

`.github/workflows/ci.yml` produces five checks — three from the
`{3.11, 3.12, 3.13}` matrix, plus `Base install (no extras)` and
`Shell script analysis`.

Requiring those by name is a trap: the moment the matrix changes — a dropped
Python version, a renamed runner — the required check name never reports again,
and **every open PR hangs on "Expected — waiting for status"** with no way out
but an admin bypass. So the ruleset requires only `ci-ok`, an aggregation job
that `needs:` all three:

```yaml
  ci-ok:
    name: CI OK
    if: always()
    needs: [test, base-install, shell-lint]
```

`if: always()` is load-bearing. Without it GitHub *skips* the job when a
dependency fails, and a skipped required check reports as success — a green
gate over a red matrix. With it, the job runs and explicitly exits 1.

Expect `CI OK` to sit queued until all five upstream checks finish, so a PR
looks stalled for a minute even when everything is green. That's inherent to
the pattern, not a misconfiguration.

</details>

<details>
<summary><b>Maintainers — applying or changing the ruleset</b></summary>

The policy is version-controlled at
[`.github/rulesets/main.json`](.github/rulesets/main.json). GitHub does **not**
read it from the repo automatically — it is applied by import:

**UI:** Settings → Rules → Rulesets → **New ruleset** → *Import a ruleset* →
pick the file.

**API** (needs a PAT with `admin:repo_hook`/repo admin scope):

```bash
gh api --method POST /repos/lesysbot/lesysbot/rulesets \
  --input .github/rulesets/main.json
```

Two things to finish in the UI after importing:

1. **Bypass list** — ships empty. Add **Repository admin** unless you want a
   locked-out admin with a broken CI runner to have no recovery path.
2. **Require linear history** — deliberately **off**. It's compatible with this
   repo but changes habit: it forbids merge commits on `main`, so the green
   button becomes squash-or-rebase only. Past PRs here merged with merge commits
   (`1acc21e Merge pull request #2 …`), so turning it on is a workflow decision,
   not a security one. The genuinely protective rules are the other four.

Changing the policy? Edit the JSON *and* re-import — an edit made only in the UI
silently drifts from the file, which defeats keeping it in the repo at all.

</details>

---

## Questions?

Open a GitHub issue — including for "is this a good idea?" questions before
you build something large. For understanding the code, start with
[docs/architecture.md](docs/architecture.md); the finer-grained internals live
in [CLAUDE.md](CLAUDE.md).
