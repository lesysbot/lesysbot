"""Python dependencies for installed packages.

A package may need libraries the bot doesn't ship. Those go into **the
environment LeSysBot itself runs in**, because that is the interpreter that
imports a tool's ``tool.py`` — installing them anywhere else would leave the
tool failing on ``ImportError`` with everything apparently in place.

This is the one thing LeSysBot installs on your behalf without asking a second
time, and it stays deliberately narrow: pip packages into its own environment,
nothing else. System packages, drivers and daemons are *prerequisites* — they
are detected and explained (see :mod:`lesysbot.prereq`), never installed, because
every route to installing them wants root and the project has none.

When the interpreter can't pip-install — a PyInstaller build has no pip, and a
system-managed Python may refuse — nothing is attempted and the exact command is
printed instead. A wrong guess here is worse than no guess: it would half-install
into an environment the bot never reads.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lesysbot.core.paths import is_frozen

# A requirements.txt may reference others or point pip at an index; those are
# pip's business, not ours, and are passed through untouched.
_COMMENT = "#"


@dataclass
class DepsOutcome:
    """What happened to a package's Python dependencies."""

    requirements: list[str] = field(default_factory=list)
    installed: list[str] = field(default_factory=list)
    #: Set when nothing was installed and the user has to run it themselves.
    command: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return not self.requirements or bool(self.installed)


def read_requirements(target: Path) -> list[str]:
    """Requirement lines from a package's ``requirements.txt``."""
    path = target / "requirements.txt"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith(_COMMENT):
            out.append(line)
    return out


def requirements_for(pkg, target: Path) -> list[str]:
    """Everything a package declares: ``requires_python:`` plus requirements.txt.

    Duplicates are collapsed while keeping order, so a manifest that repeats a
    line already in requirements.txt doesn't hand pip the same spec twice.
    """
    return list(dict.fromkeys([*getattr(pkg, "requires_python", []),
                               *read_requirements(target)]))


#: Set this to any non-empty value to make dependency installation a no-op that
#: prints the command instead. The test suite sets it globally (tests/conftest.py):
#: installing a package's requirements means running pip against whatever
#: environment the tests happen to be in, and a single test that forgets to stub
#: `subprocess.run` would mutate a developer's real interpreter. A safety net
#: beats remembering.
SKIP_ENV = "LESYSBOT_SKIP_DEP_INSTALL"


def can_install() -> tuple[bool, str | None]:
    """Whether this interpreter can pip-install; the reason when it can't."""
    import os

    if os.environ.get(SKIP_ENV):
        return False, f"{SKIP_ENV} is set"
    if is_frozen():
        return False, "this is a standalone build, which has no pip"
    try:
        proc = subprocess.run([sys.executable, "-m", "pip", "--version"],
                              capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"pip could not be run ({e})"
    if proc.returncode != 0:
        return False, "pip is not available in this environment"
    return True, None


def pip_command(requirements: list[str]) -> str:
    """The command a user would run to install *requirements* themselves."""
    return f"{sys.executable} -m pip install " + " ".join(
        f'"{r}"' if " " in r else r for r in requirements
    )


def install_for(pkg, target: Path, *, console=None) -> DepsOutcome:
    """Install a package's Python dependencies into LeSysBot's environment."""
    requirements = requirements_for(pkg, target)
    outcome = DepsOutcome(requirements=requirements)
    if not requirements:
        return outcome

    def say(message: str) -> None:
        if console is not None:
            console.print(message)

    ok, reason = can_install()
    if not ok:
        outcome.reason = reason
        outcome.command = pip_command(requirements)
        say(f"[yellow]![/yellow] {pkg.name} needs {', '.join(requirements)}, but "
            f"{reason}.\n    Install them with:\n      {outcome.command}")
        return outcome

    say(f"  Installing {len(requirements)} Python "
        f"{'dependency' if len(requirements) == 1 else 'dependencies'}: "
        f"{', '.join(requirements)}")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", *requirements],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # A failed dependency install is not a failed *package* install: the
        # files are already in place and the tool may still work (or degrade to
        # its own ImportError handling). Report it and leave it to the user.
        outcome.reason = (proc.stderr or proc.stdout or "pip failed").strip().splitlines()[-1:]
        outcome.reason = outcome.reason[0] if outcome.reason else "pip failed"
        outcome.command = pip_command(requirements)
        say(f"[yellow]![/yellow] Could not install dependencies: {outcome.reason}\n"
            f"    {pkg.name} is installed; finish it with:\n      {outcome.command}")
        return outcome

    outcome.installed = requirements
    say(f"[green]✔[/green] Installed {', '.join(requirements)}")
    return outcome
