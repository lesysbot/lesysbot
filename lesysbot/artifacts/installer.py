"""Install packages into the directory their kind belongs in.

Installing means getting the package(s) into a staging directory and moving each
into the right destination (one atomic directory move, so a running bot's hot
reload sees a single clean change), then recording provenance in the lock file so
``lesysbot list/info/remove`` know where an installed package came from.

A payload reaches staging one of two ways — :meth:`ArtifactInstaller.install`
unpacks a GitHub zipball, :meth:`~ArtifactInstaller.install_path` copies a folder
or a ``.zip`` from this machine. Everything after that point (discovery,
validation, consent, placement, deps) is one shared path, because nothing past
staging cares where the bytes came from. The two differ only in what they print
and what provenance they record, which is what :class:`_Remote` and
:class:`_Local` carry.

Installing is all this module does. Reading back what is installed belongs to
the registry and the lock — ``lesysbot list/info`` join live registry rows with
lock entries — and removal is ``registry.remove_tool()`` plus
``lockfile.drop_entries()``. Keeping one path for each avoids two sources of
truth about what is on disk.

**Re-installing is updating.** ``_check_collisions`` refuses only directories
the lock has never heard of, so anything the installer placed is replaced in
place; ``lesysbot update`` is that, re-resolved at the recorded ref.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from lesysbot.artifacts.archive import extract_tree, zip_commit_sha
from lesysbot.artifacts.errors import ToolInstallError
from lesysbot.artifacts.fetch import Fetcher, UrllibFetcher, download_zipball
from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.artifacts.lockfile import ArtifactLock
from lesysbot.artifacts.manifest import (
    NAME_RE,
    ArtifactPackage,
    contains_dashboard,
    discover_packages,
)
from lesysbot.artifacts.spec import ToolSource
from lesysbot.core.paths import force_rmtree as _rmtree

STAGE_PREFIX = ".lesysbot-stage-"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _join_subdir(requested: str | None, relative: Path) -> str | None:
    """The package's path inside the repo: what was asked for, plus where it was
    found under that. ``.`` means "the requested path *is* the package"."""
    parts = [p for p in (requested or "", "" if str(relative) == "." else str(relative))
             if p]
    return "/".join(parts) or None


def _default_confirm(message: str) -> bool:
    from rich.prompt import Confirm

    try:
        return Confirm.ask(message, default=False)
    except EOFError:  # non-interactive stdin — require --yes
        return False


@dataclass(frozen=True)
class _Remote:
    """Payload origin: a GitHub zipball, pinned to the commit it unpacked from."""

    src: ToolSource
    commit: str | None = None

    @property
    def label(self) -> str:
        return str(self.src)

    @property
    def slug(self) -> str:
        return self.src.slug

    @property
    def header(self) -> str:
        pin = self.commit[:12] if self.commit else (self.src.ref or "HEAD")
        return f"[bold]{self.src.slug}[/bold] @ {pin}"

    def consent(self, count: int) -> str:
        pin = f" @ {self.commit[:12]}" if self.commit else ""
        return (f"Install {count} package(s) from {self.src.slug}{pin}? "
                "Packages run arbitrary code as your user")

    def lock_fields(self, pkg: ArtifactPackage, staging: Path) -> dict[str, Any]:
        # Where this package sits inside the repo, which is not the same as the
        # subdir that was *requested*: installing `acme/repo` finds `alpha/` and
        # `beta/` inside it, and `update` has to re-fetch each from its own path.
        return {
            "repo": self.src.slug,
            "subdir": _join_subdir(self.src.subdir, pkg.path.relative_to(staging)),
            "requested_ref": self.src.ref,
            "commit": self.commit,
        }


@dataclass(frozen=True)
class _Local:
    """Payload origin: a folder or ``.zip`` already on this machine.

    Records the path it was copied from and, deliberately, **no** ``repo`` — so
    ``lesysbot update`` (which re-fetches at a recorded ref) skips it. Re-running
    ``lesysbot install <path>`` is the update for a local package.
    """

    path: Path

    @property
    def label(self) -> str:
        return str(self.path)

    @property
    def slug(self) -> str:
        return str(self.path)

    @property
    def header(self) -> str:
        return f"[bold]{self.path}[/bold] [dim](local)[/dim]"

    def consent(self, count: int) -> str:
        return (f"Install {count} package(s) from {self.path}? "
                "Packages run arbitrary code as your user")

    def lock_fields(self, pkg: ArtifactPackage, staging: Path) -> dict[str, Any]:
        return {"path": str(self.path)}


Origin = _Remote | _Local


@dataclass
class InstallResult:
    """What an install actually did, for the CLI and the panel to report."""

    installed: list[ArtifactPackage]
    skipped: list[ArtifactPackage]

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.installed]

    def __bool__(self) -> bool:
        return bool(self.installed)


class ArtifactInstaller:
    """Installs tool and dashboard packages from GitHub or from a local path.

    *destinations* maps each kind to the directory its packages live in, so the
    caller (which owns config resolution) decides where things land and this
    stays a pure mechanism.
    """

    def __init__(
        self,
        destinations: dict[ArtifactKind, Path],
        lock_path: Path,
        fetcher: Fetcher | None = None,
        *,
        confirm: Callable[[str], bool] | None = None,
        console: Console | None = None,
        preflight: Callable[[ArtifactPackage], Any] | None = None,
    ) -> None:
        self.destinations = {ArtifactKind(k): Path(v) for k, v in destinations.items()}
        self.lock = ArtifactLock(Path(lock_path))
        self._fetcher = fetcher or UrllibFetcher()
        self._confirm = confirm or _default_confirm
        self.console = console or Console()
        # Given a package, returns a report to print before asking for consent
        # (lesysbot.prereq). None means no preflight.
        self._preflight = preflight

    def destination(self, kind: ArtifactKind) -> Path:
        try:
            return self.destinations[ArtifactKind(kind)]
        except KeyError:
            raise ToolInstallError(
                f"No install directory configured for {ArtifactKind(kind).value} packages"
            ) from None

    # -- install --------------------------------------------------------------

    def install(
        self,
        src: ToolSource,
        *,
        only: list[str] | None = None,
        kind: ArtifactKind | None = None,
        force: bool = False,
        yes: bool = False,
        install_deps: bool = True,
    ) -> InstallResult:
        """Install the package(s) at *src* from GitHub; returns what was installed."""
        self.console.print(f"Fetching [bold]{src}[/bold]…")
        data = download_zipball(self._fetcher, src)

        staging = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX))
        try:
            extract_tree(data, src.subdir, staging)
            default_name = (src.subdir or src.repo).rstrip("/").rsplit("/", 1)[-1]
            return self._install_staged(
                staging, _Remote(src, zip_commit_sha(data)), default_name,
                only=only, kind=kind, force=force, yes=yes, install_deps=install_deps,
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def install_path(
        self,
        path: Path | str,
        *,
        only: list[str] | None = None,
        kind: ArtifactKind | None = None,
        force: bool = False,
        yes: bool = False,
        install_deps: bool = True,
    ) -> InstallResult:
        """Install the package(s) in a folder or ``.zip`` on this machine.

        The copy-paste path with the checks kept: the same manifest discovery,
        preflight, consent and dependency install a GitHub package gets. Copying
        the folder into the tools dir by hand does work — hot reload sees it —
        but skips all of that, which is why this exists.
        """
        source = Path(path).expanduser()
        staging = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX))
        try:
            self.console.print(f"Reading [bold]{source}[/bold]…")
            default_name = self._stage_local(source, staging)
            return self._install_staged(
                staging, _Local(source.resolve()), default_name,
                only=only, kind=kind, force=force, yes=yes, install_deps=install_deps,
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _stage_local(self, source: Path, staging: Path) -> str:
        """Copy a local folder or ``.zip`` into *staging*; returns the default name.

        Contents land at the staging **root** — exactly where ``extract_tree``
        leaves a zipball's after stripping its single top-level directory. That
        is what lets `discover_packages` treat both shapes alike, so a folder that
        *is* one package and a folder holding `tools/` both install correctly.
        """
        if not source.exists():
            raise ToolInstallError(f"No such file or directory: {source}")
        if source.is_dir():
            shutil.copytree(source, staging, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", ".git*"))
            return source.name
        if source.suffix.lower() == ".zip":
            # Reuses the zipball guards: zip-slip, symlink entries, zip bombs.
            extract_tree(source.read_bytes(), None, staging)
            return source.stem
        raise ToolInstallError(
            f"{source} is not a folder or a .zip — a tool package is a folder "
            "holding a tool.py (and usually a README.md)."
        )

    def _install_staged(
        self,
        staging: Path,
        origin: Origin,
        default_name: str,
        *,
        only: list[str] | None,
        kind: ArtifactKind | None,
        force: bool,
        yes: bool,
        install_deps: bool,
    ) -> InstallResult:
        """Everything past staging — identical for a zipball and a local folder."""
        packages = discover_packages(staging, default_name)
        if not packages and contains_dashboard(staging):
            raise ToolInstallError(
                f"{origin.label} is a Grafana dashboard, not a tool. LeSysBot has one "
                "dashboard — to use this one instead, run `lesysbot dashboard customize`, "
                "replace the file it prints with this dashboard's JSON, then run "
                "`lesysbot dashboard start`."
            )
        packages = self._select(packages, only, origin)
        if kind is not None:
            packages = self._filter_kind(packages, ArtifactKind(kind), origin)
        self._validate(packages)
        self._check_collisions(packages, force)
        self._print_plan(origin, packages)

        if not yes and not self._confirm(origin.consent(len(packages))):
            self.console.print("Aborted.")
            return InstallResult([], packages)

        installed = [
            self._place(pkg, origin, staging, install_deps=install_deps)
            for pkg in packages
        ]
        self._print_epilogue(installed)
        return InstallResult(installed, [])

    def _place(self, pkg: ArtifactPackage, origin: Origin, staging: Path,
               *, install_deps: bool) -> ArtifactPackage:
        """Move one staged package into its destination and record it."""
        dest_dir = self.destination(pkg.kind)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / pkg.name

        if target.exists():
            self._carry_preserved(pkg, target)
            _rmtree(target)
        shutil.move(str(pkg.path), str(target))

        prev = self.lock.get(pkg.kind, pkg.name) or {}
        self.lock.put(pkg.kind, pkg.name, {
            "name": pkg.name,
            "kind": pkg.kind.value,
            **origin.lock_fields(pkg, staging),
            "version": pkg.version,
            "description": pkg.description,
            "deps": prev.get("deps", []),
            "bundled": prev.get("bundled", False),
            "installed_at": prev.get("installed_at") or _now(),
            "updated_at": _now(),
        })
        self.console.print(
            f"[green]✔[/green] Installed [bold]{pkg.name}[/bold] "
            f"[dim]({pkg.kind.value})[/dim] → {target}"
        )
        if install_deps and (pkg.has_requirements or pkg.requires_python):
            self._install_deps(pkg, target)
        return pkg

    def _carry_preserved(self, pkg: ArtifactPackage, target: Path) -> None:
        """Copy the package's ``preserve:`` paths out of the installed copy and
        into the staged one, so an update can't eat a file the user owns.

        Missing entries are skipped silently: a manifest naming a `.env` the user
        never created is not an error, and failing the update over it would make
        ``preserve:`` a liability rather than a safeguard.
        """
        target_root = target.resolve()
        for rel in pkg.preserve:
            # A manifest is untrusted input written by somebody else, so
            # `preserve: ../../.ssh/id_rsa` must not reach outside the package.
            candidate = (target / rel).resolve()
            if not candidate.is_relative_to(target_root):
                self.console.print(
                    f"[yellow]![/yellow] ignoring preserve entry {rel!r} "
                    "(escapes the package)"
                )
                continue
            if not candidate.exists():
                continue
            keep = pkg.path / rel
            keep.parent.mkdir(parents=True, exist_ok=True)
            if candidate.is_dir():
                shutil.copytree(candidate, keep, dirs_exist_ok=True)
            else:
                shutil.copy2(candidate, keep)
            self.console.print(f"  [dim]kept your {rel}[/dim]")

    # -- selection and validation ---------------------------------------------

    def _select(self, packages: list[ArtifactPackage], only: list[str] | None,
                origin: Origin) -> list[ArtifactPackage]:
        if not packages:
            raise ToolInstallError(
                f"No packages found in {origin.label} — expected a `tool.py` "
                "(plus README.md) in the repo root, or per-package subdirectories "
                "there or under `tools/`."
            )
        if not only:
            return packages
        by_name = {p.name: p for p in packages}
        missing = [n for n in only if n not in by_name]
        if missing:
            raise ToolInstallError(
                f"Package(s) {', '.join(missing)} not found in {origin.slug}. "
                f"Available: {', '.join(sorted(by_name))}"
            )
        return [by_name[n] for n in only]

    def _filter_kind(self, packages: list[ArtifactPackage], kind: ArtifactKind,
                     origin: Origin) -> list[ArtifactPackage]:
        kept = [p for p in packages if p.kind is kind]
        if not kept:
            found = ", ".join(sorted({p.kind.value for p in packages})) or "nothing"
            raise ToolInstallError(
                f"No {kind.value} packages in {origin.slug} (found: {found})."
            )
        return kept

    def _validate(self, packages: list[ArtifactPackage]) -> None:
        seen: set[tuple[str, str]] = set()
        for pkg in packages:
            if not NAME_RE.match(pkg.name):
                raise ToolInstallError(
                    f"Invalid package name {pkg.name!r} — must match {NAME_RE.pattern} "
                    "(the loader ignores names starting with '.' or '_')"
                )
            key = (pkg.kind.value, pkg.name)
            if key in seen:
                raise ToolInstallError(
                    f"Duplicate {pkg.kind.value} package in archive: {pkg.name!r}"
                )
            seen.add(key)

    def _check_collisions(self, packages: list[ArtifactPackage], force: bool) -> None:
        """Refuse to clobber a directory the lock has never heard of.

        Anything this installer placed is in the lock and is replaced freely —
        that is what makes re-install mean update. A directory that is *not* in
        the lock was put there by hand (or seeded before the lock existed), so
        overwriting it would destroy work with no record of what was lost.
        """
        conflicts = [
            f"{p.kind.value} {p.name}"
            for p in packages
            if (self.destination(p.kind) / p.name).exists()
            and self.lock.get(p.kind, p.name) is None
        ]
        if conflicts and not force:
            raise ToolInstallError(
                f"already present and not installed by lesysbot: {', '.join(conflicts)} "
                "— pass --force to overwrite."
            )

    # -- reporting ------------------------------------------------------------

    def _print_plan(self, origin: Origin, packages: list[ArtifactPackage]) -> None:
        self.console.print(f"\n{origin.header}")
        for pkg in packages:
            ver = f" v{pkg.version}" if pkg.version else ""
            self.console.print(
                f"  [bold]{pkg.name}[/bold]{ver} [dim]({pkg.kind.value})[/dim] — "
                f"{pkg.description or '(no description)'}"
            )
            if pkg.tool_files:
                self.console.print(f"    files: {', '.join(pkg.tool_files)}")
            if pkg.has_requirements or pkg.requires_python:
                self.console.print("    has Python dependencies")
            self.console.print(f"    → {self.destination(pkg.kind) / pkg.name}")
        if self._preflight is not None:
            self._report_preflight(packages)

    def _report_preflight(self, packages: list[ArtifactPackage]) -> None:
        """Print what this machine can and can't satisfy, before consent.

        One "Checking this machine…" header for the whole install, with each
        package labelled underneath — repeating the header per package makes a
        multi-package collection read like several separate operations.
        """
        reports = [(pkg, self._preflight(pkg)) for pkg in packages]
        reports = [(pkg, r) for pkg, r in reports if getattr(r, "render", None)]
        if not reports:
            return
        multiple = len(reports) > 1
        for index, (pkg, report) in enumerate(reports):
            self.console.print(report.render(
                header=index == 0,
                label=pkg.name if multiple else "",
            ))

    def _print_epilogue(self, installed: list[ArtifactPackage]) -> None:
        if installed:
            self.console.print(
                "A running LeSysBot with hot_reload picks new tools up automatically; "
                "otherwise restart it. Type /help in the chat to see them."
            )

    # -- dependencies ---------------------------------------------------------

    def _install_deps(self, pkg: ArtifactPackage, target: Path) -> None:
        """Install the package's Python dependencies and record what landed."""
        from lesysbot.artifacts import deps

        outcome = deps.install_for(pkg, target, console=self.console)
        if outcome.installed:
            entry = self.lock.get(pkg.kind, pkg.name) or {}
            entry["deps"] = outcome.installed
            self.lock.put(pkg.kind, pkg.name, entry)

