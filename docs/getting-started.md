# Getting started

Install it, say hello, open the control panel. About five minutes, most of it
spent downloading a model.

## 1. Install

```bash
curl -fsSL https://lesysbot.github.io/install.sh | sh
```

One command, no questions, no password. It installs LeSysBot, Ollama and a small
model (`qwen3.5:4b`), sets up the [Grafana dashboard](dashboards.md), and starts
the [background service](service.md). Your settings go in
`~/.lesysbot/config.yaml`.

> **Ollama needs root to install.** If you aren't root, the installer skips it
> and prints the two commands to run yourself:
>
> ```bash
> curl -fsSL https://ollama.com/install.sh | sh
> ollama pull qwen3.5:4b
> ```

## 2. Say hello

```bash
lesysbot chat
```

```
You: how much space is left on /?
Bot: 45 GB free out of 200 GB — 78% used.

You: /disk_usage /
Bot: Path: /   Total: 200.0 GB   Free: 45.0 GB   Used: 78.0%
```

Ask in plain words and the model picks a tool. Start with `/` to run a tool
yourself — that works even when the model is off. `/help` lists every tool;
`exit` leaves.

## 3. Open the control panel

Go to **<http://127.0.0.1:8700>** to change settings and turn tools on or off.
It's always on, and only reachable from this machine.

For a quick health check in the terminal, run `lesysbot` on its own.

## Change your answers

```bash
lesysbot setup
```

Answer **y** to replace your settings. The wizard then asks which model to use,
whether to connect Telegram or Discord, and whether to start at boot — press
Enter to take a default. It restarts the service when it's done.

## Next steps

| I want to… | Read |
|---|---|
| Message it from my phone | [Telegram & Discord](adapters.md) |
| Learn the day-to-day basics | [Everyday use](usage.md) |
| Give it a new ability | [Write a tool](writing-tools.md) |
| Fix something | [Troubleshooting](troubleshooting.md) |

---

## Install options

Add flags after `sh -s --`:

```bash
curl -fsSL https://lesysbot.github.io/install.sh | sh -s -- --skip-dashboard
```

| Flag | Effect |
|---|---|
| `--model NAME` | Pull a different model — see [Choosing a model](models.md) |
| `--skip-ollama` | Don't install Ollama (you already have one, or you use OpenAI) |
| `--skip-dashboard` | Don't set up Grafana |
| `--no-modify-path` | Don't touch your shell startup files |
| `--help` | List every flag |

<details>
<summary><b>Other ways to install</b></summary>

**Read the script first:**

```bash
curl -fsSL https://lesysbot.github.io/install.sh -o install.sh
less install.sh
sh install.sh
```

**With pipx** (needs Python 3.11+):

```bash
pipx install "lesysbot[telegram,discord] @ git+https://github.com/lesysbot/lesysbot"
lesysbot setup
```

**From a checkout** — installs that checkout:

```bash
git clone https://github.com/lesysbot/lesysbot
cd lesysbot && sh scripts/install.sh
```

</details>

<details>
<summary><b>Unattended install (scripts, CI)</b></summary>

The installer runs `lesysbot setup --yes`, which never prompts and reads its
answers from the environment. A complete Telegram install:

```bash
LESYSBOT_SETUP_PROVIDER=telegram \
LESYSBOT_SETUP_TELEGRAM_TOKEN=123456:ABC… \
LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS=123456789 \
  curl -fsSL https://lesysbot.github.io/install.sh | sh
```

| Variable | Default |
|---|---|
| `LESYSBOT_SETUP_LLM` | `ollama` — or `openai`, `vllm`, `custom` |
| `LESYSBOT_SETUP_BASE_URL` | set per backend |
| `LESYSBOT_SETUP_MODEL` | `qwen3.5:4b` |
| `LESYSBOT_SETUP_API_KEY` | `ollama` — required for `openai` |
| `LESYSBOT_SETUP_PROVIDER` | `cli` — or `telegram`, `discord` |
| `LESYSBOT_SETUP_TELEGRAM_TOKEN`, `…_TELEGRAM_ALLOWED_IDS` | required for `telegram` |
| `LESYSBOT_SETUP_DISCORD_TOKEN`, `…_DISCORD_ALLOWED_IDS` | required for `discord` |
| `LESYSBOT_SETUP_AUTOSTART` | `1` (start at boot) |
| `LESYSBOT_SETUP_GRAFANA_USER` | `admin` |
| `LESYSBOT_SETUP_GRAFANA_PASSWORD` | generated |

A missing required value stops the install and names the variable. Running it
again keeps your existing `config.yaml` and refreshes everything else — that's
how you upgrade. Add `--reconfigure` to replace the config.

</details>

## Uninstall

```bash
~/.local/share/lesysbot/install.sh --uninstall
```

This stops the service and the Grafana stack and removes the `lesysbot` command.
Your config, tools and logs in `~/.lesysbot` stay, so a reinstall picks up where
you left off. Add `--purge` to delete them too.

Installed with pipx? Run `pipx uninstall lesysbot`, then `rm -rf ~/.lesysbot`.
