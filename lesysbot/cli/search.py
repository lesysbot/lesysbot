"""``lesysbot search`` — browse the marketplace from the terminal.

Defaults to showing only what runs on this machine, because a list padded with
packages for hardware this host doesn't have is a list you stop reading.
``--all`` opts out.
"""

from __future__ import annotations

import argparse

from rich.table import Table

from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.cli.context import CLIContext, config_parent


def register(subparsers: argparse._SubParsersAction) -> None:
    search = subparsers.add_parser(
        "search", parents=[config_parent()],
        help="Find tools and dashboards you can install",
    )
    search.add_argument("query", nargs="?", default="",
                        help="Match against name, description, and tags")
    search.add_argument("--kind", choices=[k.value for k in ArtifactKind], default=None)
    search.add_argument("--all", action="store_true", dest="show_all",
                        help="Include entries that don't run on this machine")
    search.add_argument("--refresh", action="store_true",
                        help="Fetch the latest catalog before searching")


def run(args: argparse.Namespace) -> int:
    from lesysbot.artifacts.catalog import load_catalog, refresh

    ctx = CLIContext.load(args)

    if args.refresh:
        catalog, error = refresh()
        if error:
            # Being offline degrades discovery; it must not break it.
            ctx.console.print(f"[yellow]![/yellow] {error} — using the cached copy.")
    else:
        catalog = load_catalog()

    if not catalog.entries:
        ctx.console.print(
            "No marketplace catalog available.\n"
            "  Try `lesysbot search --refresh`, or install directly:\n"
            "    lesysbot install owner/repo"
        )
        return 0

    results = catalog.search(args.query, kind=args.kind, here_only=not args.show_all)
    if not results:
        hidden = len(catalog.search(args.query, kind=args.kind)) - len(results)
        ctx.console.print(f"Nothing matches {args.query!r}.")
        if hidden > 0:
            ctx.console.print(
                f"[dim]{hidden} entr{'y' if hidden == 1 else 'ies'} matched but "
                "don't run on this machine — `--all` to see them.[/dim]"
            )
        return 0

    table = Table(box=None, pad_edge=False)
    for col in ("id", "kind", "", "description"):
        table.add_column(col)
    for entry in results:
        badge = "[cyan]official[/cyan]" if entry.official else ""
        if not entry.runs_here():
            badge = "[dim]other OS[/dim]"
        table.add_row(entry.id, entry.kind.value, badge, entry.description)
    ctx.console.print(table)
    ctx.console.print(f"\n[dim]Install one with:  lesysbot install {results[0].id}[/dim]")
    return 0
