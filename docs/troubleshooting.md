# Troubleshooting

Start here when something doesn't work. Each entry is a symptom you'd actually
see, with the fix underneath.

**Two things to try before anything else:**

```bash
lesysbot            # status screen: is the model reachable? is the service up?
                    # where is the config? how many tools are enabled?
```

```bash
lesysbot --provider cli -v      # same chat, but with the log on screen
```

The status screen answers most "why isn't it working" questions in one look.

---

## Talking to it

### "LLM unavailable: …"

The model backend isn't reachable. Check it directly:

```bash
curl http://localhost:11434/         # Ollama → "Ollama is running"
ollama list                          # is your configured model here?
```

- Ollama not running → start it (`ollama serve`, or launch the app on
  macOS/Windows).
- Model not in the list → `ollama pull <name>`, or fix `llm.model` in
  `~/.lesysbot/config.yaml`.
- Using a remote backend → check `llm.base_url` ends in `/v1` and the key is
  right.

Slash commands (`/disk_usage path=/`) keep working while the model is down —
they never touch it.

### It picked the wrong tool, or didn't use one at all

Smaller models call tools unreliably. In order of effectiveness:

1. Use a stronger model — see [Choosing a model](models.md). Tool calling is the
   single thing model size helps most with here.
2. Be more specific: "check the temperature of the CPU" beats "how is it".
3. Call the tool yourself with `/tool_name`, which never involves the model.

### The first reply takes forever

The model is loading into memory. Later replies are much faster. `ollama ps`
shows what's currently loaded; a model unloads after a few idle minutes.

### I sent a second message and nothing happened

Each conversation advances one turn at a time, so a message sent while the bot
is still working waits for the current answer before it starts. Nothing is
dropped — you'll get both replies, in order. This is most noticeable when a
confirmation prompt is sitting unanswered: that turn stays open until you tap a
button (or it times out after five minutes), and anything you type meanwhile
queues behind it. Answer the prompt, or run the tool yourself with `/tool_name`
— slash commands skip the queue entirely and work even mid-turn.

### It forgot what we were talking about

History is trimmed past `agent.max_history` (default 50 messages), and `/clear`
wipes it. Raise the limit in [Settings](configuration.md) if your model has room
for it.

---

## Tools

### A tool isn't in `/help`

- Is the file in the right folder? For an installed setup that's
  `~/.lesysbot/tools/`, not the repo you cloned. `lesysbot` (the status screen)
  prints the path it's actually loading from.
- Files and folders starting with `_` are skipped on purpose.
- An import error keeps the file from loading. Check the log:
  `tail -n 50 ~/.lesysbot/logs/lesysbot.log`.
- If `mcp.hot_reload` is off, restart the bot.

### A tool is listed but refuses to run

```
'gpu_temp' is unavailable on this machine — requires 'nvidia-smi' on PATH (not found).
```

That's by design: tools declare which OSes and programs they need, and say so
rather than failing cryptically. Install the missing program, or use a tool that
fits this machine.

```
'gpu_temp' is disabled.
```

Turn it back on: `lesysbot tools enable gpu_temp`.

### `lesysbot tools install` fails

| Message | What to do |
|---|---|
| `Not found: owner/repo@ref` | Check the spelling and the branch/tag. For a private repo, set `GITHUB_TOKEN`. |
| `tools dir already has X` | That folder wasn't installed by LeSysBot, so it won't be overwritten. Use `--force` if you're sure. |
| Installed, but not in `/help` | Restart if hot reload is off; otherwise check the log for an import error. |
| Tool complains about a missing Python package | Re-run with `--install-deps`, or run the `pip install -r` line it printed. |

---

## Installing and starting

### `lesysbot: command not found`

pip put the command somewhere that isn't on your `PATH`:

```bash
python -m site --user-scripts     # e.g. /home/you/.local/bin
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

On Windows, re-run the Python installer and tick **Add Python to PATH**.

### PowerShell refuses to run the install script

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

### `bash: scripts/install.sh: Permission denied`

```bash
chmod +x scripts/install.sh scripts/uninstall.sh
```

### Edits to the code or a tool seem to do nothing

A non-editable install elsewhere may be shadowing your checkout:

```bash
python -c "import lesysbot; print(lesysbot.__file__)"
```

If that doesn't point at your repo, re-run `pip install -e .`.

---

## Running in the background

### The service starts, then exits immediately

Read the real error first:

```bash
journalctl --user -u lesysbot -n 50            # Linux
tail -n 50 ~/Library/Logs/lesysbot/stderr.log  # macOS
```

Windows: Task Scheduler history, or Event Viewer → Windows Logs → Application.

Common causes:

- The model backend wasn't up yet when the service started.
- Wrong working directory — the service must run from the folder holding
  `config.yaml` and `tools/`, normally `~/.lesysbot`.
- A wrong or revoked Telegram/Discord token.

### "Another instance is already running"

Only one copy of a Telegram or Discord bot can poll at a time (Telegram rejects
both otherwise), so LeSysBot takes a lock and refuses the second, naming the PID
that holds it. Stop the service first:

```bash
systemctl --user stop lesysbot          # Linux
```

A terminal chat (`lesysbot --provider cli`) doesn't poll, so it always runs fine
alongside the service.

### Config changes don't take effect

Most settings are read at startup. Restart the service:

```bash
systemctl --user restart lesysbot                                 # Linux
launchctl kickstart -k gui/$(id -u)/com.lesysbot.lesysbot         # macOS
Stop-ScheduledTask -TaskName LeSysBot; Start-ScheduledTask -TaskName LeSysBot   # Windows
```

Enabling and disabling *tools* is the exception — that applies within a second,
no restart needed.

---

## Telegram and Discord

| Symptom | Fix |
|---|---|
| Telegram replies `Unauthorized.` | Your numeric ID isn't in `allowed_user_ids`. Check it with [@userinfobot](https://t.me/userinfobot). |
| Telegram: no response at all | Wrong token, or the bot isn't running. Check the service status and the log. |
| Telegram: replies show raw `*asterisks*` | Harmless — the model produced Markdown Telegram couldn't parse, so it was sent as plain text instead of being dropped. |
| `The 'discord' provider needs a dependency that isn't installed` | `pip install ".[discord]"` |
| Discord: online but ignores every message | **MESSAGE CONTENT INTENT** is off. Enable it under **Bot → Privileged Gateway Intents** and restart — the log names it too. |
| Discord: `Discord rejected the bot token` | Wrong or revoked token. **Bot → Reset Token**, then update `config.yaml`. |
| Discord: replies `Unauthorized.` | Your user ID isn't in `allowed_user_ids`. Re-copy it with Developer Mode on. |
| Discord: no answer in a channel | The bot only answers channel messages that **@-mention** it. DMs need no mention. |
| Tools missing from the `/` menu | Registered at startup only — restart after installing or enabling a tool. On Discord the bot must also have been invited with the **`applications.commands`** scope. Disabled and platform-unavailable tools are left out on purpose. |
| A tool never appears in the `/` menu | Its name must be lowercase letters, digits or `_` (both platforms' rule); the log names any tool skipped for this. It still works typed out. |
| Discord: can't open a DM with the bot | You don't share a server with it — re-run the OAuth2 invite URL. |

Full setup for both: [Telegram & Discord](adapters.md).

---

## Control panel and monitoring

| Symptom | Fix |
|---|---|
| `lesysbot` prints status when you wanted a chat | Use `lesysbot --provider cli`. Bare `lesysbot` is the health view; the panel and the bot run in the background service. |
| The panel says **offline** | The service isn't running — start it (`systemctl --user start lesysbot`, `launchctl start com.lesysbot.lesysbot`, `Start-ScheduledTask -TaskName 'LeSysBot'`). To use it without a service: `lesysbot manage`. |
| The log says `Control panel not started — port … already in use` | Something else owns `webui.port` (often a second LeSysBot). Change the port in `config.yaml` and restart the service; the bot keeps running either way. |
| The UI port is taken | `lesysbot manage --port 9000`, or change `webui.port`. |
| The UI isn't reachable from another machine | Correct — it binds `127.0.0.1` only, deliberately, and rejects non-localhost `Host` headers. Use SSH port forwarding if you need remote access. |
| Grafana shows empty panels | The exporters need a minute of data. If it stays empty, check `docker compose ps` in `monitoring/`. |
| "share me the dashboard" fails | The [monitoring stack](../monitoring/README.md) has to be running. LeSysBot finds Grafana itself (the `GRAFANA_PORT` from `monitoring/.env`, then `localhost:3000`/`3001`); set `LESYSBOT_GRAFANA_URL` only if it runs on another host. |
| The status screen shows Grafana on the wrong port | It probes `GRAFANA_PORT` from `~/.lesysbot/monitoring/.env` first and verifies each candidate answers as Grafana, so a stack moved to 3001 is reported there. If you pinned `LESYSBOT_GRAFANA_URL` in `~/.lesysbot/grafana.env` to a port Grafana left, clear or correct that line — an unreachable pin is reported as "not answering", not as a link. |

---

## Digging deeper

<details>
<summary><b>Reading the logs</b></summary>

Two files live next to your active config — `~/.lesysbot/logs/` for a normal
install:

```bash
tail -f ~/.lesysbot/logs/lesysbot.log     # plain text: what the program did
tail -f ~/.lesysbot/logs/traces.jsonl     # one JSON line per message you sent
```

`traces.jsonl` is the one to read when you want to know *what the model
decided*: every turn, every tool call with its arguments and how long it took,
and the final reply. Format reference:
[Settings → traces](configuration.md#under-the-hood).

Both rotate daily and keep a week by default. Credentials are stripped before
anything is written, so a log is safe to paste into a bug report — though if you
ran a much older version, check first:

```bash
grep -c 'bot[0-9]\{6,\}:' ~/.lesysbot/logs/lesysbot.log
```

A non-zero count means an old log holds a token; rotate that token if the file
was ever shared.

</details>

<details>
<summary><b>Turning up the detail</b></summary>

```bash
lesysbot --provider cli -v          # DEBUG on screen for one session
```

Or permanently, in `~/.lesysbot/config.yaml`:

```yaml
logging:
  level: DEBUG
```

In an interactive chat the console stays quiet regardless (only warnings and
worse) so log lines don't interrupt you — the file gets everything. For a
Telegram/Discord service, `level` controls both.

</details>

<details>
<summary><b>Starting clean</b></summary>

Reset your settings without touching your tools:

```bash
mv ~/.lesysbot/config.yaml ~/.lesysbot/config.yaml.bak
lesysbot setup
```

Reset which tools are enabled:

```bash
rm ~/.lesysbot/tool_state.json
```

Remove everything: [uninstalling](getting-started.md#uninstalling).

</details>

---

Still stuck? Open an issue at
[github.com/lesysbot/lesysbot/issues](https://github.com/lesysbot/lesysbot/issues)
with your `lesysbot` status output and the last few lines of
`~/.lesysbot/logs/lesysbot.log`.
