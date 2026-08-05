# Run as a service

LeSysBot runs in the background so two things are always there: the
[management panel](management-ui.md) at `http://127.0.0.1:8700`, and — if you use
Telegram or Slack — the bot answering your messages. This page covers keeping it
alive, starting it at boot, and finding the logs when something's off.

Installing LeSysBot itself is in [Getting started](getting-started.md).

---

## You already have one

The setup wizard installs it for every configuration — systemd on Linux, launchd
on macOS, Task Scheduler on Windows. It runs from `~/.lesysbot`, restarts itself
if it crashes, and starts on boot if you asked for that.

It's installed even if you picked **Terminal only**: the service is what keeps
the management panel online. With that provider there's no chat to serve, so the
panel is all it does — your terminal chat is still something you start yourself
with `lesysbot --provider cli`.

To see whether it's up, run `lesysbot` — that prints health and metrics and
exits, without starting anything.

The day-to-day rhythm is two commands:

```bash
$EDITOR ~/.lesysbot/config.yaml       # change something
systemctl --user restart lesysbot     # apply it (Linux — see the table below)
```

---

## Controlling it

**Linux (systemd)**

| Action | Command |
|---|---|
| Is it running? | `systemctl --user status lesysbot` |
| Start / stop | `systemctl --user start lesysbot` / `stop lesysbot` |
| Apply config changes | `systemctl --user restart lesysbot` |
| Start at login, or not | `systemctl --user enable lesysbot` / `disable lesysbot` |
| Remove it | `systemctl --user disable lesysbot && rm ~/.config/systemd/user/lesysbot.service && systemctl --user daemon-reload` |

**macOS (launchd)**

| Action | Command |
|---|---|
| Is it running? | `launchctl list \| grep lesysbot` |
| Start / stop | `launchctl start com.lesysbot.lesysbot` / `stop com.lesysbot.lesysbot` |
| Apply config changes | `launchctl kickstart -k gui/$(id -u)/com.lesysbot.lesysbot` |
| Remove it | `launchctl unload -w ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist && rm ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist` |

**Windows (Task Scheduler)**

| Action | Command (PowerShell) |
|---|---|
| Is it running? | `Get-ScheduledTask -TaskName 'LeSysBot' \| Select-Object State` |
| Start / stop | `Start-ScheduledTask -TaskName 'LeSysBot'` / `Stop-ScheduledTask …` |
| Remove it | `Unregister-ScheduledTask -TaskName 'LeSysBot' -Confirm:$false` |

The graphical Task Scheduler (`taskschd.msc`) works too — the task is called
**LeSysBot**.

---

## Starting at boot

- **Linux** — the service starts when you log in. To start it before anyone logs
  in (a headless box), run `loginctl enable-linger $USER`. Undo with
  `disable-linger`.
- **macOS** — starts at login automatically. For before-login, the plist has to
  live in `/Library/LaunchDaemons/` and be loaded with `sudo`.
- **Windows** — starts when you log in. For a headless server,
  [NSSM](https://nssm.cc) can register it as a true service.

---

## The message you get when it starts

With Telegram or Slack, LeSysBot messages you as soon as it connects. Since the
service starts at boot, that doubles as a "your machine just came up" ping.

It's a short report — CPU temperature, GPU temperature, disk usage, internet
speed — with each line included only if this machine can answer it. No NVIDIA
driver, no GPU line.

Turn it off or tune it in your config:

```yaml
messaging:
  startup_notice:
    enabled: true
    notify: []          # Telegram chat ids / Slack channel ids
    speedtest: true     # set false to skip the speed measurement
```

Telegram falls back to `allowed_user_ids` when `notify` is empty. Slack has no
equivalent default, so put a channel id there.

---

## Finding the logs

**What the service itself printed:**

```bash
journalctl --user -u lesysbot -f                # Linux, live
tail -f ~/Library/Logs/lesysbot/stderr.log      # macOS
```

Windows: Task Scheduler history, or Event Viewer → Windows Logs → Application.

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

Use the `run` subcommand — that's the service: the management panel plus the bot. A
bare `lesysbot` only prints status and exits, so a unit that calls it would come
straight back down.

<details>
<summary><b>Linux — systemd user service</b></summary>

`~/.config/systemd/user/lesysbot.service`:

```ini
[Unit]
Description=LeSysBot — local AI assistant with tools (management panel + bot)
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
<summary><b>macOS — launchd agent</b></summary>

`~/Library/LaunchAgents/com.lesysbot.lesysbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lesysbot.lesysbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/lesysbot</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/you/.lesysbot</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/you/Library/Logs/lesysbot/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/you/Library/Logs/lesysbot/stderr.log</string>
</dict>
</plist>
```

Replace the path with `which lesysbot` and `you` with your username, then:

```bash
mkdir -p ~/Library/Logs/lesysbot
launchctl load -w ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist
```

</details>

<details>
<summary><b>Windows — Task Scheduler</b></summary>

In PowerShell, as your regular user:

```powershell
$bin     = (Get-Command lesysbot).Source
$workdir = Join-Path $HOME ".lesysbot"

$action   = New-ScheduledTaskAction -Execute $bin -Argument 'run' -WorkingDirectory $workdir
$trigger  = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([System.TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -StartWhenAvailable $true
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName "LeSysBot" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
Start-ScheduledTask -TaskName "LeSysBot"
```

</details>

<details>
<summary><b>Just for now — no service at all</b></summary>

```bash
nohup lesysbot run > logs/lesysbot-stdout.log 2>&1 &    # stop with: pkill -f lesysbot
screen -S lesysbot -d -m lesysbot run                   # or tmux
```

```powershell
Start-Process lesysbot -ArgumentList run -WindowStyle Hidden   # stop: Stop-Process -Name lesysbot
```

</details>

---

## Only one at a time

Two copies would fight — over the management panel's port, and, with Telegram, over
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
