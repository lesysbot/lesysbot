"""Install packages from GitHub into the directory their kind belongs in.

Installing means extracting the package(s) from a GitHub zipball into the right
destination (one atomic directory move, so a running bot's hot reload sees a
single clean change) and recording provenance in the lock file so
``lesysbot list/info/remove`` know where an installed package came from.

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
from lesysbot.artifacts.manifest import NAME_RE, ArtifactPackage, discover_packages
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
    """Installs tool and dashboard packages from GitHub.

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
        """Install the package(s) at *src*; returns what was installed."""
        self.console.print(f"Fetching [bold]{src}[/bold]…")
        data = download_zipball(self._fetcher, src)
        commit = zip_commit_sha(data)

        staging = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX))
        try:
            extract_tree(data, src.subdir, staging)
            default_name = (src.subdir or src.repo).rstrip("/").rsplit("/", 1)[-1]
            packages = discover_packages(staging, default_name)
            packages = self._select(packages, only, src)
            if kind is not None:
                packages = self._filter_kind(packages, ArtifactKind(kind), src)
            self._validate(packages)
            self._check_collisions(packages, force)
            self._print_plan(src, commit, packages)

            prompt = (
                f"Install {len(packages)} package(s) from {src.slug}"
                f"{f' @ {commit[:12]}' if commit else ''}? "
                "Packages run arbitrary code as your user"
            )
            if not yes and not self._confirm(prompt):
                self.console.print("Aborted.")
                return InstallResult([], packages)

            installed = [
                self._place(pkg, src, commit, staging, install_deps=install_deps)
                for pkg in packages
            ]
            self._print_epilogue(installed)
            return InstallResult(installed, [])
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _place(self, pkg: ArtifactPackage, src: ToolSource, commit: str | None,
               staging: Path, *, install_deps: bool) -> ArtifactPackage:
        """Move one staged package into its destination and record it."""
        dest_dir = self.destination(pkg.kind)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / pkg.name

        # Where this package sits inside the repo, which is not the same as the
        # subdir that was *requested*: installing `acme/repo` finds `alpha/` and
        # `beta/` inside it, and `update` has to re-fetch each from its own path.
        pkg_subdir = _join_subdir(src.subdir, pkg.path.relative_to(staging))

        if target.exists():
            self._carry_preserved(pkg, target)
            _rmtree(target)
        shutil.move(str(pkg.path), str(target))

        prev = self.lock.get(pkg.kind, pkg.name) or {}
        self.lock.put(pkg.kind, pkg.name, {
            "name": pkg.name,
            "kind": pkg.kind.value,
            "repo": src.slug,
            "subdir": pkg_subdir,
            "requested_ref": src.ref,
            "commit": commit,
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
                src: ToolSource) -> list[ArtifactPackage]:
        if not packages:
            raise ToolInstallError(
                f"No packages found in {src} — expected a `tool.py` or a "
                "`dashboard.json`/`dashboard.py` (plus README.md) in the repo root, "
                "or per-package subdirectories there or under `tools/`/`dashboards/`."
            )
        if not only:
            return packages
        by_name = {p.name: p for p in packages}
        missing = [n for n in only if n not in by_name]
        if missing:
            raise ToolInstallError(
                f"Package(s) {', '.join(missing)} not found in {src.slug}. "
                f"Available: {', '.join(sorted(by_name))}"
            )
        return [by_name[n] for n in only]

    def _filter_kind(self, packages: list[ArtifactPackage], kind: ArtifactKind,
                     src: ToolSource) -> list[ArtifactPackage]:
        kept = [p for p in packages if p.kind is kind]
        if not kept:
            found = ", ".join(sorted({p.kind.value for p in packages})) or "nothing"
            raise ToolInstallError(
                f"No {kind.value} packages in {src.slug} (found: {found})."
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

    def _print_plan(self, src: ToolSource, commit: str | None,
                    packages: list[ArtifactPackage]) -> None:
        pin = commit[:12] if commit else (src.ref or "HEAD")
        self.console.print(f"\n[bold]{src.slug}[/bold] @ {pin}")
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
        kinds = {p.kind for p in installed}
        if ArtifactKind.TOOL in kinds:
            self.console.print(
                "A running LeSysBot with hot_reload picks new tools up automatically; "
                "otherwise restart it. Type /help in the chat to see them."
            )
        if ArtifactKind.DASHBOARD in kinds:
            self.console.print(
                "Render it with `lesysbot dashboard render`; "
                "Grafana picks it up within 30s."
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

