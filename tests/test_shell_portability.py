"""Guard the shell scripts against bash-4-only syntax.

macOS ships **bash 3.2** as `/bin/bash` (Apple froze it at the last GPLv2
release), and every script here starts `#!/usr/bin/env bash`, which finds that
one unless the user happens to have a newer bash earlier on PATH. Bash 4 syntax
therefore fails on the primary supported platform.

The failure mode is what makes this worth a test: `${var,,}` is a *runtime*
error ("bad substitution"), not a parse error, so `bash -n` reports the file as
fine and CI stays green. Combined with `set -e` it aborts the script mid-run —
which is exactly how `uninstall.sh` once died half-way through an uninstall,
after removing the service and the package but before stopping the dashboard
stack or offering to remove ~/.lesysbot.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(
    p for p in (*(REPO / "scripts").glob("*.sh"),
                *(REPO / "dashboard" / "scripts").glob("*.sh"))
)

# (regex, what to use instead) — each is valid bash 4+ and broken on 3.2.
BASH4_ONLY = [
    (re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*,,\}"),
     "${var,,} lowercasing — use a case-based helper (see is_yes in uninstall.sh)"),
    (re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\^\^\}"),
     "${var^^} uppercasing — use tr or a case statement"),
    (re.compile(r"^\s*declare\s+-A\b", re.M), "associative arrays — use parallel arrays"),
    (re.compile(r"^\s*(mapfile|readarray)\b", re.M), "mapfile/readarray — use a while-read loop"),
    (re.compile(r"\[\[\s+-v\s"), "[[ -v var ]] — use [ -n \"${var:-}\" ]"),
    (re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*@[QEPAa]\}"),
     "${var@Q} parameter transformations — bash 4.4+"),
]


def test_scripts_exist():
    """A silent glob miss would make every check below vacuously pass."""
    assert SCRIPTS, "no shell scripts found — did the layout change?"


def _strip_comments(text: str) -> str:
    """Blank out whole-line comments, keeping line numbers intact.

    Only full-line comments: a trailing-comment stripper would have to know
    where quoting ends, and `${var#prefix}` / `"$#"` are not comments. The
    documentation for this very rule quotes `${var,,}` in a comment, so scanning
    comments would make the guard flag its own explanation.
    """
    return "\n".join("" if line.lstrip().startswith("#") else line
                     for line in text.splitlines())


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_no_bash4_only_syntax(script: Path):
    text = _strip_comments(script.read_text(encoding="utf-8"))
    problems = []
    for pattern, advice in BASH4_ONLY:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            problems.append(f"{script.name}:{line}: {match.group(0)!r} — {advice}")
    assert not problems, (
        "bash 4 syntax breaks at runtime on macOS (/bin/bash is 3.2):\n  "
        + "\n  ".join(problems)
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_uses_env_bash_shebang(script: Path):
    """`#!/bin/sh` would be worse still — these scripts use arrays and [[ ]]."""
    first = script.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("#!"), f"{script.name} has no shebang"
    assert "bash" in first, f"{script.name} must run under bash, not: {first}"
