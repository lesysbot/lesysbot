# Everyday use

Everything here works the same in the terminal, Telegram and Discord.

## Start a chat

```bash
lesysbot chat
```

`lesysbot` on its own doesn't chat — it prints a health check and exits.

## Two ways to ask

| | **Ask in words** | **Run a tool yourself** |
|---|---|---|
| Example | `how much space is left on /?` | `/disk_usage /` |
| Who picks the tool | the model | you |
| Needs the model running | yes | no |
| Remembered in the conversation | yes | no |

Both reach the same tools. Ask in words for questions and follow-ups — it
remembers the conversation. Use `/` when you know the tool, or when the model is
down.

## Running a tool yourself

```
/disk_usage /                        arguments in order
/disk_usage path=/tmp                or by name
/fetch_url url="https://example.com" quote anything with spaces
```

Leave out an argument and it tells you what it needs. In `/help`, `<angle>`
arguments are required and `[square]` ones are optional.

In **Telegram and Discord**, type `/` to pick a tool from a menu. Discord also
gives you a field for each argument. A newly installed tool works straight away
when typed, but joins the menu after the next restart.

## Built-in commands

| Command | What it does |
|---|---|
| `/help` | List every tool and its arguments |
| `/clear` | Forget the conversation |
| `/history` | Show what it remembers |
| `exit` | Leave a terminal chat (or press `Ctrl+C`) |

## Confirmations

Tools that reboot or power off the machine ask first when the **model** decides
to use them:

```
⚠ This will power off the machine in 1 minute — are you sure?
Proceed? [y/n] (n):
```

In Telegram and Discord you get **✅ Yes / ❌ No** buttons. Typing `/power_off`
yourself skips the question — you already decided.

## Turning tools on and off

```bash
lesysbot list                 # every tool and its status
lesysbot disable traceroute   # hide it from the model; /traceroute refuses too
lesysbot enable traceroute    # back on
lesysbot remove traceroute    # delete it and its package (asks first)
```

Changes reach a running bot within a second. The
[control panel](management-ui.md) has the same switches.

## Try a different model

For one session, without editing anything:

```bash
lesysbot chat --model qwen3.5
```

To change it for good, use `lesysbot setup` or [Settings](configuration.md).

## Logs

```
~/.lesysbot/logs/lesysbot.log    what the program did
~/.lesysbot/logs/traces.jsonl    one line per message: tools used, timings
```

Tokens and API keys are removed before anything is written. Run
`lesysbot chat -v` to see the log on screen.
