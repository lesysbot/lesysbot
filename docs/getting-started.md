# Getting started

From a fresh machine to a working bot. Roughly five minutes, most of it
downloading a model.

---

## Install it

One command. It works on a machine with nothing on it — no Python, no pipx, no
git, no clone — and it never asks you anything, so it is safe to run from a
script.

```bash
curl -fsSL https://lesysbot.github.io/install.sh | sh
```

```powershell
# Windows
irm https://lesysbot.github.io/install.ps1 | iex
```

Here is everything it does, in order:

| | |
|---|---|
| **Finds a Python** | 3.11 or newer. If there isn't one it fetches a private copy with [uv](https://docs.astral.sh/uv/) — no system packages, no root. |
| **Builds an isolated environment** | `~/.local/share/lesysbot/venv`, so LeSysBot's dependencies can't collide with anything else you have installed. |
| **Puts `lesysbot` on your PATH** | A link in `~/.local/bin`, added to your shell startup files if it isn't there already (`--no-modify-path` to skip). |
| **Gets a model ready** | Installs [Ollama](https://ollama.com) and pulls `qwen3.5:4b` — small, runs on almost anything, reliable at picking the right tool. |
| **Configures everything** | Runs `lesysbot setup --yes`: writes `~/.lesysbot/config.yaml`, installs the bundled tools and dashboards, brings up the Grafana stack, and starts the background service. |

When it finishes you have a working bot. Skip to [Check it worked](#check-it-worked).

> **Read it first?** Sensible — you should with any `curl | sh`.
> ```bash
> curl -fsSL https://lesysbot.github.io/install.sh -o install.sh
> less install.sh
> sh install.sh
> ```

### Options

Pass these after `sh -s --` when piping (`… | sh -s -- --skip-dashboard`), or
directly when you've downloaded the script. `--help` lists them all.

| Flag | What it does |
|---|---|
| `--skip-dashboard` | Don't set up Grafana/Prometheus. The fastest install. |
| `--skip-ollama` | Leave the model runner alone — you already have one, or you're using OpenAI. |
| `--no-model` | Install Ollama but don't download a model. |
| `--model NAME` | Pull a different model (see [Choosing a model](models.md)). |
| `--provider telegram` | Configure Telegram instead of terminal-only (see below). |
| `--no-modify-path` | Never touch your shell startup files. |
| `--prefix DIR` / `--bin-dir DIR` | Put the environment / the command somewhere else. |
| `--version X.Y.Z` / `--ref REF` | Install a specific release, branch or tag. |
| `--uninstall` / `--purge` | See [Uninstalling](#uninstalling). |

Every flag also has a `LESYSBOT_*` environment variable, because a bare
`curl … | sh` can't easily take arguments — `LESYSBOT_SKIP_DASHBOARD=1`,
`LESYSBOT_MODEL=…`, and so on.

### Where does Ollama need a password?

Nowhere that LeSysBot can avoid, and it never asks for one. On **macOS** and
**Windows** Ollama installs without elevation, so the installer just does it. On
**Linux** Ollama's own installer needs root — so unless you're already root (or
have passwordless `sudo`), the installer **skips it** and prints the two lines
for you to run:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:4b
```

Everything else is already configured, so that's all that's left. `--with-ollama`
runs it anyway and accepts the password prompt.

<details>
<summary><b>Installing a different way</b></summary>

**Into an environment you manage**, with Python 3.11+ already present:

```bash
pipx install git+https://github.com/lesysbot/lesysbot
lesysbot setup
```

The tools, the dashboards and the Prometheus/Grafana stack all ship inside the
package, so this works offline and `lesysbot update` can refresh them later.

**From a git checkout** — for working *on* LeSysBot, or to run an unreleased
version. Run from a checkout, the installer installs *that* checkout:

```bash
git clone https://github.com/lesysbot/lesysbot
cd lesysbot
sh scripts/install.sh
```

**By hand**, if you'd rather own every step:

```bash
python -m venv ~/.local/share/lesysbot/venv
~/.local/share/lesysbot/venv/bin/pip install "lesysbot[telegram,discord] @ https://github.com/lesysbot/lesysbot/archive/refs/heads/main.zip"
~/.local/share/lesysbot/venv/bin/lesysbot setup
```

</details>

<details>
<summary><b>Unattended and scripted installs</b></summary>

`lesysbot setup --yes` is what the installer runs. It takes every default
without prompting and reads overrides from the environment, so a complete
Telegram install is one command with no terminal involved:

```bash
LESYSBOT_SETUP_PROVIDER=telegram \
LESYSBOT_SETUP_TELEGRAM_TOKEN=123456:ABC… \
LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS=123456789 \
  curl -fsSL https://lesysbot.github.io/install.sh | sh
```

| Variable | Default |
|---|---|
| `LESYSBOT_SETUP_LLM` | `ollama` — or `openai`, `vllm`, `custom` |
| `LESYSBOT_SETUP_BASE_URL` | per backend (`http://localhost:11434/v1` for Ollama) |
| `LESYSBOT_SETUP_MODEL` | `qwen3.5:4b` |
| `LESYSBOT_SETUP_API_KEY` | `ollama` — **required** when the backend is `openai` |
| `LESYSBOT_SETUP_PROVIDER` | `cli` — or `telegram`, `discord` |
| `LESYSBOT_SETUP_TELEGRAM_TOKEN` | — required for `telegram` |
| `LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS` | — required for `telegram`, comma-separated |
| `LESYSBOT_SETUP_DISCORD_TOKEN` / `_DISCORD_ALLOWED_IDS` | the same, for Discord |
| `LESYSBOT_SETUP_AUTOSTART` | `1` — start at boot |
| `LESYSBOT_SETUP_GRAFANA_USER` | `admin` |
| `LESYSBOT_SETUP_GRAFANA_PASSWORD` | **generated**, saved 0600 to `~/.lesysbot/grafana.env` |

A missing required value aborts and names the variable to set, rather than
leaving a half-configured bot that anyone can message.

Re-running `lesysbot setup --yes` **keeps** your existing `config.yaml` and
refreshes everything else (tools, dashboards, service) — that's the upgrade
path. `--reconfigure` replaces the config instead.

</details>

Run **`lesysbot setup`** with no flags anytime to change your answers through
the interactive wizard. No reinstall needed.

<details>
<summary><b>Every question the interactive wizard asks, explained</b></summary>

Each prompt shows a default in `[brackets]` — press Enter to take it. Menus
respond to **↑/↓ + Enter**, or just press the option's number. From the second
question onward every menu has a **← Back** entry, reachable with the **←** key
or **Esc**. Esc at a typed prompt (URL, model, token) abandons it and returns to
the menu, so you can never get stuck.

**"`~/.lesysbot/config.yaml` already exists — overwrite?" `[y/N]`**
Only appears if you've installed before. `n` keeps your current settings and
skips to the startup question; `y` starts fresh. This protects a config you may
have hand-edited.

**"LLM Backend" `[1]`**

```
1) Ollama   — local, recommended (no API key needed)
2) OpenAI   — cloud API
3) vLLM     — self-hosted OpenAI-compatible server
4) Custom   — any OpenAI-compatible endpoint
```

All four speak the same protocol, so this only picks a URL and a key.

- **Ollama** — the wizard runs `ollama list` and shows the models you already
  have as a menu. The last entry lets you type any model name and pulls it on
  the spot. No models yet? It offers to download one (default `qwen3.5:4b`). No
  Ollama CLI on PATH? It asks for a name to use once Ollama is available.
- **OpenAI** — asks for a model (`gpt-4o`) and your API key. The key is stored
  in `config.yaml`, so keep that file private.
- **vLLM** — asks for the base URL (`http://localhost:8000/v1`) and the model id
  your server serves.
- **Custom** — anything else OpenAI-compatible (LM Studio, llama.cpp server, a
  proxy). Asks for the full URL including `/v1`, a model id, and an optional key.

**"How to reach LeSysBot" `[1]`**

```
1) Terminal only (default)
2) Telegram
3) Discord
```

The terminal always works regardless of this choice — `lesysbot chat`
opens a chat whatever you pick here. Telegram and Discord are *extra* remote
channels that run in the background.

- **Telegram** — asks for a bot token from
  [@BotFather](https://t.me/BotFather) and the numeric user IDs allowed to use
  the bot (find yours via [@userinfobot](https://t.me/userinfobot)). At least one
  ID is required; the wizard re-asks until you give one, because an empty list
  means *anyone who finds your bot can run your tools*.
- **Discord** — asks for a bot token and the numeric user IDs allowed to use
  the bot, the same way. Create the bot at
  [discord.com/developers/applications](https://discord.com/developers/applications)
  and **turn on the Message Content intent** — without it the bot can't read your
  messages. Full setup: [Telegram & Discord §3](adapters.md#3-discord).

**"Service" — start now, or also at every reboot? `[1]`**
Option 1 starts it now and again on every boot; option 2 starts it now only.
Every setup gets the service, whichever channel you picked: it serves the
[control panel](management-ui.md) (settings, tools, health) and, with Telegram or
Discord, receives your messages. A terminal chat is still yours to start — the
service never opens one.

**Summary — apply, change, or quit**
A final menu showing your model, provider, startup behaviour, and where the
config will go. **Apply** writes everything. The **Change …** entries jump back
into any step with your previous answers as the defaults. **Quit** exits without
writing anything.

**The Grafana dashboard — set up during install**
After it writes the config, setup also seeds the
[dashboard stack](../dashboard/README.md) into `~/.lesysbot/dashboard` and
gets you to a Grafana dashboard at **http://localhost:3000/d/lesysbot**. It first asks **how**
you want it set up (see per-OS below), then the **Grafana username and password**
LeSysBot should use to reach it (defaults `admin` / `admin`; the password is
hidden as you type). Those are saved to `~/.lesysbot/grafana.env`, which LeSysBot
loads at startup — so the `share_dashboard` tool and the status screen
authenticate automatically. This is a standard part of LeSysBot, not an opt-in —
and always no-`sudo`, never fatal to the install:

- **Linux** — Docker is the path. If Docker is already running, setup **asks
  whether to auto-start** the bundled Prometheus + Grafana stack now, or **set it
  up manually** later. The bundled Grafana boots with the username/password you
  entered. If Docker isn't ready, it prints the exact steps to get it going
  (install Docker Engine, start the daemon, or join the `docker` group) — or run
  Grafana natively instead.
- **macOS** — Homebrew is the path, and it **doesn't require Docker Desktop**.
  Setup asks whether to install it now, then `brew install`s Grafana, Prometheus
  and `node_exporter`, wires the datasource and dashboard up, sets Grafana's
  admin password to the one you entered, and runs all three under `brew
  services` so they survive a reboot. Nothing else to do — open
  `http://localhost:3000`. If Homebrew isn't installed, setup says so and falls
  back to the manual instructions below.

  It asks **one extra question here**: whether to install a small helper for
  CPU/GPU **die temperature**. macOS publishes that only through a private
  framework or root-only `powermetrics`, and LeSysBot never uses `sudo`, so those
  two tiles need `macmon` (Apple Silicon) or `smctemp` (either chip). The answer
  **defaults to no**, only the tool that can work on your Mac is offered, and a
  failed install never fails the setup — every other panel works without it, and
  you can add one at any time. Answer up front, or skip the prompt entirely on an
  unattended install, with `LESYSBOT_TEMP_HELPER=macmon|smctemp|none`.
- **Windows** — setup **doesn't require Docker Desktop**. It warns and walks you
  through a native Grafana install from
  [grafana.com/grafana/download](https://grafana.com/grafana/download): install
  it, open `http://localhost:3000`, and **set Grafana's admin login to the
  username/password you entered** so LeSysBot connects (it detects Grafana on
  port 3000 automatically; set `LESYSBOT_GRAFANA_URL` only if it runs elsewhere).
  If you *do* have Docker running, it also points out the one-command bundled
  stack as a shortcut.

Set `LESYSBOT_SKIP_DASHBOARD=1` before running setup to skip this step entirely
(e.g. an unattended install that shouldn't pull images or prompt).

**Re-running setup is how the stack gets updated.** From a checkout, it refreshes
the shipped scripts, dashboards and compose files in `~/.lesysbot/dashboard`
whenever they've changed upstream, while leaving the two things you own alone
forever: `.env` (ports, Grafana login) and `prometheus/` (any scrape targets you
added). Re-run your OS's start script afterwards so the dashboard is rebuilt with
the new code.

</details>

<details>
<summary><b>Install by hand instead (no wizard)</b></summary>

Three steps: install the package, write a config, run it.

**Install the package**

```bash
pip install ".[all]"       # terminal + Telegram + Discord
pip install .              # terminal and tools only — smaller
pip install -e ".[dev]"    # development install (adds pytest + ruff)
```

| Extra | Adds | Needed for |
|---|---|---|
| `telegram` | `python-telegram-bot` | `--provider telegram` |
| `discord` | `discord.py` | `--provider discord` |
| `all` | both | what the install scripts use |

Pick a provider you didn't install and LeSysBot tells you which extra to add
rather than crashing.

**Write a config**

```bash
cp config/default.yaml config.yaml
```

The parts that matter:

```yaml
messaging:
  provider: cli                 # cli | telegram | discord

llm:
  base_url: "http://localhost:11434/v1"   # Ollama default
  model: "qwen3.5:4b"           # a model you've pulled (ollama list)
  api_key: "ollama"             # any non-empty string for Ollama/vLLM
```

For OpenAI, change those three lines to
`https://api.openai.com/v1`, `gpt-4o`, and your real key. Everything else is in
[Settings](configuration.md).

**Run it**

```bash
lesysbot run                      # control panel + bot, using ./config.yaml
lesysbot chat -v        # force a terminal chat, verbose
lesysbot -c /path/to/config.yaml  # status for a config somewhere else
```

If you want it running in the background, set that up yourself:
[Run as a service](service.md#setting-one-up-by-hand).

</details>

---

## Check it worked

Run `lesysbot` on its own. It prints a health screen and exits — it starts
nothing, so it's safe to run any time, and it's the one command worth
remembering:

```console
$ lesysbot

LeSysBot v0.1.0
  LLM backend  reachable · 248 ms
  Backend URL  http://localhost:11434/v1
     Provider  cli · model qwen3.5:4b
        Tools  13/13 enabled
      Service  running (PID 1767)
Control panel  online · http://127.0.0.1:8700
      Grafana  http://localhost:3000/d/lesysbot · v11.5.1
       Config  /home/you/.lesysbot/config.yaml
```

Green across the board means you're done. If a row disagrees:

| Row | If it isn't happy | What to do |
|---|---|---|
| **LLM backend** | `down · …` | Ollama isn't running or the model isn't pulled. `ollama serve`, then `ollama pull qwen3.5:4b`. On Linux the installer may have left Ollama to you — see [above](#where-does-ollama-need-a-password). |
| **Tools** | `0/0 enabled` | Setup didn't finish seeding. Re-run `lesysbot setup --yes`. |
| **Service** | `stopped` | The background service isn't up. The row prints the exact start command for your OS; more in [Run as a service](service.md). |
| **Control panel** | `offline` | It comes up with the service — fix that row first. |
| **Grafana** | `not running` | Optional, and nothing else depends on it. `lesysbot dashboard start`. |
| — | `lesysbot: command not found` | Your shell hasn't picked up the new PATH entry yet. Open a new terminal, or run `. ~/.profile`. Details in [Troubleshooting](troubleshooting.md#lesysbot-command-not-found). |

Anything else: [Troubleshooting](troubleshooting.md) is organised by symptom.

---

## Say hello

```bash
lesysbot chat
```

```
You: what is 2 + 2?
Bot: 4.

You: what's the disk usage of /tmp?
Bot: /tmp has 2.3 GB free out of 20 GB — 11% used.

You: /disk_usage path=/tmp
Bot: Path: /tmp   Total: 20.0 GB   Free: 2.3 GB   Used: 11.0%
```

Those last two do the same thing two different ways. The first asked the model,
which chose a tool. The second called the tool directly — no model involved, so
it works even when Ollama is off.

Type **`/help`** to see every tool it currently has.

> Running as a Telegram/Discord service already? `lesysbot chat` still opens a
> separate terminal chat alongside it. They don't conflict. (`lesysbot chat` is
> short for `lesysbot --provider cli`, which also still works.)

Day-to-day guide: **[Everyday use](usage.md)**.

---

## Give it more to do

**Install the ready-made official collection** — one repo, every OS:

```bash
lesysbot search             # see what's on offer first
lesysbot install official   # network, temperature, battery, speedtest, dashboards
```

A running bot picks them up immediately — no restart.

`official` is a shortcut for the GitHub repo it lives in, and that's all an
install ever is:

```bash
lesysbot install lesysbot/lesysbot-packages-official   # the same thing, spelled out
lesysbot install someone/their-tools                   # anyone's repo, same command
```

More in [Install tools](installing-tools.md).

**Or write one.** Create `~/.lesysbot/tools/hello/tool.py`:

```python
from lesysbot.mcp import tool

@tool(description="Say hello to someone")
async def hello(name: str) -> str:
    return f"Hello, {name}! Nice to meet you."
```

Save it. It's live:

```
You: /hello name=World
Bot: Hello, World! Nice to meet you.

You: say hello to Alice
Bot: Hello, Alice! Nice to meet you.
```

Shell commands work too, with no Python logic:

```python
from lesysbot.mcp import CLITool

df = CLITool(
    name="df",
    description="Show disk usage for a filesystem path",
    command="df -h {path}",
    params={"path": "Filesystem path to check"},
)
```

Full guide: **[Write a tool](writing-tools.md)**.

---

## Manage it from a browser

The control panel is always on — the background service serves it:

```
http://127.0.0.1:8700
```

Edit settings and toggle, install, or remove tools there. It's bound to
`127.0.0.1`, so it never appears on your network. See
[Control panel](management-ui.md).

To check on things from a terminal instead, run `lesysbot` with no arguments: it
prints health and metrics — backend, tools, service, panel, Grafana — and exits.

---

## Uninstalling

The installer leaves a copy of itself behind, so this works with no network and
no checkout:

```bash
~/.local/share/lesysbot/install.sh --uninstall
```
```powershell
& "$env:USERPROFILE\.local\share\lesysbot\install.ps1" -Uninstall
```

It works backwards through what the installer did: stops and removes the
background service, stops the Grafana stack (without removing its Docker
volumes, so your stored history survives a reinstall), deletes the `lesysbot`
command and its environment, and takes its entry back out of your shell startup
files.

**It keeps `~/.lesysbot`** — your config, tools, dashboards and logs — so a
later reinstall finds everything as you left it. Add `--purge` (`-Purge` on
Windows) to delete that too.

Installed some other way? Then remove it that way — `pipx uninstall lesysbot`,
or delete the virtualenv you made — and `rm -rf ~/.lesysbot` when you're done
with the data.

---

## Where to next

| Want to… | Go to |
|---|---|
| Use it properly (history, arguments, confirmations) | [Everyday use](usage.md) |
| Message it from your phone | [Telegram & Discord](adapters.md) |
| Add abilities | [Write a tool](writing-tools.md) · [Install tools](installing-tools.md) |
| Change model, history size, logging | [Settings](configuration.md) |
| Keep it running in the background | [Run as a service](service.md) |
| Graph the machine over time | [Dashboards](../dashboard/README.md) |
| Fix something | [Troubleshooting](troubleshooting.md) |
| Understand the internals | [How it works](architecture.md) |
