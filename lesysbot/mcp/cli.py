"""`lesysbot tools …` subcommands — install and manage tools from the terminal.

One command family for the whole tool lifecycle: ``install`` fetches tool
folder packages straight from a GitHub link (no registries, no catalogs),
``list``/``info`` show runtime status plus install provenance from the lock
file, ``enable``/``disable`` persist to ``mcp.state_file``, and
``remove`` deletes from ``mcp.tools_dir`` — all against the same resolved
paths the bot loads. Wired into the root parser by ``__main__.build_parser()``
(``tool`` works as an alias).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from lesysbot.core.config import Settings, resolve_paths
from lesysbot.mcp.registry import ToolRegistry


def register_subcommands(subparsers: argparse._SubParsersAction) -> None:
    # -c is repeated on each leaf with SUPPRESS so both `lesysbot -c x.yaml tools
    # list` and `lesysbot tools list -c x.yaml` work.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default=argparse.SUPPRESS, help="Path to config.yaml")

    tool = subparsers.add_parser(
        "tools",
        aliases=["tool"],
        help="Install, list, enable/disable, and remove tools",
    )
    tsub = tool.add_subparsers(dest="tool_cmd", metavar="action", required=True)

    t_install = tsub.add_parser(
        "install",
        parents=[common],
        help="Install tool package(s) from GitHub: owner/repo[/subdir][@ref] or URL",
    )
    t_install.add_argument("spec", help="GitHub spec or github.com URL")
    t_install.add_argument("--ref", default=None, help="Branch, tag, or commit SHA")
    t_install.add_argument(
        "--only", action="append", default=None, metavar="NAME",
        help="Install only this package from a multi-package repo (repeatable)",
    )
    t_install.add_argument("--force", action="store_true", help="Overwrite an unmanaged folder")
    t_install.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    t_install.add_argument(
        "--install-deps", action="store_true",
        help="pip-install the package's requirements.txt after installing",
    )

    t_list = tsub.add_parser(
        "list", parents=[common], help="List tools with status, source, and origin"
    )
    t_list.add_argument("--json", action="store_true", dest="as_json")

    t_info = tsub.add_parser("info", parents=[common], help="Show details for a tool")
    t_info.add_argument("name")

    t_enable = tsub.add_parser("enable", parents=[common], help="Re-enable a disabled tool")
    t_enable.add_argument("name")

    t_disable = tsub.add_parser(
        "disable", parents=[common],
        help="Disable a tool (hidden from the LLM, /commands refuse it)",
    )
    t_disable.add_argument("name")

    t_remove = tsub.add_parser(
        "remove", parents=[common],
        help="Delete a tool's folder package (or loose .py) from the tools dir",
    )
    t_remove.add_argument("name")
    t_remove.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")


def _confirm(message: str) -> bool:
    from rich.prompt import Confirm

    try:
        return Confirm.ask(message, default=False)
    except EOFError:  # non-interactive stdin — require --yes
        return False


def run(args: argparse.Namespace) -> int:
    console = Console()
    settings = Settings.load(getattr(args, "config", None))
    resolve_paths(settings)

    if args.tool_cmd == "install":
        return _install(settings, console, args)

    registry = ToolRegistry()
    registry.set_state_path(settings.mcp.state_file)
    registry.load_state()
    registry.load_directory(settings.mcp.tools_dir)

    if args.tool_cmd == "list":
        return _list(registry, settings, console, args.as_json)
    if args.tool_cmd == "info":
        return _info(registry, settings, console, args.name)
    if args.tool_cmd in ("enable", "disable"):
        if not settings.mcp.state_file:
            console.print(
                "[red]Error:[/red] mcp.state_file is null in the config — "
                "there is nowhere to persist tool state."
            )
            return 1
        return _set_enabled(registry, console, args.name, args.tool_cmd == "enable")
    return _remove(registry, settings, console, args.name, yes=args.yes)


def _load_lock(settings: Settings) -> dict:
    from lesysbot.install.lockfile import LOCK_KEY, JsonState

    return JsonState(Path(settings.mcp.lock_file), LOCK_KEY).load()


def _origin(lock: dict, unit: str | None) -> str:
    """Human-readable install origin for a package unit: repo@commit or local."""
    entry = lock.get(unit) if unit else None
    if not entry:
        return "local"
    origin = entry.get("repo", "?")
    if entry.get("commit"):
        origin += f"@{entry['commit'][:7]}"
    return origin


def _install(settings: Settings, console: Console, args: argparse.Namespace) -> int:
    from dataclasses import replace

    from lesysbot.install.errors import ToolInstallError
    from lesysbot.install.manager import ToolInstaller
    from lesysbot.install.spec import parse_source

    if "/" not in args.spec and "://" not in args.spec and not args.spec.startswith("git@"):
        console.print(
            f"[red]Error:[/red] {args.spec!r} isn't a GitHub link. Tools install "
            "straight from GitHub:"
        )
        console.print(
            "    lesysbot tools install owner/repo[/subdir][@ref]\n"
            "    lesysbot tools install https://github.com/owner/repo",
            markup=False,
        )
        return 1
    try:
        src = parse_source(args.spec)
        if args.ref:
            src = replace(src, ref=args.ref)
        installer = ToolInstaller(
            Path(settings.mcp.tools_dir),
            Path(settings.mcp.lock_file),
            console=console,
        )
        installer.install(
            src,
            only=args.only,
            force=args.force,
            yes=args.yes,
            install_deps=args.install_deps,
        )
        return 0
    except ToolInstallError as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1


def _missing(console: Console, name: str) -> int:
    console.print(f"[red]Error:[/red] no tool named {name!r} (see `lesysbot tools list`)")
    return 1


def _list(registry: ToolRegistry, settings: Settings, console: Console, as_json: bool) -> int:
    rows = registry.tool_status()
    lock = _load_lock(settings)
    for row in rows:
        src = row["source"]
        row["origin"] = _origin(lock, src["unit"] if src else None)
    if as_json:
        console.print_json(json.dumps(rows))
        return 0
    if not rows:
        console.print(
            "No tools found. Drop one into the tools dir or "
            "`lesysbot tools install owner/repo`."
        )
        return 0
    table = Table(box=None, pad_edge=False)
    for col in ("tool", "status", "source", "origin", "description"):
        table.add_column(col)
    for row in rows:
        status = "[green]enabled[/green]" if row["enabled"] else "[red]disabled[/red]"
        if not row["available"]:
            status += f" [yellow]⚠ {row['unavailable_reason']}[/yellow]"
        src = row["source"]
        unit = f"{src['unit']}/" if src and src["kind"] == "package" else (
            src["unit"] if src else "—"
        )
        origin = row["origin"] if row["origin"] != "local" else "[dim]local[/dim]"
        table.add_row(row["name"], status, unit, origin, row["description"] or "")
    console.print(table)
    return 0


def _info(registry: ToolRegistry, settings: Settings, console: Console, name: str) -> int:
    row = next((r for r in registry.tool_status() if r["name"] == name), None)
    if row is None:
        return _missing(console, name)
    src = row["source"]
    lock_entry = _load_lock(settings).get(src["unit"]) if src else None
    params = ", ".join(p["name"] + ("" if p["required"] else "?") for p in row["params"])
    pairs = [
        ("name", row["name"]),
        ("description", row["description"]),
        ("enabled", row["enabled"]),
        ("available", True if row["available"] else f"no — {row['unavailable_reason']}"),
        ("platforms", ", ".join(row["platforms"]) if row["platforms"] else None),
        ("requires", ", ".join(row["requires"]) if row["requires"] else None),
        ("confirm", row["confirm"] or None),
        ("params", params or None),
        ("source", f"{src['path']} ({src['kind']}: {', '.join(src['tools'])})" if src else None),
    ]
    if lock_entry:
        pairs += [
            ("installed from", lock_entry.get("repo")),
            ("commit", lock_entry.get("commit")),
            ("version", lock_entry.get("version")),
            ("installed at", lock_entry.get("installed_at")),
        ]
    for key, value in pairs:
        if value not in (None, ""):
            console.print(f"[bold]{key}:[/bold] {value}")
    return 0


def _set_enabled(registry: ToolRegistry, console: Console, name: str, enabled: bool) -> int:
    if registry.get_tool_meta(name) is None:
        return _missing(console, name)
    registry.set_enabled(name, enabled)
    console.print(f"[green]✔[/green] {name} {'enabled' if enabled else 'disabled'}")
    console.print(
        "[dim]A running LeSysBot watches the state file, so it applies this "
        "within a second — no restart needed.[/dim]"
    )
    return 0


def _remove(
    registry: ToolRegistry, settings: Settings, console: Console, name: str, *, yes: bool
) -> int:
    if registry.get_tool_meta(name) is None:
        return _missing(console, name)
    info = registry.tool_source(name)
    if info is None:
        console.print(
            f"[red]Error:[/red] {name!r} wasn't loaded from the tools directory, "
            "so it can't be removed here."
        )
        return 1
    console.print(f"[bold]{info['unit']}[/bold] ({info['kind']}) — {info['path']}")
    console.print(f"  tools: {', '.join('/' + t for t in info['tools'])}")
    if not yes and not _confirm(f"Permanently delete {info['path']}?"):
        console.print("Aborted.")
        return 0
    try:
        registry.remove_tool(name)
    except (ValueError, OSError) as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1
    if info["kind"] == "package":
        from lesysbot.install.lockfile import drop_entries

        dropped = drop_entries(Path(settings.mcp.lock_file), [info["unit"]])
        if dropped:
            console.print(f"[dim]Install lock entry dropped: {', '.join(dropped)}[/dim]")
    console.print(f"[green]✔[/green] Removed {', '.join('/' + t for t in info['tools'])}")
    console.print(
        "[dim]A running LeSysBot with hot_reload drops it automatically; otherwise restart.[/dim]"
    )
    return 0
