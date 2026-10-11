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

    ``requires:`` predates this module and stays exactly as it was — it is
    folded in here rather than reimplemented, so a package written years ago is
    checked by the same machinery as one written today. ``requires_python:``
    entries are marked auto-fixable via the ``pip`` checker.
    """
    out: list[Requirement] = []
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
