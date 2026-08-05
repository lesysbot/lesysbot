"""Shared plumbing for the artifact CLI verbs.

One place that turns "the user typed a command" into "here are the resolved
paths, the lock, and an installer pointed at them", so every verb agrees about
where things live — the bug this replaces is a CLI writing into a different
tools dir than the bot reads.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.artifacts.lockfile import ArtifactLock
from lesysbot.core.config import Settings, resolve_paths
from lesysbot.core.paths import installed_dashboards_dir


def config_parent() -> argparse.ArgumentParser:
    """``-c/--config``, repeated on each leaf so flag order is free.

    ``SUPPRESS`` matters: without it every leaf would write ``config=None`` over
    a root-level ``-c`` that was parsed first.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("-c", "--config", default=argparse.SUPPRESS,
                        help="Path to config.yaml")
    return parent


@dataclass
class CLIContext:
    settings: Settings
    console: Console

    @classmethod
    def load(cls, args: argparse.Namespace, console: Console | None = None) -> "CLIContext":
        settings = Settings.load(getattr(args, "config", None))
        resolve_paths(settings)
        return cls(settings, console or Console())

    # -- resolved locations ---------------------------------------------------

    @property
    def tools_dir(self) -> Path:
        return Path(self.settings.mcp.tools_dir)

    @property
    def dashboards_dir(self) -> Path:
        """Where dashboard packages install.

        Anchored to the *config's* directory when there is one, so a dev
        checkout with a local config.yaml keeps its dashboards beside it rather
        than reaching into the user's real home.
        """
        return installed_dashboards_dir(self.settings.config_dir)

    @property
    def destinations(self) -> dict[ArtifactKind, Path]:
        return {
            ArtifactKind.TOOL: self.tools_dir,
            ArtifactKind.DASHBOARD: self.dashboards_dir,
        }

    @property
    def lock_path(self) -> Path:
        return Path(self.settings.mcp.lock_file)

    @property
    def lock(self) -> ArtifactLock:
        return ArtifactLock(self.lock_path)

    # -- collaborators --------------------------------------------------------

    def installer(self, **kwargs):
        """An installer pointed at this context's paths.

        Both `console` and `preflight` are defaults rather than fixed, so the
        panel can hand in a console that writes into a background job's output
        without needing a second construction path.
        """
        from lesysbot.artifacts.installer import ArtifactInstaller

        kwargs.setdefault("preflight", self.preflight)
        kwargs.setdefault("console", self.console)
        return ArtifactInstaller(self.destinations, self.lock_path, **kwargs)

    def preflight(self, pkg):
        """Prerequisite report for *pkg*, or None when nothing is declared."""
        from lesysbot.prereq import check_package

        return check_package(pkg)

    def registry(self):
        from lesysbot.core.status import build_registry

        return build_registry(self.settings)

    # -- output ---------------------------------------------------------------

    def error(self, message: str) -> int:
        self.console.print(f"[red]Error:[/red] {message}")
        return 1
