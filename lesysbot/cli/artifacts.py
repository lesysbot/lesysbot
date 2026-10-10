"""``lesysbot install|update|remove|list|info|enable|disable`` — the whole lifecycle.

One command family for tools *and* dashboards. The user does not have to know or
say which they are installing: the package's manifest decides, and each lands in
the directory its kind belongs in. That is the point of

    lesysbot install <github_uri>

being a single verb — a repo holding both installs both, in one step.

Installs are **GitHub links only** (or a catalog id, which resolves to one). A
bare word that is neither gets a usage error rather than a guess, because
guessing at what to download is the one place this must not be clever.
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
        help="Add tools or dashboards from GitHub or `lesysbot search`",
    )
    install.add_argument("source", help="owner/repo[/subdir][@ref], a github.com URL, "
                                        "or a marketplace id from `lesysbot search`")
    install.add_argument("--ref", default=None, help="Branch, tag, or commit SHA")
    install.add_argument("--kind", choices=[k.value for k in ArtifactKind], default=None,
                         help="Install only packages of this kind")
    install.add_argument("--only", action="append", default=None, metavar="NAME",
                         help="Install only this package from a multi-package repo")
    install.add_argument("--force", action="store_true",
                         help="Overwrite a directory lesysbot didn't install")
    install.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    install.add_argument("--no-deps", action="store_true",
                         help="Don't install the package's Python dependencies")

    update = subparsers.add_parser(
        "update", parents=[common],
        help="Re-download installed tools and dashboards",
    )
    update.add_argument("names", nargs="*", metavar="NAME",
                        help="Which to update (default: everything)")
    update.add_argument("--check", action="store_true",
                        help="Report what would change; write nothing")
    update.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    listing = subparsers.add_parser("list", parents=[common],
                                    help="List installed tools and dashboards")
    listing.add_argument("--kind", choices=[k.value for k in ArtifactKind], default=None)
    listing.add_argument("--json", action="store_true", dest="as_json")

    info = subparsers.add_parser("info", parents=[common], help="Show details for a tool or dashboard")
    info.add_argument("name")

    remove = subparsers.add_parser("remove", parents=[common],
                                   help="Delete a tool or dashboard")
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


def _resolve_source(ctx: CLIContext, source: str) -> str:
    """Turn a marketplace id into its GitHub link, or pass a link through.

    The catalog is metadata, never a resolver of its own: whatever it hands back
    goes through the same `parse_source` and the same consent prompt as a link
    typed by hand, so "you can read the repo before you install it" still holds.
    """
    from lesysbot.artifacts.catalog import load_catalog

    if _looks_like_github(source):
        return source
    entry = load_catalog().find(source)
    if entry is None:
        # Printed here rather than raised, because the usage lines contain
        # `[/subdir]` — which Rich's markup parser reads as a closing tag and
        # then raises MarkupError on, turning a helpful message into a crash.
        ctx.console.print(
            f"[red]Error:[/red] {source!r} isn't a GitHub link, and no "
            "marketplace entry matches it."
        )
        ctx.console.print(
            "    lesysbot install owner/repo[/subdir][@ref]\n"
            "    lesysbot install https://github.com/owner/repo\n"
            "    lesysbot search <query>      to find an id",
            markup=False,
        )
        raise _Reported()
    ctx.console.print(f"[dim]{source} → {entry.source}[/dim]")
    return entry.source


class _Reported(ToolInstallError):
    """Raised after the message has already been printed, to unwind to exit 1.

    Exists so a multi-line usage block can be printed with markup disabled
    without also having to thread a return code back up through the call.
    """

    def __str__(self) -> str:                # pragma: no cover - never displayed
        return ""


def _install(ctx: CLIContext, args: argparse.Namespace) -> int:
    from lesysbot.artifacts.spec import parse_source

    src = parse_source(_resolve_source(ctx, args.source))
    if args.ref:
        src = replace(src, ref=args.ref)
    result = ctx.installer().install(
        src,
        only=args.only,
        kind=ArtifactKind(args.kind) if args.kind else None,
        force=args.force,
        yes=args.yes,
        install_deps=not args.no_deps,
    )
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
    updatable = {k: e for k, e in entries.items() if e.get("repo")}
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
    for col in ("name", "kind", "origin", "pinned", "installed"):
        table.add_column(col)
    for key, entry in sorted(wanted.items()):
        table.add_row(
            entry.get("name", key.split(":", 1)[-1]),
            entry.get("kind", "tool"),
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

def _rows(ctx: CLIContext, kind: str | None) -> list[dict]:
    """Installed packages, joining live tool status with lock provenance."""
    lock = ctx.lock.load()
    rows: list[dict] = []

    if kind in (None, ArtifactKind.TOOL.value):
        registry = ctx.registry()
        for row in registry.tool_status():
            src = row.get("source")
            unit = src["unit"] if src else None
            entry = lock.get(f"tool:{unit}") if unit else None
            rows.append({**row, "kind": "tool", "unit": unit,
                         "origin": _origin(entry), "version": (entry or {}).get("version")})

    if kind in (None, ArtifactKind.DASHBOARD.value):
        for name, entry in sorted(ctx.lock.of_kind(ArtifactKind.DASHBOARD).items()):
            installed = ctx.dashboards_dir / name
            rows.append({
                "name": name, "kind": "dashboard",
                "description": entry.get("description", ""),
                "enabled": True, "available": installed.is_dir(),
                "unavailable_reason": "" if installed.is_dir() else "files are missing",
                "unit": name, "origin": _origin(entry), "version": entry.get("version"),
            })
    return rows


def _origin(entry: dict | None) -> str:
    if not entry:
        return "local"
    if entry.get("bundled"):
        return "bundled"
    origin = entry.get("repo", "?")
    if entry.get("commit"):
        origin += f"@{entry['commit'][:7]}"
    return origin


def _list(ctx: CLIContext, args: argparse.Namespace) -> int:
    rows = _rows(ctx, args.kind)
    if args.as_json:
        ctx.console.print_json(json.dumps(rows))
        return 0
    if not rows:
        ctx.console.print(
            "Nothing installed. Find something with `lesysbot search`, "
            "or `lesysbot install owner/repo`."
        )
        return 0
    table = Table(box=None, pad_edge=False)
    for col in ("name", "kind", "status", "origin", "description"):
        table.add_column(col)
    for row in rows:
        if not row["enabled"]:
            status = "[red]disabled[/red]"
        elif not row["available"]:
            status = f"[yellow]⚠ {row['unavailable_reason']}[/yellow]"
        else:
            status = "[green]ok[/green]"
        origin = row["origin"]
        table.add_row(row["name"], row["kind"], status,
                      origin if origin not in ("local", "bundled") else f"[dim]{origin}[/dim]",
                      row.get("description") or "")
    ctx.console.print(table)
    return 0


def _info(ctx: CLIContext, args: argparse.Namespace) -> int:
    row = next((r for r in _rows(ctx, None) if r["name"] == args.name), None)
    if row is None:
        return _missing(ctx, args.name)
    entry = ctx.lock.get(row["kind"], row.get("unit") or row["name"]) or {}
    pairs = [
        ("name", row["name"]),
        ("kind", row["kind"]),
        ("description", row.get("description")),
        ("version", entry.get("version")),
        ("enabled", row.get("enabled")),
        ("available", True if row["available"] else f"no — {row['unavailable_reason']}"),
        ("platforms", ", ".join(row.get("platforms") or []) or None),
        ("requires", ", ".join(row.get("requires") or []) or None),
        ("installed from", entry.get("repo")),
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

    row = next((r for r in _rows(ctx, None) if r["name"] == args.name), None)
    if row is None:
        return _missing(ctx, args.name)

    if row["kind"] == ArtifactKind.DASHBOARD.value:
        return _remove_dashboard(ctx, args, row)

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


def _remove_dashboard(ctx: CLIContext, args, row) -> int:
    from lesysbot.artifacts.lockfile import drop_entries
    from lesysbot.core.paths import force_rmtree, generated_dashboards_dir

    target = ctx.dashboards_dir / args.name
    ctx.console.print(f"[bold]{args.name}[/bold] (dashboard) — {target}")
    if not args.yes and not _confirm(f"Permanently delete {target}?"):
        ctx.console.print("Aborted.")
        return 0
    if target.is_dir():
        force_rmtree(target)
    # Un-provision too: leaving the rendered JSON behind means Grafana keeps
    # serving a dashboard the user just deleted.
    rendered = generated_dashboards_dir(ctx.settings.config_dir) / f"{args.name}.json"
    if rendered.exists():
        rendered.unlink()
        ctx.console.print("[dim]un-provisioned from Grafana[/dim]")
    drop_entries(ctx.lock_path, [args.name], ArtifactKind.DASHBOARD)
    ctx.console.print(f"[green]✔[/green] Removed {args.name}")
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


def dashboards_dir_for(settings) -> Path:
    """Public helper for callers that have Settings but no CLIContext."""
    from lesysbot.core.paths import installed_dashboards_dir

    return installed_dashboards_dir(settings.config_dir)
