"""``lesysbot install|update|remove|list|info|enable|disable`` — the whole lifecycle.

A tool is a folder, so ``install`` takes one: a path to a folder (or a ``.zip``)
on this machine, or a GitHub link to fetch one from. **Anything on disk wins** —
if the argument names a real path, that is what gets installed, because pointing
at a real thing is never the ambiguous case. A bare word that is neither a path
nor a GitHub link gets a usage error rather than a guess, since guessing at what
to download is the one place this must not be clever.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from rich.table import Table

from lesysbot.artifacts.errors import ToolInstallError
from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.cli.context import CLIContext, config_parent


def register(subparsers: argparse._SubParsersAction) -> None:
    common = config_parent()

    install = subparsers.add_parser(
        "install", parents=[common],
        help="Add a tool from a folder, a .zip, or GitHub",
    )
    install.add_argument("source", help="a path to a folder or .zip on this machine, "
                                        "or owner/repo[/subdir][@ref] / a github.com URL")
    install.add_argument("--ref", default=None, help="Branch, tag, or commit SHA")
    install.add_argument("--only", action="append", default=None, metavar="NAME",
                         help="Install only this package from a multi-package repo")
    install.add_argument("--force", action="store_true",
                         help="Overwrite a directory lesysbot didn't install")
    install.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    install.add_argument("--no-deps", action="store_true",
                         help="Don't install the package's Python dependencies")

    update = subparsers.add_parser(
        "update", parents=[common],
        help="Re-download installed tools",
    )
    update.add_argument("names", nargs="*", metavar="NAME",
                        help="Which to update (default: everything)")
    update.add_argument("--check", action="store_true",
                        help="Report what would change; write nothing")
    update.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    listing = subparsers.add_parser("list", parents=[common],
                                    help="List installed tools")
    listing.add_argument("--json", action="store_true", dest="as_json")

    info = subparsers.add_parser("info", parents=[common], help="Show details for a tool")
    info.add_argument("name")

    remove = subparsers.add_parser("remove", parents=[common],
                                   help="Delete a tool")
    remove.add_argument("name")
    remove.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    enable = subparsers.add_parser("enable", parents=[common], help="Turn a tool back on")
    enable.add_argument("name")
    disable = subparsers.add_parser(
        "disable", parents=[common],
        help="Turn a tool off")
    disable.add_argument("name")


# -- dispatch ------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    ctx = CLIContext.load(args)
    handlers = {
        "install": _install, "update": _update, "list": _list, "info": _info,
        "remove": _remove, "enable": _enable, "disable": _disable,
    }
    try:
        return handlers[args.command](ctx, args)
    except _Reported:
        return 1
    except ToolInstallError as e:
        return ctx.error(str(e))


# -- install -------------------------------------------------------------------

def _looks_like_github(source: str) -> bool:
    return "/" in source or "://" in source or source.startswith("git@")


def _unusable_source(ctx: CLIContext, source: str) -> _Reported:
    """Report a source that is neither a path on disk nor a GitHub link.

    Printed here rather than raised, because the usage lines contain
    `[/subdir]` — which Rich's markup parser reads as a closing tag and then
    raises MarkupError on, turning a helpful message into a crash.
    """
    ctx.console.print(
        f"[red]Error:[/red] {source!r} is neither a path on this machine "
        "nor a GitHub link."
    )
    ctx.console.print(
        "    lesysbot install ./my-tool                 a folder (or a .zip)\n"
        "    lesysbot install owner/repo[/subdir][@ref]\n"
        "    lesysbot install https://github.com/owner/repo",
        markup=False,
    )
    return _Reported()


class _Reported(ToolInstallError):
    """Raised after the message has already been printed, to unwind to exit 1.

    Exists so a multi-line usage block can be printed with markup disabled
    without also having to thread a return code back up through the call.
    """

    def __str__(self) -> str:                # pragma: no cover - never displayed
        return ""


def _install(ctx: CLIContext, args: argparse.Namespace) -> int:
    """Install from a local path if there is one, else from GitHub.

    Disk is checked first and wins outright: a bare word is not a valid GitHub
    spec anyway, so the only way both could match is a relative path that also
    reads as `owner/repo` — and there, the folder the user can actually see is
    the better answer.
    """
    from lesysbot.artifacts.spec import parse_source

    common = dict(
        only=args.only,
        force=args.force,
        yes=args.yes,
        install_deps=not args.no_deps,
    )

    local = Path(args.source).expanduser()
    if local.exists():
        if args.ref:
            return ctx.error("--ref applies to a GitHub source, not a local path")
        result = ctx.installer().install_path(local, **common)
    else:
        if not _looks_like_github(args.source):
            raise _unusable_source(ctx, args.source)
        src = parse_source(args.source)
        if args.ref:
            src = replace(src, ref=args.ref)
        result = ctx.installer().install(src, **common)
    return 0 if result or not result.skipped else 1


# -- update --------------------------------------------------------------------

def _update(ctx: CLIContext, args: argparse.Namespace) -> int:
    """Re-fetch each recorded package at the ref it was installed from.

    Re-install already *is* update — the installer replaces anything the lock
    knows about — so this only has to decide *what* to re-fetch and report what
    moved. `--check` stops before writing anything.
    """
    from lesysbot.artifacts.spec import parse_source

    entries = ctx.lock.load()
    if not entries and not args.names:
        ctx.console.print("Nothing installed yet — `lesysbot install owner/repo`.")
        return 0

    # Named packages are validated even when the lock is empty: `update nope`
    # asked about a specific thing, and answering "nothing is installed" would
    # let a typo look like success.
    wanted = _select_for_update(ctx, entries, args.names)
    if wanted is None:
        return 1
    if not wanted:
        ctx.console.print("Nothing to update.")
        return 0

    if args.check:
        return _report_update_check(ctx, wanted)

    installer = ctx.installer()
    changed, failed = [], []
    for key, entry in wanted.items():
        name, before = entry.get("name", key), entry.get("commit")
        spec = entry["repo"] + (f"/{entry['subdir']}" if entry.get("subdir") else "")
        if entry.get("requested_ref"):
            spec += f"@{entry['requested_ref']}"
        try:
            src = parse_source(spec)
            installer.install(src, only=[name], yes=True, force=True)
        except ToolInstallError as e:
            ctx.console.print(f"[red]![/red] {name}: {e}")
            failed.append(name)
            continue
        after = (ctx.lock.get(entry.get("kind", "tool"), name) or {}).get("commit")
        if after != before:
            changed.append(f"{name} {(before or '?')[:7]} → {(after or '?')[:7]}")

    if changed:
        ctx.console.print(f"\n[green]Updated:[/green] {', '.join(changed)}")
    else:
        ctx.console.print("\nEverything is already current.")
    return 1 if failed else 0


def _select_for_update(ctx: CLIContext, entries: dict, names: list[str]) -> dict | None:
    """Entries to update, honouring bare names given on the command line."""
    # Only kinds this version installs: an older lock may still name dashboards.
    updatable = {k: e for k, e in entries.items()
                 if e.get("repo") and e.get("kind", "tool") == ArtifactKind.TOOL.value}
    if not names:
        return updatable
    chosen, missing = {}, []
    for name in names:
        matches = {k: e for k, e in updatable.items()
                   if (e.get("name") or k.split(":", 1)[-1]) == name}
        if matches:
            chosen.update(matches)
        else:
            missing.append(name)
    if missing:
        ctx.error(f"not installed from a repo: {', '.join(missing)}")
        return None
    return chosen


def _report_update_check(ctx: CLIContext, wanted: dict) -> int:
    """What `--check` prints. Deliberately writes nothing and fetches nothing."""
    table = Table(box=None, pad_edge=False)
    for col in ("name", "origin", "pinned", "installed"):
        table.add_column(col)
    for key, entry in sorted(wanted.items()):
        table.add_row(
            entry.get("name", key.split(":", 1)[-1]),
            entry.get("repo", "?"),
            entry.get("requested_ref") or "HEAD",
            (entry.get("commit") or "?")[:7],
        )
    ctx.console.print(table)
    ctx.console.print(
        f"\n[dim]{len(wanted)} package(s) would be re-fetched. "
        "Run `lesysbot update` to apply.[/dim]"
    )
    return 0


# -- list / info ---------------------------------------------------------------

def _rows(ctx: CLIContext) -> list[dict]:
    """Installed tools, joining live tool status with lock provenance."""
    lock = ctx.lock.load()
    rows: list[dict] = []
    for row in ctx.registry().tool_status():
        src = row.get("source")
        unit = src["unit"] if src else None
        entry = lock.get(f"tool:{unit}") if unit else None
        rows.append({**row, "kind": "tool", "unit": unit,
                     "origin": _origin(entry), "version": (entry or {}).get("version")})
    return rows


def _origin(entry: dict | None) -> str:
    # No entry means a folder someone copied in by hand; a `path` entry means
    # `lesysbot install <path>` did the copying. Both are local.
    if not entry:
        return "local"
    if entry.get("bundled"):
        return "bundled"
    if not entry.get("repo"):
        return "local"
    origin = entry["repo"]
    if entry.get("commit"):
        origin += f"@{entry['commit'][:7]}"
    return origin


def _list(ctx: CLIContext, args: argparse.Namespace) -> int:
    rows = _rows(ctx)
    if args.as_json:
        ctx.console.print_json(json.dumps(rows))
        return 0
    if not rows:
        ctx.console.print(
            "Nothing installed. Add a tool with `lesysbot install <folder>`, "
            "or `lesysbot install owner/repo`."
        )
        return 0
    table = Table(box=None, pad_edge=False)
    for col in ("name", "status", "origin", "description"):
        table.add_column(col)
    for row in rows:
        if not row["enabled"]:
            status = "[red]disabled[/red]"
        elif not row["available"]:
            status = f"[yellow]⚠ {row['unavailable_reason']}[/yellow]"
        else:
            status = "[green]ok[/green]"
        origin = row["origin"]
        table.add_row(row["name"], status,
                      origin if origin not in ("local", "bundled") else f"[dim]{origin}[/dim]",
                      row.get("description") or "")
    ctx.console.print(table)
    return 0


def _info(ctx: CLIContext, args: argparse.Namespace) -> int:
    row = next((r for r in _rows(ctx) if r["name"] == args.name), None)
    if row is None:
        return _missing(ctx, args.name)
    entry = ctx.lock.get(row["kind"], row.get("unit") or row["name"]) or {}
    pairs = [
        ("name", row["name"]),
        ("description", row.get("description")),
        ("version", entry.get("version")),
        ("enabled", row.get("enabled")),
        ("available", True if row["available"] else f"no — {row['unavailable_reason']}"),
        ("requires", ", ".join(row.get("requires") or []) or None),
        ("installed from", entry.get("repo") or entry.get("path")),
        ("commit", entry.get("commit")),
        ("installed at", entry.get("installed_at")),
        ("updated at", entry.get("updated_at")),
        ("python deps", ", ".join(entry.get("deps") or []) or None),
    ]
    for key, value in pairs:
        if value not in (None, ""):
            ctx.console.print(f"[bold]{key}:[/bold] {value}")
    return 0


def _missing(ctx: CLIContext, name: str) -> int:
    return ctx.error(f"nothing installed called {name!r} (see `lesysbot list`)")


# -- remove --------------------------------------------------------------------

def _confirm(message: str) -> bool:
    from rich.prompt import Confirm

    try:
        return Confirm.ask(message, default=False)
    except EOFError:
        return False


def _remove(ctx: CLIContext, args: argparse.Namespace) -> int:
    from lesysbot.artifacts.lockfile import drop_entries

    row = next((r for r in _rows(ctx) if r["name"] == args.name), None)
    if row is None:
        return _missing(ctx, args.name)

    registry = ctx.registry()
    info = registry.tool_source(args.name)
    if info is None:
        return ctx.error(
            f"{args.name!r} wasn't loaded from the tools directory, so it can't "
            "be removed here."
        )
    ctx.console.print(f"[bold]{info['unit']}[/bold] ({info['kind']}) — {info['path']}")
    ctx.console.print(f"  tools: {', '.join('/' + t for t in info['tools'])}")
    if not args.yes and not _confirm(f"Permanently delete {info['path']}?"):
        ctx.console.print("Aborted.")
        return 0
    try:
        registry.remove_tool(args.name)
    except (ValueError, OSError) as e:
        return ctx.error(str(e))
    if info["kind"] == "package":
        drop_entries(ctx.lock_path, [info["unit"]], ArtifactKind.TOOL)
    ctx.console.print(f"[green]✔[/green] Removed {', '.join('/' + t for t in info['tools'])}")
    ctx.console.print(
        "[dim]A running LeSysBot with hot_reload drops it automatically; "
        "otherwise restart.[/dim]"
    )
    return 0


# -- enable / disable ----------------------------------------------------------

def _set_enabled(ctx: CLIContext, name: str, enabled: bool) -> int:
    if not ctx.settings.mcp.state_file:
        return ctx.error(
            "mcp.state_file is null in the config — there is nowhere to persist state."
        )
    registry = ctx.registry()
    if registry.get_tool_meta(name) is None:
        return _missing(ctx, name)
    registry.set_enabled(name, enabled)
    ctx.console.print(f"[green]✔[/green] {name} {'enabled' if enabled else 'disabled'}")
    ctx.console.print(
        "[dim]A running LeSysBot watches the state file, so this applies within "
        "a second — no restart needed.[/dim]"
    )
    return 0


def _enable(ctx: CLIContext, args: argparse.Namespace) -> int:
    return _set_enabled(ctx, args.name, True)


def _disable(ctx: CLIContext, args: argparse.Namespace) -> int:
    return _set_enabled(ctx, args.name, False)

