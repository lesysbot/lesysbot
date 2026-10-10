# Install & uninstall

Most people only need the one command in [Getting started](getting-started.md).
This page covers everything else.

## What the installer does

It installs LeSysBot, [Ollama](https://ollama.com) and the `qwen3.5:4b` model,
sets up the [Grafana dashboard](dashboards.md), and starts the
[background service](service.md). It never prompts and never asks for a
password. Your settings go in `~/.lesysbot/config.yaml`.

Ollama's own installer needs root, so if you aren't root the installer skips it
and prints these for you to run:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:4b
```

## Options

Add flags after `sh -s --`:

```bash
curl -fsSL https://lesysbot.github.io/install.sh | sh -s -- --skip-dashboard
```

| Flag | Effect |
|---|---|
| `--model NAME` | Pull a different model. See [Choosing a model](models.md). |
| `--skip-ollama` | Don't install Ollama (you already have it, or you use OpenAI). |
| `--skip-dashboard` | Don't set up Grafana. |
| `--no-modify-path` | Don't touch your shell startup files. |
| `--help` | List every flag. |

## Other ways to install

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

**From a git checkout:**

```bash
git clone https://github.com/lesysbot/lesysbot
cd lesysbot && sh scripts/install.sh
```

## Change your settings

```bash
lesysbot setup
```

Answer **y** to replace your current settings. The wizard then asks which model
to use, whether to connect Telegram or Discord, and whether to start at boot.
Press Enter to take a default. It restarts the
service when it's done. You can also change most settings in the
[control panel](management-ui.md).

## Upgrade

Run the install command again. It keeps your `config.yaml` and refreshes
everything else.

## Uninstall

```bash
~/.local/share/lesysbot/install.sh --uninstall
```

This stops the service and the Grafana stack and removes the `lesysbot` command.
Your config, tools and logs in `~/.lesysbot` stay, so a reinstall picks up where
you left off. Use `--purge` instead to delete them too.

Installed with pipx? Run `pipx uninstall lesysbot`, then `rm -rf ~/.lesysbot`.

## Unattended install

For scripts and CI. The installer runs `lesysbot setup --yes`, which reads its
answers from environment variables instead of prompting. A complete Telegram
install:

```bash
LESYSBOT_SETUP_PROVIDER=telegram \
LESYSBOT_SETUP_TELEGRAM_TOKEN=123456:ABC… \
LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS=123456789 \
  curl -fsSL https://lesysbot.github.io/install.sh | sh
```

| Variable | Default |
|---|---|
| `LESYSBOT_SETUP_LLM` | `ollama`, or `openai`, `vllm`, `custom` |
| `LESYSBOT_SETUP_BASE_URL` | set per backend |
| `LESYSBOT_SETUP_MODEL` | `qwen3.5:4b` |
| `LESYSBOT_SETUP_API_KEY` | `ollama`; required for `openai` |
| `LESYSBOT_SETUP_PROVIDER` | `cli`, or `telegram`, `discord` |
| `LESYSBOT_SETUP_TELEGRAM_TOKEN`, `…_TELEGRAM_ALLOWED_IDS` | required for `telegram` |
| `LESYSBOT_SETUP_DISCORD_TOKEN`, `…_DISCORD_ALLOWED_IDS` | required for `discord` |
| `LESYSBOT_SETUP_AUTOSTART` | `1` (start at boot) |
| `LESYSBOT_SETUP_GRAFANA_USER` | `admin` |
| `LESYSBOT_SETUP_GRAFANA_PASSWORD` | generated |

A missing required value stops the install and names the variable. To replace
an existing config this way, run `lesysbot setup --yes --reconfigure`.
