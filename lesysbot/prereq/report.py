"""The vocabulary of prerequisites: what a package needs, and what this machine has.

The product claim is that LeSysBot tells you *precisely* why something won't work
and how to fix it without sudo. That only holds if "unavailable" carries a reason
and a remedy, so a :class:`Result` always has both when it fails — a checker that
can't explain itself is a checker that shouldn't exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Requirement:
    """Something that must be true for a package to work."""

    type: str
    value: str = ""
    #: An optional requirement degrades the package rather than blocking it —
    #: `temperature` works without `osx-cpu-temp`, with fewer readings.
    optional: bool = False

    def __str__(self) -> str:
        return f"{self.type} {self.value}".strip()


@dataclass
class Result:
    """The outcome of checking one requirement on this machine."""

    requirement: Requirement
    satisfied: bool
    #: What was actually found ("nvidia-smi 550.90", "nothing listening on 9090").
    detail: str = ""
    #: A command or URL that would fix it. Never a `sudo` invocation — if the
    #: only fix needs root, say so in words and let the user decide.
    fix: str = ""
    #: True when LeSysBot can fix this itself (pip deps, its own packages).
    auto_fixable: bool = False

    @property
    def blocking(self) -> bool:
        return not self.satisfied and not self.requirement.optional


@dataclass
class Report:
    """Every requirement of one package, checked."""

    name: str = ""
    results: list[Result] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.results)

    @property
    def ok(self) -> bool:
        """True when nothing *blocking* is missing (optionals may be unmet)."""
        return not any(r.blocking for r in self.results)

    @property
    def unmet(self) -> list[Result]:
        return [r for r in self.results if not r.satisfied]

    @property
    def blockers(self) -> list[Result]:
        return [r for r in self.results if r.blocking]

    @property
    def reason(self) -> str:
        """One line naming what's wrong, for a status row."""
        blockers = self.blockers
        if not blockers:
            return ""
        head = blockers[0]
        rest = f" (+{len(blockers) - 1} more)" if len(blockers) > 1 else ""
        return f"{head.detail or head.requirement}{rest}"

    def render(self, *, header: bool = True, label: str = "") -> str:
        """The preflight block shown before an install prompt.

        Aligned three-column output rather than prose, because the reader is
        scanning for the one row that says `missing` — and every unmet row is
        immediately followed by what to do about it.

        *header* is suppressed when several packages are reported together, so
        "Checking this machine…" appears once rather than once per package;
        *label* then names which package each group belongs to.
        """
        if not self.results:
            return ""
        width = max(len(str(r.requirement)) for r in self.results)
        lines = ["\n  Checking this machine…"] if header else []
        if label:
            lines.append(f"    [bold]{label}[/bold]")
        for r in self.results:
            if r.satisfied:
                state = "[green]ok[/green]"
            elif r.requirement.optional:
                state = "[yellow]missing[/yellow]"
            else:
                state = "[red]missing[/red]"
            note = f"  [dim]{r.detail}[/dim]" if r.detail and not r.satisfied else ""
            lines.append(f"    {str(r.requirement):<{width}}  {state}{note}")
        fixes = [r for r in self.results if not r.satisfied and r.fix]
        if fixes:
            lines.append("")
            for r in fixes:
                if r.auto_fixable:
                    lines.append(f"    [dim]{r.requirement}:[/dim] LeSysBot will install this")
                else:
                    lines.append(f"    [dim]{r.requirement}:[/dim] {r.fix}")
        return "\n".join(lines)
