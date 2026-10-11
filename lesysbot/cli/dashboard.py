"""``lesysbot dashboard …`` — the one Grafana dashboard, and the stack behind it.

There is one dashboard. By default it is generated for this machine every time
the stack starts, so it only has panels the hardware can fill. A user who wants
to change it runs ``customize``: that saves a copy to ``dashboard.json`` in the
stack directory, which is then used as-is instead of the generated one — and
``reset`` goes back. Keeping the user's version in its own file is what lets an
edit survive an upgrade: the generated dashboard is rewritten on every start,
the user's file never is.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from lesysbot.cli.context import CLIContext, config_parent


def register(subparsers: argparse._SubParsersAction) -> None:
    common = config_parent()
    dashboard = subparsers.add_parser(
        "dashboard", parents=[common],
        help="Start or stop Grafana, and change its dashboard",
    )
    sub = dashboard.add_subparsers(dest="dashboard_cmd", metavar="action")

    start = sub.add_parser("start", parents=[common],
                           help="Start Grafana and Prometheus (also applies dashboard changes)")
    start.add_argument("--grafana-port", metavar="PORT",
                       help="Run Grafana on this port (saved for next time). "
                            "Without it, a taken port is replaced by the next free one.")
    sub.add_parser("stop", parents=[common], help="Stop Grafana and Prometheus")
    sub.add_parser("customize", parents=[common],
                   help="Save a copy of the dashboard you can edit")
    sub.add_parser("reset", parents=[common],
                   help="Go back to the automatic dashboard")


def run(args: argparse.Namespace) -> int:
    ctx = CLIContext.load(args)
    return {
        None: _status, "start": _start, "stop": _stop,
        "customize": _customize, "reset": _reset,
    }[getattr(args, "dashboard_cmd", None)](ctx, args)


def _stack(ctx: CLIContext) -> Path:
    from lesysbot.core.paths import dashboard_dir

    return dashboard_dir(ctx.settings.config_dir)


def _custom(ctx: CLIContext) -> Path:
    from lesysbot.core.paths import custom_dashboard_path

    return custom_dashboard_path(ctx.settings.config_dir)


def _short(path: Path) -> str:
    """*path* with the home directory written as ``~``, so it fits on one line."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _status(ctx: CLIContext, _args) -> int:
    """Bare ``lesysbot dashboard``: where it is, which version, what to do next."""
    from lesysbot.core.grafana import detect_grafana, home_dashboard_url

    base = ctx.settings.config_dir
    gf = detect_grafana(base)
    if gf and gf["reachable"]:
        where = home_dashboard_url(gf["url"], base) or gf["url"]
        ctx.console.print(f"Grafana:    [green]running[/green] — {where}")
    else:
        ctx.console.print("Grafana:    [yellow]not running[/yellow] — "
                          "start it with: lesysbot dashboard start")

    custom = _custom(ctx)
    if custom.is_file():
        ctx.console.print(f"Dashboard:  yours — {_short(custom)}")
        ctx.console.print("\n[dim]Edit that file, then run `lesysbot dashboard start`. "
                          "`lesysbot dashboard reset` goes back to the automatic one.[/dim]")
    else:
        ctx.console.print("Dashboard:  automatic — built for this machine")
        ctx.console.print("\n[dim]Want to change it? Run `lesysbot dashboard customize`.[/dim]")
    return 0


def _customize(ctx: CLIContext, _args) -> int:
    from lesysbot.core.paths import bundled_dir, generated_dashboards_dir

    custom = _custom(ctx)
    if custom.is_file():
        ctx.console.print(f"You already have your own dashboard: {_short(custom)}")
        ctx.console.print("  Edit it, then run:  lesysbot dashboard start")
        return 0

    stack = _stack(ctx)
    if not stack.is_dir():
        return ctx.error(
            f"no dashboard stack at {stack} — run `lesysbot setup` to install it."
        )
    # Start from what Grafana is showing now — the copy generated for this
    # machine — and fall back to the portable one if the stack never started.
    candidates = (
        generated_dashboards_dir(ctx.settings.config_dir) / "system-overview.json",
        stack / "grafana" / "dashboards" / "system-overview.json",
        bundled_dir() / "dashboard" / "grafana" / "dashboards" / "system-overview.json",
    )
    source = next((c for c in candidates if c.is_file()), None)
    if source is None:
        return ctx.error("no dashboard to copy — run `lesysbot dashboard start` first.")

    shutil.copyfile(source, custom)
    ctx.console.print(f"[green]✔[/green] Your dashboard: {_short(custom)}")
    ctx.console.print("  Edit it (or paste a Grafana export into it), then run:")
    ctx.console.print("  lesysbot dashboard start")
    return 0


def _reset(ctx: CLIContext, _args) -> int:
    custom = _custom(ctx)
    if not custom.is_file():
        ctx.console.print("You're already using the automatic dashboard.")
        return 0
    # Kept, not deleted: it may hold hours of someone's edits, and getting it
    # back should be a rename, not a rewrite.
    backup = custom.with_name(custom.name + ".bak")
    custom.replace(backup)
    ctx.console.print("[green]✔[/green] Back to the automatic dashboard.")
    ctx.console.print(f"  Your copy is saved as {_short(backup)}")
    ctx.console.print("  Apply it now:  lesysbot dashboard start")
    return 0


def _stack_script(ctx: CLIContext, action: str, *extra: str) -> int:
    """Run the stack's own start/stop script — the same one setup uses."""
    import subprocess

    stack = _stack(ctx)
    script = stack / "scripts" / "start.sh"
    if not script.is_file():
        return ctx.error(
            f"no dashboard stack at {stack} — run `lesysbot setup` to install it."
        )
    return subprocess.run(["bash", str(script), action, *extra], cwd=str(stack)).returncode


def _start(ctx: CLIContext, args) -> int:
    from lesysbot.core.grafana import sync_saved_url
    from lesysbot.core.paths import user_dir

    extra = ("--grafana-port", args.grafana_port) if args.grafana_port else ()
    rc = _stack_script(ctx, "up", *extra)
    # start.sh may have moved Grafana off a taken port; keep the saved URL true.
    url = sync_saved_url(_stack(ctx), user_dir() / "grafana.env")
    if url:
        ctx.console.print(f"Saved Grafana address updated to {url}")
    return rc


def _stop(ctx: CLIContext, _args) -> int:
    return _stack_script(ctx, "down")
