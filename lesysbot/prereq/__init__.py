"""Prerequisites: what a package needs, whether this machine has it, and the fix.

The entry points are :func:`check_package` (one package's manifest, used for the
preflight block before an install) and :func:`check_host` (the machine itself,
used by ``lesysbot doctor``).

Two rules hold throughout:

* **Nothing here installs anything.** Checkers report; only pip dependencies and
  LeSysBot's own packages are ever auto-fixed, and that happens elsewhere.
* **Nothing here runs sudo.** Where the only real fix needs root, the fix is
  *text* the user can read and run themselves.
"""

from __future__ import annotations

from lesysbot.prereq.checks import CHECKERS, check, check_all
from lesysbot.prereq.report import Report, Requirement, Result

__all__ = [
    "CHECKERS", "Report", "Requirement", "Result",
    "check", "check_all", "check_host", "check_package", "requirements_of",
]


def requirements_of(pkg) -> list[Requirement]:
    """Every requirement a package declares, from all three frontmatter shapes.

    ``platforms:`` and ``requires:`` predate this module and stay exactly as
    they were — they are folded in here rather than reimplemented, so a package
    written years ago is checked by the same machinery as one written today.
    ``requires_python:`` entries are marked auto-fixable via the ``pip`` checker.
    """
    from lesysbot.prereq.checks import ANY_PLATFORM

    out: list[Requirement] = []
    platforms = getattr(pkg, "platforms", None) or []
    # `platforms: all` is a statement that there is no constraint, so it becomes
    # no requirement at all rather than one that trivially passes — otherwise
    # `lesysbot doctor` pads every cross-platform package with a noise row.
    if platforms and not (ANY_PLATFORM & {p.lower() for p in platforms}):
        out.append(Requirement("os", " ".join(platforms)))
    out += [Requirement("binary", b) for b in getattr(pkg, "requires", None) or []]
    out += [Requirement("pip", p) for p in getattr(pkg, "requires_python", None) or []]
    out += [Requirement(t, v) for t, v in getattr(pkg, "prerequisites", None) or []]
    return out


def check_package(pkg) -> Report | None:
    """Check everything *pkg* declares. None when it declares nothing."""
    requirements = requirements_of(pkg)
    if not requirements:
        return None
    return Report(name=getattr(pkg, "name", ""), results=check_all(requirements))


def check_host() -> Report:
    """The machine itself: what LeSysBot needs, and what dashboards can use.

    Every entry is ``optional`` — this is a description of the machine, not a
    gate. `lesysbot doctor` shows it so a user can see at a glance which
    capabilities are available and what would unlock the rest.
    """
    probes = [
        Requirement("service", "ollama", optional=True),
        Requirement("service", "prometheus", optional=True),
        Requirement("service", "grafana", optional=True),
        Requirement("docker", optional=True),
        Requirement("gpu", "nvidia", optional=True),
        Requirement("gpu", "amd", optional=True),
    ]
    return Report(name="this machine", results=check_all(probes))
