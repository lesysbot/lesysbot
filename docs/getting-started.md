# Getting started

## 1. Install

```bash
curl -fsSL https://lesysbot.github.io/install.sh | sh
```

This installs LeSysBot, [Ollama](https://ollama.com) and a small local model,
then starts LeSysBot in the background. You won't be asked any questions.

Not root? The installer skips Ollama and prints the two commands to run
yourself.

## 2. Chat

```bash
lesysbot chat
```

```text
You: how much space is left on /?
Bot: 45 GB free out of 200 GB — 78% used.
```

Ask in plain words. `/help` lists every tool; `exit` leaves.

## 3. Open the control panel

Go to **<http://127.0.0.1:8700>** to change settings and turn tools on or off.

## What next?

- [Chat from your phone](adapters.md) with Telegram or Discord
- [See graphs of your machine](dashboards.md) in Grafana
- [Learn the basics](usage.md): running tools yourself, confirmations
- [Install options and uninstalling](install.md)
- [Fix a problem](troubleshooting.md)
