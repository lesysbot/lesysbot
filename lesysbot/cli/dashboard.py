"""``lesysbot dashboard …`` — render the installed dashboard and drive the stack.

``render`` resolves the installed dashboard package against this host and this
Prometheus, then writes the JSON Grafana provisions. A dashboard whose metrics
aren't being scraped is deliberately **not** written: a panel querying a series
nobody collects renders empty, and an empty panel is indistinguishable from a
broken one — which is the exact ambiguity this whole design exists to remove.

There is one dashboard per install, so ``render`` takes no names. Changing it is
``lesysbot install owner/repo``, which replaces it; ``reset`` puts the bundled
default back.
"""

from __future__ import annotations

import argparse

from rich.table import Table

from lesysbot.cli.context import CLIContext, config_parent


def register(subparsers: argparse._SubParsersAction) -> None:
    common = config_parent()
    dashboard = subparsers.add_parser(
        "dashboard", help="Render dashboards and start/stop the Grafana stack",
    )
    sub = dashboard.add_subparsers(dest="dashboard_cmd", metavar="action", required=True)

    render = sub.add_parser("render", parents=[common],
                            help="Render the installed dashboard for Grafana")
    render.add_argument("--force", action="store_true",
                        help="Render even when required metrics are missing")

    sub.add_parser("current", parents=[common],
                   help="Which dashboard is installed, and its state")
    sub.add_parser("list", parents=[common], help="Alias for `current`")
    sub.add_parser("reset", parents=[common],
                   help="Restore the default dashboard that ships with LeSysBot")
    sub.add_parser("start", parents=[common], help="Start the Grafana/Prometheus stack")
    sub.add_parser("stop", parents=[common], help="Stop the Grafana/Prometheus stack")


def run(args: argparse.Namespace) -> int:
    ctx = CLIContext.load(args)
    return {
        "render": _render, "current": _current, "list": _current,
        "reset": _reset, "start": _start, "stop": _stop,
    }[args.dashboard_cmd](ctx, args)


def _no_dashboard(ctx: CLIContext) -> None:
    ctx.console.print(
        "No dashboard installed. `lesysbot dashboard reset` restores the default, "
        "or install one with `lesysbot install owner/repo`."
    )


def _render(ctx: CLIContext, args: argparse.Namespace) -> int:
    from lesysbot.dashboards.render import render_all

    results = render_all(ctx, force=args.force)
    if not results:
        _no_dashboard(ctx)
        return 0

    result = results[0]
    if result.written:
        ctx.console.print(f"[green]✔[/green] {result.name} → {result.path}")
        ctx.console.print("\n[dim]Grafana picks changes up within 30s.[/dim]")
        return 0

    ctx.console.print(f"[yellow]○[/yellow] {result.name} — {result.reason}")
    ctx.console.print(
        "\n[dim]Withheld, not broken: a panel querying a metric nothing collects "
        "looks exactly like a broken one. `lesysbot doctor` has the fix.[/dim]"
    )
    return 0


def _current(ctx: CLIContext, _args) -> int:
    from lesysbot.dashboards.render import describe_all

    rows = describe_all(ctx)
    if not rows:
        _no_dashboard(ctx)
        return 0

    lock = ctx.lock
    table = Table(box=None, pad_edge=False)
    for col in ("name", "from", "state", "in grafana", "description"):
        table.add_column(col)
    for row in rows:
        entry = lock.get("dashboard", row["name"]) or {}
        origin = "bundled" if entry.get("bundled") else (entry.get("repo") or "[dim]—[/dim]")
        state = "[green]ready[/green]" if row["ok"] else f"[yellow]{row['reason']}[/yellow]"
        table.add_row(row["name"], origin, state,
                      "yes" if row["provisioned"] else "[dim]no[/dim]",
                      row["description"])
    ctx.console.print(table)

    if len(rows) > 1:
        # The singleton rule is broken — say so here rather than only in doctor,
        # because this is the command someone runs when Grafana shows two pages.
        ctx.console.print(
            f"\n[yellow]![/yellow] {len(rows)} dashboards installed but LeSysBot "
            "uses one — `lesysbot doctor` explains, `lesysbot dashboard reset` fixes it."
        )
    return 0


def _reset(ctx: CLIContext, _args) -> int:
    from lesysbot.dashboards.render import render_all
    from lesysbot.setup.apply import reset_dashboard

    if not reset_dashboard(None, ctx.data_dir):
        return ctx.error(
            "no bundled dashboard to restore — reinstall LeSysBot, or install one "
            "with `lesysbot install owner/repo`."
        )
    ctx.console.print("[green]✔[/green] Restored the default dashboard.")
    for result in render_all(ctx):
        if not result.written:
            ctx.console.print(f"[yellow]○[/yellow] {result.name} — {result.reason}")
    return 0


def _stack_script(ctx: CLIContext, action: str) -> int:
    """Run the stack's own start/stop script — the same one setup uses."""
    import subprocess
    import sys

    from lesysbot.core.paths import dashboard_dir

    stack = dashboard_dir(ctx.settings.config_dir)
    script = stack / "scripts" / ("start.ps1" if sys.platform == "win32" else "start.sh")
    if not script.is_file():
        return ctx.error(
            f"no dashboard stack at {stack} — run `lesysbot setup` to install it."
        )
    cmd = (["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)]
           if sys.platform == "win32" else ["bash", str(script)])
    return subprocess.run([*cmd, action], cwd=str(stack)).returncode


def _start(ctx: CLIContext, _args) -> int:
    return _stack_script(ctx, "up")


def _stop(ctx: CLIContext, _args) -> int:
    return _stack_script(ctx, "down")
