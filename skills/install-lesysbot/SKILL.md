---
name: install-lesysbot
description: Install LeSysBot from scratch on Linux — the one-command installer (no prerequisites at all), a fully scripted unattended install driven by LESYSBOT_SETUP_* variables, the interactive wizard with every prompt explained, or a by-hand install from a clone. Use when asked to "install lesysbot", "set up lesysbot", "get lesysbot running", or to onboard a new machine.
---

# Install LeSysBot

LeSysBot is a local AI assistant: an LLM (Ollama by default) plus a set of tools it
can call, reachable from the terminal, Telegram, or Discord. Installing it means:
install the Python package, write a config, and register the background service
that serves the control panel (and any Telegram/Discord bot).

**Path A does all of that in one command and is what you should reach for.**
Paths B–D exist for scripting, for a human who wants to choose, and for working
on LeSysBot itself.

## 1. Path A — the one-command installer (use this unless told otherwise)

```bash
curl -fsSL https://lesysbot.github.io/install.sh | sh
```

**There are no prerequisites.** The script finds a Python 3.11+ or fetches one
with uv, builds an isolated venv at `~/.local/share/lesysbot/venv`, links
`lesysbot` into `~/.local/bin` and puts that on PATH, installs Ollama and pulls
`qwen3.5:4b`, then runs `lesysbot setup --yes`. It never prompts and never asks
for a password, so it is safe to run non-interactively.

Verify:

```bash
lesysbot          # status: LLM backend, service, control panel, Grafana
lesysbot chat     # terminal chat
```

**Useful flags** — pass after `sh -s --` when piping, or use the `LESYSBOT_*`
environment twin of each (a bare `curl … | sh` can't easily take arguments):

| Flag | Env | Use when |
|---|---|---|
| `--skip-dashboard` | `LESYSBOT_SKIP_DASHBOARD=1` | Fastest install; skips Grafana/Prometheus (which needs Docker). |
| `--skip-ollama` | `LESYSBOT_SKIP_OLLAMA=1` | A model runner already exists, or the backend is OpenAI. |
| `--model NAME` | `LESYSBOT_MODEL` | A different model. |
| `--no-modify-path` | `LESYSBOT_NO_MODIFY_PATH=1` | Never touch shell startup files (CI). |
| `--prefix DIR` / `--bin-dir DIR` | `LESYSBOT_INSTALL_DIR` / `LESYSBOT_BIN_DIR` | Relocate the venv / the command. |
| `--version X.Y.Z` / `--ref REF` | `LESYSBOT_VERSION` / `LESYSBOT_REF` | Pin a release, branch or tag. Default: the latest release, falling back to `main`. |
| `--skip-setup` | `LESYSBOT_SKIP_SETUP=1` | Install the command only; configure later. |

**The one thing it can't always finish:** on **Linux**, Ollama's own installer
needs root, and LeSysBot never asks for a password. Unless already root or
passwordless-sudo, the installer skips it and prints the two lines to run.
`--with-ollama` forces the attempt and accepts the prompt.

## 2. Path B — scripted / unattended (no terminal at all)

`lesysbot setup --yes` takes every default and reads overrides from the
environment. A complete Telegram install in one command:

```bash
LESYSBOT_SETUP_PROVIDER=telegram \
LESYSBOT_SETUP_TELEGRAM_TOKEN=123456:ABC… \
LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS=123456789 \
  curl -fsSL https://lesysbot.github.io/install.sh | sh
```

| Variable | Default |
|---|---|
| `LESYSBOT_SETUP_LLM` | `ollama` \| `openai` \| `vllm` \| `custom` |
| `LESYSBOT_SETUP_BASE_URL` | per backend (`http://localhost:11434/v1`) |
| `LESYSBOT_SETUP_MODEL` | `qwen3.5:4b` |
| `LESYSBOT_SETUP_API_KEY` | per backend; **required** for `openai` |
| `LESYSBOT_SETUP_PROVIDER` | `cli` \| `telegram` \| `discord` |
| `LESYSBOT_SETUP_TELEGRAM_TOKEN` / `_TELEGRAM_ALLOWED_IDS` | — both required for `telegram` |
| `LESYSBOT_SETUP_DISCORD_TOKEN` / `_DISCORD_ALLOWED_IDS` | — both required for `discord` |
| `LESYSBOT_SETUP_AUTOSTART` | `1` |
| `LESYSBOT_SETUP_GRAFANA_USER` / `_GRAFANA_PASSWORD` | `admin` / generated (0600 in `~/.lesysbot/grafana.env`) |

A missing required value **aborts and names the variable** — never guess one and
never leave a remote bot with an empty allow-list, which would let anyone who
can message it run tools on the machine.

Two more guards worth knowing when scripting or testing:

- `LESYSBOT_SKIP_SERVICE=1` — don't install/replace the background service.
  `LESYSBOT_HOME` does *not* relocate the `systemd --user` unit, so **without
  this a scratch-home test replaces the real machine's service.**
- `LESYSBOT_HOME` — move config, tools, logs and dashboards somewhere else.

Re-running the installer or `lesysbot setup --yes` is the **upgrade** path: it
keeps `config.yaml`, refreshes tools/dashboards, and restarts the service.
`--reconfigure` replaces the config instead.

## 3. Path C — the interactive wizard

For a human at a keyboard who wants to choose, or to reconfigure later:

```bash
lesysbot setup
```

The install hands off to
**`lesysbot setup`** — the wizard is part of LeSysBot (Rich panels, one
cross-platform implementation in `lesysbot/setup/`), so **re-run `lesysbot setup`
anytime to reconfigure without reinstalling**.

Menus accept ↑/↓ + Enter (or →) or the option's number; without an
interactive terminal (piped input) they fall back to plain "type a number"
prompts. Pressing Enter through every default gives a working local CLI bot.
Steps 3 and 4 end with a **← Back** entry that returns to the previous step —
the **← arrow key** or **Esc** takes it directly — and **Esc at any typed
prompt** (base URL, model, tokens, IDs) abandons it and returns to that step's
menu. The final summary is a menu with **Change …** entries that jump back
into any step: revisits offer the previous answers as defaults (picking a
different LLM backend clears its follow-ups). Nothing is written until Apply.

The prompts, in order:

1. **"~/.lesysbot/config.yaml already exists — overwrite?" `[y/N]`** — only on
   re-install. `n` keeps existing settings and skips to the service step.
2. **LLM backend** — `1) Ollama` (default; lists your installed models via
   `ollama list`, can pull a new one on the spot), `2) OpenAI` (asks model +
   `sk-…` key), `3) vLLM` (asks base URL, default `http://localhost:8000/v1`,
   and model), `4) Custom` (any OpenAI-compatible endpoint incl. `/v1`).
3. **How to reach LeSysBot** — `1) Terminal only` (default), `2) Telegram`
   (asks bot token from @BotFather + allowed user IDs; at least one numeric
   ID is required — it re-asks on blank/invalid input),
   `3) Discord` (asks bot token + allowed user IDs, same validation;
   the bot needs MESSAGE CONTENT INTENT enabled in the developer portal),
   `4) ← Back` (re-pick the LLM backend).
   The terminal always works regardless: `lesysbot chat`.
4. **"Service"** — asked for **every** provider (a `systemd --user` unit),
   because the service also serves the always-on control panel:
   `1) Start now and automatically after reboot` (default), `2) Start now only`,
   `3) ← Back` (re-pick how to reach LeSysBot).
   On the kept-config path this is a plain
   **"Start LeSysBot automatically after reboot?" `[Y/n]`** instead.
5. **Summary menu** — `1) Apply these settings` (default; only now is
   anything written), `2) Change LLM backend`, `3) Change how to reach
   LeSysBot`, `4) Change startup behaviour`,
   last) `Quit — exit without writing config`. On the kept-config path it's
   a plain **"Apply these settings?" `[Y/n]`**, and the summary shows the
   settings read back from the existing `config.yaml` (marked *kept as-is*) —
   only the service/startup choice is being decided there.

The wizard never uses `sudo` — and neither does any tool. No official package
requires root, a sudoers rule, or an Administrator prompt, so there is never a
privileged follow-up step: install a package and it works.

What the wizard does: writes **`~/.lesysbot/config.yaml`**, seeds
**`~/.lesysbot/tools/`** (never clobbers an existing one), installs the `lesysbot`
command, and installs + starts the background service running from
`~/.lesysbot` — for every provider, since that service hosts the control panel
(`http://127.0.0.1:8700`) as well as any Telegram/Discord bot. Re-running it stops
and replaces an existing service. `LESYSBOT_HOME` overrides the `~/.lesysbot`
location.

It also seeds **`~/.lesysbot/dashboard/`** (the Grafana/Prometheus dashboard) and
sets it up — a standard part of LeSysBot. It first **asks for the Grafana username
and password** LeSysBot should use (defaults `admin`/`admin`), saving them to
**`~/.lesysbot/grafana.env`** (loaded into the bot's environment at startup, so
`share_dashboard`/status authenticate automatically). Then, never fatal: if
Docker is running it **asks** whether to auto-start the bundled stack now or set
it up manually; if Docker isn't ready it prints the exact no-`sudo` steps to get
it going (install Docker Engine, start the daemon, join the `docker` group) — or
points at a native Grafana install from `https://grafana.com/grafana/download`
and how to connect it (auto-detected on `localhost:3000`, else
`LESYSBOT_GRAFANA_URL`).

Set `LESYSBOT_SKIP_DASHBOARD=1` to skip this step on an unattended install.

## 4. Path D — by hand from a clone (full control, no service)

Run the installer from a checkout and it installs *that checkout* — the usual
way to test an unreleased change:

```bash
git clone https://github.com/lesysbot/lesysbot.git
cd lesysbot && sh scripts/install.sh
```

Or do every step yourself:

```bash
git clone https://github.com/lesysbot/lesysbot.git
cd lesysbot
pip install ".[all]"             # telegram + discord extras
# pip install .                  # minimal: terminal chat and tools only
# pip install -e ".[dev]"        # development (adds pytest + ruff)
lesysbot --help                    # verify the command exists
cp config/default.yaml config.yaml
```

Edit the essentials in `config.yaml`:

```yaml
messaging:
  provider: cli                 # cli | telegram | discord
llm:
  base_url: "http://localhost:11434/v1"   # Ollama default
  model: "qwen3.5:4b"           # a model you've pulled (ollama list)
  api_key: "ollama"             # any non-empty string for Ollama/vLLM; real key for OpenAI
mcp:
  hot_reload: true
```

Run it:

```bash
lesysbot                          # health + metrics for ./config.yaml, then exit
lesysbot run                      # the service: control panel + bot
lesysbot chat -v        # force CLI chat + verbose logging
lesysbot -c /path/to/config.yaml  # explicit config
lesysbot --model qwen3.5 --base-url http://localhost:11434/v1   # ad-hoc overrides
```

No service is set up on this path — see [manage-service](../manage-service/SKILL.md)
to add one by hand.

## 5. Verify the install

```bash
lesysbot chat
```

Then in the session: `/help` lists the tools; `/disk_usage path=/tmp` runs one
directly (no LLM needed); a natural-language question ("what's the disk usage
of /tmp?") exercises the LLM + tool-calling path. `exit` quits.

If `lesysbot: command not found`: the shell was started before the command
existed. Open a new terminal, or `export PATH="$HOME/.local/bin:$PATH"`. On the
by-hand path, `python -m site --user-scripts` shows where pip put it.

## Related

- Change settings later: [configure-lesysbot](../configure-lesysbot/SKILL.md) —
  edit `~/.lesysbot/config.yaml`, restart the service.
- Telegram/Discord details: [setup-messaging](../setup-messaging/SKILL.md).
- Pick a model for the hardware: [switch-llm-backend](../switch-llm-backend/SKILL.md).
- Remove everything: [uninstall-lesysbot](../uninstall-lesysbot/SKILL.md).
