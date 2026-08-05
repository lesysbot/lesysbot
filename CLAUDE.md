# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, includes dev deps; [dev] pulls [all] = telegram+slack)
pip install -e ".[dev]"
# NOTE: the `lesysbot` console script imports whatever `lesysbot` is installed. A stale
# NON-editable build in site-packages can shadow this repo, making code/tool edits
# (e.g. newly added tools) appear to do nothing — `/help` may even show no tools.
# Check with: python -c "import lesysbot; print(lesysbot.__file__)"  → must point here.
# Fix by re-running:  pip install -e .

# Run the bot (CLI mode — no messaging credentials needed)
lesysbot --provider cli --model qwen3.5:4b

# Run with verbose logging
lesysbot --provider cli -v

# Run against an explicit config (otherwise ~/.lesysbot/config.yaml is the installed default)
lesysbot -c ~/.lesysbot/config.yaml

# Install and manage tools AND dashboards (bare `lesysbot` prints status and exits)
lesysbot install owner/repo[/subdir][@ref]     # a github.com URL, or a catalog id
lesysbot search [QUERY] [--refresh]            # browse the marketplace
lesysbot list | info NAME | enable NAME | disable NAME | remove NAME
lesysbot update [NAME…] [--check]              # re-fetch at the recorded ref
lesysbot doctor [NAME]                         # what's missing here, and the fix
lesysbot dashboard render | list | start | stop

# Interactive setup wizard (config + service). --repo is only for development:
# a normal install seeds from the content bundled in the wheel.
lesysbot setup [--repo PATH]

# Build a standalone Windows executable (run on Windows)
.\scripts\build-exe.ps1
```

`pytest` uses `asyncio_mode = "auto"` (set in `pyproject.toml`), so async test functions work without extra decorators.

## Architecture

Three independent layers wired together by `Agent` in `lesysbot/core/agent.py`:

```
MessagingAdapter → Agent.handle(user_id, text) → LLMClient → ToolRegistry → reply
```

**Request flow:** Messages arrive at a `MessagingAdapter`, which calls `Agent.handle`. If the text starts with `/`, it's dispatched directly to `_handle_slash()` — the LLM is never called. Otherwise, the agent appends the message to the per-user `ConversationHistory`, calls `LLMClient.chat()` with all registered tool schemas, and if the LLM returns `tool_calls`, executes them and loops. Tool calls run in parallel via `asyncio.gather` unless any tool has `confirm=True/str`, in which case they run sequentially so each confirmation can be awaited.

### LLM (`lesysbot/llm/client.py`)

Single `AsyncOpenAI` client with a configurable `base_url`. Always streams (`stream=True`). `LLMClient.health()` is a non-streaming probe: it times a `models.list()` call (5 s timeout override, not the 120 s chat timeout) and returns `{ok, latency_ms, base_url, model, model_available, models}` or `{ok: False, error, ...}`. Three optional callbacks flow from `CLIAdapter` through `Agent.handle` into the stream loop: `on_token` (answer text, `delta.content`), `on_reasoning` (`delta.reasoning_content`, for reasoning models that expose it), and `on_status` — emitted by `Agent.handle` itself, not the LLM: `"Thinking…"` before each LLM turn and `"Running <tool>…"` before executing tools. `on_reasoning`/`on_status` are keyword-only with `None` defaults on `Agent.handle`, so Telegram/Slack (which call `handler(user_id, text)` with no extras) are unaffected. All local backends (Ollama, vLLM, LlamaCpp) expose an OpenAI-compatible API, so no backend-specific code exists.

### Tool registry (`lesysbot/mcp/registry.py`)

Tools live in `tools/` in two layouts: **folder packages** — each subdirectory (e.g. `gpu-temp/`) is a self-contained, copy-paste tool with its own `README.md` + `tool.py` (the recommended, shareable form, like a Claude Skill) — and **loose `.py` files** dropped straight in `tools/` (quick local tools, still supported). At startup `ToolRegistry.load_directory()` imports every non-`_`-prefixed `.py` (loose files first, then each subdir via `_load_package()`) and scans their module attributes. Anything with `__tool_meta__` dict (set by `@tool`) or that is a `CLITool` instance is registered. With `hot_reload: true`, `watchfiles.awatch` (recursive) re-runs this on any `.py` change without restarting.

`load_directory()` inserts the resolved tools directory into `sys.path` (for loose files); `_load_package()` temporarily inserts each package's own directory so its files can `from _helpers import ...`. Because helpers are imported by their bare name (globally cached), `_drop_user_helpers()` evicts top-level `_`-prefixed **user** helper modules **both before and after** each package load — guarded by `_stdlib_dirs()` so stdlib/site `_`-modules (`_thread`, `_py_abc`, …) survive. That forces each package to re-import the `_helpers.py` sitting next to it, so a like-named helper cached from another package or tools dir can't shadow it (and package helper imports must stay at module top level — the package dir is on `sys.path` only during load). Package tool modules import under a unique `_lesysbot_tools.<folder>.<stem>` name. On `reload()`, `_invalidate_cached_modules()` drops any cached `sys.modules` entry whose `__file__` lives under the tools dir (plus `importlib.invalidate_caches()`), so edits to helpers hot-reload too.

**Enable/disable:** the registry tracks a `_disabled` set (names turned off via `lesysbot disable`). `is_enabled`/`enable`/`disable`/`set_enabled` mutate it; `get_openai_schemas()` omits disabled tools (hidden from the LLM) and `call()` refuses them with a "disabled" message (so `/slash` calls respect it too). The set is an instance attr so it survives `reload()` (hot-reload); `set_state_path()`/`load_state()`/`_save_state()` persist it as `{"disabled": [...]}` JSON to `mcp.state_file` (anchored like `tools_dir` → `~/.lesysbot/tool_state.json`) across restarts. `tool_status()` returns the per-tool status rows (`enabled`, `available`, `unavailable_reason`, `platforms`, `requires`, `confirm`, `params`, `source`).

**Source mapping & removal:** `register()` records each tool's defining file as `meta["source"]` (passed down from `_load_file`), and `load_directory()` remembers the resolved tools dir. `tool_source(name)` maps a tool back to its removable unit — the folder package directly under the tools dir, or the loose `.py` itself — as `{path, kind: "package"|"file", unit, tools}` where `tools` lists every registered tool sharing the unit (one file/package can define several). `remove_tool(name)` deletes that unit (`force_rmtree` from `core/paths.py`, shared with the installer), deregisters all its tools, purges them from `_disabled` (state saved), and refuses paths that aren't a direct child of the tools dir. Callers keep `lesysbot.lock.json` in sync via `artifacts/lockfile.py:drop_entries()` when the removed unit was installed from GitHub. `lesysbot remove` goes through this; tools registered programmatically (no `source`) return `None`/raise.

**Cross-platform gating:** `register()` calls `availability(platforms, requires)` (`lesysbot/mcp/platform.py`) once per tool. `platforms` (subset of `{linux, macos, windows}`, `None` = all) is checked against `current_os()`; `requires` is a list of executables checked via `shutil.which`. If unavailable the tool is **still registered** (visible in `/help` and to the LLM) but its `fn` is swapped for `_make_stub()`, which returns a one-line explanation when called; `meta["available"]`/`["unavailable_reason"]` are recorded and `list_tools_text()` appends a `⚠ unavailable here:` note. Pip deps are **not** `requires` (those are PATH binaries) — tools import them and handle `ImportError` themselves (see `tools/web/tool.py`).

**Important:** `CLITool.__tool_meta__` is a `@property` (not a plain attribute like `@tool`), which is why `_is_tool()` uses `isinstance(obj, CLITool)` as a separate branch from checking `__tool_meta__` on callables.

### `@tool` decorator (`lesysbot/mcp/decorators.py`)

Sets `fn.__tool_meta__` as a plain dict `{name, description, parameters, fn, confirm, platforms, requires}`. The `parameters` field is a JSON schema built from Python type hints via `_build_schema`. `platforms`/`requires` (both `None` by default) drive the registry's cross-platform gating described above. Type hint → JSON type mapping covers `str/int/float/bool/list/dict`; anything else defaults to `"string"`. Both sync and async functions are supported; sync functions are wrapped in `async def`.

`_build_schema` resolves hints via `typing.get_type_hints()` (not raw `func.__annotations__`), so tool files that use `from __future__ import annotations` (PEP 563 string annotations) still get correctly typed schemas instead of everything collapsing to `"string"`.

The `confirm` field (`bool | str`) propagates all the way to `Agent.handle`, which checks it before calling `adapter.confirm(user_id, tool_name, prompt, args)`. Set `confirm=True` for a generic prompt or pass a string for a custom message.

### `CLITool` (`lesysbot/mcp/cli_tool.py`)

Wraps a shell command template string (`command="ping -c 3 {host}"`) as a tool. Uses `str.format(**kwargs)` for interpolation. `command` may also be a dict keyed by OS name (`linux`/`macos`/`windows`) — `_run` executes the current OS's variant, and `__tool_meta__` derives `platforms` from the dict keys unless set explicitly, so the tool gates itself off where it has no command. All params in `params={}` are treated as required strings. Has its own `timeout` (default 30 s) and the same `platforms`/`requires` gating fields as `@tool` (surfaced through its `__tool_meta__` property).

### Config (`lesysbot/core/config.py`)

`Settings.load()` tries, in order: CLI `-c` flag → `config.yaml` (cwd) → `~/.lesysbot/config.yaml` → `config.yaml` next to the executable (frozen builds) → `config/default.yaml` → `app_dir()/config/default.yaml` → hardcoded defaults. String values may reference environment variables as `${VAR}` — expanded at load time by `_expand_env()` (unset vars keep the literal text and log a warning). All fields are also overridable via `LESYSBOT_` env vars with `__` as the nested delimiter (e.g. `LESYSBOT_LLM__MODEL=llama3.1`); env vars and CLI flags take precedence over the file. To customize by hand, copy `config/default.yaml` to `config.yaml` (or edit `~/.lesysbot/config.yaml`).

`from_yaml()` records the loaded file's absolute path on a `PrivateAttr`; `Settings.config_dir` exposes its directory (or `None` when running on built-in defaults). The two `config/default.yaml` candidates are loaded with `bundled=True`: they ship **with the package**, not as a config the user edits, so their values apply but `config_dir` stays `None` — otherwise a fresh checkout would anchor `./tools` to `<repo>/config/tools` and load no tools at all (`tests/test_config.py::test_bundled_default_does_not_anchor_paths_to_itself`). This is what lets relative `tools_dir`/log paths anchor next to the config the user actually edits — see **Paths** below.

### Paths & the `~/.lesysbot` home (`lesysbot/core/paths.py`)

`~/.lesysbot/` is the **installed per-user home** — one stable place for `config.yaml`, `tools/` and `logs/`, decoupled from wherever the source was cloned. The install wizard writes `config.yaml` and seeds `tools/` there, and the Telegram/Slack background service runs from it, so the supported workflow is: **edit `~/.lesysbot/config.yaml`, restart the service, done.**

- `user_dir()` → `~/.lesysbot`, overridable with the `LESYSBOT_HOME` env var (also used to make tests hermetic).
- `app_dir()` → the cwd normally, or the folder containing the executable in a frozen (PyInstaller) build.
- `anchor(path, base=None)` resolves a relative path against `base`, falling back to `app_dir()` when `base is None`; absolute paths pass through unchanged.

`config.resolve_paths(settings)` anchors `mcp.tools_dir`, `mcp.lock_file`, `mcp.state_file`, and `logging.file`/`logging.trace_file` against `settings.config_dir` (the directory the active config came from). It's called from `__main__.main()` on the bot path **and** from `cli/context.py:CLIContext.load()`, so `lesysbot install` writes into exactly the tools dir the bot loads. An installed setup resolves `./tools` → `~/.lesysbot/tools` and `logs/…` → `~/.lesysbot/logs`; a dev checkout with a local `./config.yaml`, or a shipped `.exe` with config beside it, keeps resolving them next to that config; and built-in defaults — including the bundled `config/default.yaml` — fall back to `app_dir()`. See `docs/configuration.md`, `docs/building-windows-exe.md` and `packaging/`.

### Messaging (`lesysbot/messaging/`)

Each adapter implements `MessagingAdapter.start(handler)` and `send(user_id, text)`. The optional `confirm()` method defaults to auto-approve; CLI and Telegram override it. Adapters are imported lazily in `__main__.py` so missing optional deps (Telegram, Slack) don't break CLI usage. Wire new adapters in the `if/elif` block in `__main__.py` and call `agent.set_confirm_fn(adapter.confirm)`.

**CLI adapter** renders LLM answers as **live Markdown** (color/bold/headings/lists/code) by accumulating `on_token` chunks into a `rich.live.Live` + `Markdown`. While generating it shows a `Thinking…` / `Running <tool>…` spinner (driven by `on_status`); reasoning — from `on_reasoning` or inline `<think>…</think>` tags split out by `_split_think()` — renders dim above the answer. **Slash-command/instant results and `/help` are still printed verbatim** (`markup=False`): Markdown would strip `<param>` signatures and collapse column whitespace (e.g. `df`); a status spinner runs while they execute. `confirm()` pauses the active `Live` (`self._live.stop()` then `.start()`) so the confirmation prompt renders cleanly. `_format_history` uses plain `LABEL:` lines, not `**bold**`.

**Startup notice (`lesysbot/messaging/notice.py`):** with Telegram/Slack and `messaging.startup_notice.enabled` (default true), `__main__._run` spawns `send_startup_notice()` as a background task. It waits on the adapter's `ready` event (a lazily created `asyncio.Event` on `MessagingAdapter`; Telegram sets it after `start_polling()`, Slack before the blocking `start_async()` since `send()` uses the Web API), builds `core/sysinfo.startup_report()`, and `send()`s it to `startup_notice.notify` (Telegram falls back to `allowed_user_ids`; Slack needs an explicit channel id), retrying failed sends. For an installed service this is the "machine just booted" ping. `core/sysinfo.py` holds the best-effort collectors — CPU temp (Linux `/sys` thermal zones + hwmon), GPU temp (nvidia-smi), disk usage, internet speed (Cloudflare, `speedtest`/`speedtest_mb` config keys), uptime — each returning `None` when the host can't answer, so the report omits those lines. It deliberately does **not** call registered tools (must work regardless of tools-dir contents); the bundled `cpu-temp`/`gpu-temp`/`speedtest` packages duplicate the readings for chat, on purpose (packages stay copy-paste self-contained).

**Out-of-band pushes (`lesysbot/core/notify.py`):** tools normally only *return* text, so they can't say anything after their reply. `Agent.handle` stamps the requesting user on a `ContextVar` before dispatch (slash and LLM paths) and `__main__._run` wires the active adapter's `send` via `notify.set_sender`, so a tool can call `notify_later(text, delay)` (re-exported from `lesysbot.mcp`) to push a follow-up message to that user. It returns the `asyncio.Task` (cancel it to drop the announcement) or `None` when no sender/user is wired — best-effort by design; send failures are logged, not raised. The `power` package uses it for a "powering off now" heads-up ~10 s before a scheduled shutdown/reboot fires, cancelled again by `cancel_shutdown`.

**Telegram adapter** targets python-telegram-bot v20+ (no `Updater.idle()` — `start()` awaits an `asyncio.Event` and shuts the app down on cancel). Replies go through `_reply_safe()`, which tries `parse_mode="Markdown"` and falls back to plain text on `BadRequest`, so malformed LLM Markdown never drops a message.

**Optional dependencies:** only the CLI provider, the registry and the `tools`/`setup` subcommands are in the base install. Chat platforms are extras — `telegram` (`python-telegram-bot`), `slack` (`slack-bolt` **plus `aiohttp`**, which slack-bolt itself does not declare but its async socket handler imports), and `all` (both; `dev` pulls `all`). `scripts/install.{sh,ps1}` install `.[all]` so every option the wizard offers works. `_run()` wraps the lazy adapter imports in one `try/except ImportError` that names the missing extra instead of dumping a traceback — for a background service that message is the user's only clue. CI's `base-install` job installs bare `.`, asserts `telegram`/`slack_bolt`/`aiohttp` are absent, and smoke-tests the CLI, so the base install can't silently regain a heavy dep.

**Live enable/disable across processes:** the disabled set lives in each process's registry, but two things write the file it persists to (`mcp.state_file`) — `lesysbot enable/disable` (a separate process, so it has no handle on the bot's registry) and hand edits. `Agent._watch_tool_state` watches that file with `watchfiles` and re-runs `registry.load_state()`, so both apply **live**. It's deliberately not gated on `mcp.hot_reload` (which governs re-importing tool *code*) — this is about other processes. Regression test: `tests/test_agent.py::test_enable_disable_from_another_process_applies_live`.

**Artifact CLI (`lesysbot/cli/`):** `lesysbot install|update|list|info|enable|disable|remove|search|doctor|dashboard` — the whole lifecycle without a running bot, registered by `cli.register_all()` in `build_parser()` (each leaf repeats `-c` with `default=argparse.SUPPRESS` so a root-level `-c` isn't clobbered). `install` accepts **GitHub links or a catalog id** — a bare word that is neither gets a usage error rather than a guess, since guessing at what to download is the one place this must not be clever. `list`/`info` join registry rows with the lock for provenance (`origin` = `repo@commit7`, `bundled`, or `local`); enable/disable persist to `mcp.state_file` (a running bot picks that up **live**); `remove` handles both kinds and un-provisions a removed dashboard from Grafana.

**Single-instance guard (`lesysbot/core/singleton.py`):** two copies of the same bot fight over the same updates (Telegram 409s both), so for remote providers `main()` takes an OS-level lock (flock / msvcrt byte lock on `user_dir()/lesysbot.<provider>.<token-digest>.lock`) before starting and exits 1 with a "stop the service first" message when it's held, naming the holder's PID from the lock file. Keyed on a token digest so different bots coexist; the kernel drops the lock on process exit (crash included) so stale files never wedge a restart; CLI provider skips the guard (doesn't poll). Held handles stay referenced in a module-global so GC can't release them. Tests: `tests/test_singleton.py` (subprocess-based, hermetic via `LESYSBOT_HOME`).

**Concurrency pattern (`__main__._run`):** the messaging adapter is the **primary** coroutine; the startup notice runs as an `asyncio.create_task` **background** task. Tools only ever run in response to a user message or `/command` — there is deliberately no scheduler or other unattended trigger (the startup notice reports via `core/sysinfo.py` collectors, not tools). `await adapter.start(...)` in a `try`, and the `finally` cancels the background tasks (`await asyncio.gather(*background, return_exceptions=True)`), so a CLI `exit` actually terminates the process instead of hanging on a long-lived background task.

### Tracing (`lesysbot/core/trace.py`)

`TraceWriter` appends one JSON line per user message to the resolved `logging.trace_file` (default `logs/traces.jsonl`, anchored to the config dir — so `~/.lesysbot/logs/traces.jsonl` for an installed setup). Slash commands aren't traced — they return before `_tracer.start()`. It writes through a dedicated non-propagating logger backed by a `TimedRotatingFileHandler`, so traces rotate on `logging.when` and keep `logging.backup_count` dated files. `ActiveTrace` accumulates per-LLM-turn and per-tool-call timings during a single `Agent.handle()` call, then flushes on `finish()`. Tracing has no levels — it's all-or-nothing per message; `result`/`reply` are truncated at 2000 characters.

### Secret redaction (`lesysbot/core/redact.py`)

Credentials must never reach a log handler. The forcing case is Telegram: the Bot API carries the token in the URL **path**, and `httpx` logs every request at INFO, so an unredacted service writes its own token to disk thousands of times a day — into the file people paste into bug reports. Redaction lives at the logging layer because the leak isn't ours to fix at the source (it comes from a library), so filtering on the way out is what catches every producer, present and future.

Two sources of truth: `_PATTERNS` (token *shapes* — Telegram `<digits>:<35 chars>`, Slack `xox[baprs]-`/`xapp-`, OpenAI `sk-`/`sk-proj-`) work with zero configuration, which matters because the worst leak is logged by a library before anything registers a secret; `add_secret()`/`register_settings_secrets(settings)` add the *exact* values from the active config (telegram token, both Slack tokens, `llm.api_key`), called from `main()` right after `resolve_paths()` so the window before logging is configured is already covered. `add_secret` ignores values shorter than `_MIN_SECRET_LEN` (12) — **`llm.api_key` is `"ollama"` on a default install, and registering a six-letter dictionary word would rewrite unrelated log text**. `redact()` is idempotent (the `<redacted>` placeholder matches no pattern), which it must be since one filter instance is attached to several handlers.

`RedactingFilter` is attached to **handlers, not loggers** — a logger's filters don't run on records propagated from child loggers, and `httpx` logs to its own. When it changes a message it folds args in and sets `record.args = None`, so re-formatting can't resurrect the secret; untouched records keep lazy `%`-formatting. `RedactingFormatter` (used for the file handler) additionally scrubs the *formatted* output, which is the only place a traceback gets covered — httpx puts the request URL on the exception. Tests: `tests/test_redact.py`.

### Logging (`lesysbot/__main__.py`)

`_setup_logging(verbose, log_cfg, interactive)` attaches a Rich console handler plus a **`TimedRotatingFileHandler`** on the resolved `logging.file` that rotates per `logging.when` (default `midnight`) and keeps `logging.backup_count` dated files (e.g. `lesysbot.log.2026-06-21`) — neither file grows unbounded. The baseline level is `logging.level` (wired here; `-v` forces DEBUG). Root sits at DEBUG so each handler filters independently: the **file** logs at the config level, while the **console** is clamped to `WARNING+` in interactive CLI mode (keeps the chat clean — no `httpx`/`watchfiles`/`Tools loaded` INFO) and honours the config level for the Telegram/Slack daemons. `main()` passes `interactive=(settings.messaging.provider == "cli")`. Set `logging.file`/`logging.trace_file` to `null` to disable either. Every handler gets a `RedactingFilter`, and the file handler a `RedactingFormatter` — see **Secret redaction** above; new handlers must get the same treatment.

### Artifact installer (`lesysbot/artifacts/`)

The engine behind `lesysbot install`. One installer for **tools and dashboards**, because they differ only in where they land and what has to be true for them to work — everything else (fetch, extraction, consent, provenance, update) is identical. Formerly `lesysbot/install/`; the rename also ends the collision `setup/` (install *wizard*) vs `install/` (tool *installer*) that this file used to have to apologize for.

**Kind** (`kinds.py`) is `tool | dashboard`, resolved from README frontmatter `kind:`, else inferred from the payload (a folder holding `dashboard.json`/`dashboard.py` is a dashboard), else `tool`. All three fallbacks matter: every tool package written before dashboards existed still installs unchanged, and a plain Grafana export dropped in a repo — the most likely thing someone publishes — is installable as-is. A repo containing both kinds installs both, each routed to its own directory, which is what makes `lesysbot install <uri>` a single verb.

Module layout: `spec.py` parses `owner/repo[/subdir][@ref]` + GitHub URLs into a frozen `ToolSource`; `fetch.py` downloads **codeload zipballs via stdlib urllib** (no git binary, no GitHub API calls — candidate order tries `refs/tags/` before `refs/heads/`; `GITHUB_TOKEN`/`GH_TOKEN` sent as a Bearer header for private repos); `archive.py` extracts with zip-slip/symlink/zip-bomb guards and reads the pinned commit SHA from the **zip archive comment**; `manifest.py` (was `meta.py`) parses README frontmatter — the only frontmatter parser in the codebase, every key optional, never blocks an install — and discovers packages (root-with-payload = single-package repo, else immediate subdirs of `tools/`/`dashboards/`, else of the root; package code is **never imported** pre-consent); `installer.py` (`ArtifactInstaller`) stages extraction to a temp dir then `shutil.move`s each package into the directory its kind belongs in (one clean hot-reload event); `lockfile.py` records provenance in `lesysbot.lock.json` keyed `<kind>:<name>` (so a tool and a dashboard may share a name); `deps.py` installs Python dependencies; `catalog.py` is the marketplace index.

Installer rules: y/N confirmation before install (`--yes` skips; packages are arbitrary code), a **preflight report** from `lesysbot/prereq/` printed before that prompt, refusal to overwrite a directory the lock has never heard of (`--force` overrides), and `preserve:` paths carried across an update — confined to the package, since a manifest is untrusted input. **Re-installing is updating**: `_check_collisions` only refuses unmanaged dirs, so `lesysbot update` is that, re-resolved at each entry's recorded ref. `ArtifactInstaller` **only installs**: reading back is `lesysbot list/info` (registry rows joined with the lock), removal is `registry.remove_tool()` + `lockfile.drop_entries()`. Tests (`tests/test_artifacts_*.py`) are network-free via `tests/install_utils.py`.

**Dependencies (`artifacts/deps.py`) now install by default.** They used to print a pip command behind `--install-deps`; the goal is a package that works when the command ends, so `requires_python:` plus `requirements.txt` are installed into **LeSysBot's own environment** (the interpreter that imports `tool.py` — anywhere else and the tool fails on ImportError with everything apparently in place), recorded in the lock, and skipped with `--no-deps`. When pip can't run — a frozen build has none — nothing is attempted and the exact command is printed. `tests/conftest.py` sets `LESYSBOT_SKIP_DEP_INSTALL` for the whole suite so a test can never pip-install into a developer's real environment.

### Prerequisites (`lesysbot/prereq/`)

What a package needs, whether this machine has it, and the fix. `Requirement(type, value, optional)` → `Result(satisfied, detail, fix, auto_fixable)`; checkers cover `os arch binary python pip gpu docker service metric port`. Surfaces: the preflight block before an install, `lesysbot doctor`, `/api/prereq`, and `mcp/platform.availability()` — which is now a thin wrapper over this, so registry gating is unchanged but shares one implementation.

Two rules hold throughout: **nothing here installs anything** (only pip deps and LeSysBot's own packages are auto-fixed, elsewhere), and **nothing here runs sudo** — where the only real fix needs root, the fix is *text*. `_binary_fix` deliberately refuses to guess `brew install <command>`: package names routinely differ from the command they install, and `brew install nvidia-smi` is not a thing. Exact commands only where known correct; otherwise name the binary and let the user pick.

**GPU is the case this layer exists for** (`prereq/gpu.py`). Generalizes what `start.sh` and `install-macos.sh` already do: **key on the reading tool, never the card**, because `nvidia_gpu_exporter` shells out to `nvidia-smi` and a driverless GPU is unscrapeable. `lspci`/`system_profiler`/`Win32_VideoController` are consulted *only to explain* — so a box with an RTX 3080 and no driver reads as "present, driver not installed → …" rather than "no GPU".

### Marketplace catalog (`lesysbot/artifacts/catalog.py`)

`catalog.json`: display metadata whose every `source` is an ordinary github.com link. **It is a list, never a resolver** — installing an entry resolves that link through the same `parse_source` and the same consent prompt as one typed by hand, so "no registry decides what you may install, and you can read the repo first" still holds. Sources in order: explicit path → `~/.lesysbot/catalog.json` (refreshed) → the copy bundled in the wheel, which is why `lesysbot search` works offline. A failed refresh falls back rather than erroring: being offline degrades discovery, it must not break it.

### Dashboards (`lesysbot/dashboards/`)

`render.py` turns an installed dashboard package into the JSON Grafana provisions; `provision.py`'s output directory is `dashboard/grafana/dashboards/generated/`, which **all three launch paths now mount** (both composes and `install-macos.sh`), replacing the single-file `DASH_JSON` mount that made a second dashboard structurally impossible. Payload is `dashboard.json` (portable, what Grafana's export button gives you) or `dashboard.py` exposing `build(host, caps, ctx)` (host-adaptive). **An unavailable dashboard is not written** — and a previously rendered copy is *removed* when it stops being available, so a dashboard whose exporter went away doesn't keep serving empty panels. Deliberate asymmetry with tools, which stay visible with an explaining stub.

The bundled System Overview is the first dashboard package (`dashboards/system-overview/`), mapping LeSysBot's host/capability vocabulary onto `gen-dashboards.py`, which stays the single source of truth and standalone-runnable. `tests/test_dashboards.py` pins byte-identical output per host cut.

### Bundled content (`hatch_build.py`, `paths.bundled_dir()`)

`tools/`, `dashboard/`, `dashboards/` and `catalog.json` are copied into `lesysbot/_bundled/` at build time, so `pip install lesysbot && lesysbot setup` is a complete, offline install and `--repo` is development-only. `bundled_dir()` returns the packaged copy when present, else the repo root beside the package — one resolver, both layouts identical.

The copy goes through a **build hook** rather than a plain `force-include` because hatchling's `exclude` patterns do not apply to force-include, and `dashboard/.env` is git-ignored precisely because it holds the Grafana admin password: a release built on a machine with a real password would ship it to every user. `bin/`, `run/`, `native/` and generated dashboards are excluded for size, not secrecy. `tests/test_bundled.py` pins all of it.

Seeding (`setup/apply.py`) installs bundled packages through the same rules and records them as `bundled: true`, replacing `seed_tools`' old `if dst.exists(): return False` — which meant a fix to a bundled tool could never reach anyone who already had it.

### Management panel & CLI dispatch (`lesysbot/management/`, `__main__.py`)

A **loopback-only web management panel** for config + tools, **served by the service so it is always online** (`lesysbot run` → `serve_background()`; see the dispatch paragraph). This is the one listener in the project, so it is deliberately fenced: stdlib `http.server.ThreadingHTTPServer` bound to **127.0.0.1 only**, a **DNS-rebinding guard** (`_Handler._host_ok` rejects any non-loopback `Host` header → 403), **no auth** (trust boundary = a shell on the machine, same as editing `config.yaml`), and **zero new dependencies**. `management/page.py` inlines the single-page UI as a Python string so it ships with the package (no package-data wiring; survives a PyInstaller build); it follows the docs-site brand (slate + `brand-*` cyan tokens) and renders its header mark + favicon to SVG from `core/_logo` (the same sprite `core/banner.py` draws in the terminal — `gen_logo.py` now emits both `MARK` (16px) and `MARK_32` into that module) so the web copy can't drift from the generated art. The page carries a 2-state light/dark toggle keyed on a `data-theme` attribute on `<html>` (a pre-paint script reads `localStorage['lesysbot-ui-theme']`, else the `prefers-color-scheme` media query drives it — no framework, no new dependency). API: `GET /api/status` (via `core/status.gather_status`), `/api/tools`, `/api/config`; `POST /api/config` (validates with `Settings(**yaml)` **before** writing), `/api/tools/{toggle,install,remove}`. Toggle calls `registry.set_enabled()` which persists to `mcp.state_file`, so a running bot applies it live via `Agent._watch_tool_state`; config edits need a restart. Registry mutations are serialized under one `threading.Lock`; the LLM health probe runs outside it.

**CLI dispatch** (`__main__.main`): everything that *manages* LeSysBot rather than being it — `install`, `update`, `list`, `info`, `remove`, `enable`, `disable`, `search`, `doctor`, `dashboard`, `setup`, and the `tools` alias — is owned by **`lesysbot/cli/`** and exits before any bot setup. `lesysbot.cli.handles(command)` decides; `dispatch()` imports the verb module lazily, so `lesysbot --provider cli` doesn't pay for the marketplace and a syntax error in a rarely used verb can't stop the bot starting. `CLIContext` (`cli/context.py`) is the one place that turns "the user typed a command" into resolved paths, lock and installer — the panel uses the *same* object, so browser and terminal can't disagree about where things live. Then: `manage` → `_manage()`; `_runs_the_bot(command, args)` (true for `run` or an explicit `--provider`) → `_run()`; **bare `lesysbot`** → `_print_status()` and exit.

`core/status.gather_status()` is the shared status snapshot (CLI view + `/api/status`). `detect_panel()` probes `/api/ping` — a body-less, lock-free endpoint that answers `{"service": "lesysbot-webui"}` so a *stranger* on that port reads as offline instead of being advertised as the panel (the server answers its own `/api/status` with `running: True` rather than probing itself). The `daemon` row is now computed for **every** provider (the service exists regardless) via `singleton.is_running()`, which tests the lock on a second open file description: the lock *file* outlives a crash with a stale PID in it, so `holder_pid()` alone would report a dead service as running. It also `detect_grafana()`s the dashboard stack so the status screen links to Grafana: candidates are `grafana_candidates()` — the bundled stack's own `GRAFANA_PORT` (read from `~/.lesysbot/dashboard/.env`) first, then `localhost`/`127.0.0.1` on 3000/3001 — and each is **verified** via `/api/health`. `LESYSBOT_GRAFANA_URL` is honoured but *also* verified, then falls through to probing: a saved URL goes stale the moment the stack moves off 3000 (because something else owns that port), and linking that impostor as "Grafana" is worse than probing. Only if nothing answers is the override returned with `reachable: False`, which both renderers (`_print_status`, `management/page.py`) show as "not answering" rather than a link. LLM health probes go through `status.probe_health()`, which closes the httpx client in-loop (one-shot `asyncio.run` otherwise finalizes it on a closed loop → "Event loop is closed"); `Agent.aclose()` does the same on bot shutdown. Tests: `tests/test_management.py` starts the real server on an ephemeral port (plus `/api/ping`, `detect_panel` vs. a foreign server, `serve_background` refusing a second bind) and `tests/test_singleton.py` covers the stale-lock case. Security posture is documented on the site (`security.md` §4 — the listener is now the always-on localhost panel, not an opt-in one) — keep those in sync.

## Adding a new tool

Use the **`.claude/skills/add-tool/` project skill** when scaffolding a tool — it
encodes the conventions (folder package under `tools/` with README frontmatter +
`tool.py`, `@tool` vs `CLITool`, `platforms`/`requires` gating, package-local
`_helpers.py`, the `tools/README.md` catalog row). `tools/README.md` is the catalog.

## Adding a new messaging adapter

Subclass `MessagingAdapter` (`lesysbot/messaging/base.py`) and implement `start()` and `send()`. Override `confirm()` to add confirmation UI (default auto-approves). Wire it in the `if/elif` block in `lesysbot/__main__.py` and pass `adapter.confirm` to `agent.set_confirm_fn`.

## LLM backend switching

All backends accept the same config shape — only `base_url`, `model`, and `api_key` differ:

| Backend | base_url | api_key |
|---|---|---|
| Ollama | `http://localhost:11434/v1` | `ollama` |
| vLLM | `http://localhost:8000/v1` | `vllm` |
| OpenAI | `https://api.openai.com/v1` | actual key |

## Tests

`tests/` holds the pytest suite. Tests construct registries/agents over temp tool dirs and don't need a running LLM, messaging backend, or network. `test_macos_metrics.py`, `test_gen_dashboards.py` and `test_start_detect.py` are the exceptions to the tests-cover-`lesysbot/` rule: they exercise `dashboard/scripts/` by path, because `dashboard/` sits outside the package. `test_macos_metrics` stubs its one OS entry point (`_run`) so the macOS-only parsing is verified on Linux too; `test_gen_dashboards` is pure and pins which panels each host cut includes (plus a staleness check that the committed JSONs still match the generator); `test_start_detect` sources `start.sh` and drives `detect_capabilities_linux` against a fixture `/sys` tree, overriding `is_virtual`/`command` for the two facts that aren't in sysfs. All three run on any OS on purpose — the platform-specific logic is exactly what a developer on another platform would never otherwise execute. `test_config.py` covers the search order and the `~/.lesysbot` home via a monkeypatched `LESYSBOT_HOME` (`test_load_picks_up_user_dir`) plus `config_dir` tracking and `resolve_paths` anchoring. Installer tests share `tests/install_utils.py`: `make_github_zip()` builds GitHub-shaped zipballs (single `repo-ref/` root + commit SHA in the archive comment) and `FakeFetcher` serves them from a dict while recording requested URLs (used to assert the zipball candidate fallback order); hermeticity comes from the same `LESYSBOT_HOME` monkeypatch. `asyncio_mode = "auto"` means async tests need no decorator.

## Setup wizard (`lesysbot/setup/`) and install scripts (`scripts/install.{sh,ps1}`)

The install scripts are **bootstrap only** and hand off to `lesysbot setup`, one
cross-platform Python wizard in `lesysbot/setup/`. Details in the
`.claude/skills/setup-wizard/` project skill (kept out of `lesysbot/` so hatchling
never bundles it into the wheel). Naming note: `lesysbot/setup/` is the *install wizard*;
`lesysbot/artifacts/` is the *package installer* — unrelated modules. (They used to be `setup/` and `install/`, which is why this note exists at all; the rename removed most of the confusion.)

**No sudo, ever** — this holds project-wide, not just for the wizard: **no tool may
require root either**. Never shell out through `sudo`, never ship a sudoers script,
prefer the unprivileged source of the same fact, and where none exists say so in the
reply instead of elevating (`docs/writing-tools.md`).

## Documentation structure

Docs are written **user-first**: every page opens with the plain-language answer and the shortest path that works, and pushes internals into collapsed `<details><summary><b>…</b></summary>` blocks at the end (GitHub renders these natively; the site styles them — see the docs-site note below). The rule when adding text: if a reader who just wants the thing to work doesn't need it, it belongs in a `<details>` block, not the main flow. Deliberately *not* numbered on the user-facing pages (`getting-started`, `usage`, `configuration`, `writing-tools`, `installing-tools`, `service`, `management-ui`, `troubleshooting`) — headings are questions, and cross-links use slug anchors; the reference-ish pages (`adapters.md`, `architecture.md`, `building-windows-exe.md`, `CONTRIBUTING.md`) keep their numbering.

All guides live in `docs/` (the root keeps only `README.md`, `CONTRIBUTING.md`, and this file). `docs/README.md` is the index, grouped **Start here → Everyday use → Give it new abilities → Keep it running → Under the hood**. `docs/architecture.md` is the technical page (life of a message, layer detail, management panel/CLI dispatch, where-to-change-what) and says so at the top; `docs/troubleshooting.md` is the single home for symptom→fix content — other pages link to it rather than growing their own tables; `docs/service.md` covers background-service operation (install/uninstall live in `docs/getting-started.md` — don't re-document them elsewhere); `CONTRIBUTING.md` holds dev setup + per-change-type checklists. When changing behaviour, update the guide that documents it; when adding a page, slot it into `docs/README.md`, the root README's "What next?" table, **and** the docs site (`content/<version>/nav.json` + the `GUIDES` map in `scripts/import-docs.js`). Cross-link rather than repeat — each fact has one home (tool management commands: `docs/usage.md` → "Turning tools on and off").

`skills/` holds **agent-facing skills** (Claude Skill format, one `SKILL.md` per job) distilled from the docs so an AI agent can operate/extend LeSysBot without reading `docs/` or source — deliberately copyable as a unit, so unlike the docs it *duplicates* facts. The mapping mirrors the docs (`docs/configuration.md` ↔ `skills/configure-lesysbot/`, `docs/service.md` ↔ `skills/manage-service/`, `dashboard/README.md` ↔ `skills/manage-dashboards/`, …; `skills/README.md` is the routing index). When a behaviour change updates a doc page, update the matching skill too. (`.claude/skills/` is separate: project skills for working *on this repo* in Claude Code.)

This repo is also a **Claude Code plugin marketplace** (`.claude-plugin/marketplace.json` + the `lesysbot-tool-dev` plugin in `claude-plugin/`): it distributes a repo-agnostic `add-tool` skill to tool authors in *other* repos — the official tools collections commit a `.claude/settings.json` (`extraKnownMarketplaces`/`enabledPlugins`) so cloners get prompted to install it (docs: `docs/claude-code.md`). The plugin is deliberately unversioned (every push is a new version). When tool-package conventions change, update **both** `.claude/skills/add-tool/` (core-repo variant) and `claude-plugin/lesysbot-tool-dev/skills/add-tool/` (generalized variant — no relative doc links, no `tools/`-dir or catalog/tests assumptions).

## Brand assets (`assets/brand/`, `scripts/gen_logo.py`)

**Never hand-edit anything in `assets/brand/` except its `README.md`**, and never
hand-edit `lesysbot/core/_logo.py` — both are *generated*. Edit the sprite grids or
the `PALETTE` in `scripts/gen_logo.py` and re-run it. Details in
`assets/brand/CLAUDE.md`.

## Packaging (Windows .exe)

`packaging/` (PyInstaller `lesysbot.spec` + `entry.py`) and `scripts/build-exe.ps1` build a standalone `lesysbot.exe`. The spec bundles core deps and optionally Telegram/Slack/httpx (skipped if absent). Frozen builds rely on `lesysbot/core/paths.py`: `app_dir()` resolves `config.yaml`/`tools/`/`logs/` next to the executable, and `Settings.load()` still checks `~/.lesysbot/config.yaml` ahead of the exe-adjacent file. Full guide: `docs/building-windows-exe.md`. Build artifacts (`build/`, `dist/`, `.build-venv/`) are git-ignored.

## Dashboard stack (`dashboard/`)

The bundled Prometheus + Grafana stack — seeded by `lesysbot setup`, **default,
not optional**, lives outside the Python package (hatchling never bundles it),
binds `127.0.0.1` only and needs **no sudo**. Details in `dashboard/CLAUDE.md`.
