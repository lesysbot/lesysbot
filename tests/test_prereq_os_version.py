"""OS-version gating: `os_version: ">=14"` in a package manifest.

The reason this exists separately from `os:` is that the OS name alone is not
enough to know whether a package will work. Exporter metric names move between
releases, so Ubuntu 22.04 vs 24.04 is a real behavioural gap for some
dashboards even though the OS itself is a given.

The load-bearing rule: **an undeterminable version passes.** A machine whose
/etc/os-release we cannot read is a detection gap on our side, and turning that
into a refusal to install would push our problem onto the user.
"""

from __future__ import annotations

import pytest

from lesysbot.prereq import Requirement, check
from lesysbot.prereq import checks as checks_mod


@pytest.fixture
def version(monkeypatch):
    """Pin the reported OS version for the duration of a test."""
    def _set(value: str) -> None:
        monkeypatch.setattr("lesysbot.core.host.os_version", lambda: value)
    return _set


def _check(value: str):
    return check(Requirement("os_version", value))


# -- comparison ----------------------------------------------------------------

@pytest.mark.parametrize("here,want", [
    ("14.5", ">=14"),
    ("14.5", ">=14.5"),
    ("15.0", ">=14.5"),
    ("14.5.1", ">=14.5"),
    ("11", ">=10"),
])
def test_satisfied_minimums(version, here, want):
    version(here)
    assert _check(want).satisfied


@pytest.mark.parametrize("here,want", [
    ("13.6", ">=14"),
    ("14.4", ">=14.5"),
    ("9", ">=10"),
])
def test_unsatisfied_minimums(version, here, want):
    version(here)
    result = _check(want)
    assert not result.satisfied
    assert here in result.detail          # the reason names the actual version


def test_a_bare_value_means_at_least(version):
    """What a manifest almost always intends: needs 14, works on 15."""
    version("15.1")
    assert _check("14").satisfied


def test_exact_match_compares_only_as_precisely_as_asked(version):
    version("14.5.1")
    assert _check("==14").satisfied         # any 14.x
    assert _check("==14.5").satisfied
    assert not _check("==15").satisfied


def test_strictly_greater(version):
    version("14.5")
    assert _check(">14").satisfied
    assert not _check(">14.5").satisfied


# -- the failure modes that must not become hard failures ----------------------

def test_an_unknown_version_passes(version):
    """A detection gap on our side must not block the user's install."""
    version("")
    result = _check(">=14")
    assert result.satisfied
    assert "unknown" in result.detail


def test_an_unparseable_requirement_passes(version):
    version("14.5")
    assert _check("sonoma").satisfied
    assert _check("").satisfied


def test_non_numeric_version_components_do_not_raise(version):
    version("22.04.1-ubuntu")
    assert _check(">=22").satisfied


# -- detection -----------------------------------------------------------------

def test_linux_version_comes_from_os_release_not_the_kernel(tmp_path, monkeypatch):
    """A dashboard cares which Ubuntu this is, not which kernel."""
    from lesysbot.core import host as platform_mod

    release = tmp_path / "os-release"
    release.write_text('NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\n')

    real_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda path, *a, **kw: real_open(
            release if path == "/etc/os-release" else path, *a, **kw),
    )
    monkeypatch.setattr(platform_mod.platform, "system", lambda: "Linux")
    assert platform_mod.os_version() == "24.04"


def test_a_missing_os_release_is_empty_not_an_error(monkeypatch):
    from lesysbot.core import host as platform_mod

    def _raise(*_a, **_kw):
        raise OSError("nope")

    monkeypatch.setattr("builtins.open", _raise)
    monkeypatch.setattr(platform_mod.platform, "system", lambda: "Linux")
    assert platform_mod.os_version() == ""


def test_the_checker_is_registered_under_both_spellings():
    assert "os_version" in checks_mod.CHECKERS
    assert checks_mod.CHECKERS["os-version"] is checks_mod.CHECKERS["os_version"]
