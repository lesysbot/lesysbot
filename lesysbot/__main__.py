from __future__ import annotations

import argparse
import asyncio
import logging
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


async def _run(settings: Settings) -> None:
    agent = Agent(settings)
    await agent.setup()

    provider = settings.messaging.provider

    # Adapters are imported lazily so a missing optional dependency only affects
    # the provider that needs it. Report that as one actionable line rather than
    # an ImportError traceback — for a background service it is the only clue
    # the user gets (`slack-bolt` ships without aiohttp, for instance).
    try:
        if provider == "cli":
            from lesysbot.messaging.cli import CLIAdapter
            adapter = CLIAdapter()

        elif provider == "telegram":
            from lesysbot.messaging.telegram import TelegramAdapter
            adapter = TelegramAdapter(settings.messaging.telegram)

        elif provider == "slack":
            from lesysbot.messaging.slack import SlackAdapter
            adapter = SlackAdapter(settings.messaging.slack)

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
        # Close the LLM's httpx client here, while the loop is still open.
        await agent.aclose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lesysbot", description="LeSysBot — local LLM + tools bot")
    parser.add_argument("-c", "--config", default=None, help="Path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--provider",
        choices=["cli", "telegram", "slack"],
        default=None,
        help="Override messaging provider",
    )
    parser.add_argument("--model", default=None, help="Override LLM model name")
    parser.add_argument("--base-url", default=None, help="Override LLM base URL")

    # Subcommands. Bare `lesysbot` in a terminal opens the management UI; the
    # background service runs `lesysbot run`; `lesysbot --provider …` runs the bot.
    from lesysbot.mcp.cli import register_subcommands
    from lesysbot.setup.cli import register_subcommand as register_setup

    subparsers = parser.add_subparsers(dest="command", metavar="{run,manage,tools,setup}")
    # Re-add -c on each leaf (SUPPRESS default) so a root-level -c isn't clobbered
    # and `lesysbot manage -c …` works regardless of flag order — same pattern as
    # the `tools` subcommands.
    run = subparsers.add_parser("run", help="Run the bot (what the background service uses)")
    run.add_argument("-c", "--config", default=argparse.SUPPRESS, help="Path to config.yaml")
    manage = subparsers.add_parser(
        "manage", help="Open the local management UI (config + tools; localhost only)"
    )
    manage.add_argument("-c", "--config", default=argparse.SUPPRESS, help="Path to config.yaml")
    manage.add_argument("--port", type=int, default=None, help="Management UI port")
    manage.add_argument("--open", action="store_true", help="Open the UI in a browser")
    register_subcommands(subparsers)
    register_setup(subparsers)
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
    from lesysbot.core.redact import register_settings_secrets

    resolve_paths(settings)          # anchor tools/log/state paths to the config dir
    register_settings_secrets(settings)   # redact creds before any handler exists
    return settings


def _print_status(settings: Settings) -> None:
    """The status screen shown by bare `lesysbot` / `lesysbot manage`."""
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
    if dm:
        service = f"[green]running[/green] (PID {dm['pid']})" if dm.get("running") else "[dim]stopped[/dim]"
    else:
        service = "[dim]CLI provider (on demand)[/dim]"

    t = Table(show_header=False, box=None, pad_edge=False)
    t.add_column(style="dim", justify="right")
    t.add_column()
    t.add_row("LLM backend", backend)
    t.add_row("Backend URL", st["base_url"])
    t.add_row("Provider", f"{st['provider']} · model [bold]{st['model']}[/bold]")
    tools = st["tools"]
    unavail = f" · {tools['unavailable']} unavailable here" if tools["unavailable"] else ""
    t.add_row("Tools", f"{tools['enabled']}/{tools['total']} enabled{unavail}")
    t.add_row("Bot service", service)
    gf = st.get("grafana")
    if gf:
        ver = f" · v{gf['version']}" if gf.get("version") else ""
        t.add_row("Grafana", f"[link={gf['url']}]{gf['url']}[/link]{ver}")
    else:
        t.add_row("Grafana", "[dim]not running — start it with monitoring/scripts/start.sh[/dim]")
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
    # hand the already-built registry to the server so tools aren't imported twice
    _print_status.registry = registry  # type: ignore[attr-defined]


def _manage(settings: Settings, port: int | None, open_browser: bool) -> None:
    _print_status(settings)
    from lesysbot.webui.server import serve

    serve(settings, registry=getattr(_print_status, "registry", None),
          port=port, open_browser=open_browser)


def _wants_management_ui(command, args) -> bool:
    """Bare `lesysbot` opens the management UI **only** when a human is at a
    terminal and hasn't asked to run the bot. A non-interactive invocation (the
    background service, a pipe) keeps the old behaviour and runs the bot, so
    existing services that call bare `lesysbot` are unaffected."""
    if command == "manage":
        return True
    if command == "run":
        return False
    # bare (no subcommand): an explicit --provider means "run the bot"
    if getattr(args, "provider", None):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def main() -> None:
    args = build_parser().parse_args()

    command = getattr(args, "command", None)
    if command == "setup":
        from lesysbot.setup.cli import run as run_setup

        sys.exit(run_setup(args))
    if command in ("tools", "tool"):
        from lesysbot.mcp.cli import run as run_tool_cli

        sys.exit(run_tool_cli(args))

    # command is now one of: None (bare), "run", "manage".
    settings = _load_settings(args)

    if _wants_management_ui(command, args):
        # Console-only logging (no chat) for the control panel.
        _setup_logging(args.verbose, settings.logging, interactive=True)
        _manage(settings, port=getattr(args, "port", None),
                open_browser=getattr(args, "open", False))
        return

    _setup_logging(
        args.verbose,
        settings.logging,
        interactive=(settings.messaging.provider == "cli"),
    )

    # Single-instance guard for remote providers: a second copy of the same bot
    # would fight over the same updates (Telegram answers 409 Conflict to
    # both). CLI sessions don't poll and may run alongside a service freely.
    if settings.messaging.provider != "cli":
        from lesysbot.core.singleton import acquire_instance_lock, holder_pid, instance_key

        key = instance_key(settings)
        if not acquire_instance_lock(key):
            pid = holder_pid(key)
            who = f" (PID {pid})" if pid else ""
            print(
                f"Another LeSysBot instance for this {settings.messaging.provider} bot "
                f"is already running{who} — most likely the background service.\n"
                "Stop it first (Linux: systemctl --user stop lesysbot; "
                "macOS: launchctl stop com.lesysbot.lesysbot; Windows: Task Scheduler), "
                "or use `lesysbot --provider cli` for an interactive session, "
                "which runs fine alongside the service.",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
