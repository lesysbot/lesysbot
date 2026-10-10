"""``lesysbot dashboard …`` — render the installed dashboard and drive the stack.

``render`` resolves the installed dashboard package against this host and this
Prometheus, then writes the JSON Grafana provisions. A dashboard whose metrics
aren't being scraped is deliberately **not** written: a panel querying a series
nobody collects renders empty, and an empty panel is indistinguishable from a
broken one — which is the exact ambiguity this whole design exists to remove.

There is one dashboard per install, so ``render`` takes no names. Changing it is
``lesysbot install owner/repo``, which replaces it; ``reset`` puts the bundled
default back.

``new`` is the authoring entry point: it writes a package — README plus payload
— either from a starter or from a Grafana export, and with ``--install`` puts it
straight into the slot and renders it. Before it existed the documented way to
start a dashboard was ``rm -rf ~/.lesysbot/dashboard/installed/*`` followed by
``cp -r``, which is filesystem surgery as step one.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.table import Table

from lesysbot.cli.context import CLIContext, config_parent
from lesysbot.dashboards.scaffold import ScaffoldError


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

    new = sub.add_parser(
        "new", parents=[common],
        help="Create a dashboard package (optionally from a Grafana export)",
    )
    new.add_argument("name", help="Package name, kebab-case (e.g. postgres-health)")
    new.add_argument("--dir", default=".", metavar="PATH",
                     help="Where to create the folder (default: here)")
    new.add_argument("--from-json", metavar="FILE",
                     help="Seed from a Grafana export JSON; `-` reads stdin")
    new.add_argument("--python", action="store_true",
                     help="Write a dashboard.py that adapts per OS, not a dashboard.json")
    new.add_argument("--install", action="store_true",
                     help="Put it in the dashboard slot and render it (replaces the current one)")
    new.add_argument("--description", default="", metavar="TEXT",
                     help="One-line description for the README frontmatter")
    new.add_argument("--force", action="store_true",
                     help="Overwrite an existing folder of that name")

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
        "new": _new, "render": _render, "current": _current, "list": _current,
        "reset": _reset, "start": _start, "stop": _stop,
    }[args.dashboard_cmd](ctx, args)


def _no_dashboard(ctx: CLIContext) -> None:
    ctx.console.print(
        "No dashboard installed. `lesysbot dashboard reset` restores the default, "
        "or install one with `lesysbot install owner/repo`."
    )


def _read_export(ctx: CLIContext, source: str) -> dict:
    """Load a Grafana export from a file or stdin."""
    import json
    import sys

    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as e:
        raise ScaffoldError(f"cannot read {source}: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ScaffoldError(f"{source} is not valid JSON: {e}") from e


def _clear_slot(ctx: CLIContext, keep: str) -> list[str]:
    """Empty the dashboard slot so *keep* becomes the only package in it.

    The singleton rule is enforced on the install path by
    ``ArtifactInstaller._replace_current_dashboard``; scaffolding writes into the
    same slot without going through the installer, so it has to hold the same
    line. The lock entry for *keep* goes too: a scaffolded package came from no
    repo, and leaving a stale entry behind would have `lesysbot update` re-fetch
    over the top of work the user just started.
    """
    from lesysbot.artifacts.kinds import ArtifactKind
    from lesysbot.core.paths import force_rmtree

    slot = ctx.dashboards_dir
    slot.mkdir(parents=True, exist_ok=True)
    replaced = [
        d.name for d in sorted(slot.iterdir())
        if d.is_dir() and not d.name.startswith((".", "_")) and d.name != keep
    ]
    for name in replaced:
        force_rmtree(slot / name)
    ctx.lock.drop([*replaced, keep], ArtifactKind.DASHBOARD)
    return replaced


def _new(ctx: CLIContext, args: argparse.Namespace) -> int:
    from lesysbot.dashboards import scaffold

    try:
        exported = _read_export(ctx, args.from_json) if args.from_json else None

        if args.install:
            if args.dir != ".":
                raise ScaffoldError(
                    "--install writes into the dashboard slot, so --dir does not "
                    "apply. Drop one of them."
                )
            replaced = _clear_slot(ctx, args.name)
            dest = ctx.dashboards_dir
        else:
            replaced = []
            dest = Path(args.dir).expanduser()

        result = scaffold.create(
            args.name, dest, from_json=exported, python=args.python,
            description=args.description, force=args.force,
        )
    except ScaffoldError as e:
        return ctx.error(str(e))

    for name in replaced:
        ctx.console.print(f"  [dim]replaced {name} — an install has one dashboard[/dim]")
    ctx.console.print(
        f"[green]✔[/green] {args.name} → {result.path}"
        f"\n  [dim]README.md + {result.payload}[/dim]"
    )
    for note in result.notes:
        ctx.console.print(f"  [dim]· {note}[/dim]")

    if args.install:
        return _render(ctx, argparse.Namespace(force=False))

    ctx.console.print(
        "\n[dim]Try it:[/dim]  lesysbot dashboard new "
        f"{args.name} --install   [dim](or copy the folder into "
        "~/.lesysbot/dashboard/installed/)[/dim]"
        "\n[dim]Ship it:[/dim] push the folder to GitHub — "
        f"`lesysbot install you/{args.name}` is then all anyone needs."
    )
    return 0


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
