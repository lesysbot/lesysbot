# Background service

The installer sets LeSysBot up as a background service. It keeps the
[control panel](management-ui.md) online and, if you use Telegram or Discord,
answers your messages. It restarts itself if it crashes.

## Everyday commands

| To… | Run |
|---|---|
| Check it | `lesysbot` |
| Apply config changes | `systemctl --user restart lesysbot` |
| Stop / start | `systemctl --user stop lesysbot` / `start lesysbot` |
| Start at boot, or not | `systemctl --user enable lesysbot` / `disable lesysbot` |
| See its output | `journalctl --user -u lesysbot -f` |

## Start before anyone logs in

A user service normally starts when you log in. On a headless server, let it
start at boot:

```bash
loginctl enable-linger $USER
```

`lesysbot setup` does this for you when you choose to start at boot.

## The startup message

With Telegram or Discord, the bot messages you when it comes online — so after a
reboot you get a short report: CPU and GPU temperature, disk use, internet
speed. Turn it off in `config.yaml`:

```yaml
messaging:
  startup_notice:
    enabled: false
```

## Chatting while it runs

`lesysbot chat` works alongside the service. Only one *service* can run at a
time — a second copy refuses to start and names the one already running.

<details>
<summary><b>Setting up the service by hand</b></summary>

Only needed if you installed without the installer or `lesysbot setup`.

Create `~/.config/systemd/user/lesysbot.service` (use the path from
`which lesysbot` in `ExecStart`):

```ini
[Unit]
Description=LeSysBot
After=network.target

[Service]
WorkingDirectory=%h/.lesysbot
ExecStart=/home/you/.local/bin/lesysbot run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now lesysbot
```

Use `lesysbot run`, not bare `lesysbot` — the bare command only prints status
and exits.

</details>

Problems? See [Troubleshooting](troubleshooting.md#the-service).
