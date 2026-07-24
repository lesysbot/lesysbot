---
name: use-lesysbot
description: Day-to-day use of a running LeSysBot — chatting with the LLM, running tools directly with /slash commands, passing arguments, built-in commands (/help, /clear, /history), confirmation prompts, and conversation history. Use when asked "how do I use lesysbot", "run a tool", "call a command", or "why did it ask for confirmation".
---

# Using LeSysBot

Everything here works the same in CLI, Telegram, and Slack.

## Start a session

```bash
lesysbot --provider cli     # force a terminal chat (works even if config says telegram/slack)
lesysbot run                # run the bot using the config's provider
lesysbot                    # in a terminal: opens the management UI (status + web panel), NOT a chat
```

Bare `lesysbot` in a terminal now opens the management UI, so use `--provider
cli` (or `run`) to actually chat. A CLI session can run *alongside* a
Telegram/Slack background service — separate history; they don't conflict.

## Two ways to interact

| | **Natural language** | **Slash command** (`/...`) |
|---|---|---|
| Example | `what's my disk usage on /?` | `/disk_usage path=/` |
| Who handles it | The **LLM** decides whether to call a tool | The tool runs **directly** — no LLM involved |
| Needs a model running | Yes | **No** |
| Added to history | Yes | No (stateless one-shot) |
| Best for | Questions, multi-step requests | Running a known tool exactly; when the LLM is offline |

Both reach the same tools. In **Slack**, a leading `/` collides with Slack's own
slash commands — type `/ ` *with a space* first: `/ disk_usage path=/tmp`.

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
| Slack | Auto-approves by default |

## Conversation history

- Kept **per user**, seeded with the system prompt from config; only
  natural-language exchanges are stored (slash commands aren't).
- Trimmed past `agent.max_history` (default 50 messages); the system prompt is
  always kept.

## Quick overrides without editing config

```bash
lesysbot --model qwen3.5                                        # different model
lesysbot --base-url https://api.openai.com/v1 --model gpt-4o    # different backend
lesysbot --provider telegram                                    # different adapter
LESYSBOT_AGENT__MAX_HISTORY=100 lesysbot                          # any setting via env var
```

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
