# Run as a service

LeSysBot runs in the background so two things are always there: the
[control panel](management-ui.md) at `http://127.0.0.1:8700`, and — if you use
Telegram or Discord — the bot answering your messages. This page covers keeping it
alive, starting it at boot, and finding the logs when something's off.

Installing LeSysBot itself is in [Getting started](getting-started.md).

---

## You already have one

The setup wizard installs it for every configuration — a `systemd --user` unit.
It runs from `~/.lesysbot`, restarts itself if it crashes, and starts on boot if
you asked for that.

It's installed even if you picked **Terminal only**: the service is what keeps
the control panel online. With that provider there's no chat to serve, so the
panel is all it does — your terminal chat is still something you start yourself
with `lesysbot --provider cli`.

To see whether it's up, run `lesysbot` — that prints health and metrics and
exits, without starting anything.

The day-to-day rhythm is two commands:

```bash
$EDITOR ~/.lesysbot/config.yaml       # change something
systemctl --user restart lesysbot     # apply it
```

---

## Controlling it

| Action | Command |
|---|---|
| Is it running? | `systemctl --user status lesysbot` |
| Start / stop | `systemctl --user start lesysbot` / `stop lesysbot` |
| Apply config changes | `systemctl --user restart lesysbot` |
| Start at login, or not | `systemctl --user enable lesysbot` / `disable lesysbot` |
| Remove it | `systemctl --user disable lesysbot && rm ~/.config/systemd/user/lesysbot.service && systemctl --user daemon-reload` |

---

## Starting at boot

A `--user` service starts when you log in. To start it before anyone logs in — a
headless server, which is the usual case — enable lingering:

```bash
loginctl enable-linger $USER      # undo with: loginctl disable-linger $USER
```

The setup wizard does this for you when you pick auto-start.

---

## The message you get when it starts

With Telegram or Discord, LeSysBot messages you as soon as it connects. Since the
service starts at boot, that doubles as a "your machine just came up" ping.

It's a short report — CPU temperature, GPU temperature, disk usage, internet
speed — with each line included only if this machine can answer it. No NVIDIA
driver, no GPU line.

Turn it off or tune it in your config:

```yaml
messaging:
  startup_notice:
    enabled: true
    notify: []          # Telegram chat ids / Discord user or channel ids
    speedtest: true     # set false to skip the speed measurement
```

Both providers fall back to their `allowed_user_ids` when `notify` is empty, so
usually there is nothing to set. A Discord entry may also be a **channel** id, if
you'd rather the report landed in a channel than in your DMs.

---

## Finding the logs

**What the service itself printed:**

```bash
journalctl --user -u lesysbot -f           # live
journalctl --user -u lesysbot -n 100       # the last 100 lines
```

**What LeSysBot wrote:**

```bash
tail -f ~/.lesysbot/logs/lesysbot.log      # what the program did
tail -f ~/.lesysbot/logs/traces.jsonl      # what the model decided, per message
```

Both rotate daily; see [Settings](configuration.md) to change the level or
switch them off.

---

## Setting one up by hand

You need this if you installed manually, or want something the wizard doesn't
offer. One rule matters more than the rest: **the service must run from the
directory holding your `config.yaml` and `tools/`** — normally `~/.lesysbot`.

Use the `run` subcommand — that's the service: the control panel plus the bot. A
bare `lesysbot` only prints status and exits, so a unit that calls it would come
straight back down.

<details>
<summary><b>systemd user service</b></summary>

`~/.config/systemd/user/lesysbot.service`:

```ini
[Unit]
Description=LeSysBot — local AI assistant with tools (control panel + bot)
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

Set `ExecStart` from `which lesysbot`, then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now lesysbot
```

</details>

<details>
<summary><b>Just for now — no service at all</b></summary>

```bash
nohup lesysbot run > logs/lesysbot-stdout.log 2>&1 &    # stop with: pkill -f lesysbot
screen -S lesysbot -d -m lesysbot run                   # or tmux
```

</details>

---

## Only one at a time

Two copies would fight — over the control panel's port, and, with Telegram, over
the same messages (Telegram rejects both with a `409`). So the service takes a
lock at startup and a second one refuses to start, naming the process that holds
it.

Stop the service first if you want a foreground run. The lock is released
automatically when the process ends, crashes included, so nothing gets stuck. A
terminal chat (`lesysbot --provider cli`) doesn't poll, so it always runs fine
alongside the service.

---

## Something's wrong

Service problems — exits immediately, `command not found`, config changes not
taking effect — are covered in
[Troubleshooting](troubleshooting.md#running-in-the-background).
