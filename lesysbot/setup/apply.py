"""Applying wizard answers: config.yaml, bundled tools, background service.

Nothing here runs until the summary's Apply. Service management shells out
(systemctl / launchctl / PowerShell's ScheduledTask cmdlets); the *runner*
parameter exists so tests can record invocations instead of touching the host.
No sudo, ever — the wizard must stay password-free. That now holds for tools
too: none of them may require root either, so there is no privileged setup step
to hand off to (see docs/writing-tools.md §6).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from lesysbot.setup.wizard import WizardState

CONFIG_TEMPLATE = """\
messaging:
  provider: {provider}

  telegram:
    token: "{tg_token}"
    allowed_user_ids: {tg_allowed_ids}

  slack:
    bot_token: "{slack_bot}"
    app_token: "{slack_app}"

llm:
  base_url: "{base_url}"
  model: "{model}"
  api_key: "{api_key}"
  temperature: 0.7
  max_tokens: 4096
  timeout: 120.0

mcp:
  tools_dir: "./tools"
  hot_reload: true

agent:
  system_prompt: >
    You are a helpful assistant with access to tools.
    Use tools when they help answer the user's question.
    Be concise and clear.
  max_history: 50
  max_tool_calls: 10

logging:
  level: INFO
  file: logs/lesysbot.log
  trace_file: logs/traces.jsonl
"""


def write_config(st: WizardState, data_dir: Path) -> Path:
    """Write config.yaml from the wizard state; returns its path.

    tools_dir/logs stay relative — the app anchors them to the config's
    directory, so they resolve to ``data_dir/tools`` and ``data_dir/logs``.
    """
    path = data_dir / "config.yaml"
    path.write_text(
        CONFIG_TEMPLATE.format(
            provider=st.msg_provider,
            tg_token=st.tg_token,
            tg_allowed_ids=st.tg_allowed_ids,
            slack_bot=st.slack_bot,
            slack_app=st.slack_app,
            base_url=st.llm_base_url,
            model=st.llm_model,
            api_key=st.llm_api_key,
        ),
        encoding="utf-8",
    )
    return path


def seed_tools(repo_dir: Path | None, data_dir: Path) -> bool:
    """Copy the repo's bundled tools/ on first install; never clobber."""
    if repo_dir is None:
        return False
    src = repo_dir / "tools"
    dst = data_dir / "tools"
    if dst.exists() or not src.is_dir():
        return False
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return True


def read_provider(config_file: Path) -> str:
    """Best-effort provider from an existing config.yaml (kept-config path)."""
    for line in config_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("provider:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                return value
    return "cli"


def lesysbot_binary() -> str:
    """The executable the service should run."""
    if getattr(sys, "frozen", False):
        return sys.executable
    argv0 = Path(sys.argv[0])
    if argv0.name.startswith("lesysbot") and argv0.exists():
        return str(argv0.resolve())
    return shutil.which("lesysbot") or "lesysbot"


# ── Linux (systemd --user) ────────────────────────────────────────────────────
_UNIT_TEMPLATE = """\
[Unit]
Description=LeSysBot — local AI assistant with tools
After=network.target

[Service]
Type=simple
WorkingDirectory={data_dir}
ExecStart={lesysbot_bin} run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "lesysbot.service"


def setup_service_linux(ui, st: WizardState, data_dir: Path, runner=subprocess.run) -> None:
    unit = _unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)

    # Replace any existing service so the new config takes effect (a running
    # service keeps its old config in memory — `start` alone would not reload).
    if unit.exists():
        ui.warn("Existing LeSysBot service found — stopping and replacing it…")
        runner(["systemctl", "--user", "stop", "lesysbot"], capture_output=True)

    unit.write_text(
        _UNIT_TEMPLATE.format(data_dir=data_dir, lesysbot_bin=lesysbot_binary()),
        encoding="utf-8",
    )
    runner(["systemctl", "--user", "daemon-reload"], capture_output=True)

    # `restart` (not `start`) guarantees a running instance reloads the config.
    if st.auto_start:
        runner(["systemctl", "--user", "enable", "lesysbot"], capture_output=True)
        runner(["systemctl", "--user", "restart", "lesysbot"], capture_output=True)
        if shutil.which("loginctl"):
            rc = runner(
                ["loginctl", "enable-linger", os.environ.get("USER", "")],
                capture_output=True,
            ).returncode
            if rc == 0:
                ui.ok("Linger enabled — starts at boot without login")
            else:
                ui.warn("Could not enable linger — service will start on first login")
        ui.ok("systemd service installed, enabled, and (re)started")
    else:
        runner(["systemctl", "--user", "restart", "lesysbot"], capture_output=True)
        ui.ok("systemd service (re)started (not enabled at boot)")

    ui.say("\n  Manage:")
    ui.note("systemctl --user status lesysbot")
    ui.note("systemctl --user stop   lesysbot")
    ui.note("journalctl --user -u lesysbot -f")


def remove_stale_service_linux(ui, runner=subprocess.run) -> None:
    unit = _unit_path()
    if not unit.exists():
        return
    ui.say("")
    ui.warn("A background LeSysBot service is still installed from a previous setup.")
    active = runner(
        ["systemctl", "--user", "is-active", "--quiet", "lesysbot"], capture_output=True
    ).returncode == 0
    if active:
        ui.warn("It is currently running.")
    if ui.confirm_yn("Stop and remove that background service?", default=True):
        runner(["systemctl", "--user", "stop", "lesysbot"], capture_output=True)
        runner(["systemctl", "--user", "disable", "lesysbot"], capture_output=True)
        unit.unlink(missing_ok=True)
        runner(["systemctl", "--user", "daemon-reload"], capture_output=True)
        ui.ok("Background service stopped and removed")
    else:
        ui.warn("Left it in place — it will keep running in the background.")


# ── macOS (launchd) ───────────────────────────────────────────────────────────
_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lesysbot.lesysbot</string>

    <key>ProgramArguments</key>
    <array>
        <string>{lesysbot_bin}</string>
        <string>run</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{data_dir}</string>

    <key>RunAtLoad</key>
    {run_at_load}

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{log_dir}/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/stderr.log</string>
</dict>
</plist>
"""


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.lesysbot.lesysbot.plist"


def setup_service_macos(ui, st: WizardState, data_dir: Path, runner=subprocess.run) -> None:
    plist = _plist_path()
    log_dir = Path.home() / "Library" / "Logs" / "lesysbot"
    plist.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    if plist.exists():
        ui.warn("Existing LeSysBot LaunchAgent found — stopping and replacing it…")
    runner(["launchctl", "unload", "-w", str(plist)], capture_output=True)

    plist.write_text(
        _PLIST_TEMPLATE.format(
            lesysbot_bin=lesysbot_binary(),
            data_dir=data_dir,
            run_at_load="<true/>" if st.auto_start else "<false/>",
            log_dir=log_dir,
        ),
        encoding="utf-8",
    )
    runner(["launchctl", "load", "-w", str(plist)], capture_output=True)
    ui.ok("LaunchAgent installed and started")
    if st.auto_start:
        ui.ok("Auto-starts at login")

    ui.say("\n  Manage:")
    ui.note("launchctl stop  com.lesysbot.lesysbot")
    ui.note("launchctl start com.lesysbot.lesysbot")
    ui.note(f"tail -f {log_dir}/stdout.log")


def remove_stale_service_macos(ui, runner=subprocess.run) -> None:
    plist = _plist_path()
    if not plist.exists():
        return
    ui.say("")
    ui.warn("A background LeSysBot LaunchAgent is still installed from a previous setup.")
    if ui.confirm_yn("Stop and remove that background service?", default=True):
        runner(["launchctl", "unload", "-w", str(plist)], capture_output=True)
        plist.unlink(missing_ok=True)
        ui.ok("Background service stopped and removed")
    else:
        ui.warn("Left it in place — it will keep running in the background.")


# ── Windows (Task Scheduler, via PowerShell cmdlets) ──────────────────────────
def _powershell(script: str, runner=subprocess.run) -> subprocess.CompletedProcess:
    return runner(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )


def _task_exists(runner=subprocess.run) -> bool:
    return _powershell(
        "if (Get-ScheduledTask -TaskName 'LeSysBot' -ErrorAction SilentlyContinue) "
        "{ exit 0 } else { exit 1 }",
        runner,
    ).returncode == 0


def setup_service_windows(ui, st: WizardState, data_dir: Path, runner=subprocess.run) -> None:
    if _task_exists(runner):
        ui.warn("Existing LeSysBot task found — stopping and replacing it…")
        _powershell(
            "Stop-ScheduledTask -TaskName 'LeSysBot' -ErrorAction SilentlyContinue; "
            "Unregister-ScheduledTask -TaskName 'LeSysBot' -Confirm:$false",
            runner,
        )

    trigger = (
        "$trigger = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME; "
        if st.auto_start
        else ""
    )
    register = (
        "Register-ScheduledTask -TaskName 'LeSysBot' -Action $action "
        + ("-Trigger $trigger " if st.auto_start else "")
        + "-Settings $settings -Principal $principal -Force | Out-Null"
    )
    script = (
        f"$action = New-ScheduledTaskAction -Execute '{lesysbot_binary()}' "
        f"-Argument 'run' -WorkingDirectory '{data_dir}'; "
        "$settings = New-ScheduledTaskSettingsSet -RestartCount 3 "
        "-RestartInterval (New-TimeSpan -Minutes 1) "
        "-ExecutionTimeLimit ([System.TimeSpan]::Zero) "
        "-MultipleInstances IgnoreNew -StartWhenAvailable $true; "
        "$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest; "
        f"{trigger}{register}; "
        "Start-ScheduledTask -TaskName 'LeSysBot'"
    )
    result = _powershell(script, runner)
    if result.returncode != 0:
        ui.warn(f"Task Scheduler setup failed: {result.stderr.strip()}")
        return
    if st.auto_start:
        ui.ok("Task Scheduler entry created — starts at login")
    else:
        ui.ok("Task Scheduler entry created (no auto-start trigger)")
    ui.ok("LeSysBot started")

    ui.say("\n  Manage:")
    ui.note("Get-ScheduledTask  -TaskName 'LeSysBot' | Select-Object State")
    ui.note("Stop-ScheduledTask  -TaskName 'LeSysBot'")
    ui.note("Start-ScheduledTask -TaskName 'LeSysBot'")
    ui.note("Or open Task Scheduler (taskschd.msc) and find 'LeSysBot'.")


def remove_stale_service_windows(ui, runner=subprocess.run) -> None:
    if not _task_exists(runner):
        return
    ui.say("")
    ui.warn("A background LeSysBot task is still installed from a previous setup.")
    if ui.confirm_yn("Stop and remove that background service?", default=True):
        _powershell(
            "Stop-ScheduledTask -TaskName 'LeSysBot' -ErrorAction SilentlyContinue; "
            "Unregister-ScheduledTask -TaskName 'LeSysBot' -Confirm:$false",
            runner,
        )
        ui.ok("Background service stopped and removed")
    else:
        ui.warn("Left it in place — it will keep running in the background.")


def setup_service(ui, st: WizardState, data_dir: Path) -> None:
    if sys.platform.startswith("linux"):
        setup_service_linux(ui, st, data_dir)
    elif sys.platform == "darwin":
        setup_service_macos(ui, st, data_dir)
    elif sys.platform == "win32":
        setup_service_windows(ui, st, data_dir)
    else:
        ui.warn(f"Unsupported OS: {sys.platform} — see docs/service.md for manual setup.")


def remove_stale_service(ui) -> None:
    if sys.platform.startswith("linux"):
        remove_stale_service_linux(ui)
    elif sys.platform == "darwin":
        remove_stale_service_macos(ui)
    elif sys.platform == "win32":
        remove_stale_service_windows(ui)


# ── Epilogue ──────────────────────────────────────────────────────────────────
def print_epilogue(ui, provider: str, needs_service: bool, data_dir: Path) -> None:
    ui.say("\n  [bold]How to use[/bold]\n")
    if provider in ("telegram", "slack"):
        place = "Telegram" if provider == "telegram" else "Slack"
        first = (
            "Open Telegram and find the bot you created with @BotFather"
            if provider == "telegram"
            else "Invite the bot to a channel, or open a direct message with it"
        )
        ui.say(f"  LeSysBot is running as a [bold]{place}[/bold] bot.\n")
        ui.say(f"    1. {first}")
        ui.say("    2. Send it a message, e.g.  [bold]what's my disk usage on / ?[/bold]")
        ui.say("    3. Built-in commands:  [bold]/help[/bold] (list tools)  "
               "[bold]/clear[/bold]  [bold]/history[/bold]\n")
        ui.say("  Prefer the terminal? Start a local chat anytime:")
        ui.say("    [bold]lesysbot --provider cli[/bold]")
    else:
        ui.say("  Start chatting in your terminal:")
        ui.say("    [bold]lesysbot --provider cli[/bold]\n")
        ui.say("  Then try:")
        ui.say("    • Ask in plain language    [bold]what's my disk usage on / ?[/bold]")
        ui.say("    • Run a tool directly      [bold]/disk_usage path=/[/bold]")
        ui.say("    • List available tools     [bold]/help[/bold]")
        ui.say("    • Clear the conversation   [bold]/clear[/bold]")
        ui.say("    • Leave                    type [bold]exit[/bold]")

    ui.say("\n  Full usage guide:  [bold]docs/usage.md[/bold]")
    ui.say(f"  Activity logs:     [bold]{data_dir}/logs/lesysbot.log[/bold]")
    ui.say(f"  Reconfigure:       [bold]lesysbot setup[/bold]  (or edit "
           f"[bold]{data_dir}/config.yaml[/bold])")
    if needs_service:
        ui.say("\n  [green][bold]LeSysBot is running.[/bold][/green]")
        restart = {
            "darwin": "launchctl kickstart -k gui/$(id -u)/com.lesysbot.lesysbot",
            "win32": "Stop-ScheduledTask -TaskName 'LeSysBot'; Start-ScheduledTask -TaskName 'LeSysBot'",
        }.get(sys.platform, "systemctl --user restart lesysbot")
        ui.say(f"  After config edits, restart to apply:  [bold]{restart}[/bold]\n")
    else:
        ui.say("\n  [green][bold]LeSysBot is ready.[/bold][/green]\n")
