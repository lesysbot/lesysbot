"""``lesysbot dashboard …`` — render installed dashboards and drive the stack.

``render`` resolves each installed dashboard package against this host and this
Prometheus, then writes the JSON Grafana provisions. A dashboard whose metrics
aren't being scraped is deliberately **not** written: a panel querying a series
nobody collects renders empty, and an empty panel is indistinguishable from a
broken one — which is the exact ambiguity this whole design exists to remove.
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
                            help="Render installed dashboards for Grafana")
    render.add_argument("names", nargs="*", metavar="NAME")
    render.add_argument("--force", action="store_true",
                        help="Render even when required metrics are missing")

    sub.add_parser("list", parents=[common], help="Installed dashboards and their state")
    sub.add_parser("start", parents=[common], help="Start the Grafana/Prometheus stack")
    sub.add_parser("stop", parents=[common], help="Stop the Grafana/Prometheus stack")


def run(args: argparse.Namespace) -> int:
    ctx = CLIContext.load(args)
    return {
        "render": _render, "list": _list, "start": _start, "stop": _stop,
    }[args.dashboard_cmd](ctx, args)


def _render(ctx: CLIContext, args: argparse.Namespace) -> int:
    from lesysbot.dashboards.render import render_all

    results = render_all(ctx, names=args.names or None, force=args.force)
    if not results:
        ctx.console.print(
            "No dashboards installed. Find one with `lesysbot search --kind dashboard`."
        )
        return 0

    for result in results:
        if result.written:
            ctx.console.print(f"[green]✔[/green] {result.name} → {result.path}")
        else:
            ctx.console.print(f"[yellow]○[/yellow] {result.name} — {result.reason}")

    provisioned = sum(1 for r in results if r.written)
    ctx.console.print(
        f"\n{provisioned}/{len(results)} provisioned. "
        "[dim]Grafana picks changes up within 30s.[/dim]"
    )
    return 0


def _list(ctx: CLIContext, _args) -> int:
    from lesysbot.dashboards.render import describe_all

    rows = describe_all(ctx)
    if not rows:
        ctx.console.print("No dashboards installed.")
        return 0
    table = Table(box=None, pad_edge=False)
    for col in ("name", "state", "provisioned", "description"):
        table.add_column(col)
    for row in rows:
        state = "[green]ready[/green]" if row["ok"] else f"[yellow]{row['reason']}[/yellow]"
        table.add_row(row["name"], state,
                      "yes" if row["provisioned"] else "[dim]no[/dim]",
                      row["description"])
    ctx.console.print(table)
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
