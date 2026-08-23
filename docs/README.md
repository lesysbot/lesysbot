# LeSysBot documentation

Every page here answers one question and starts with the short version. If a
page has technical detail, it's tucked into a **"Under the hood"** section at
the end — open it only if you want it.

**New here?** [Getting started](getting-started.md) takes you from nothing to a
working bot in about five minutes.

---

## Start here

| Guide | What it's for |
|---|---|
| [Getting started](getting-started.md) | Install it, chat with it, write your first tool |
| [Choosing a model](models.md) | Which local model to run on the hardware you have |

## Everyday use

| Guide | What it's for |
|---|---|
| [Everyday use](usage.md) | Chatting, running tools directly, history, confirmations |
| [Telegram & Discord](adapters.md) | Reach the bot from your phone or your workspace |
| [Control panel](management-ui.md) | Edit settings and toggle tools from a local web page — always on |
| [Settings](configuration.md) | Every option, and the three ways to set it |
| [Troubleshooting](troubleshooting.md) | When something doesn't work |

## Give it new abilities

| Guide | What it's for |
|---|---|
| [Install tools](installing-tools.md) | Add tools from GitHub with one command |
| [Your dashboard](dashboards.md) | The one dashboard: install, update, modify, reset |
| [Write a tool](writing-tools.md) | Turn a Python function or a shell command into an ability |
| [Write a dashboard](writing-dashboards.md) | Build a page of graphs and publish it for other people |
| [Share your tools](sharing-tools.md) | Publish yours so other people can install them |
| [Write tools with Claude Code](claude-code.md) | Let an AI assistant scaffold them for you |

## Keep it running

| Guide | What it's for |
|---|---|
| [Run as a service](service.md) | Background operation, auto-start on boot, logs |
| [The dashboard stack](../dashboard/README.md) | Prometheus + Grafana: ports, exporters, running it |
| [Build a Windows .exe](building-windows-exe.md) | Ship a standalone executable to people without Python |

## Under the hood

| Guide | What it's for |
|---|---|
| [How it works](architecture.md) | The life of a message, layer by layer — for contributors |
| [Contributing](../CONTRIBUTING.md) | Dev setup, tests, and the checklist for each kind of change |
| [Brand assets](../assets/brand/README.md) | The logo, the palette, and how to regenerate them |
| [CLAUDE.md](../CLAUDE.md) | Fine-grained internals, written for AI coding assistants |

---

## Shortcuts

- **"I just want to try it."** → [Getting started](getting-started.md), then press
  Enter through the wizard.
- **"I want it to do X."** → [Write a tool](writing-tools.md), or check whether
  someone already did: [Install tools](installing-tools.md).
- **"I want more graphs."** → [Your dashboard](dashboards.md), or
  build your own: [Write a dashboard](writing-dashboards.md).
- **"I want to message it from my phone."** → [Telegram setup](adapters.md#2-telegram).
- **"Something's wrong."** → [Troubleshooting](troubleshooting.md).
- **"I want to change how it behaves."** → [Settings](configuration.md).
- **"I want to fix or add something in the code."** → [How it works](architecture.md),
  then [CONTRIBUTING.md](../CONTRIBUTING.md).
- **"An AI agent is doing this for me."** → [skills/](../skills/README.md) —
  self-contained instructions per job, no docs or source needed.
