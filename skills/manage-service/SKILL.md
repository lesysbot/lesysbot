---
name: manage-service
description: Operate LeSysBot as a background service on Linux — status, start/stop/restart, auto-start on boot, reading logs, and writing a systemd --user unit by hand. Use when asked to "restart the bot", "is lesysbot running", "start on boot", "check the logs", or "set up lesysbot as a daemon".
---

# Run and manage LeSysBot as a service

The install wizard registers the service for **every** configuration, not just
Telegram/Discord: it serves the always-on **control panel**
(`http://127.0.0.1:8700`) and, when a remote provider is configured, runs the
bot. With `provider: cli` the service serves the panel and idles — the terminal
chat stays an on-demand `lesysbot chat` session. The service runs from
**`~/.lesysbot`** (where `config.yaml` and `tools/` live), restarts on failure,
and optionally starts on boot.

The service's exec command is **`lesysbot run`**. Bare `lesysbot` prints health
and metrics and exits, so a hand-written unit must call `lesysbot run`.

The working rhythm: edit `~/.lesysbot/config.yaml` → restart the service.
Check state with `lesysbot` (Service / Control panel rows) or the commands below.

Only one instance can run: starting `lesysbot run` manually while the service is
up refuses with "Another LeSysBot instance … is already running (PID N)" — stop
the service first for a foreground run. `lesysbot chat` doesn't poll or
bind a port and runs fine alongside the service.

## Managing the installed service

It is a **`systemd --user`** unit (`lesysbot.service`):

| Action | Command |
|---|---|
| Status | `systemctl --user status lesysbot` |
| Start / Stop | `systemctl --user start lesysbot` / `stop lesysbot` |
| Restart (apply config edits) | `systemctl --user restart lesysbot` |
| Auto-start on/off | `systemctl --user enable lesysbot` / `disable lesysbot` |
| Remove | `systemctl --user disable lesysbot && rm ~/.config/systemd/user/lesysbot.service && systemctl --user daemon-reload` |

Re-running the install wizard stops and replaces an existing service — the
easiest way to apply a provider/model change end to end.

## Auto-start on boot

A `--user` service starts at *login*. For a headless box that must come up
before anyone logs in, enable lingering: `loginctl enable-linger $USER` (undo:
`loginctl disable-linger $USER`). The install wizard does this when you pick
auto-start.

## Setting up a service by hand

Key rule: **the service must run from the directory holding `config.yaml` and
`tools/`** — `~/.lesysbot` for a standard install.

`~/.config/systemd/user/lesysbot.service` (set `ExecStart` to
`which lesysbot`; `%h` = home):

```ini
[Unit]
Description=LeSysBot — local AI assistant with tools
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/.lesysbot
ExecStart=/home/you/.local/bin/lesysbot run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Then `systemctl --user daemon-reload && systemctl --user enable --now lesysbot`.

**Throwaway background run (no service):**

```bash
nohup lesysbot run > logs/lesysbot-stdout.log 2>&1 &   # stop: pkill -f lesysbot
tmux new-session -d -s lesysbot "lesysbot run"         # or screen -S lesysbot -d -m lesysbot run
```

## Logs

```bash
journalctl --user -u lesysbot -f           # service stdout/stderr (live)
tail -f ~/.lesysbot/logs/lesysbot.log      # LeSysBot's own log
tail -f ~/.lesysbot/logs/traces.jsonl      # per-request traces (what the LLM did)
```

Both LeSysBot logs rotate daily (configurable; `null` path disables).

## Service starts but exits immediately?

Check the service logs above for the real error. Usual causes: **Ollama not
running** (start it, or point `llm.base_url` at a live backend), **wrong
`WorkingDirectory`** (must contain `config.yaml`/`tools/`), or **bad
Telegram/Discord credentials** (fix in `~/.lesysbot/config.yaml`, restart).

`lesysbot: command not found` in a unit file → use the absolute path from
`which lesysbot`; for your shell, add pip's script dir
(`python -m site --user-scripts`) to PATH.

## Related

- Every config key: [configure-lesysbot](../configure-lesysbot/SKILL.md).
- The boot-time ping: [setup-messaging](../setup-messaging/SKILL.md) §startup notice.
