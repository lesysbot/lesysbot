"""Applying wizard answers: config.yaml, bundled tools, background service.

Nothing here runs until the summary's Apply. Service management shells out to
``systemctl --user``; the *runner* parameter exists so tests can record
invocations instead of touching the host.
No sudo, ever — the wizard must stay password-free. That now holds for tools
too: none of them may require root either, so there is no privileged setup step
to hand off to (see docs/writing-tools.md, "Never require root").
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.artifacts.lockfile import LOCK_NAME
from lesysbot.core.paths import parse_env_file
from lesysbot.setup.wizard import WizardState


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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


def _bundled_source(repo_dir: Path | None, name: str) -> Path | None:
    """Where bundled *name* comes from: an explicit checkout, else the wheel.

    ``--repo`` still wins so a developer can seed from the tree they are editing;
    everyone else gets the copy that shipped with the package, which is what
    makes `pip install lesysbot && lesysbot setup` a complete install.
    """
    from lesysbot.core.paths import bundled_dir

    for root in (repo_dir, bundled_dir()):
        if root is not None and (root / name).is_dir():
            return root / name
    return None


def seed_tools(repo_dir: Path | None, data_dir: Path) -> bool:
    """Install/refresh the bundled tools in ~/.lesysbot, recording them in the lock.

    This used to be ``if dst.exists(): return False`` — copy once, then never
    again. That meant a fix to a bundled tool could not reach anyone who already
    had it: every existing install silently kept running the version it was born
    with, and there was no command that could tell you so.

    Now each package is seeded like anything else installed — refreshed when the
    shipped copy differs, left alone where the manifest says ``preserve:``, and
    recorded in the lock as ``bundled: true`` so ``lesysbot list`` shows where it
    came from and ``lesysbot update`` can refresh it.
    """
    src = _bundled_source(repo_dir, "tools")
    if src is None:
        return False
    return _seed_packages(src, data_dir / "tools", data_dir, ArtifactKind.TOOL)


def seed_dashboards(repo_dir: Path | None, data_dir: Path) -> bool:
    """Install/refresh the bundled dashboard packages, same rules as tools."""
    from lesysbot.core.paths import installed_dashboards_dir

    src = _bundled_source(repo_dir, "dashboards")
    if src is None:
        return False
    return _seed_packages(src, installed_dashboards_dir(data_dir), data_dir,
                          ArtifactKind.DASHBOARD)


def seed_catalog(repo_dir: Path | None, data_dir: Path) -> bool:
    """Put the bundled marketplace catalog where `lesysbot search` reads it.

    Only when there isn't one already: a cached copy is *newer* than the bundled
    one by definition, so overwriting it would undo a `--refresh`.
    """
    from lesysbot.artifacts.catalog import CATALOG_NAME
    from lesysbot.core.paths import bundled_dir

    dst = data_dir / CATALOG_NAME
    if dst.exists():
        return False
    for root in (repo_dir, bundled_dir()):
        if root is not None and (root / CATALOG_NAME).is_file():
            shutil.copyfile(root / CATALOG_NAME, dst)
            return True
    return False


def _seed_packages(src: Path, dst: Path, data_dir: Path, kind) -> bool:
    """Copy each package folder under *src* into *dst*, recording the lock entry.

    Refreshes a shipped file whose contents differ and leaves the user's alone —
    the same split ``seed_dashboard`` applies to the stack, but per package,
    driven by each manifest's ``preserve:`` rather than one global list.
    """
    from lesysbot.artifacts.lockfile import ArtifactLock
    from lesysbot.artifacts.manifest import _package_from

    lock = ArtifactLock(data_dir / LOCK_NAME)
    changed = False
    dst.mkdir(parents=True, exist_ok=True)

    for folder in sorted(p for p in src.iterdir() if p.is_dir()):
        if folder.name.startswith((".", "_")) or folder.name == "__pycache__":
            continue
        pkg = _package_from(folder, folder.name)
        if _copy_package(folder, dst / pkg.name, pkg.preserve):
            changed = True
        entry = lock.get(kind, pkg.name) or {}
        lock.put(kind, pkg.name, {
            **entry,
            "name": pkg.name,
            "kind": kind.value,
            "bundled": True,
            "version": pkg.version,
            "description": pkg.description,
            "installed_at": entry.get("installed_at") or _now(),
            "updated_at": _now(),
        })
    return changed


def _copy_package(src: Path, dst: Path, preserve: list[str]) -> bool:
    """Refresh *dst* from *src*, keeping the paths named in *preserve*."""
    changed = False
    keep = {p.strip("/") for p in preserve}
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if "__pycache__" in rel.parts:
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if str(rel) in keep and target.exists():
            continue
        if target.exists() and target.read_bytes() == path.read_bytes():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        changed = True
    return changed


# The stack's directory name under ~/.lesysbot.
DASHBOARD_DIRNAME = "dashboard"

DASHBOARD_SKIP = ("__pycache__", "bin", "run", "native")

# Top-level names the *user* owns. Everything else under the stack dir is program
# code that ships with the release, and is refreshed on upgrade — see
# seed_dashboard. `.env` holds ports and the Grafana login; `prometheus/` is
# where extra scrape targets get added by hand (dashboard/README.md documents
# exactly that). Both would be destroyed by a refresh, and neither carries fixes.
DASHBOARD_KEEP = (".env", "prometheus")


def seed_dashboard(repo_dir: Path | None, data_dir: Path) -> bool:
    """Install/refresh the repo's dashboard/ stack in ~/.lesysbot.

    The Grafana dashboard is a standard part of LeSysBot, so — like ``tools/`` —
    it is seeded into the installed home, self-contained and re-runnable there
    even without the source checkout. Runtime dirs (``bin/``, ``run/``,
    ``native/``) and caches are skipped, and a ``.env`` is seeded from the
    example so ports/login are editable in one place.

    **Shipped files are refreshed when they differ; the user's are never
    touched.** The split is ``DASHBOARD_KEEP``: ``.env`` (ports, Grafana login)
    and ``prometheus/`` (hand-added scrape targets) are seeded once and then left
    alone forever; the scripts, compose files and Grafana provisioning are
    program code, and an installed copy of those has no value except to be
    current.

    This used to add missing files but never update changed ones, and that made
    the stack effectively unpatchable: a fix to ``start.sh`` or a dashboard
    could not reach anyone who already had the file, so every existing
    install silently kept running last release's code. Re-running
    ``lesysbot setup`` now delivers fixes, which is what a user reasonably
    expects it to do.

    Returns True when anything was added or refreshed.
    """
    src = _bundled_source(repo_dir, "dashboard")
    dst = data_dir / DASHBOARD_DIRNAME
    if src is None:
        return False

    changed = False
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if any(part in DASHBOARD_SKIP for part in rel.parts):
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if rel.parts[0] in DASHBOARD_KEEP and target.exists():
            continue
        # filecmp would be one more import for a comparison this cheap; these are
        # small text files and the read is what a copy would do anyway.
        if target.exists() and target.read_bytes() == path.read_bytes():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)          # copy2 keeps the executable bit
        changed = True

    env, example = dst / ".env", dst / ".env.example"
    if not env.exists() and example.exists():
        shutil.copyfile(example, env)
        changed = True
    return changed


def dashboard_dir(data_dir: Path) -> Path:
    """The installed dashboard stack under *data_dir*.

    Delegates to :func:`lesysbot.core.paths.dashboard_dir` so the wizard and the
    bot can never disagree about which directory is the live stack.
    """
    from lesysbot.core.paths import dashboard_dir as _resolve

    return _resolve(data_dir)


GRAFANA_DOWNLOAD = "https://grafana.com/grafana/download"
# An installed user has no docs/ folder, so point at the published guides.
DOCS_URL = "https://lesysbot.github.io/latest"


def _grafana_env_path(data_dir: Path) -> Path:
    return data_dir / "grafana.env"


from lesysbot.core.grafana import grafana_port_of_stack as grafana_port  # noqa: E402


def grafana_local_url(data_dir: Path) -> str:
    """``http://localhost:<the bundled stack's Grafana port>``."""
    return f"http://localhost:{grafana_port(dashboard_dir(data_dir))}"


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

    Unattended (``lesysbot setup --yes``) there is nobody to ask, and shipping
    every install with admin/admin would be worse than no dashboard at all — so
    the password is **generated**. The fallback order is deliberate: a previous
    run's password wins over a freshly generated one, because Grafana only
    honours ``GF_SECURITY_ADMIN_PASSWORD`` on an empty volume — rotating it on a
    re-install would leave the saved credentials unable to log in.
    """
    prev = parse_env_file(_grafana_env_path(data_dir))
    if getattr(ui, "unattended", False):
        from lesysbot.setup.unattended import ENV_PREFIX, generated_password

        user = (os.environ.get(ENV_PREFIX + "GRAFANA_USER")
                or prev.get("LESYSBOT_GRAFANA_USER") or "admin")
        password = (prev.get("LESYSBOT_GRAFANA_PASSWORD")
                    or os.environ.get(ENV_PREFIX + "GRAFANA_PASSWORD")
                    or generated_password())
        return default_grafana_url(data_dir), user, password
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


def _apply_creds_to_stack_env(mon: Path, user: str, password: str) -> None:
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


def _run_stack(ui, mon: Path, script: Path, finish_cmd: str, runner,
               user: str, url: str, banner: str) -> bool:
    """Run one of the stack scripts (``bash <script> up``) and report."""
    ui.say(f"\n  {banner}\n")
    try:
        rc = runner(["bash", str(script), "up"], cwd=str(mon)).returncode
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


def _run_bundled_stack(ui, mon: Path, start: Path, finish_cmd: str, runner,
                       user: str, url: str) -> bool:
    """Run the bundled Docker stack (Linux ``start.sh up``) and report."""
    return _run_stack(
        ui, mon, start, finish_cmd, runner, user, url,
        "Starting the Grafana dashboard "
        "(first run pulls images — may take a few minutes)…",
    )


def _persist_grafana(ui, data_dir: Path, mon: Path, url: str, user: str, password: str) -> None:
    """Save the login where the bot reads it, and point the bundled Grafana at it."""
    env_path = write_grafana_env(data_dir, url, user, password)
    _apply_creds_to_stack_env(mon, user, password)
    ui.ok(f"Grafana login saved to {env_path} — LeSysBot uses it to reach the dashboard")
    if getattr(ui, "unattended", False):
        # Nobody chose this password, so say where to find it. Never print the
        # value itself: the file is 0600, the terminal and its scrollback aren't.
        ui.note(f"Username {user}; the password was generated. Read it with:")
        ui.note(f"  grep LESYSBOT_GRAFANA_PASSWORD {env_path}")


def _grafana_linux(ui, data_dir: Path, mon: Path, start: Path, finish_cmd: str, runner) -> bool:
    """Ask *how* to set the dashboard up first (auto-start vs. manual when Docker
    is running; otherwise how to get Docker ready — no sudo from us), then ask the
    Grafana login and save it."""
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
        ui.warn("The Grafana dashboard uses Docker, which isn't installed.")
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


def start_dashboard(ui, data_dir: Path, runner=subprocess.run) -> bool:
    """Set up the Grafana dashboard as part of install — default, not optional.

    The flow asks *how* to set it up first, then the Grafana username/password
    LeSysBot should use, and saves that to ``~/.lesysbot/grafana.env`` (read back
    at bot startup). It never fails the install:

    Docker is the path. If Docker is already running, ask whether to
    **auto-start** the bundled stack now or **set it up manually** later; if it
    isn't running, print the exact (no-sudo) steps to get it ready.

    Set ``LESYSBOT_SKIP_DASHBOARD`` to skip this entirely (unattended installs).
    Returns True only when the bundled stack was actually started.
    """
    mon = dashboard_dir(data_dir)
    if not mon.is_dir():
        return False
    start = mon / "scripts" / "start.sh"
    finish_cmd = str(start)

    if os.environ.get("LESYSBOT_SKIP_DASHBOARD"):
        ui.warn("Skipping the Grafana dashboard (LESYSBOT_SKIP_DASHBOARD set).")
        ui.note("Start it anytime with `lesysbot dashboard start`.")
        return False

    # Ask *how* to set the dashboard up first, then the Grafana login, then
    # persist it (grafana.env + the bundled dashboard/.env).
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
    argv0 = Path(sys.argv[0])
    if argv0.name.startswith("lesysbot") and argv0.exists():
        return str(argv0.resolve())
    return shutil.which("lesysbot") or "lesysbot"


# ── Background service (systemd --user) ──────────────────────────────────────
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


def setup_service(ui, st: WizardState, data_dir: Path, runner=subprocess.run) -> None:
    """Install and start the background service.

    ``LESYSBOT_SKIP_SERVICE`` skips it. The systemd --user unit is the one thing
    setup writes that ``LESYSBOT_HOME`` does *not* relocate — it lives at a fixed
    per-user path — so a test or CI run pointed at a scratch home would still
    replace the real machine's service. This is the guard that keeps those runs
    hermetic.
    """
    if os.environ.get("LESYSBOT_SKIP_SERVICE"):
        ui.warn("Skipping the background service (LESYSBOT_SKIP_SERVICE set).")
        ui.note("Install it anytime by re-running `lesysbot setup`.")
        return
    setup_service_linux(ui, st, data_dir, runner=runner)


# ── Epilogue ──────────────────────────────────────────────────────────────────
def control_panel_url() -> str:
    """Where the service serves the control panel (config's ``management.port``)."""
    from lesysbot.core.config import Settings

    try:
        return f"http://127.0.0.1:{Settings.load().management.port}"
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
        ui.say("    [bold]lesysbot chat[/bold]")
    else:
        ui.say("  Start chatting in your terminal:")
        ui.say("    [bold]lesysbot chat[/bold]\n")
        ui.say("  Then try:")
        ui.say("    • Ask in plain language    [bold]what's my disk usage on / ?[/bold]")
        ui.say("    • Run a tool directly      [bold]/disk_usage path=/[/bold]")
        ui.say("    • List available tools     [bold]/help[/bold]")
        ui.say("    • Clear the conversation   [bold]/clear[/bold]")
        ui.say("    • Leave                    type [bold]exit[/bold]")

    ui.say(f"\n  Full usage guide:  [bold]{DOCS_URL}/guides/usage/[/bold]")
    ui.say(f"  Control panel:     [bold]{control_panel_url()}[/bold]  "
           "(settings, tools, health — always on)")
    # Follow the port the stack was actually configured with, like every other
    # site does — a stack moved to 3001 was being advertised on 3000, where the
    # thing that took 3000 answers. The username is echoed, the password never:
    # `ask_grafana_credentials` masks it on the way in, so printing it back here
    # would undo that.
    grafana_user = parse_env_file(_grafana_env_path(data_dir)).get(
        "LESYSBOT_GRAFANA_USER") or "admin"
    ui.say(f"  Dashboard:         [bold]{default_grafana_url(data_dir)}[/bold]  "
           f"(Grafana — log in as {grafana_user})")
    ui.say("  Health check:      [bold]lesysbot[/bold]  (status of all of the above)")
    ui.say(f"  Activity logs:     [bold]{data_dir}/logs/lesysbot.log[/bold]")
    ui.say(f"  Reconfigure:       [bold]lesysbot setup[/bold]  (or edit "
           f"[bold]{data_dir}/config.yaml[/bold])")
    if needs_service:
        ui.say("\n  [green][bold]LeSysBot is running.[/bold][/green]")
        ui.say("  After config edits, restart to apply:  "
               "[bold]systemctl --user restart lesysbot[/bold]\n")
    else:
        ui.say("\n  [green][bold]LeSysBot is ready.[/bold][/green]\n")
