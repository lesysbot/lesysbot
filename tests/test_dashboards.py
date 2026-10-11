"""The one dashboard: `lesysbot dashboard`, customize/reset, and the leftovers
an upgrade from dashboard *packages* has to clean up.

The rule these pin: by default the dashboard is generated for the machine, and a
user who wants to change it gets their own file — which nothing LeSysBot does
afterwards (start, setup, upgrade) is allowed to overwrite.
"""

from __future__ import annotations

import json

import pytest

from lesysbot.__main__ import build_parser
from lesysbot.cli import dispatch
from lesysbot.core.paths import custom_dashboard_path, generated_dashboards_dir


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A hermetic ~/.lesysbot holding an installed stack with a generated dashboard."""
    home = tmp_path / ".lesysbot"
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("lesysbot.core.grafana.detect_grafana", lambda base=None: None)
    generated = generated_dashboards_dir(home)
    generated.mkdir(parents=True)
    (generated / "system-overview.json").write_text(
        json.dumps({"uid": "lesysbot-node", "title": "This host"}))
    return home


def _run(*argv: str) -> int:
    return dispatch(build_parser().parse_args(["dashboard", *argv]))


def test_bare_command_says_the_dashboard_is_automatic(home, capsys):
    assert _run() == 0
    out = capsys.readouterr().out
    assert "automatic" in out and "lesysbot dashboard customize" in out
    assert "not running" in out


def test_customize_copies_what_grafana_shows(home, capsys):
    assert _run("customize") == 0
    custom = custom_dashboard_path(home)
    assert json.loads(custom.read_text())["title"] == "This host"
    assert "dashboard.json" in capsys.readouterr().out

    assert _run() == 0
    assert "yours" in capsys.readouterr().out


def test_customize_never_overwrites_an_existing_copy(home):
    custom = custom_dashboard_path(home)
    custom.write_text('{"title": "mine"}')
    assert _run("customize") == 0
    assert custom.read_text() == '{"title": "mine"}'


def test_customize_falls_back_to_the_bundled_dashboard(home):
    """A stack that never started has no generated copy to start from."""
    for f in generated_dashboards_dir(home).glob("*.json"):
        f.unlink()
    assert _run("customize") == 0
    assert json.loads(custom_dashboard_path(home).read_text())["uid"]


def test_customize_without_a_stack_says_to_run_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / ".lesysbot"))
    monkeypatch.chdir(tmp_path)
    assert _run("customize") == 1
    assert "lesysbot setup" in capsys.readouterr().out


def test_reset_keeps_a_backup(home, capsys):
    custom = custom_dashboard_path(home)
    custom.write_text('{"title": "mine"}')
    assert _run("reset") == 0
    assert not custom.exists()
    assert custom.with_name("dashboard.json.bak").read_text() == '{"title": "mine"}'
    assert "automatic" in capsys.readouterr().out


def test_reset_when_already_automatic(home, capsys):
    assert _run("reset") == 0
    assert "already" in capsys.readouterr().out


# -- installing a dashboard is turned away, with directions ----------------------

def test_installing_a_dashboard_folder_points_at_customize(tmp_path):
    from rich.console import Console

    from lesysbot.artifacts.errors import ToolInstallError
    from lesysbot.artifacts.installer import ArtifactInstaller
    from lesysbot.artifacts.kinds import ArtifactKind

    folder = tmp_path / "my-dashboard"
    folder.mkdir()
    (folder / "dashboard.json").write_text("{}")
    installer = ArtifactInstaller({ArtifactKind.TOOL: tmp_path / "tools"},
                                  tmp_path / "lock.json", console=Console(quiet=True))
    with pytest.raises(ToolInstallError, match="dashboard customize"):
        installer.install_path(folder, yes=True)
    assert not (tmp_path / "tools" / "my-dashboard").exists()


def test_a_dashboard_py_is_not_mistaken_for_a_tool(tmp_path):
    from lesysbot.artifacts.manifest import discover_packages

    (tmp_path / "dashboard.py").write_text("def build(host, caps, ctx): return {}\n")
    assert discover_packages(tmp_path, "x") == []


# -- upgrading from dashboard packages -----------------------------------------

def test_setup_retires_old_dashboard_packages(home):
    from lesysbot.artifacts.lockfile import ArtifactLock
    from lesysbot.setup import apply

    installed = home / "dashboard" / "installed" / "gpu-detail"
    installed.mkdir(parents=True)
    (installed / "dashboard.py").write_text("")
    stale = generated_dashboards_dir(home) / "gpu-detail.json"
    stale.write_text("{}")
    custom = custom_dashboard_path(home)
    custom.write_text('{"title": "mine"}')
    lock = ArtifactLock(home / "lesysbot.lock.json")
    lock.save({
        "dashboard:gpu-detail": {"name": "gpu-detail", "kind": "dashboard", "bundled": True},
        "tool:greet": {"name": "greet", "kind": "tool"},
    })

    assert apply.retire_dashboard_packages(home) is True
    assert not installed.parent.exists()
    assert not stale.exists()
    assert (generated_dashboards_dir(home) / "system-overview.json").exists()
    assert custom.read_text() == '{"title": "mine"}'
    assert set(lock.load()) == {"tool:greet"}

    assert apply.retire_dashboard_packages(home) is False      # idempotent


def test_update_skips_retired_dashboard_entries(home, capsys):
    from lesysbot.artifacts.lockfile import ArtifactLock

    # No config file, so the lock anchors to the cwd, not the home.
    ArtifactLock(home.parent / "lesysbot.lock.json").save({
        "dashboard:x": {"name": "x", "kind": "dashboard", "repo": "acme/x"},
    })
    assert dispatch(build_parser().parse_args(["update", "--check"])) == 0
    assert "Nothing to update" in capsys.readouterr().out
