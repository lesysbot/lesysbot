---
name: use-lesysbot
description: Day-to-day use of a running LeSysBot — chatting with the LLM, running tools directly with /slash commands, passing arguments, built-in commands (/help, /clear, /history), confirmation prompts, and conversation history. Use when asked "how do I use lesysbot", "run a tool", "call a command", or "why did it ask for confirmation".
---

# Using LeSysBot

Everything here works the same in CLI, Telegram, and Discord.

## Start a session

```bash
lesysbot chat     # force a terminal chat (works even if config says telegram/discord)
lesysbot run                # the service: control panel + bot (what systemd/launchd runs)
lesysbot                    # health + metrics, then exits — NOT a chat, starts nothing
```

Bare `lesysbot` only prints status (backend, tools, service, control panel,
Grafana), so use `--provider cli` to chat. `lesysbot run` is the service, not a
chat: with `provider: cli` it serves the control panel and idles. A CLI session
runs *alongside* the service — separate history; they don't conflict.

The control panel is always on at **http://127.0.0.1:8700** (`management.port`),
served by the service.

## Two ways to interact

| | **Natural language** | **Slash command** (`/...`) |
|---|---|---|
| Example | `what's my disk usage on /?` | `/disk_usage path=/` |
| Who handles it | The **LLM** decides whether to call a tool | The tool runs **directly** — no LLM involved |
| Needs a model running | Yes | **No** |
| Added to history | Yes | No (stateless one-shot) |
| Best for | Questions, multi-step requests | Running a known tool exactly; when the LLM is offline |

Both reach the same tools. **Telegram and Discord also list every tool in the
platform's own `/` menu** (registered at startup), so you can pick a tool instead
of remembering its name — on Discord that gives you a labelled, typed field per
parameter. Newly installed or re-enabled tools join the menu on the next restart;
they are callable as typed text immediately.

## Built-in commands (handled by LeSysBot, not the LLM)

| Command | What it does |
|---|---|
| `/help` (or `/tools`) | List every tool with its parameters — `<angle>` = required, `[square]` = optional |
| `/clear` | Forget the conversation, start fresh |
| `/history` | Show what's currently remembered |
| `exit` / `quit` / `q` | Leave the CLI (CLI only); `Ctrl+C` force-exits |

## Passing arguments to `/` commands

```
/fetch_url https://example.com          # positional — fills params in order
/disk_usage path=/tmp                   # named — key=value, any order
/search query="weekly report" folder=/docs   # quote values with spaces
```

Missing a required argument prints the usage line instead of failing; a
mistyped command name points to `/help`.

## Confirmation prompts

Tools marked destructive ask for approval **only when the LLM initiates the
call** — typing `/tool_name …` yourself runs immediately (you already decided).

| Adapter | Behaviour |
|---|---|
| CLI | Prints tool name, args, prompt; asks `y/n` |
| Telegram | ✅ Yes / ❌ No inline buttons; auto-cancels after 120 s |
| Discord | ✅ Yes / ❌ No message buttons; auto-cancels after 300 s |

## Conversation history

- Kept **per user**, seeded with the system prompt from config; only
  natural-language exchanges are stored (slash commands aren't).
- Trimmed past `agent.max_history` (default 50 messages); the system prompt is
  always kept.

## Quick overrides without editing config

```bash
lesysbot chat --model qwen3.5                                        # different model
lesysbot chat --base-url https://api.openai.com/v1 --model gpt-4o    # different backend
lesysbot --provider telegram                                         # different adapter
LESYSBOT_AGENT__MAX_HISTORY=100 lesysbot chat                        # any setting via env var
```

The flags only take effect on an invocation that actually starts something —
`lesysbot chat`, `lesysbot run`, or an explicit `--provider`. Bare `lesysbot`
prints status and exits whatever else you pass it.

Precedence: **CLI flags → `LESYSBOT_*` env vars → config file**.

## Where activity is logged

- `logs/lesysbot.log` — application log (`~/.lesysbot/logs/` for an installed
  setup). Background log lines (httpx, tool watcher) go here, not the chat;
  `-v` shows them on screen with DEBUG detail.
- `logs/traces.jsonl` — one JSON line per request: which tools ran, arguments,
  timings.

## Related

- Symptom → fix table: [troubleshoot-lesysbot](../troubleshoot-lesysbot/SKILL.md).
- Enable/disable/remove/install tools: [manage-tools](../manage-tools/SKILL.md).
- All settings: [configure-lesysbot](../configure-lesysbot/SKILL.md).
