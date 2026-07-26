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

from lesysbot.core.paths import parse_env_file
from lesysbot.setup.wizard import WizardState

CONFIG_TEMPLATE = """\
messaging:
  provider: {provider}

  telegram:
    token: "{tg_token}"
    allowed_user_ids: {tg_allowed_ids}

  discord:
    token: "{dc_token}"
    allowed_user_ids: {dc_allowed_ids}

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
            dc_token=st.dc_token,
            dc_allowed_ids=st.dc_allowed_ids,
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


def seed_monitoring(repo_dir: Path | None, data_dir: Path) -> bool:
    """Copy the repo's monitoring/ stack into ~/.lesysbot on first install.

    The Grafana dashboard is a standard part of LeSysBot, so — like ``tools/`` —
    it is seeded into the installed home, self-contained and re-runnable there
    even without the source checkout. Never clobbers an existing copy (preserves
    user edits to ``.env`` / dashboards); runtime dirs (``bin/``, ``run/``) and
    caches are skipped, and a ``.env`` is seeded from the example so ports/login
    are editable in one place.
    """
    if repo_dir is None:
        return False
    src = repo_dir / "monitoring"
    dst = data_dir / "monitoring"
    if dst.exists() or not src.is_dir():
        return False
    shutil.copytree(
        src, dst, ignore=shutil.ignore_patterns("__pycache__", "bin", "run")
    )
    env, example = dst / ".env", dst / ".env.example"
    if not env.exists() and example.exists():
        shutil.copyfile(example, env)
    return True


def monitoring_dir(data_dir: Path) -> Path:
    return data_dir / "monitoring"


GRAFANA_DOWNLOAD = "https://grafana.com/grafana/download"


def _grafana_env_path(data_dir: Path) -> Path:
    return data_dir / "grafana.env"


DEFAULT_GRAFANA_PORT = "3000"


def monitoring_port(mon: Path) -> str:
    """Grafana's host port from the bundled stack's ``.env``, else 3000.

    That file is the one place the port is set (``GRAFANA_PORT``), and it gets
    moved off 3000 whenever something else on the machine already owns it — so
    it, not a fixed 3000, decides where LeSysBot expects Grafana.
    """
    port = parse_env_file(mon / ".env").get("GRAFANA_PORT", "")
    return port if port.isdigit() else DEFAULT_GRAFANA_PORT


def grafana_local_url(data_dir: Path) -> str:
    """``http://localhost:<the bundled stack's Grafana port>``."""
    return f"http://localhost:{monitoring_port(monitoring_dir(data_dir))}"


def default_grafana_url(data_dir: Path) -> str:
    """Where a (re)run should expect Grafana to be.

    A previously saved **non-local** URL is a deliberate choice (Grafana on
    another host) and is kept. A saved *localhost* one is only a port away from
    the bundled stack, so the stack's own ``GRAFANA_PORT`` wins — otherwise a
    stack moved to 3001 keeps being advertised on 3000, where something else
    answers.
    """
    from urllib.parse import urlsplit

    prev = parse_env_file(_grafana_env_path(data_dir)).get("LESYSBOT_GRAFANA_URL", "")
    if prev and urlsplit(prev).hostname not in ("localhost", "127.0.0.1", "::1", None):
        return prev
    return grafana_local_url(data_dir)


def ask_grafana_credentials(ui, data_dir: Path) -> tuple[str, str, str]:
    """Ask which Grafana login LeSysBot should use to reach the dashboard.

    Returns ``(url, user, password)``. Defaults are the standard admin/admin, and
    the URL follows the bundled stack's configured port (see
    ``default_grafana_url``); a previous run's user/password are offered so
    reconfiguring keeps them. Esc/empty keeps the default (this is an apply-time
    prompt, not a step with back-navigation).
    """
    prev = parse_env_file(_grafana_env_path(data_dir))
    ui.say("\n  Grafana login LeSysBot will use to reach the dashboard "
           "(match it in Grafana):")
    user = ui.text("Grafana username", prev.get("LESYSBOT_GRAFANA_USER") or "admin") or "admin"
    password = ui.text("Grafana password",
                       prev.get("LESYSBOT_GRAFANA_PASSWORD") or "admin",
                       secret=True) or "admin"
    return default_grafana_url(data_dir), user, password


def write_grafana_env(data_dir: Path, url: str, user: str, password: str) -> Path:
    """Persist the Grafana connection to ``~/.lesysbot/grafana.env``.

    ``lesysbot`` loads this into the environment at startup, so the
    ``share_dashboard`` tool and the status screen authenticate with it. Written
    0600 because it holds a password.
    """
    path = _grafana_env_path(data_dir)
    path.write_text(
        "# Grafana connection for LeSysBot — loaded into the environment at startup.\n"
        "# Used by the share_dashboard tool and the status screen's Grafana probe.\n"
        f"LESYSBOT_GRAFANA_URL={url}\n"
        f"LESYSBOT_GRAFANA_USER={user}\n"
        f"LESYSBOT_GRAFANA_PASSWORD={password}\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _apply_creds_to_monitoring_env(mon: Path, user: str, password: str) -> None:
    """Point the bundled Docker Grafana at the same admin login (fresh installs).

    Grafana only honours ``GF_SECURITY_ADMIN_*`` on first boot of an empty
    ``grafana-data`` volume, so this matches the login on a clean install; an
    already-initialised volume keeps its old password (change it in the Grafana UI).
    """
    env = mon / ".env"
    try:
        existing = env.read_text(encoding="utf-8").splitlines()
    except OSError:
        existing = []
    lines, seen_user, seen_pw = [], False, False
    for line in existing:
        if line.startswith("GRAFANA_ADMIN_USER="):
            lines.append(f"GRAFANA_ADMIN_USER={user}")
            seen_user = True
        elif line.startswith("GRAFANA_ADMIN_PASSWORD="):
            lines.append(f"GRAFANA_ADMIN_PASSWORD={password}")
            seen_pw = True
        else:
            lines.append(line)
    if not seen_user:
        lines.append(f"GRAFANA_ADMIN_USER={user}")
    if not seen_pw:
        lines.append(f"GRAFANA_ADMIN_PASSWORD={password}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compose_ok(runner=subprocess.run) -> bool:
    """Compose v2 present? (client-side — works even with the daemon down)."""
    try:
        return runner(["docker", "compose", "version"], capture_output=True).returncode == 0
    except OSError:
        return False


def _daemon_ok(runner=subprocess.run) -> bool:
    """Is the Docker daemon reachable? False when Desktop isn't started yet."""
    try:
        return runner(["docker", "info"], capture_output=True).returncode == 0
    except OSError:
        return False


def _docker_running(runner=subprocess.run) -> bool:
    """Docker installed, Compose v2 present, and the daemon reachable."""
    return (
        shutil.which("docker") is not None
        and _compose_ok(runner)
        and _daemon_ok(runner)
    )


def _run_bundled_stack(ui, mon: Path, start: Path, finish_cmd: str, runner,
                       user: str, url: str) -> bool:
    """Run the bundled Docker stack (Linux ``start.sh up``) and report."""
    ui.say("\n  Starting the Grafana monitoring dashboard "
           "(first run pulls images — may take a few minutes)…\n")
    try:
        rc = runner(["bash", str(start), "up"], cwd=str(mon)).returncode
    except OSError as e:
        ui.warn(f"Could not start the dashboard: {e}")
        ui.note(f"Finish it later with:  {finish_cmd}")
        return False
    if rc == 0:
        ui.ok(f"Grafana dashboard is up at {url}  "
              f"(log in as {user} with the password you set)")
        return True
    ui.warn("The dashboard didn't start cleanly — see the output above.")
    ui.note(f"Retry with:  {finish_cmd}")
    return False


def _persist_grafana(ui, data_dir: Path, mon: Path, url: str, user: str, password: str) -> None:
    """Save the login where the bot reads it, and point the bundled Grafana at it."""
    env_path = write_grafana_env(data_dir, url, user, password)
    _apply_creds_to_monitoring_env(mon, user, password)
    ui.ok(f"Grafana login saved to {env_path} — LeSysBot uses it to reach the dashboard")


def _grafana_manual_instructions(ui, data_dir: Path, mon: Path, finish_cmd: str, runner) -> bool:
    """macOS/Windows: warn, instruct a native Grafana install, then ask the login
    LeSysBot should use. We deliberately don't require Docker Desktop here —
    Grafana ships a native package for both OSes. Returns False (nothing started)."""
    ui.warn("On macOS/Windows the Grafana dashboard is set up by hand — a quick one-time step:")
    ui.note(f"1. Install Grafana (native package for your OS):  {GRAFANA_DOWNLOAD}")
    ui.note("2. Start Grafana and open  http://localhost:3000  (first login admin / admin).")
    ui.note("3. On the default port 3000 LeSysBot detects Grafana automatically (status")
    ui.note("   screen + 'share dashboard'); on another host/port set LESYSBOT_GRAFANA_URL.")
    ui.note("   The metrics feed (Prometheus + exporters) is in monitoring/README.md.")
    if _docker_running(runner):
        ui.note(f"Shortcut: Docker is running, so you can instead bring up the whole "
                f"bundled stack in one step:  {finish_cmd}")
    url, user, password = ask_grafana_credentials(ui, data_dir)
    _persist_grafana(ui, data_dir, mon, url, user, password)
    ui.note(f"Set that same login ({user} / the password you entered) as Grafana's admin "
            "when you first open it, so LeSysBot can connect.")
    return False


def _grafana_linux(ui, data_dir: Path, mon: Path, start: Path, finish_cmd: str, runner) -> bool:
    """Linux: ask *how* to set the dashboard up first (auto-start vs. manual when
    Docker is running; otherwise how to get Docker ready — no sudo from us), then
    ask the Grafana login and save it."""
    if _docker_running(runner):
        auto = True
        if getattr(ui, "interactive", False):
            auto = ui.menu(
                "Set up the Grafana system dashboard now?",
                [
                    "Auto-start it now with Docker (recommended)",
                    "I'll set it up manually later",
                ],
                default=1,
            ) == 1
        url, user, password = ask_grafana_credentials(ui, data_dir)
        _persist_grafana(ui, data_dir, mon, url, user, password)
        if auto:
            return _run_bundled_stack(ui, mon, start, finish_cmd, runner, user, url)
        ui.note(f"OK — start the dashboard whenever you like with:  {finish_cmd}")
        ui.note(f"(Grafana lands on {url}, log in as {user} — "
                "LeSysBot detects it there.)")
        return False

    # Docker isn't ready — tell the user precisely how to fix it, no sudo from us.
    if shutil.which("docker") is None:
        ui.warn("The Grafana dashboard uses Docker on Linux, which isn't installed.")
        ui.note("Install Docker Engine:  https://docs.docker.com/engine/install/")
    elif not _compose_ok(runner):
        ui.warn("Docker is installed but Compose v2 ('docker compose') is missing.")
        ui.note("Install the docker compose plugin for your distro.")
    else:
        ui.warn("The Docker daemon isn't reachable.")
        ui.note("Start it ('sudo systemctl start docker'), or join the 'docker' group")
        ui.note("('sudo usermod -aG docker $USER', then log out/in).")
    ui.note(f"Then start the dashboard with:  {finish_cmd}")
    ui.note(f"Prefer no Docker? You can also run Grafana natively:  {GRAFANA_DOWNLOAD}")
    url, user, password = ask_grafana_credentials(ui, data_dir)
    _persist_grafana(ui, data_dir, mon, url, user, password)
    return False


def start_monitoring(ui, data_dir: Path, runner=subprocess.run) -> bool:
    """Set up the Grafana dashboard as part of install — default, not optional.

    Each OS flow asks *how* to set it up first, then the Grafana username/password
    LeSysBot should use, and saves that to ``~/.lesysbot/grafana.env`` (read back
    at bot startup). It never fails the install:

    * **Linux** — Docker is the path. If Docker is already running, ask whether to
      **auto-start** the bundled stack now or **set it up manually** later; if it
      isn't running, print the exact (no-sudo) steps to get it ready.
    * **macOS/Windows** — don't force Docker Desktop: **warn and instruct** a
      native Grafana install (``grafana.com/grafana/download``) and how to connect
      it to LeSysBot. If Docker happens to be running, mention the one-command
      bundled stack as a shortcut.

    Set ``LESYSBOT_SKIP_MONITORING`` to skip this entirely (unattended installs).
    Returns True only when the bundled stack was actually started.
    """
    mon = monitoring_dir(data_dir)
    if not mon.is_dir():
        return False
    win = sys.platform == "win32"
    start = mon / "scripts" / ("start.ps1" if win else "start.sh")
    finish_cmd = (
        f"powershell -ExecutionPolicy Bypass -File {start}" if win else str(start)
    )

    if os.environ.get("LESYSBOT_SKIP_MONITORING"):
        ui.warn("Skipping the Grafana dashboard (LESYSBOT_SKIP_MONITORING set).")
        ui.note(f"Set it up anytime — see monitoring/README.md ({GRAFANA_DOWNLOAD}).")
        return False

    # Each flow asks *how* to set the dashboard up first, then the Grafana login,
    # then persists it (grafana.env + the bundled monitoring/.env).
    if win or sys.platform == "darwin":
        return _grafana_manual_instructions(ui, data_dir, mon, finish_cmd, runner)
    return _grafana_linux(ui, data_dir, mon, start, finish_cmd, runner)


def _section(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _ids(value) -> tuple[str, str]:
    """An ``allowed_user_ids`` list as the wizard's ``(raw, yaml_list)`` pair."""
    ids = [str(v).strip() for v in value] if isinstance(value, list) else []
    ids = [v for v in ids if v]
    return ",".join(ids), "[" + ", ".join(ids) + "]"


def _llm_choice(base_url: str, api_key: str) -> int:
    """Which Step-1 menu entry an existing llm section came from."""
    if "api.openai.com" in base_url:
        return 2
    if "11434" in base_url:
        return 1
    return 3 if api_key == "vllm" else 4


def read_config_state(config_file: Path) -> WizardState:
    """Rebuild a :class:`WizardState` from an existing config.yaml.

    The kept-config path skips the wizard chain, so without this the summary
    would describe a blank default state (empty model, empty allow-list)
    instead of the install the user is actually keeping. Best-effort: an
    unreadable or oddly shaped config degrades to whatever did parse.
    """
    import yaml

    st = WizardState()
    try:
        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return st
    if not isinstance(data, dict):
        return st

    msg = _section(data, "messaging")
    provider = str(msg.get("provider") or "").strip()
    if provider:
        st.msg_provider = provider
    st.msg_choice = {"telegram": 2, "discord": 3}.get(st.msg_provider, 1)

    tg = _section(msg, "telegram")
    st.tg_token = str(tg.get("token") or "")
    st.tg_raw_ids, st.tg_allowed_ids = _ids(tg.get("allowed_user_ids"))
    dc = _section(msg, "discord")
    st.dc_token = str(dc.get("token") or "")
    st.dc_raw_ids, st.dc_allowed_ids = _ids(dc.get("allowed_user_ids"))

    # A config may legitimately omit keys — the bot then runs on the model's
    # own defaults, so those are what the summary should show.
    from lesysbot.core.config import LLMConfig

    fallback = LLMConfig()
    llm = _section(data, "llm")
    st.llm_base_url = str(llm.get("base_url") or fallback.base_url)
    st.llm_model = str(llm.get("model") or fallback.model)
    st.llm_api_key = str(llm.get("api_key") or fallback.api_key)
    st.llm_choice = _llm_choice(st.llm_base_url, st.llm_api_key)
    return st


def read_provider(config_file: Path) -> str:
    """Best-effort provider from an existing config.yaml (kept-config path)."""
    return read_config_state(config_file).msg_provider


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
Description=LeSysBot — local AI assistant with tools (control panel + bot)
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


def setup_service(ui, st: WizardState, data_dir: Path, runner=subprocess.run) -> None:
    if sys.platform.startswith("linux"):
        setup_service_linux(ui, st, data_dir, runner=runner)
    elif sys.platform == "darwin":
        setup_service_macos(ui, st, data_dir, runner=runner)
    elif sys.platform == "win32":
        setup_service_windows(ui, st, data_dir, runner=runner)
    else:
        ui.warn(f"Unsupported OS: {sys.platform} — see docs/service.md for manual setup.")


# ── Epilogue ──────────────────────────────────────────────────────────────────
def control_panel_url() -> str:
    """Where the service serves the control panel (config's ``webui.port``)."""
    from lesysbot.core.config import Settings

    try:
        return f"http://127.0.0.1:{Settings.load().webui.port}"
    except Exception:
        return "http://127.0.0.1:8700"


def print_epilogue(ui, provider: str, needs_service: bool, data_dir: Path) -> None:
    ui.say("\n  [bold]How to use[/bold]\n")
    if provider in ("telegram", "discord"):
        place = "Telegram" if provider == "telegram" else "Discord"
        first = (
            "Open Telegram and find the bot you created with @BotFather"
            if provider == "telegram"
            else "Invite the bot to your server with its OAuth2 URL, then DM it "
                 "(or @-mention it in a channel)"
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
    ui.say(f"  Control panel:     [bold]{control_panel_url()}[/bold]  "
           "(settings, tools, health — always on)")
    ui.say("  Dashboard:         [bold]http://localhost:3000[/bold]  "
           "(Grafana — login admin / admin)")
    ui.say("  Health check:      [bold]lesysbot[/bold]  (status of all of the above)")
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
