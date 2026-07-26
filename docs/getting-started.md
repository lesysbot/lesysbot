# Getting started

From a fresh machine to a working bot. Roughly five minutes, most of it
downloading a model.

---

## What you need

- **Python 3.11 or newer.** Check with `python --version` (`python3` on
  Linux/macOS). On Windows, tick **"Add Python to PATH"** in the installer.
- **A model to talk to.** [Ollama](https://ollama.com) runs one locally and is
  what we'll use below. If you'd rather use OpenAI or another remote service,
  skip step 1 — you'll pick that in the wizard.

---

## 1. Get a model running

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS
brew install ollama

# Windows — download the installer from https://ollama.com/download
```

Then pull a model. `llama3.2` is small (~2 GB) and a fine starting point:

```bash
ollama pull llama3.2
```

Check it's up:

```bash
curl http://localhost:11434/          # → "Ollama is running"
```

> **Bigger machine?** A stronger model makes the bot noticeably better at
> picking the right tool. [Choosing a model](models.md) matches models to GPU
> memory.

---

## 2. Install LeSysBot

```bash
git clone https://github.com/lesysbot/lesysbot
cd lesysbot
```

```bash
bash scripts/install.sh          # Linux / macOS
```
```powershell
.\scripts\install.ps1            # Windows (PowerShell)
```

> **PowerShell blocked the script?** Run
> `powershell -ExecutionPolicy Bypass -File scripts\install.ps1` instead.

A wizard opens and asks a handful of short questions. **Press Enter through all
of them** for a working local bot you chat with in your terminal. Nothing is
written to disk until you pick **Apply** at the end, and you can back out of any
answer with **Esc** or the **←** key.

Your settings land in **`~/.lesysbot/config.yaml`**, with your tools in
`~/.lesysbot/tools/`. That folder is your bot's home from then on — it doesn't
matter where you cloned the source.

Want to change something later? Run **`lesysbot setup`** again. No reinstall
needed.

<details>
<summary><b>Every question the wizard asks, explained</b></summary>

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
  the spot. No models yet? It offers to download one (default `llama3.2`). No
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

The terminal always works regardless of this choice — `lesysbot --provider cli`
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
[monitoring stack](../monitoring/README.md) into `~/.lesysbot/monitoring` and
gets you to a Grafana dashboard at **http://localhost:3000**. It first asks **how**
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
- **macOS / Windows** — setup **doesn't require Docker Desktop**. It warns and
  walks you through a native Grafana install from
  [grafana.com/grafana/download](https://grafana.com/grafana/download): install
  it, open `http://localhost:3000`, and **set Grafana's admin login to the
  username/password you entered** so LeSysBot connects (it detects Grafana on
  port 3000 automatically; set `LESYSBOT_GRAFANA_URL` only if it runs elsewhere).
  If you *do* have Docker running, it also points out the one-command bundled
  stack as a shortcut.

Set `LESYSBOT_SKIP_MONITORING=1` before running setup to skip this step entirely
(e.g. an unattended install that shouldn't pull images or prompt).

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
  model: "llama3.2"             # a model you've pulled (ollama list)
  api_key: "ollama"             # any non-empty string for Ollama/vLLM
```

For OpenAI, change those three lines to
`https://api.openai.com/v1`, `gpt-4o`, and your real key. Everything else is in
[Settings](configuration.md).

**Run it**

```bash
lesysbot run                      # control panel + bot, using ./config.yaml
lesysbot --provider cli -v        # force a terminal chat, verbose
lesysbot -c /path/to/config.yaml  # status for a config somewhere else
```

If you want it running in the background, set that up yourself:
[Run as a service](service.md#setting-one-up-by-hand).

</details>

---

## 3. Say hello

```bash
lesysbot --provider cli
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

> Running as a Telegram/Discord service already? `lesysbot --provider cli` still
> opens a separate terminal chat alongside it. They don't conflict.

Day-to-day guide: **[Everyday use](usage.md)**.

---

## 4. Give it more to do

**Install a ready-made collection for your OS:**

```bash
lesysbot tools install lesysbot/lesysbot-linux-tools-official     # ping, DNS, traceroute, temps
lesysbot tools install lesysbot/lesysbot-macos-tools-official     # battery, temps
lesysbot tools install lesysbot/lesysbot-windows-tools-official   # ping, tracert, temps
```

A running bot picks them up immediately. More in
[Install tools](installing-tools.md).

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

## 5. Manage it from a browser

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

From the cloned repository:

```bash
bash scripts/uninstall.sh          # Linux / macOS
```
```powershell
.\scripts\uninstall.ps1            # Windows (PowerShell)
```

It works backwards through what the installer did:

1. **Stops and removes the background service**, if you had one. On Linux it
   also offers to undo `loginctl` linger.
2. **Reports any leftover sudoers rule** from an older version and prints the
   command to delete it — it won't delete it itself, since that would mean
   asking for your password. Current LeSysBot needs no root, so this usually
   prints nothing.
3. **Uninstalls the `lesysbot` package** via pip.
4. **Offers to stop the Grafana monitoring dashboard** (the Docker containers
   setup started). It stops them without removing the Docker volumes, so your
   stored history survives a reinstall.
5. **Asks before deleting `~/.lesysbot`** — your config, tools, monitoring stack,
   and logs. The default is **No**, so a later reinstall finds everything as you
   left it.

---

## Where to next

| Want to… | Go to |
|---|---|
| Use it properly (history, arguments, confirmations) | [Everyday use](usage.md) |
| Message it from your phone | [Telegram & Discord](adapters.md) |
| Add abilities | [Write a tool](writing-tools.md) · [Install tools](installing-tools.md) |
| Change model, history size, logging | [Settings](configuration.md) |
| Keep it running in the background | [Run as a service](service.md) |
| Graph the machine over time | [System monitoring](../monitoring/README.md) |
| Fix something | [Troubleshooting](troubleshooting.md) |
| Understand the internals | [How it works](architecture.md) |
