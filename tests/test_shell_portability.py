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

# Scripts that must run under POSIX sh rather than bash: the documented install
# command pipes them straight into `sh`.
POSIX_SCRIPTS = {"install.sh"}

# (regex, what to use instead) — valid bash, broken or unreliable in dash.
#
# This is a backstop for developers without shellcheck installed; CI runs
# `shellcheck --shell=sh --severity=warning` over the same file, which is the
# precise check. So these patterns are deliberately conservative — a false
# positive here would push someone to "fix" correct code, which is worse than a
# miss that shellcheck catches a minute later in CI. `local` is absent on
# purpose: not POSIX, but dash, ash and busybox all have it, and rustup and uv
# both rely on that.
BASHISMS = [
    # (?!:) so POSIX character classes — [[:space:]] inside a sed or grep
    # expression — are not mistaken for a bash conditional.
    (re.compile(r"\[\[(?!:)"), "[[ … ]] — use [ … ]"),
    (re.compile(r"\bBASH_SOURCE\b"), "BASH_SOURCE — derive the path from $0"),
    (re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=\(", re.M), "arrays — use \"$@\" or a string"),
    (re.compile(r"^\s*function\s+[A-Za-z_]", re.M), "`function f` — use `f() {`"),
    (re.compile(r"&>"), "&> redirection — use >… 2>&1"),
    (re.compile(r"\+=\("), "array append — use \"$@\""),
    (re.compile(r"^\s*source\s", re.M), "`source` — use `.`"),
    (re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(,,|\^\^)\}"), "case conversion — use tr"),
    (re.compile(r"^\s*echo\s+-[eEn]\b", re.M), "echo -e/-n — use printf"),
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
    if script.name in POSIX_SCRIPTS:
        pytest.skip(f"{script.name} is POSIX sh on purpose — see the test below")
    first = script.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("#!"), f"{script.name} has no shebang"
    assert "bash" in first, f"{script.name} must run under bash, not: {first}"


@pytest.mark.parametrize("name", sorted(POSIX_SCRIPTS))
def test_posix_scripts_use_a_sh_shebang(name: str):
    script = REPO / "scripts" / name
    assert script.is_file(), f"{name} is listed in POSIX_SCRIPTS but does not exist"
    first = script.read_text(encoding="utf-8").splitlines()[0]
    assert first == "#!/bin/sh", (
        f"{name} is piped to `sh` by the documented install command, so it must "
        f"declare #!/bin/sh — found: {first}"
    )


@pytest.mark.parametrize("name", sorted(POSIX_SCRIPTS))
def test_posix_scripts_have_no_bashisms(name: str):
    """The install command is `curl … | sh`, and /bin/sh is **dash** on Debian
    and Ubuntu — the single most common place LeSysBot gets installed.

    Every construct below is fine in bash and a syntax error or silent
    misbehaviour in dash, so one of them slipping in doesn't degrade the
    installer, it makes the advertised one-liner fail outright on the platform
    it fails on hardest to notice from a Mac.
    """
    text = _strip_comments((REPO / "scripts" / name).read_text(encoding="utf-8"))
    problems = []
    for pattern, advice in BASHISMS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            problems.append(f"{name}:{line}: {match.group(0).strip()!r} — {advice}")
    assert not problems, (
        "bash-only syntax in a script that runs under dash:\n  " + "\n  ".join(problems)
    )


@pytest.mark.parametrize("name", sorted(POSIX_SCRIPTS))
def test_posix_scripts_guard_pipefail(name: str):
    """`set -o pipefail` is not POSIX. Asking dash for it fails, and under
    `set -e` that failure aborts the script on its second line — so it has to be
    probed in a subshell first, never requested outright.
    """
    text = _strip_comments((REPO / "scripts" / name).read_text(encoding="utf-8"))
    if "pipefail" not in text:
        return
    assert "(set -o pipefail 2>/dev/null)" in text, (
        f"{name} asks for pipefail without the subshell guard — on dash that "
        f"aborts the script. Use:\n"
        f"    (set -o pipefail 2>/dev/null) && set -o pipefail || true"
    )
    for line in text.splitlines():
        stripped = line.strip()
        if "pipefail" not in stripped or stripped.startswith("(set -o pipefail"):
            continue
        assert stripped.startswith("&& set -o pipefail") or "&& set -o pipefail" in stripped, (
            f"{name}: unguarded pipefail: {stripped!r}"
        )
