# Everyday use

How to actually use LeSysBot once it's installed.

Everything here works the same whether you're in a terminal, in Telegram, or in
Slack. The examples use the terminal because it needs no setup.

---

## Starting a chat

```bash
lesysbot --provider cli
```

```
LeSysBot — local AI assistant with tools
Type a message to chat, or use /commands directly. Type 'exit' to quit.

You:
```

> **`lesysbot` on its own does something different** — it prints health and
> metrics (backend, tools, service, [control panel](management-ui.md), Grafana)
> and exits. To chat, use `lesysbot --provider cli`.

Already running as a Telegram or Slack service? A terminal chat runs happily
alongside it, with its own separate conversation.

---

## Two ways to ask for something

This is the one thing worth understanding well.

| | **Ask in words** | **Run it directly** (`/…`) |
|---|---|---|
| Looks like | `what's my disk usage on /?` | `/disk_usage path=/` |
| Who decides | the model picks a tool | nothing to decide — it just runs |
| Needs a model running | yes | **no** |
| Speed | as fast as your model | instant |
| Good for | questions, vague requests, several steps at once | a tool you already know, quick checks, when the model is down |

Both reach exactly the same tools. They're two doors into the same room.

---

## Asking in words

Type a sentence and press Enter.

```
You: what operating system is this machine running?
Bot: Linux 6.8.0.

You: and how much free space is on / ?
Bot: The root filesystem has 143 GB free out of 980 GB — 80% used.
```

Notice the second question didn't repeat any context. LeSysBot remembers the
conversation, so follow-ups work.

While it thinks you'll see a **`Thinking…`** spinner, switching to
**`Running <tool>…`** when it uses one. The reply streams in and renders as
proper Markdown — headings, **bold**, lists and `code` show as formatting rather
than raw symbols. If your model exposes its reasoning, that appears dimmed above
the answer.

Background log lines stay out of your way (they go to a file). Add `-v` if you
want to watch them.

---

## Running a tool directly

Anything starting with `/` runs a tool immediately, without the model.

**Pass arguments in order:**

```
You: /disk_usage /
You: /fetch_url https://example.com
```

**Or by name, in any order** — clearer when there are several:

```
You: /disk_usage path=/tmp
You: /search query="weekly report" folder=/docs
```

Quote anything containing spaces.

**Forget an argument** and it shows you what it wanted:

```
You: /disk_usage
Missing required parameter(s): path

Usage: /disk_usage <path>
  Check how much free disk space is available at a given path
```

**Mistype a name** and it points you at `/help`.

In `/help` output, `<angle brackets>` mean required and `[square brackets]` mean
optional.

> Direct calls don't go into your conversation history — they're one-shot and
> stateless, which is exactly why they still work when no model is running.

---

## Built-in commands

Handled by LeSysBot itself, in every chat platform:

| Command | What it does |
|---|---|
| `/help` *(or `/tools`)* | List every tool, with its parameters |
| `/clear` | Forget the conversation and start fresh |
| `/history` | Show what it currently remembers |
| `exit` / `quit` / `q` | Leave a terminal session |
| `Ctrl+C` | Force-quit a terminal session |

---

## When it asks permission

Some tools require approval before they run — anything that deletes, reboots, or
powers off. When the *model* decides to use one, you get asked first:

```
⚠ Confirmation required
  Tool : power_off
  This will power off the machine in 1 minute — are you sure?
Proceed? [y/n] (n):
```

`y` runs it; anything else cancels. In Telegram this arrives as ✅/❌ buttons
(they expire after two minutes). Slack auto-approves unless you customise it.

> **Typing `/power_off` yourself skips the prompt.** You already decided. The
> confirmation exists to catch the *model* acting on your behalf, not to
> second-guess you.

---

## Conversation memory

- Each user gets their own history, seeded with the system prompt from your
  config.
- Only word-based messages and replies are kept — `/` commands aren't.
- Old messages are dropped once you pass `agent.max_history` (default 50). The
  system prompt always stays.
- `/history` shows what's remembered; `/clear` wipes it.

Tune the limit in [Settings](configuration.md).

---

## Changing the model for one session

No need to edit anything:

```bash
lesysbot --provider cli --model qwen3.5                        # a different local model
lesysbot --base-url https://api.openai.com/v1 --model gpt-4o   # talk to OpenAI instead
LESYSBOT_AGENT__MAX_HISTORY=100 lesysbot run                   # any setting, via the environment
```

Command-line flags win over environment variables, which win over your config
file. Full list: [Settings](configuration.md).

---

## Turning tools on and off

From any terminal, whether or not the bot is running:

```bash
lesysbot tools list                # everything installed, with its status
lesysbot tools info gpu_temp       # what it takes, where it came from
lesysbot tools disable gpu_temp    # hide it from the model; /gpu_temp refuses too
lesysbot tools enable gpu_temp     # back on
lesysbot tools remove gpu_temp     # delete it (asks first)
lesysbot tools install owner/repo  # add tools from GitHub
```

**Enabling and disabling applies within a second** to a running bot — no restart.
**Removing** deletes the tool's whole folder, including any sibling tools defined
alongside it; those are listed before you confirm.

You can do all of this from the [control panel](management-ui.md) too, if you'd
rather click.

Installing is covered properly in [Install tools](installing-tools.md).

---

## Where things are written

```
~/.lesysbot/logs/lesysbot.log     what the program did
~/.lesysbot/logs/traces.jsonl     one JSON line per message: which tools ran, how long
```

(For a source checkout with its own `config.yaml`, they're next to that instead.)

Both rotate daily. Set either to `null` in your config to switch it off. Tokens
and API keys are stripped before anything is written.

---

## Something not working?

See **[Troubleshooting](troubleshooting.md)** — it covers the model being
unreachable, tools not showing up, service problems, and Telegram/Slack setup
issues.

---

## Where to next

| Want to… | Go to |
|---|---|
| Message it from your phone | [Telegram & Slack](adapters.md) |
| Add your own abilities | [Write a tool](writing-tools.md) |
| Install tools from GitHub | [Install tools](installing-tools.md) |
| Change models, history, logging | [Settings](configuration.md) |
| Keep it running in the background | [Run as a service](service.md) |
| Understand how it works inside | [How it works](architecture.md) |
