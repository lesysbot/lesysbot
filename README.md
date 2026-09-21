<img src="assets/brand/lesysbot-wordmark.svg" alt="LeSysBot" width="380">

**Chat with your Linux machine.** Ask in plain words — from the terminal,
Telegram or Discord — and it answers using tools that read and control the
machine.

```
You: how hot is it running?
Bot: CPU 41–47 °C across 16 cores, GPU 38 °C. Nothing to worry about.

You: how much space is left on /?
Bot: 45 GB free out of 200 GB — 78% used.

You: reboot it
Bot: ⚠ This will reboot the machine in 1 minute. Proceed? [y/n]
```

The model runs **locally** with [Ollama](https://ollama.com), so your messages
stay on your machine. No account, no cloud.

**📖 Docs: [lesysbot.github.io](https://lesysbot.github.io)**

## Get started

**1. Install** — one command, no questions, no password:

```bash
curl -fsSL https://lesysbot.github.io/install.sh | sh
```

**2. Chat:**

```bash
lesysbot chat
```

**3. Open the control panel** at **<http://127.0.0.1:8700>** to change settings
and manage tools.

Full walkthrough: **[Getting started](docs/getting-started.md)**.

## What you get

- **15 tools, ready to use** — system info, disk usage, temperatures, ping,
  speed test, reboot and power off, and more.
- **Chat from anywhere** — terminal, [Telegram or Discord](docs/adapters.md).
- **Asks before anything drastic** — reboot and power off wait for your yes.
- **[Graphs over time](docs/dashboards.md)** — CPU, memory, disk, network and
  GPU in Grafana, which the bot can share as a link.
- **Easy to extend** — a tool is one small Python file:

```python
# ~/.lesysbot/tools/hello/tool.py
from lesysbot.mcp import tool

@tool(description="Say hello to someone")
async def hello(name: str) -> str:
    return f"Hello, {name}!"
```

Save it and it works — as `/hello Ada`, or when you say "say hi to Ada".

## What next?

| I want to… | Read |
|---|---|
| Learn the basics | [Everyday use](docs/usage.md) |
| Message it from my phone | [Telegram & Discord](docs/adapters.md) |
| Add tools other people wrote | [Install tools](docs/installing-tools.md) |
| Write my own tool | [Write a tool](docs/writing-tools.md) |
| Fix something | [Troubleshooting](docs/troubleshooting.md) |

All guides: **[docs/](docs/README.md)**. Setting it up with an AI agent? Point
it at **[skills/](skills/README.md)**.

## Contributing

A new tool doesn't need a pull request — put it in your own repo and people
install it with `lesysbot install you/repo`. For changes to LeSysBot itself, see
[CONTRIBUTING.md](CONTRIBUTING.md) and [How it works](docs/architecture.md).

Questions or ideas? [LinkedIn](https://www.linkedin.com/in/syandev/) ·
[syan.vn@gmail.com](mailto:syan.vn@gmail.com)

## License

MIT
