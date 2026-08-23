"""``lesysbot doctor`` — what's wrong with this machine, and how to fix it.

The answer to "why isn't this working?" in one screen. Everything red carries a
command you can run; nothing here needs root, and where a fix genuinely does,
it says so instead of pretending otherwise.
"""

from __future__ import annotations

import argparse
import json

from rich.table import Table

from lesysbot.cli.context import CLIContext, config_parent


def register(subparsers: argparse._SubParsersAction) -> None:
    doctor = subparsers.add_parser(
        "doctor", parents=[config_parent()],
        help="Check this machine and every installed package for problems",
    )
    doctor.add_argument("name", nargs="?",
                        help="Check just this package (default: everything)")
    doctor.add_argument("--json", action="store_true", dest="as_json")


def run(args: argparse.Namespace) -> int:
    ctx = CLIContext.load(args)
    reports = _gather(ctx, args.name)

    if args.as_json:
        ctx.console.print_json(json.dumps([_as_dict(r) for r in reports]))
        return 0 if all(r.ok for r in reports) else 1

    for report in reports:
        _render(ctx, report)

    blocked = [r for r in reports if not r.ok]
    ctx.console.print()
    if blocked:
        names = ", ".join(r.name for r in blocked)
        ctx.console.print(f"[yellow]{len(blocked)} needs attention:[/yellow] {names}")
    else:
        ctx.console.print("[green]Everything checks out.[/green]")
    return 1 if blocked else 0


def _gather(ctx: CLIContext, only: str | None):
    from lesysbot.prereq import check_host, check_package

    reports = []
    if not only:
        reports.append(check_host())
        invariant = _dashboard_invariant(ctx)
        if invariant is not None:
            reports.append(invariant)
    for pkg in _installed_packages(ctx):
        if only and pkg.name != only:
            continue
        report = check_package(pkg)
        if report is not None:
            reports.append(report)
    return reports


def _dashboard_invariant(ctx: CLIContext):
    """Report a second installed dashboard; ``None`` when the rule holds.

    An install has exactly one dashboard, and the installer enforces it — but a
    home that predates the rule, or a folder copied in by hand, can still carry
    two. Grafana then shows a page nobody chose beside the real one, which is
    hard to diagnose from the Grafana end. Reported only when violated: a green
    row on every run would be noise, and ``lesysbot dashboard current`` already
    answers "what have I got".
    """
    from lesysbot.artifacts.kinds import ArtifactKind
    from lesysbot.prereq.report import Report, Requirement, Result

    names = [pkg.name for pkg in _installed_packages(ctx)
             if pkg.kind is ArtifactKind.DASHBOARD]
    if len(names) < 2:
        return None
    return Report(name="dashboard", results=[Result(
        requirement=Requirement("dashboard", "exactly one installed"),
        satisfied=False,
        detail=f"{len(names)} installed: {', '.join(names)}",
        fix="lesysbot dashboard reset  (or remove the ones you don't want)",
    )])


def _installed_packages(ctx: CLIContext):
    """Read installed packages off disk, without importing their code."""
    from lesysbot.artifacts.manifest import _package_from

    for directory in (ctx.tools_dir, ctx.dashboards_dir):
        if not directory.is_dir():
            continue
        for sub in sorted(directory.iterdir()):
            if sub.is_dir() and not sub.name.startswith((".", "_")):
                yield _package_from(sub, sub.name)


def _render(ctx: CLIContext, report) -> None:
    ctx.console.print(f"\n[bold]{report.name}[/bold]")
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_column()
    for result in report.results:
        if result.satisfied:
            state = "[green]ok[/green]"
        elif result.requirement.optional:
            state = "[dim]not available[/dim]"
        else:
            state = "[red]missing[/red]"
        note = result.detail
        if not result.satisfied and result.fix:
            note = f"{note}\n[cyan]→ {result.fix}[/cyan]" if note else f"[cyan]→ {result.fix}[/cyan]"
        table.add_row(str(result.requirement), state, note)
    ctx.console.print(table)


def _as_dict(report) -> dict:
    return {
        "name": report.name,
        "ok": report.ok,
        "results": [
            {
                "type": r.requirement.type,
                "value": r.requirement.value,
                "optional": r.requirement.optional,
                "satisfied": r.satisfied,
                "detail": r.detail,
                "fix": r.fix,
                "auto_fixable": r.auto_fixable,
            }
            for r in report.results
        ],
    }
