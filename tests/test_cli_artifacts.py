"""The `lesysbot` artifact CLI: parser grammar and dispatch over a real temp dir.

"""

from __future__ import annotations

import json

import pytest

from lesysbot.__main__ import build_parser
from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.cli import artifacts as artifact_cli
from lesysbot.cli import dispatch, handles

TOOL = '''
from lesysbot.mcp import tool

@tool(description="say hi")
async def greet() -> str:
    return "hi"
'''


# -- grammar -------------------------------------------------------------------

def test_modern_grammar():
    args = build_parser().parse_args(["install", "acme/repo", "--ref", "v1",
                                      "--only", "a", "--only", "b", "--force", "-y"])
    assert args.command == "install"
    assert args.source == "acme/repo" and args.ref == "v1"
    assert args.only == ["a", "b"] and args.force and args.yes

    assert build_parser().parse_args(["list", "--json"]).as_json
    assert build_parser().parse_args(["update", "--check"]).check
    assert build_parser().parse_args(["doctor"]).command == "doctor"
    assert build_parser().parse_args(["search", "temp"]).query == "temp"




def test_config_flag_both_positions():
    args = build_parser().parse_args(["-c", "root.yaml", "list"])
    assert args.config == "root.yaml"      # leaf SUPPRESS keeps the root value
    assert build_parser().parse_args(["list", "-c", "leaf.yaml"]).config == "leaf.yaml"



def test_cli_owns_the_management_verbs():
    for verb in ("install", "update", "list", "info", "remove", "enable",
                 "disable", "search", "doctor", "dashboard", "setup"):
        assert handles(verb), verb
    for verb in (None, "run", "manage"):
        assert not handles(verb), verb


# -- dispatch ------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic home + cwd: paths anchor to tmp_path (no config file found)."""
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / ".lesysbot"))
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "tools" / "greet"
    pkg.mkdir(parents=True)
    (pkg / "tool.py").write_text(TOOL)
    return tmp_path


def _run(argv: list[str]) -> int:
    return dispatch(build_parser().parse_args(argv))


def _lock(env):
    from lesysbot.artifacts.lockfile import ArtifactLock

    return ArtifactLock(env / "lesysbot.lock.json")


def test_list_shows_tool(env, capsys):
    assert _run(["list"]) == 0
    assert "greet" in capsys.readouterr().out



def test_disable_enable_persist_state(env):
    assert _run(["disable", "greet"]) == 0
    assert json.loads((env / "tool_state.json").read_text())["disabled"] == ["greet"]

    assert _run(["enable", "greet"]) == 0
    assert json.loads((env / "tool_state.json").read_text())["disabled"] == []



def test_unknown_name_errors(env):
    assert _run(["enable", "nope"]) == 1
    assert _run(["info", "nope"]) == 1
    assert _run(["remove", "nope", "-y"]) == 1


def test_info(env, capsys):
    assert _run(["info", "greet"]) == 0
    out = capsys.readouterr().out
    assert "say hi" in out and "tool" in out


def test_remove_deletes_package_and_lock_entry(env):
    lock = _lock(env)
    lock.put(ArtifactKind.TOOL, "greet", {"name": "greet", "kind": "tool",
                                          "repo": "acme/greet"})
    assert _run(["remove", "greet", "-y"]) == 0
    assert not (env / "tools" / "greet").exists()
    assert lock.load() == {}


def test_remove_without_confirmation_aborts(env, monkeypatch):
    monkeypatch.setattr(artifact_cli, "_confirm", lambda msg: False)
    assert _run(["remove", "greet"]) == 0
    assert (env / "tools" / "greet").exists()


def test_install_rejects_a_bare_word(env, capsys):
    """Neither a GitHub link nor a catalog id — must not guess at a download."""
    assert _run(["install", "gpu-temp"]) == 1
    assert "GitHub link" in capsys.readouterr().out


def _installed(name: str = "greet", kind: ArtifactKind = ArtifactKind.TOOL):
    """A stand-in for what the installer reports it placed.

    A real `ArtifactPackage`, not a bare object: the install path reads `kind`
    off these to decide what to provision afterwards.
    """
    from lesysbot.artifacts.manifest import ArtifactPackage

    from pathlib import Path
    return ArtifactPackage(path=Path(name), name=name, kind=kind)


def test_install_dispatches_to_installer(env, monkeypatch):
    from lesysbot.artifacts.installer import InstallResult
    from lesysbot.artifacts.spec import ToolSource

    calls = {}

    class FakeInstaller:
        def __init__(self, destinations, lock_path, *a, **kw):
            calls["destinations"], calls["lock"] = destinations, lock_path

        def install(self, src, **kw):
            calls["src"], calls["kw"] = src, kw
            return InstallResult([_installed()], [])

    monkeypatch.setattr("lesysbot.artifacts.installer.ArtifactInstaller", FakeInstaller)
    assert _run(["install", "acme/repo@v2", "--yes"]) == 0
    assert calls["src"] == ToolSource("acme", "repo", ref="v2")
    assert calls["kw"]["yes"] is True
    assert calls["kw"]["install_deps"] is True           # deps are on by default
    assert calls["destinations"][ArtifactKind.TOOL] == env / "tools"
    assert calls["lock"] == env / "lesysbot.lock.json"


def _fake_installer(monkeypatch, result):
    class FakeInstaller:
        def __init__(self, *a, **kw):
            pass

        def install(self, src, **kw):
            return result

    monkeypatch.setattr("lesysbot.artifacts.installer.ArtifactInstaller", FakeInstaller)


def test_installing_a_dashboard_provisions_it(env, monkeypatch, capsys):
    """"Install it, then go render it" was one step too many.

    A dashboard you just chose should be in Grafana when the command ends.
    """
    from lesysbot.artifacts.installer import InstallResult

    installed = env / ".lesysbot" / "dashboard" / "installed" / "cpu"
    installed.mkdir(parents=True)
    (installed / "dashboard.json").write_text('{"title": "CPU"}')

    _fake_installer(monkeypatch, InstallResult(
        [_installed("cpu", ArtifactKind.DASHBOARD)], []))
    assert _run(["install", "acme/repo", "--yes"]) == 0

    from lesysbot.dashboards.render import OUTPUT_NAME

    generated = (env / ".lesysbot" / "dashboard" / "grafana" / "dashboards"
                 / "generated" / OUTPUT_NAME)
    assert generated.exists(), "installing a dashboard should provision it"
    assert json.loads(generated.read_text())["title"] == "CPU"
    assert "provisioned" in capsys.readouterr().out


def test_a_withheld_dashboard_is_reported_not_hidden(env, monkeypatch, capsys):
    """Withholding is the honest outcome, so it has to be *said*.

    Otherwise the command looks like it worked and Grafana simply has no such
    dashboard — which is the confusion the whole mechanism exists to prevent.
    """
    from lesysbot.artifacts.installer import InstallResult

    from types import SimpleNamespace

    installed = env / ".lesysbot" / "dashboard" / "installed" / "gpu"
    installed.mkdir(parents=True)
    (installed / "dashboard.json").write_text('{"title": "GPU"}')

    # Patched at the renderer's own seam rather than at a checker: `CHECKERS`
    # captures the function objects at import, so patching `check_metric` would
    # be a no-op and this test would pass only because no Prometheus happens to
    # be running on the machine running it.
    monkeypatch.setattr(
        "lesysbot.dashboards.render.check",
        lambda pkg: SimpleNamespace(ok=False, reason="the NVIDIA metric isn't scraped"),
    )
    _fake_installer(monkeypatch, InstallResult(
        [_installed("gpu", ArtifactKind.DASHBOARD)], []))
    assert _run(["install", "acme/repo", "--yes"]) == 0

    out = capsys.readouterr().out
    assert "withheld" in out
    generated = (env / ".lesysbot" / "dashboard" / "grafana" / "dashboards"
                 / "generated" / "gpu.json")
    assert not generated.exists()


def test_installing_only_tools_says_nothing_about_dashboards(env, monkeypatch, capsys):
    from lesysbot.artifacts.installer import InstallResult

    _fake_installer(monkeypatch, InstallResult([_installed("greet")], []))
    assert _run(["install", "acme/repo", "--yes"]) == 0
    assert "provisioned" not in capsys.readouterr().out


def test_no_deps_flag_reaches_the_installer(env, monkeypatch):
    from lesysbot.artifacts.installer import InstallResult

    calls = {}

    class FakeInstaller:
        def __init__(self, *a, **kw):
            pass

        def install(self, src, **kw):
            calls.update(kw)
            return InstallResult([_installed()], [])

    monkeypatch.setattr("lesysbot.artifacts.installer.ArtifactInstaller", FakeInstaller)
    assert _run(["install", "acme/repo", "--yes", "--no-deps"]) == 0
    assert calls["install_deps"] is False



def test_list_shows_install_origin(env, capsys):
    _lock(env).put(ArtifactKind.TOOL, "greet",
                   {"name": "greet", "kind": "tool", "repo": "acme/greet",
                    "commit": "a" * 40})
    assert _run(["list", "--json"]) == 0
    assert "acme/greet@aaaaaaa" in capsys.readouterr().out


def test_update_check_writes_nothing(env, capsys):
    lock = _lock(env)
    lock.put(ArtifactKind.TOOL, "greet",
             {"name": "greet", "kind": "tool", "repo": "acme/greet",
              "commit": "a" * 40, "requested_ref": "main"})
    before = (env / "lesysbot.lock.json").read_text()

    assert _run(["update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "acme/greet" in out and "would be re-fetched" in out
    assert (env / "lesysbot.lock.json").read_text() == before


def test_update_rejects_an_unknown_name(env):
    assert _run(["update", "nope"]) == 1
