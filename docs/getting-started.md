# Getting Started with LeSysBot

This guide takes you from a fresh machine to a working bot with your first custom tool.

There are **two ways to install**, and they are documented separately so you can pick one and follow it top to bottom:

- **[Quick Start — guided installer](#5-quick-start--guided-installer)** — one command runs a wizard that asks a few questions and sets everything up for you (including an optional background service). Best for most people. Every question is explained below.
- **[Manual installation — step by step](#6-manual-installation--step-by-step)** — you install the package, write the config file yourself, and run it. Best if you want full control or are scripting the setup.

Do **Sections 1–2 first** (they apply to both paths), then jump to whichever install path you prefer.

---

## 1. Prerequisites

| Requirement | Version | Install | Why |
|---|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) | Runs LeSysBot. On Windows, tick **"Add Python to PATH"** in the installer. |
| pip | any | bundled with Python | Installs the package. |
| Ollama *(optional)* | latest | [ollama.com](https://ollama.com) | Runs an LLM locally. Skip if you'll use OpenAI or another remote backend. |

Check Python is available:

```bash
python --version      # should print 3.11 or higher (try python3 on Linux/macOS)
```

---

## 2. Install Ollama and pull a model

Ollama runs the language model locally on your machine — no cloud, no API key. **Skip this section** if you plan to use OpenAI or another remote backend.

**Install Ollama:**

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS
brew install ollama

# Windows — download and run the installer from:
# https://ollama.com/download
```

**Pull a model.** `llama3.2` is a small, capable starting point (~2 GB):

```bash
ollama pull llama3.2
```

**Verify Ollama is running:**

```bash
curl http://localhost:11434/
# should print: Ollama is running
```

> Pick a model that fits your hardware — and manage it with Ollama — in
> [Models](models.md).

---

## 3. Get the code

Both install paths start from a local clone of the repository:

```bash
git clone https://github.com/lesysbot/lesysbot.git
cd lesysbot
```

Now choose **one** of the two paths below.

---

## 4. Which install path should I use?

| | Quick Start (wizard) | Manual installation |
|---|---|---|
| **Effort** | Answer a few prompts | Edit a YAML file yourself |
| **Config file** | Written for you | You copy and edit it |
| **Background service** | Optional, set up for you | You set it up later (see [Running as a Service](service.md)) |
| **Best for** | Most users, first-time setup | Power users, servers, automation |
| **Go to** | [Section 5](#5-quick-start--guided-installer) | [Section 6](#6-manual-installation--step-by-step) |

---

## 5. Quick Start — guided installer

Run the installer for your OS:

```bash
# Linux / macOS
bash scripts/install.sh
```

```powershell
# Windows (PowerShell)
.\scripts\install.ps1
```

> **Windows execution policy.** If PowerShell blocks the script with a red error, run it this way instead:
> ```powershell
> powershell -ExecutionPolicy Bypass -File scripts\install.ps1
> ```

The script installs the package, then hands off to **`lesysbot setup`** — the wizard itself is part of LeSysBot (drawn with panels in your terminal), so you can **re-run `lesysbot setup` at any time to reconfigure** without reinstalling. It asks the questions below. **Press Enter to accept the value shown in `[brackets]`** — the defaults are chosen so that just pressing Enter through everything gives you a working local CLI bot.

### 5.1 The wizard, question by question

Each prompt looks like `?  Question [default]:`. Here is every question you may see, what to type, and why it matters.

> **Menus are navigable.** For any multiple-choice question (LLM backend, messaging provider, Ollama model) you can move the highlight with the **↑/↓ arrow keys** and confirm with **Enter** (or **→**), or just **press the option's number**. The number-based instructions below still apply if you prefer typing. When the installer is run without an interactive terminal (e.g. piped input), it falls back to a plain "type a number" prompt.

> **And you can go back.** From the messaging step onward, every menu ends with a **← Back** entry that returns to the previous step — press the **← arrow key** or **Esc** to take it directly, no scrolling needed (the menu's hint line says so whenever it applies). **Esc also works at the typed prompts** (base URL, model, tokens, user IDs — they show an `(Esc = back)` hint): it abandons the answer and returns to that step's menu, so a wrong turn never traps you at a text field. The final summary ([Q5](#q5-summary--apply-change-or-quit)) is itself a menu whose **Change …** entries jump straight back into any step — so no choice is final until you apply. Revisiting a step offers your **previous answers as the defaults** (press Enter to keep them; picking a *different* LLM backend clears its follow-up answers, since e.g. a `gpt-4o` default would only mislead under vLLM). Nothing is written to disk until you choose **Apply** on the summary.

#### Q1. "~/.lesysbot/config.yaml already exists — overwrite with new settings?" `[y/N]`

- **Only appears if** you've installed before and a `~/.lesysbot/config.yaml` is already present.
- **Type `n` (default)** to keep your existing settings and skip straight to the service step.
- **Type `y`** to start fresh and re-answer everything.
- *Why:* protects a config you may have hand-edited from being overwritten by accident.

#### Q2. "LLM Backend — Choice" `[1]`

```
  1) Ollama    — local, recommended (no API key needed)
  2) OpenAI    — cloud API
  3) vLLM      — self-hosted OpenAI-compatible server
  4) Custom    — any OpenAI-compatible endpoint
```

- **Type `1` (default)** if you installed Ollama in Section 2. This is the recommended local setup.
- **Type `2`** to use OpenAI's cloud models (you'll need an API key).
- **Type `3`** if you run a [vLLM](https://docs.vllm.ai) server.
- **Type `4`** for any other OpenAI-compatible endpoint (LlamaCpp server, LM Studio, a proxy, etc.).
- *Why:* this picks the `base_url`/`api_key` pair LeSysBot talks to. All backends use the same OpenAI-compatible protocol, so only these connection details change.

**Follow-up questions depend on the backend you chose:**

**If you chose `1) Ollama`:**

- The wizard runs `ollama list` for you and shows a **numbered menu of the models you already have installed** — just type the number to pick one (no need to remember exact names). The last entry, **"Pull a different model (enter a name)"**, lets you type any model id (e.g. `qwen3.5`, `gemma3:4b`) and the wizard runs `ollama pull` immediately so it's ready before LeSysBot starts.
- If **no models are installed yet**, the wizard offers to download one on the spot (default `llama3.2`).
- If the **Ollama CLI isn't found**, it falls back to asking for a model name to use once Ollama is available, and points you to [ollama.com](https://ollama.com).
- *The API key is set to `ollama` automatically — Ollama ignores it but the client requires a value.*

**If you chose `2) OpenAI`:**

- **"Model"** `[gpt-4o]` — an OpenAI model id such as `gpt-4o` or `gpt-4o-mini`.
- **"API key (sk-...)"** — paste your secret key from [platform.openai.com](https://platform.openai.com/api-keys). *This is stored in `config.yaml`, so keep that file private.*

**If you chose `3) vLLM`:**

- **"vLLM base URL"** `[http://localhost:8000/v1]` — where your vLLM server listens. Keep the default if it's local.
- **"Model"** `[meta-llama/Llama-3.2-8B-Instruct]` — the model id your vLLM server serves. *API key is set to `vllm` automatically.*

**If you chose `4) Custom`:**

- **"Base URL"** `[http://localhost:8000/v1]` — the full OpenAI-compatible endpoint, including `/v1`.
- **"Model"** `[llama3.2]` — the model id that endpoint expects.
- **"API key"** `[none]` — a key if the endpoint needs one, otherwise leave the default.

#### Q3. "How to reach LeSysBot — Choice" `[1]`

```
  1) Terminal only (default)
  2) Telegram
  3) Slack
  4) ← Back — change the LLM backend
```

- **Type `1` (default)** to just chat in your terminal. Nothing else to configure — great for trying LeSysBot out.
- **Type `2`** to also run a Telegram bot you can message from your phone.
- **Type `3`** to also run a Slack bot.
- **Type `4`** to go back and re-pick the LLM backend — your previous answers are offered again as the defaults.
- *Why:* the terminal is always available regardless of this choice — `lesysbot --provider cli` works no matter what. Telegram/Slack are *additional* remote channels that run as a background service (see [Q4](#q4-service--start-now-or-also-at-every-reboot-1)). Even with one selected, you can still open a local terminal chat with `lesysbot --provider cli` — it's a separate session with its own conversation history. Change it later by editing `config.yaml` or passing `--provider`.

**Follow-up questions depend on the provider you chose:**

**If you chose `2) Telegram`:**

- **"Bot token (from @BotFather)"** — create a bot by messaging [@BotFather](https://t.me/BotFather) with `/newbot`; it gives you a token like `1234567890:ABC...`. Paste it here.
- **"Allowed Telegram user IDs, comma-separated"** — your numeric Telegram ID (find it via [@userinfobot](https://t.me/userinfobot)), e.g. `123456789`. At least one ID is required — the wizard re-asks until you enter one. *Why:* this is an allow-list so strangers can't drive your tools. If you truly want a public bot, set `allowed_user_ids: []` by hand in `config.yaml` afterwards — the wizard won't write that for you.

**If you chose `3) Slack`:**

- **"Bot token (xoxb-...)"** — the Bot User OAuth Token from your Slack app's **OAuth & Permissions** page.
- **"App token (xapp-...)"** — an app-level token with `connections:write`, used for Socket Mode.
- *See [Messaging Adapters](adapters.md#3-slack) for the exact Slack app setup steps.*

#### Q4. "Service" — start now, or also at every reboot? `[1]`

```
  1) Start now and automatically after reboot (recommended)
  2) Start now only — not after reboot
  3) ← Back — change how to reach LeSysBot
```

- **Only appears for Telegram or Slack.** Those providers run in the background to poll for incoming messages, so they're installed as a service (systemd on Linux, launchd on macOS, Task Scheduler on Windows). The **CLI** provider is an interactive terminal session you start on demand — it installs no service, so this question is skipped entirely.
- **Type `1` (default)** to have the service start now and again on every boot/login. (On Windows the wording is "at login" — the Task Scheduler trigger fires when you log on.)
- **Type `2`** to install the service but start it yourself when you want it.
- **Type `3`** to go back and re-pick how to reach LeSysBot.
- *Why:* a chat bot you message from your phone should be always-on; a terminal session shouldn't be a background daemon (it has no terminal to read from).
- *Re-running the installer over an existing config you chose to keep asks this as a plain **"Start LeSysBot automatically after reboot?" `[Y/n]`** instead — there are no other steps to navigate back to on that path.*

#### Q5. Summary — apply, change, or quit

The wizard prints a **summary** (model, provider, startup, config path) followed by a final menu:

```
  1) Apply these settings
  2) Change LLM backend
  3) Change how to reach LeSysBot
  4) Change startup behaviour
  5) Quit — exit without writing config
```

- **Type `1` (default)** to apply: only now is `config.yaml` written and any service set up.
- **Type `2`–`4`** to jump back into that step and re-answer it (previous answers offered as defaults); you then return here for another look. **"Change startup behaviour" only appears when a background service will be installed** (Telegram/Slack) — for Terminal only, the quit entry is `4`.
- **Pick "Quit"** to exit without writing anything — the `lesysbot` package itself stays installed, and re-running the script starts the wizard fresh.
- *Why:* a last chance to review — and fix — everything before the installer writes files and starts the service. If you kept an existing config at [Q1](#q1-lesysbotconfigyaml-already-exists--overwrite-with-new-settings-yn), you get a simple **"Apply these settings?" `[Y/n]`** confirmation instead.

### 5.2 What the wizard does for you

After you choose **Apply**, the installer:

1. Writes your answers to **`~/.lesysbot/config.yaml`** and seeds your tools into **`~/.lesysbot/tools/`** (override the location with `LESYSBOT_HOME`). This is your stable home, independent of where you cloned the source — edit this file to change settings later.
2. Installs the **`lesysbot`** command.
3. **For Telegram/Slack only:** installs and starts a **background service** (running from `~/.lesysbot`) that restarts on failure and (if you chose auto-start) on reboot. For **CLI**, nothing is installed to run in the background — you start a chat with `lesysbot --provider cli` when you want it. Re-running the installer **stops and replaces** any existing service (and **restarts** it) so a changed model/provider actually takes effect. If you switch *back* to **Terminal only** and a service from a previous Telegram/Slack install is still present, the wizard asks **"Stop and remove that background service?"** `[Y/n]` — answer `y` so the old bot stops polling in the background; `n` leaves it running.

When it finishes, your bot is configured — and already running if you set up a Telegram/Slack service. Continue to [Section 7](#7-have-your-first-conversation).

> **To change settings later:** re-run **`lesysbot setup`** (the same wizard, no reinstall — it offers to overwrite or keep your config), or edit `~/.lesysbot/config.yaml` by hand. Then restart the service to apply — `systemctl --user restart lesysbot` (Linux), `launchctl kickstart -k gui/$(id -u)/com.lesysbot.lesysbot` (macOS), or `Stop-ScheduledTask -TaskName LeSysBot; Start-ScheduledTask -TaskName LeSysBot` (Windows). CLI sessions just pick up the new config on next launch. (`lesysbot setup` restarts the service for you when one is installed.)

> Managing the background service (start/stop/logs) is covered in [Running as a Service](service.md).

---

## 6. Manual installation — step by step

Use this path if you'd rather not run the wizard. It does the same three things by hand: install the package, create a config, run it.

### 6.1 Install the package

```bash
# Everything the wizard can offer: Telegram, Slack, and the web dashboard
pip install ".[all]"

# …or the minimal install — terminal chat and tools only, no chat platforms
pip install .

# …or a development install (adds pytest + ruff on top of [all])
pip install -e ".[dev]"
```

**Extras.** The base install covers terminal chat, the tool registry, and the
`lesysbot tools` / `lesysbot setup` commands. Chat platforms and the dashboard are
opt-in so a CLI-only install stays small:

| Extra | Adds | Needed for |
|---|---|---|
| `telegram` | `python-telegram-bot` | `--provider telegram` |
| `slack` | `slack-bolt`, `aiohttp` | `--provider slack` |
| `dashboard` | `aiohttp` | `lesysbot --dashboard` |
| `all` | all three | what `scripts/install.{sh,ps1}` install |

Pick a provider you didn't install and LeSysBot names the extra to add rather
than failing with a traceback.

Verify the command is available:

```bash
lesysbot --help
```

> If you get "command not found", pip's scripts directory isn't on your `PATH`. See [Running as a Service §6](service.md#lesysbot-command-not-found).

### 6.2 Create your config file

Copy the documented default and open it in an editor:

```bash
cp config/default.yaml config.yaml
```

Edit the parts that matter for your setup. The essentials:

```yaml
messaging:
  provider: cli                 # cli | telegram | slack

llm:
  base_url: "http://localhost:11434/v1"   # Ollama default
  model: "llama3.2"             # a model you've pulled (ollama list)
  api_key: "ollama"             # any non-empty string for Ollama/vLLM; real key for OpenAI

mcp:
  hot_reload: true              # reload tools/ when you save a .py file
```

To use **OpenAI** instead of Ollama, change three lines:

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "sk-..."             # your real key — keep config.yaml private
```

For Telegram/Slack credentials and every available setting, see the [Configuration reference](configuration.md).

### 6.3 Run it

```bash
lesysbot                          # uses ./config.yaml (or config/default.yaml)
lesysbot --provider cli -v        # force CLI + verbose logging
lesysbot -c /path/to/config.yaml  # use a config in another location
```

You can also override settings ad-hoc without editing the file:

```bash
lesysbot --model qwen3.5 --base-url http://localhost:11434/v1
```

That's the manual install done — continue below.

---

## 7. Have your first conversation

Start a CLI session (if the service is already running, this just opens a second, interactive session):

```bash
lesysbot --provider cli
```

Try a few things:

```
You: what is 2 + 2?
Bot: 4.

You: /help
Bot: Available commands — use /help to see this list

/get_system_info
  Return basic information about the current machine.

/disk_usage <path>
  Check how much free disk space is available at a given path

/fetch_url <url>
  Fetch the text content of a URL
...

You: what's the disk usage of /tmp?
Bot: The /tmp directory has 2.3 GB free out of 20 GB total (11% used).

You: /disk_usage path=/tmp
Bot: Path: /tmp
     Total: 20.0 GB   Free: 2.3 GB   Used: 11.0%
```

Notice the last two — one used the LLM to understand the question and pick the right tool, the other called the tool directly with `/` (no LLM involved).

> **Want the full usage guide?** [Using LeSysBot](usage.md) covers chatting vs. slash commands, passing arguments, confirmations, conversation history, and switching models on the fly.

---

## 8. Write your first tool

Create a new file in the `tools/` directory:

```python
# tools/hello.py
from lesysbot.mcp import tool

@tool(description="Say hello to someone")
async def hello(name: str) -> str:
    return f"Hello, {name}! Nice to meet you."
```

Save the file. LeSysBot hot-reloads it immediately — no restart needed.

```
You: /hello name=World
Bot: Hello, World! Nice to meet you.

You: say hello to Alice
Bot: Hello, Alice! Nice to meet you.
```

The tool is available both as a `/command` and through natural language.

> A single `.py` file like this is perfect for quick local tools. To make a tool
> you can **share / copy-paste** (with a README and cross-platform metadata), put
> it in its own folder — `tools/hello/tool.py` + `tools/hello/README.md`. See
> [Writing Tools](writing-tools.md) and the catalog in `tools/README.md`.

---

## 9. Wrap a shell command as a tool

```python
# tools/ops.py
from lesysbot.mcp import CLITool

df = CLITool(
    name="df",
    description="Show disk usage for a filesystem path",
    command="df -h {path}",
    params={"path": "Filesystem path to check"},
)
```

Again, save and it's live:

```
You: /df path=/
Bot: Filesystem      Size  Used Avail Use% Mounted on
     /dev/sda1       200G  155G   45G  78% /
```

---

## 10. Uninstalling

If you want to remove LeSysBot later, run the uninstall script for your OS from the cloned repository:

```bash
# Linux / macOS
bash scripts/uninstall.sh
```

```powershell
# Windows (PowerShell)
.\scripts\uninstall.ps1
```

> **Windows execution policy.** As with the installer, if PowerShell blocks the script, run:
> ```powershell
> powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1
> ```

The script undoes everything the installer set up, in order:

1. **Stops and removes the background service** (systemd on Linux, launchd on macOS, Task Scheduler on Windows) — skipped with a note if none is installed, e.g. for a Terminal-only setup. On Linux it also offers to disable `loginctl` linger if the installer enabled it.
2. **Offers to remove the wake-up sudoers rule** (`/etc/sudoers.d/lesysbot-rtcwake`) — Linux only, and only if one was set up for the optional `shutdown-wake` tool (its `setup-sudoers.sh`, or an older install wizard).
3. **Uninstalls the `lesysbot` Python package** via pip.
4. **Asks before deleting `~/.lesysbot`** (your config, tools, and logs; the location honours `LESYSBOT_HOME`). The default is **No** — keeping it means a later re-install finds your settings and custom tools exactly as you left them. Answer `y` only if you want a completely clean machine.

Both paths (wizard and manual) are covered — if you installed manually and never set up a service, step 1 skips itself and the rest still applies.

---

## 11. Next Steps

| Topic | Where to look |
|---|---|
| Use it day to day (chat, slash commands, history) | [Using LeSysBot](usage.md) |
| All tool options (`confirm`, type hints, multiple tools per file) | [Writing Tools](writing-tools.md) |
| Manage tools + check LLM health in a browser | [Dashboard](dashboard.md) |
| Set up Telegram or Slack in detail | [Messaging Adapters](adapters.md) |
| Change model, adjust history size, disable logging | [Configuration](configuration.md) |
| Run as a background service / auto-start on boot | [Running as a Service](service.md) |
| Ship a standalone `lesysbot.exe` to Windows users | [Building a Windows .exe](building-windows-exe.md) |
| Pick the best model for your hardware | [Models](models.md) |
| Understand how it all works inside | [Architecture](architecture.md) |
| Contribute a tool, adapter, or fix | [CONTRIBUTING.md](../CONTRIBUTING.md) |
