# Settings

All settings live in one file:

```
~/.lesysbot/config.yaml
```

Three ways to change them:

- **`lesysbot setup`** — the wizard, for the model and Telegram/Discord.
- **The [control panel](management-ui.md)** — edit the file in your browser; it
  checks your changes before saving.
- **Any text editor** — then apply with `systemctl --user restart lesysbot`.

`lesysbot` (the status screen) shows which file is in use.

## The settings you'll change

```yaml
llm:
  base_url: "http://localhost:11434/v1"   # where the model runs
  model: "qwen3.5:4b"                     # which model
  api_key: "ollama"                       # any text for local models

messaging:
  provider: cli                           # cli | telegram | discord
  telegram:
    token: "1234:ABC…"
    allowed_user_ids: [123456789]         # who may use the bot

agent:
  max_history: 50                         # messages remembered per person
```

## Use a different backend

Every backend speaks the same protocol, so only these three lines change:

| Backend | `base_url` | `api_key` |
|---|---|---|
| Ollama (default) | `http://localhost:11434/v1` | `ollama` |
| vLLM | `http://localhost:8000/v1` | `vllm` |
| llama.cpp server | `http://localhost:8080/v1` | `llama` |
| OpenAI | `https://api.openai.com/v1` | your API key |

> With a cloud backend, your messages and what the tools report about your
> machine leave your hardware.

## Override for one run

```bash
lesysbot chat --model qwen3.5            # a different model
lesysbot chat --base-url http://localhost:8000/v1
lesysbot chat -v                         # show the log on screen
lesysbot -c /path/to/config.yaml         # use another config file
```

Any setting can also come from the environment: prefix `LESYSBOT_` and join
levels with `__`, for example `LESYSBOT_AGENT__MAX_HISTORY=100`. Command-line
flags win over the environment, which wins over the file.

## Keep secrets out of the file

Any value can read an environment variable:

```yaml
messaging:
  telegram:
    token: ${TELEGRAM_TOKEN}
```

## Grafana login

The dashboard login is not in `config.yaml`. `lesysbot setup` saves it to
`~/.lesysbot/grafana.env`:

```ini
LESYSBOT_GRAFANA_USER=admin
LESYSBOT_GRAFANA_PASSWORD=…
```

LeSysBot finds Grafana on its own. Add `LESYSBOT_GRAFANA_URL=…` only if Grafana
runs on another machine.

## Full reference

```yaml
messaging:
  provider: cli              # cli | telegram | discord
  telegram:
    token: "YOUR_BOT_TOKEN"
    allowed_user_ids: []     # empty = ANYONE can use the bot
  discord:
    token: "YOUR_BOT_TOKEN"
    allowed_user_ids: []     # empty = anyone who shares a server with the bot
  startup_notice:            # message you when the bot starts (Telegram/Discord)
    enabled: true
    notify: []               # chat, user or channel IDs; empty = allowed_user_ids
    speedtest: true          # include an internet speed reading
    speedtest_mb: 5

llm:
  base_url: "http://localhost:11434/v1"
  model: "qwen3.5:4b"
  api_key: "ollama"
  temperature: 0.7
  max_tokens: 4096
  timeout: 120.0             # seconds

mcp:
  tools_dir: "./tools"       # relative paths are relative to this file
  hot_reload: true           # pick up tool changes without a restart
  lock_file: tools.lock.json    # where installed packages came from
  state_file: tool_state.json   # which tools are turned off

agent:
  system_prompt: >
    You are a helpful assistant with access to tools.
    Use tools when they help answer the user's question.
    Be concise and clear.
  max_history: 50            # messages remembered per person
  max_tool_calls: 10         # tool rounds allowed for one message

logging:
  level: INFO                # DEBUG | INFO | WARNING | ERROR | CRITICAL
  file: logs/lesysbot.log    # null to turn off
  trace_file: logs/traces.jsonl   # null to turn off
  when: midnight             # when to start a new file
  backup_count: 7            # old files to keep

management:
  port: 8700                 # control panel port; always localhost-only
```

<details>
<summary><b>How LeSysBot finds the config file</b></summary>

First match wins:

1. `-c /path/to/config.yaml`
2. `config.yaml` in the current directory
3. `~/.lesysbot/config.yaml` (set `LESYSBOT_HOME` to move it)
4. The defaults built into the package

Relative paths inside a config file resolve next to that file, so an install
uses `~/.lesysbot/tools` and a source checkout uses its own `tools/`.

</details>
