# Settings

Everything LeSysBot does is controlled by one YAML file. You can also override
any of it from the environment or the command line, without editing anything.

---

## Where your settings live

After a normal install, here:

```
~/.lesysbot/config.yaml
```

That folder is your bot's home. Your tools sit in `~/.lesysbot/tools/` and logs
in `~/.lesysbot/logs/`, and the background service runs from there — so editing
that one file and restarting is the whole workflow:

```bash
$EDITOR ~/.lesysbot/config.yaml
systemctl --user restart lesysbot
```

Not sure which file is active? `lesysbot` prints it on the status screen.

You can also edit it in a browser, with validation, from the
[control panel](management-ui.md).

<details>
<summary><b>How LeSysBot finds the file</b></summary>

In order, first hit wins:

1. The path you passed with `-c / --config`
2. `config.yaml` in the current directory
3. `~/.lesysbot/config.yaml` — what the installer writes
4. `config/default.yaml` shipped inside the package
5. Built-in defaults, if there's no file at all

Entries 1–3 are files *you* edit, so relative paths inside them (`./tools`,
`logs/lesysbot.log`) resolve **next to that file**. That single rule is what
makes an installed setup use `~/.lesysbot/tools` and a source checkout use the
repo's own `tools/` — all from the same config text.

Entry 4 ships with the package rather than belonging to you, so it supplies
values but doesn't become the anchor.

Set `LESYSBOT_HOME` to use somewhere other than `~/.lesysbot`.

</details>

---

## The settings you'll actually change

**Which model, and where it runs**

```yaml
llm:
  base_url: "http://localhost:11434/v1"   # Ollama, running locally
  model: "qwen3.5:4b"                     # a model you've pulled
  api_key: "ollama"                       # any non-empty string for local backends
```

**How you reach it**

```yaml
messaging:
  provider: cli            # cli | telegram | discord
  telegram:
    token: "1234:ABC…"
    allowed_user_ids: [123456789]   # who may use it — see the warning below
```

**How much it remembers**

```yaml
agent:
  max_history: 50          # messages kept per person
  system_prompt: >
    You are a helpful assistant with access to tools.
```

**How chatty the logs are**

```yaml
logging:
  level: INFO              # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

> ⚠️ **`allowed_user_ids: []` means anyone who finds your Telegram bot can use
> it** — including tools that power the machine off. The install wizard won't
> write an empty list for you; if you're editing by hand, put your ID in.

---

## Switching model backend

Every backend speaks the same OpenAI-compatible protocol, so only three lines
change:

| Backend | `base_url` | `api_key` |
|---|---|---|
| **Ollama** (default) | `http://localhost:11434/v1` | `ollama` |
| **vLLM** | `http://localhost:8000/v1` | `vllm` |
| **LlamaCpp server** | `http://localhost:8080/v1` | `llama` |
| **OpenAI** | `https://api.openai.com/v1` | your real API key |

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "sk-..."
```

> Pointing at a cloud backend means your messages — and whatever the tools
> report about your machine — travel to someone else's servers. That's a fine
> trade to make deliberately; it's just worth making deliberately.

---

## Overriding without editing the file

**On the command line**, for one run:

```bash
lesysbot --provider cli --model qwen3.5
lesysbot --base-url http://localhost:8000/v1
lesysbot -c /etc/lesysbot/config.yaml
lesysbot run -v                          # verbose
```

| Flag | Overrides |
|---|---|
| `-c / --config` | which config file to load |
| `-v / --verbose` | `logging.level` → DEBUG |
| `--provider` | `messaging.provider` |
| `--model` | `llm.model` |
| `--base-url` | `llm.base_url` |

**From the environment**, for anything without a flag. Prefix `LESYSBOT_`, and
use `__` between levels:

```bash
LESYSBOT_LLM__MODEL=qwen3.5
LESYSBOT_MESSAGING__PROVIDER=telegram
LESYSBOT_AGENT__MAX_HISTORY=100
LESYSBOT_LOGGING__LEVEL=DEBUG
```

**Keeping secrets out of the file** — any string value may reference an
environment variable:

```yaml
messaging:
  telegram:
    token: ${TELEGRAM_TOKEN}
```

If the variable isn't set, the literal `${…}` text is kept and a warning logged,
so you'll never silently run with a placeholder.

Precedence, strongest first: **command line → environment → config file**.

### The Grafana connection (`grafana.env`)

The [monitoring dashboard](../monitoring/README.md) isn't part of `config.yaml` —
its connection lives in **`~/.lesysbot/grafana.env`**, which `lesysbot setup`
writes (asking for the username and password) and the bot loads into its
environment at startup:

```ini
LESYSBOT_GRAFANA_URL=http://localhost:3000
LESYSBOT_GRAFANA_USER=admin
LESYSBOT_GRAFANA_PASSWORD=admin
```

Edit this to change the login the `share_dashboard` tool and the status screen
use, or to point at Grafana on another host/port. A real environment variable of
the same name always wins over the file, so you can override per-run without
editing it. (`LESYSBOT_GRAFANA_TOKEN` for a Grafana API token, and
`LESYSBOT_GRAFANA_URL` alone, are also honoured.)

You rarely need to touch the **URL**: LeSysBot looks for Grafana on the port set in
`~/.lesysbot/monitoring/.env` (`GRAFANA_PORT`) and then the usual 3000/3001,
checking each really answers as Grafana — so moving the stack to 3001 because
something else owns 3000 needs no edit here. `LESYSBOT_GRAFANA_URL` is used when
Grafana answers there; if it doesn't (a stale entry, or the stack moved), LeSysBot
probes those ports rather than reporting whatever else is on the saved one.

---

## Which commands do what

```bash
lesysbot                  # health + metrics, then exit (starts nothing)
lesysbot run              # the service: control panel + bot
lesysbot --provider cli   # chat in this terminal
lesysbot manage           # open the control panel, or serve it if the service is down
lesysbot setup            # re-run the setup wizard
lesysbot tools …          # install/list/enable/disable/remove tools
```

---

## Full reference

```yaml
# ── How you reach the bot ─────────────────────────────────────────────────────
messaging:
  provider: cli              # cli | telegram | discord

  telegram:
    token: "YOUR_BOT_TOKEN"
    allowed_user_ids: []     # empty = anyone. e.g. [123456789, 987654321]

  discord:
    token: "YOUR_BOT_TOKEN"
    allowed_user_ids: []     # empty = anyone sharing a server with the bot

  startup_notice:            # ping you when the bot comes up (Telegram/Discord only)
    enabled: true            # for a background service, that means "after boot"
    notify: []               # Telegram chat ids / Discord user or channel ids
                             # falls back to that provider's allowed_user_ids
    speedtest: true          # include an internet speed reading
    speedtest_mb: 5          # how much to download for it

# ── The model ─────────────────────────────────────────────────────────────────
llm:
  base_url: "http://localhost:11434/v1"
  model: "qwen3.5:4b"
  api_key: "ollama"          # any string for local backends; a real key for OpenAI
  temperature: 0.7
  max_tokens: 4096
  timeout: 120.0             # seconds before a request is abandoned

# ── Tools ─────────────────────────────────────────────────────────────────────
mcp:
  tools_dir: "./tools"       # relative → next to this config file
  hot_reload: true           # pick up tool edits without a restart
  lock_file: tools.lock.json    # where installed packages came from
  state_file: tool_state.json   # which tools are disabled

# ── Behaviour ─────────────────────────────────────────────────────────────────
agent:
  system_prompt: >
    You are a helpful assistant with access to tools.
    Use tools when they help answer the user's question.
    Be concise and clear.
  max_history: 50            # messages kept per person
  max_tool_calls: 10         # most model→tool→model rounds for one message

# ── Logs ──────────────────────────────────────────────────────────────────────
logging:
  level: INFO                # DEBUG | INFO | WARNING | ERROR | CRITICAL
  file: logs/lesysbot.log    # null to disable
  trace_file: logs/traces.jsonl   # null to disable
  when: midnight             # rotation: midnight | H | D | W0..W6 | S
  backup_count: 7            # how many rotated files to keep

# ── Control panel (served by the service, always on) ──────────────────────────
webui:
  port: 8700                 # always bound to 127.0.0.1; only the port is settable
```

---

## Under the hood

<details>
<summary><b>How the log files behave</b></summary>

Both `file` and `trace_file` rotate on a timer, so neither grows without bound:
at each `when` rollover the current file is renamed with a date suffix
(`lesysbot.log.2026-06-21`) and only the newest `backup_count` survive.

`level` sets how much detail is written. In an interactive terminal chat the
*console* is clamped to warnings and worse regardless, so log lines can't
interrupt you — the *file* still gets everything at `level`. For a
Telegram/Discord service, `level` governs both. `-v` forces DEBUG.

</details>

<details>
<summary><b>Why your tokens never appear in a log</b></summary>

The Telegram API carries your bot token in the URL *path*, and the HTTP library
underneath logs every request it makes. Left alone, a running service would
write its own token to disk thousands of times a day — into exactly the file
people paste into bug reports.

So log records are scrubbed on the way out, at the logging layer, which catches
every producer including libraries we don't control. Two things are matched: the
*shapes* credentials come in (Telegram's `digits:letters`, Discord's
`base64.six.hmac` three-part token, OpenAI's `sk-`), which work with no
configuration at all, and the
*exact* values from your active config, registered at startup. Tracebacks are
covered too, since the request URL often rides along on the exception.

Values shorter than 12 characters are deliberately left alone — the default
`api_key: ollama` is not a secret, and rewriting every occurrence of a
six-letter dictionary word would mangle unrelated log text.

Source: `lesysbot/core/redact.py`.

</details>

<details>
<summary><b>Traces file format</b></summary>

With `logging.trace_file` set, each message you send produces one JSON line:

```json
{
  "ts": "2026-06-21T12:00:00+00:00",
  "trace_id": "ab29aaf98c9b",
  "user_id": "cli-user",
  "input": "what is my disk usage?",
  "turns": [
    {
      "index": 1,
      "model": "qwen3.5:4b",
      "messages": 3,
      "response_type": "tool_calls",
      "ms": 840.0,
      "tools": [
        {"name": "disk_usage", "args": {"path": "/"}, "result": "...", "ms": 42.5}
      ]
    },
    {
      "index": 2,
      "model": "qwen3.5:4b",
      "messages": 5,
      "response_type": "text",
      "ms": 620.0,
      "tools": []
    }
  ],
  "reply": "Your disk at / is 80% full with 40 GB free.",
  "total_ms": 1460.0
}
```

Useful for measuring latency, debugging tool calls, and auditing what the model
decided to do. Direct `/` commands aren't traced — they never reach the model.
`result` and `reply` are truncated at 2000 characters.

</details>
