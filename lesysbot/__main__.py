from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

from lesysbot.core.agent import Agent
from lesysbot.core.config import LogConfig, Settings
from lesysbot.core.redact import RedactingFilter, RedactingFormatter


def _setup_logging(verbose: bool, log_cfg: LogConfig, interactive: bool = False) -> None:
    # Baseline level comes from config (`logging.level`); `-v` forces DEBUG.
    base = getattr(logging, str(log_cfg.level).upper(), logging.INFO)
    # Interactive CLI keeps the console at WARNING+ (no httpx/watchfiles/"Tools
    # loaded" INFO interrupting the chat); the daemons honour the config level.
    if verbose:
        console_level = logging.DEBUG
    elif interactive:
        console_level = max(base, logging.WARNING)
    else:
        console_level = base

    console = RichHandler(rich_tracebacks=True, show_path=False)
    console.setLevel(console_level)
    handlers: list[logging.Handler] = [console]

    # Credentials must never reach a handler: httpx logs the Telegram API URL,
    # which carries the bot token in its path, at INFO on every poll.
    redactor = RedactingFilter()

    if log_cfg.file:
        Path(log_cfg.file).parent.mkdir(parents=True, exist_ok=True)
        # Time-based rotation: roll over per `when` (default midnight) and keep
        # `backup_count` dated files (e.g. lesysbot.log.2026-06-21) so it can't grow
        # without bound.
        fh = TimedRotatingFileHandler(
            log_cfg.file,
            when=log_cfg.when,
            backupCount=log_cfg.backup_count,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG if verbose else base)
        # RedactingFormatter (not plain Formatter) so a traceback carrying a
        # request URL is scrubbed too — the filter only sees the message.
        fh.setFormatter(
            RedactingFormatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
        handlers.append(fh)

    for handler in handlers:
        handler.addFilter(redactor)

    # Root at DEBUG so handlers decide what they emit (each has its own level).
    logging.basicConfig(level=logging.DEBUG, format="%(message)s", handlers=handlers)


def _start_ui(settings: Settings, registry):
    """Bring the control panel up beside the bot (service mode only).

    The panel is meant to be online whenever LeSysBot is, so it rides along in
    the same process — sharing the bot's registry, so a toggle in the browser
    hits the very tools the LLM sees. It is never allowed to be fatal: a busy
    port (almost always a second copy already serving) is logged and the bot
    carries on.
    """
    from lesysbot.management.server import serve_background

    ui = serve_background(settings, registry=registry)
    if ui is None:
        logging.getLogger(__name__).warning(
            "Control panel not started — port %d is already in use.", settings.management.port
        )
    else:
        # The log line is for the service journal; the banner is for a human who
        # started it in a terminal (bold escapes would just litter a log file).
        logging.getLogger(__name__).info("Control panel on %s", ui.url)
        if sys.stdout.isatty():
            print(f"\n  \033[1mControl panel:\033[0m {ui.url}   (localhost only)\n")
    return ui


async def _idle() -> None:
    """Keep the service alive when there is no messaging adapter to run."""
    await asyncio.Event().wait()


async def _run(settings: Settings, *, serve_ui: bool = False) -> None:
    agent = Agent(settings)
    await agent.setup()

    provider = settings.messaging.provider

    # Service mode: the control panel comes up first, so it answers even if the
    # messaging adapter later fails to start.
    ui = _start_ui(settings, agent.registry) if serve_ui else None

    # The terminal chat is something a person starts in a terminal; a service has
    # no terminal to chat in. So in service mode a `cli` provider means "no
    # remote channel configured" — the panel is the whole job.
    if serve_ui and provider == "cli":
        logging.getLogger(__name__).info(
            "Provider 'cli' — no remote channel to serve; running the control panel only."
        )
        if sys.stdout.isatty():
            print("  Provider is 'cli' — no remote chat to serve.\n"
                  "  Chat in this terminal with:  lesysbot chat\n")
        try:
            await _idle()
        finally:
            if ui is not None:
                ui.stop()
            await agent.aclose()
        return

    # Adapters are imported lazily so a missing optional dependency only affects
    # the provider that needs it. Report that as one actionable line rather than
    # an ImportError traceback — for a background service it is the only clue
    # the user gets.
    try:
        if provider == "cli":
            from lesysbot.messaging.cli import CLIAdapter
            adapter = CLIAdapter()

        # The remote adapters take the registry so they can publish the tool list
        # as native slash commands (Telegram's `/` menu, Discord's command
        # picker). Sharing the agent's own registry means the menu offers exactly
        # the tools the agent would run.
        elif provider == "telegram":
            from lesysbot.messaging.telegram import TelegramAdapter
            adapter = TelegramAdapter(settings.messaging.telegram, agent.registry)

        elif provider == "discord":
            from lesysbot.messaging.discord import DiscordAdapter
            adapter = DiscordAdapter(settings.messaging.discord, agent.registry)

        else:
            print(f"Unknown messaging provider: {provider}", file=sys.stderr)
            sys.exit(1)
    except ImportError as e:
        print(
            f"The '{provider}' provider needs a dependency that isn't installed: {e}\n"
            f"Install it with: pip install \"lesysbot[{provider}]\"",
            file=sys.stderr,
        )
        sys.exit(1)

    # Wire the adapter's confirmation UI into the agent so tools marked
    # confirm=True will prompt the user before executing.
    agent.set_confirm_fn(adapter.confirm)

    # Out-of-band pushes: lets tools message the user after their reply — e.g.
    # the power tool's "powering off now" heads-up (see core/notify.py).
    from lesysbot.core import notify

    notify.set_sender(adapter.send)

    # The messaging adapter is the primary service; the startup notice runs as a
    # background task beside it. When the adapter finishes — e.g. the CLI user
    # types `exit`, or a daemon is cancelled — the background tasks are cancelled
    # so the process exits cleanly instead of hanging on a forever-running task.
    background: list[asyncio.Task] = []

    # Startup notice: once the adapter is ready, ping the configured chat(s)
    # with a short system report — for an installed service this fires right
    # after the machine boots. Remote providers only; the CLI user is right here.
    if provider != "cli" and settings.messaging.startup_notice.enabled:
        from lesysbot.messaging.notice import send_startup_notice
        background.append(asyncio.create_task(send_startup_notice(adapter, settings)))

    try:
        await adapter.start(agent.handle)
    finally:
        for task in background:
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        if ui is not None:
            ui.stop()
        # Close the LLM's httpx client here, while the loop is still open.
        await agent.aclose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lesysbot", description="LeSysBot — local LLM + tools bot")
    parser.add_argument("-c", "--config", default=None, help="Path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--provider",
        choices=["cli", "telegram", "discord"],
        default=None,
        help="Override messaging provider",
    )
    parser.add_argument("--model", default=None, help="Override LLM model name")
    parser.add_argument("--base-url", default=None, help="Override LLM base URL")

    # Subcommands. Bare `lesysbot` prints status and exits; the background
    # service runs `lesysbot run` (bot + always-on control panel);
    # `lesysbot --provider …` runs the bot in the foreground.
    from lesysbot.cli import register_all

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{chat,install,search,list,doctor,dashboard,run,manage,setup}",
    )
    # Re-add -c on each leaf (SUPPRESS default) so a root-level -c isn't clobbered
    # and `lesysbot manage -c …` works regardless of flag order — the same pattern
    # every artifact verb uses.
    chat = subparsers.add_parser(
        "chat", help="Chat with LeSysBot in this terminal (the long form is --provider cli)"
    )
    chat.add_argument("-c", "--config", default=argparse.SUPPRESS, help="Path to config.yaml")
    chat.add_argument("--model", default=argparse.SUPPRESS, help="Override LLM model name")
    chat.add_argument("--base-url", default=argparse.SUPPRESS, help="Override LLM base URL")
    # -v after the subcommand too: `lesysbot chat -v` is what anyone following a
    # troubleshooting page will type, and argparse would otherwise reject it
    # because -v is only on the root parser.
    chat.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
    run = subparsers.add_parser(
        "run", help="Run the service: the control panel plus the bot (what the "
                    "background service uses)"
    )
    run.add_argument("-c", "--config", default=argparse.SUPPRESS, help="Path to config.yaml")
    manage = subparsers.add_parser(
        "manage", help="Open the control panel (localhost only; the service already serves it)"
    )
    manage.add_argument("-c", "--config", default=argparse.SUPPRESS, help="Path to config.yaml")
    manage.add_argument("--port", type=int, default=None, help="Control panel port")
    manage.add_argument("--open", action="store_true", help="Open the control panel in a browser")
    register_all(subparsers)
    return parser


def _load_settings(args) -> Settings:
    settings = Settings.load(args.config)
    if getattr(args, "provider", None):
        settings.messaging.provider = args.provider
    if getattr(args, "model", None):
        settings.llm.model = args.model
    if getattr(args, "base_url", None):
        settings.llm.base_url = args.base_url

    from lesysbot.core.config import resolve_paths
    from lesysbot.core.paths import load_grafana_env
    from lesysbot.core.redact import add_secret, register_settings_secrets

    resolve_paths(settings)          # anchor tools/log/state paths to the config dir
    register_settings_secrets(settings)   # redact creds before any handler exists

    # The Grafana login the setup wizard saved (share_dashboard + status probe
    # read it from the environment). An explicit env var still wins.
    load_grafana_env()
    for key in ("LESYSBOT_GRAFANA_PASSWORD", "LESYSBOT_GRAFANA_TOKEN"):
        add_secret(os.environ.get(key))
    return settings


def _print_status(settings: Settings) -> dict:
    """The status screen shown by bare `lesysbot` / `lesysbot manage`.

    Bare `lesysbot` is a read-only health view and nothing else — it starts no
    server, because the control panel is served by the background service.
    Returns the status snapshot so callers can reuse it.
    """
    from rich.console import Console
    from rich.table import Table

    from lesysbot.core.status import build_registry, gather_status

    console = Console()
    registry = build_registry(settings)
    st = asyncio.run(gather_status(settings, registry))

    h = st.get("health") or {}
    if h.get("ok"):
        lat = f" · {h['latency_ms']} ms" if h.get("latency_ms") is not None else ""
        miss = " · [yellow]model not pulled[/yellow]" if h.get("model_available") is False else ""
        backend = f"[green]reachable[/green]{lat}{miss}"
    else:
        backend = f"[red]down[/red] · {h.get('error', 'unreachable')}"
    dm = st.get("daemon")
    if dm and dm.get("running"):
        pid = f" (PID {dm['pid']})" if dm.get("pid") else ""
        service = f"[green]running[/green]{pid}"
    else:
        service = "[dim]stopped[/dim] — start it with " + _service_start_hint()
    ui = st.get("panel") or {}
    if ui.get("running"):
        panel = f"[green]online[/green] · [link={ui['url']}]{ui['url']}[/link]"
    else:
        panel = (f"[dim]offline[/dim] — [dim]{ui.get('url', '')} "
                 "(runs with the service; or `lesysbot manage`)[/dim]")

    t = Table(show_header=False, box=None, pad_edge=False)
    t.add_column(style="dim", justify="right")
    t.add_column()
    t.add_row("LLM backend", backend)
    t.add_row("Backend URL", st["base_url"])
    t.add_row("Provider", f"{st['provider']} · model [bold]{st['model']}[/bold]")
    tools = st["tools"]
    unavail = f" · {tools['unavailable']} unavailable here" if tools["unavailable"] else ""
    t.add_row("Tools", f"{tools['enabled']}/{tools['total']} enabled{unavail}")
    t.add_row("Service", service)
    t.add_row("Control panel", panel)
    gf = st.get("grafana")
    if gf and gf.get("reachable"):
        ver = f" · v{gf['version']}" if gf.get("version") else ""
        t.add_row("Grafana", f"[link={gf['url']}]{gf['url']}[/link]{ver}")
    elif gf:
        # configured (LESYSBOT_GRAFANA_URL) but nothing answered there or on the
        # usual ports — don't offer it as a working link
        t.add_row("Grafana", f"[dim]not answering at {gf['url']} — "
                             "start it with dashboard/scripts/start.sh[/dim]")
    else:
        t.add_row("Grafana", "[dim]not running — start it with dashboard/scripts/start.sh[/dim]")
    t.add_row("Config", st["config_path"] or "[dim](built-in defaults)[/dim]")
    from lesysbot.core.banner import banner

    mark = banner(console)
    console.print()
    if mark:
        head = Table.grid(padding=(0, 3))
        head.add_column()
        head.add_column(vertical="middle")
        head.add_row(mark, f"[bold]LeSysBot[/bold]\n[dim]v{st['version']}[/dim]")
        console.print(head)
    else:
        console.print(f"[bold]LeSysBot[/bold] [dim]v{st['version']}[/dim]")
    console.print(t)
    console.print()
    # hand the already-built registry to the server so tools aren't imported twice
    _print_status.registry = registry  # type: ignore[attr-defined]
    return st


def _service_start_hint() -> str:
    return {
        "darwin": "`launchctl start com.lesysbot.lesysbot`",
        "win32": "`Start-ScheduledTask -TaskName 'LeSysBot'`",
    }.get(sys.platform, "`systemctl --user start lesysbot`")


def _manage(settings: Settings, port: int | None, open_browser: bool) -> None:
    """`lesysbot manage` — the panel in the foreground.

    Normally the service is already serving it, and a second server on another
    port would just be a stale duplicate. So when the panel answers, this only
    points at it (and opens it, with --open); it starts one itself when nothing
    is serving — a dev checkout, or while the service is stopped.
    """
    from lesysbot.core.status import detect_panel

    st = _print_status(settings)
    ui = (st.get("panel") if port is None else detect_panel(settings, port)) or {}
    if ui.get("running"):
        print(f"  The control panel is already served by the LeSysBot service: {ui['url']}\n")
        if open_browser:
            import webbrowser

            try:
                webbrowser.open(ui["url"])
            except Exception:
                pass
        return

    from lesysbot.management.server import serve

    serve(settings, registry=getattr(_print_status, "registry", None),
          port=port, open_browser=open_browser)


def _runs_the_bot(command, args) -> bool:
    """Does this invocation start a long-running process?

    `run` is the service (bot + control panel); an explicit `--provider` is the
    foreground bot. `lesysbot chat` reaches here as `--provider cli` (main()
    normalizes it before this is called), which is the terminal chat.
    Everything else (bare `lesysbot`) is the read-only status view.
    """
    return command == "run" or bool(getattr(args, "provider", None))


def _reconfigure_utf8(stream) -> None:
    """Switch a text stream to UTF-8, permissively; no-op if it can't be."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:  # replaced streams (e.g. pytest capture) lack it
        return
    try:
        reconfigure(encoding="utf-8", errors="backslashreplace")
    except (OSError, ValueError):
        pass


def _force_utf8_io() -> None:
    """Make stdout/stderr UTF-8 on Windows so Unicode output can't crash.

    On a Windows console (CI included) ``sys.stdout`` is a cp1252 TextIOWrapper,
    so Rich writing a glyph like ``⚠`` — which the tool list, the banner and the
    setup wizard all emit — raises ``UnicodeEncodeError`` mid-render and takes the
    whole command down. POSIX is already UTF-8, so this only touches Windows;
    ``errors="backslashreplace"`` keeps an undisplayable glyph from ever raising.
    """
    if os.name != "nt":
        return
    _reconfigure_utf8(sys.stdout)
    _reconfigure_utf8(sys.stderr)


def main() -> None:
    _force_utf8_io()
    args = build_parser().parse_args()

    command = getattr(args, "command", None)

    # `chat` is `--provider cli` under a name people remember. Setting the flag
    # rather than adding a branch means every decision below it — settings
    # loading, _runs_the_bot, the interactive-logging test, the singleton guard —
    # keeps working without knowing the command exists.
    if command == "chat":
        if getattr(args, "provider", None) not in (None, "cli"):
            build_parser().error(
                "`lesysbot chat` is the terminal chat — drop --provider, or use "
                f"`lesysbot --provider {args.provider}` instead."
            )
        args.provider = "cli"

    # Everything that manages LeSysBot rather than *being* LeSysBot — install,
    # search, doctor, dashboard, setup — is handled by lesysbot.cli and exits
    # before any bot setup runs.
    from lesysbot.cli import dispatch, handles

    if handles(command):
        sys.exit(dispatch(args))

    # command is now one of: None (bare), "run", "manage".
    settings = _load_settings(args)

    if command == "manage":
        # Console-only logging (no chat) for the control panel.
        _setup_logging(args.verbose, settings.logging, interactive=True)
        _manage(settings, port=getattr(args, "port", None),
                open_browser=getattr(args, "open", False))
        return

    if not _runs_the_bot(command, args):
        # Bare `lesysbot`: health and metrics, then exit. The control panel is
        # already online — the service serves it — so there's nothing to start.
        _setup_logging(args.verbose, settings.logging, interactive=True)
        _print_status(settings)
        return

    service = command == "run"
    _setup_logging(
        args.verbose,
        settings.logging,
        interactive=(settings.messaging.provider == "cli" and not service),
    )

    # Single-instance guard. The service always takes it — it owns the control
    # panel's port whatever the provider — and so does any remote-provider bot,
    # since a second copy would fight over the same updates (Telegram answers
    # 409 Conflict to both). A foreground CLI chat doesn't poll and may run
    # alongside the service freely.
    if service or settings.messaging.provider != "cli":
        from lesysbot.core.singleton import acquire_instance_lock, holder_pid, instance_key

        key = instance_key(settings)
        if not acquire_instance_lock(key):
            pid = holder_pid(key)
            who = f" (PID {pid})" if pid else ""
            print(
                f"Another LeSysBot instance for this {settings.messaging.provider} "
                f"configuration is already running{who} — most likely the background "
                "service.\nStop it first (Linux: systemctl --user stop lesysbot; "
                "macOS: launchctl stop com.lesysbot.lesysbot; Windows: Task Scheduler), "
                "or use `lesysbot chat` for an interactive session, "
                "which runs fine alongside the service.",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        asyncio.run(_run(settings, serve_ui=service))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
