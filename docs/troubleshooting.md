# Troubleshooting

Start with these three commands:

```bash
lesysbot             # status: is the model reachable? is the service running?
lesysbot doctor      # what's missing on this machine, and how to fix it
lesysbot chat -v     # chat with the log on screen
```

## Chatting

### "LLM unavailable"

The model isn't reachable.

```bash
curl localhost:11434      # should print "Ollama is running"
ollama list               # is your model downloaded?
```

- Ollama not running → `sudo systemctl start ollama`, or `ollama serve`.
- Model missing → `ollama pull <name>`, or change `llm.model` in your config.
- Remote backend → check that `llm.base_url` ends in `/v1` and the key is right.

`/` commands keep working while the model is down.

### It picks the wrong tool, or none

Use a bigger model — see [Choosing a model](models.md). Being specific helps
too ("check the CPU temperature" beats "how is it"). Or run the tool yourself
with `/tool_name`.

### The first reply is slow

The model is loading into memory. Later replies are faster.

### My second message got no answer

It's waiting for the first to finish — you'll get both, in order. If a
confirmation is waiting for your answer, answer it first. `/` commands never
wait.

### It forgot what we were talking about

It remembers the last 50 messages (`agent.max_history`), and `/clear` wipes
them.

## Tools

### A tool is missing from `/help`

- Check it's in `~/.lesysbot/tools/` — `lesysbot` shows the folder in use.
- Files and folders starting with `_` are skipped.
- An error in the file stops it loading. Check the log:
  `tail -n 50 ~/.lesysbot/logs/lesysbot.log`

### "unavailable on this machine"

```
'traceroute' is unavailable on this machine — requires 'traceroute' on PATH (not found).
```

Install the missing program (here, your distribution's `traceroute` package).
It works straight away, no restart.

### "is disabled"

Turn it back on: `lesysbot enable traceroute`.

### `lesysbot install` fails

See [Install tools](installing-tools.md#if-it-fails).

## Installing

### `lesysbot: command not found`

Open a new terminal. If that doesn't help:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## The service

### It starts, then stops

See why:

```bash
journalctl --user -u lesysbot -n 50
```

Usual causes: a wrong Telegram/Discord token, or a missing dependency.

### "Another LeSysBot instance … is already running"

The service is already running — only one copy can run at a time. Use
`lesysbot chat` to chat alongside it, or stop it first with
`systemctl --user stop lesysbot`.

### Config changes do nothing

Restart the service: `systemctl --user restart lesysbot`. Turning tools on and
off is the only change that applies without a restart.

### The control panel says offline

The service isn't running: `systemctl --user start lesysbot`. Or run the panel
in your terminal with `lesysbot manage`.

### "Control panel not started — port … already in use"

Something else is using port 8700. Set another `management.port` in your config
and restart the service. The bot keeps running either way.

### I can't open the control panel from another computer

That's on purpose — it only listens on `127.0.0.1`. Use an SSH tunnel:
`ssh -L 8700:127.0.0.1:8700 you@server`, then open `http://127.0.0.1:8700`
locally.

## Telegram and Discord

| Problem | Fix |
|---|---|
| Replies `Unauthorized.` | Your user ID isn't in `allowed_user_ids`. Check it again — see [Telegram & Discord](adapters.md). |
| No reply at all | Wrong token, or the service is stopped. Check `lesysbot` and `journalctl --user -u lesysbot -n 50`. |
| Discord bot is online but ignores you | Turn on **Message Content Intent**: developer portal → **Bot** → **Privileged Gateway Intents**. Then restart the service. |
| `Discord rejected the bot token` | **Bot → Reset Token**, then run `lesysbot setup` again. |
| No answer in a Discord channel | @-mention the bot. Direct messages don't need it. |
| Can't DM the Discord bot | Invite it to a server you're in first. |
| A tool is missing from the `/` menu | Restart the service after installing a tool. On Discord, the invite also needs the **`applications.commands`** scope. |
| Telegram replies show `*asterisks*` | Harmless — the reply was sent as plain text. |
| `The 'discord' provider needs a dependency` | Reinstall with the installer, or `pip install "lesysbot[discord]"`. |

## Dashboards

| Problem | Fix |
|---|---|
| Grafana doesn't open | Start it: `lesysbot dashboard start`. Needs Docker — see [Dashboards](dashboards.md). |
| Every panel is empty | Wait a minute for data. Still empty? Prometheus isn't running — check `http://localhost:9090/targets`. |
| No temperature row | The machine exposes no sensors (normal in a VM). On real hardware, `lesysbot dashboard start` prints the `modprobe` to run. |
| No GPU row | NVIDIA needs `nvidia-smi` installed and working. |
| "share me the dashboard" fails | Grafana must be running: `lesysbot dashboard start`. |
| Fixes from an update don't show | Run `lesysbot setup` again, then `lesysbot dashboard start`. |

## Logs

```bash
tail -f ~/.lesysbot/logs/lesysbot.log     # what the program did
tail -f ~/.lesysbot/logs/traces.jsonl     # what the model decided, per message
```

Tokens and keys are removed from both, so they're safe to share in a bug report.
`traces.jsonl` does include what your tools returned — read it before sharing.

## Start over

```bash
mv ~/.lesysbot/config.yaml ~/.lesysbot/config.yaml.bak && lesysbot setup  # reset settings
rm ~/.lesysbot/tool_state.json                                             # turn every tool back on
```

To remove everything, see [Uninstall](getting-started.md#uninstall).

---

Still stuck? [Open an issue](https://github.com/lesysbot/lesysbot/issues) with
the output of `lesysbot` and the last lines of `~/.lesysbot/logs/lesysbot.log`.
