---
name: install-lesysbot
description: Install LeSysBot from scratch on Linux, macOS, or Windows — prerequisites (Python, Ollama), the guided install wizard with every prompt explained, or a fully scripted manual install. Use when asked to "install lesysbot", "set up lesysbot", "get lesysbot running", or to onboard a new machine.
---

# Install LeSysBot

LeSysBot is a local AI assistant: an LLM (Ollama by default) plus a set of tools it
can call, reachable from the terminal, Telegram, or Slack. Installing it means:
install the Python package, write a config, and register the background service
that serves the management panel (and any Telegram/Slack bot).

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | `python --version` (try `python3` on Linux/macOS). On Windows tick "Add Python to PATH". |
| pip | any | bundled with Python |
| Ollama *(optional)* | latest | Only for a local LLM. Skip if using OpenAI or another remote backend. |

**Install Ollama and pull a model** (skip for remote backends):

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh
# macOS
brew install ollama
# Windows: installer from https://ollama.com/download

ollama pull qwen3.5:4b        # small, capable starting point
curl http://localhost:11434/  # → "Ollama is running"
```

## 2. Path A — guided wizard (recommended for most people)

No clone needed — the package installs straight from GitHub:

```bash
# Linux / macOS
pipx install git+https://github.com/lesysbot/lesysbot && lesysbot setup
```

```powershell
# Windows
pipx install git+https://github.com/lesysbot/lesysbot; lesysbot setup
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
   `3) Slack` (asks `xoxb-…` bot token + `xapp-…` app token),
   `4) ← Back` (re-pick the LLM backend).
   The terminal always works regardless: `lesysbot --provider cli`.
4. **"Service"** — asked for **every** provider (systemd / launchd / Task
   Scheduler), because the service also serves the always-on management panel:
   `1) Start now and automatically after reboot` (default; "at login" on
   Windows), `2) Start now only`, `3) ← Back` (re-pick how to reach LeSysBot).
   On the kept-config path this is a plain
   **"Start LeSysBot automatically after reboot?" `[Y/n]`** instead.
5. **Summary menu** — `1) Apply these settings` (default; only now is
   anything written), `2) Change LLM backend`, `3) Change how to reach
   LeSysBot`, `4) Change startup behaviour`,
   last) `Quit — exit without writing config`. On the kept-config path it's
   a plain **"Apply these settings?" `[Y/n]`**.

The wizard never uses `sudo` — and neither does any tool. No official package
requires root, a sudoers rule, or an Administrator prompt, so there is never a
privileged follow-up step: install a package and it works.

What the wizard does: writes **`~/.lesysbot/config.yaml`**, seeds
**`~/.lesysbot/tools/`** (never clobbers an existing one), installs the `lesysbot`
command, and installs + starts the background service running from
`~/.lesysbot` — for every provider, since that service hosts the management panel
(`http://127.0.0.1:8700`) as well as any Telegram/Slack bot. Re-running it stops
and replaces an existing service. `LESYSBOT_HOME` overrides the `~/.lesysbot`
location.

It also seeds **`~/.lesysbot/dashboard/`** (the Grafana/Prometheus dashboard) and
sets it up — a standard part of LeSysBot. It first **asks for the Grafana username
and password** LeSysBot should use (defaults `admin`/`admin`), saving them to
**`~/.lesysbot/grafana.env`** (loaded into the bot's environment at startup, so
`share_dashboard`/status authenticate automatically). Then, OS-specific and never
fatal:
- **Linux** — if Docker is running, it **asks** whether to auto-start the bundled
  stack now or set it up manually; if Docker isn't ready it prints the exact
  no-`sudo` steps to get it going (or run Grafana natively).
- **macOS** — it does **not** require Docker Desktop. It **asks** whether to
  install now, then runs `dashboard/scripts/install-macos.sh`: `brew install`
  of `grafana`/`prometheus`/`node_exporter`, provisioning written, admin password
  set, all three started under `brew services`. Without Homebrew it says so
  (`https://brew.sh`) and falls back to the manual instructions.
- **Windows** — it does **not** require Docker Desktop; it warns and
  instructs a native Grafana install from `https://grafana.com/grafana/download`
  and how to connect it (auto-detected on `localhost:3000`, else
  `LESYSBOT_GRAFANA_URL`), mentioning the one-command Docker stack only as a
  shortcut when Docker is already running.

Set `LESYSBOT_SKIP_DASHBOARD=1` to skip this step on an unattended install.

## 3. Path B — manual install from a clone (scriptable, full control)

```bash
git clone https://github.com/lesysbot/lesysbot.git
cd lesysbot
pip install ".[all]"             # telegram + slack extras
# pip install .                  # minimal: terminal chat and tools only
# pip install -e ".[dev]"        # development (adds pytest + ruff)
lesysbot --help                    # verify the command exists
cp config/default.yaml config.yaml
```

Edit the essentials in `config.yaml`:

```yaml
messaging:
  provider: cli                 # cli | telegram | slack
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
lesysbot run                      # the service: management panel + bot
lesysbot --provider cli -v        # force CLI chat + verbose logging
lesysbot -c /path/to/config.yaml  # explicit config
lesysbot --model qwen3.5 --base-url http://localhost:11434/v1   # ad-hoc overrides
```

No service is set up on this path — see [manage-service](../manage-service/SKILL.md)
to add one by hand.

## 4. Verify the install

```bash
lesysbot --provider cli
```

Then in the session: `/help` lists the tools; `/disk_usage path=/tmp` runs one
directly (no LLM needed); a natural-language question ("what's the disk usage
of /tmp?") exercises the LLM + tool-calling path. `exit` quits.

If `lesysbot: command not found`: pip's scripts dir isn't on PATH —
`python -m site --user-scripts` shows it (e.g. `~/.local/bin`); add it to PATH.

## Related

- Change settings later: [configure-lesysbot](../configure-lesysbot/SKILL.md) —
  edit `~/.lesysbot/config.yaml`, restart the service.
- Telegram/Slack details: [setup-messaging](../setup-messaging/SKILL.md).
- Pick a model for the hardware: [switch-llm-backend](../switch-llm-backend/SKILL.md).
- Remove everything: [uninstall-lesysbot](../uninstall-lesysbot/SKILL.md).
