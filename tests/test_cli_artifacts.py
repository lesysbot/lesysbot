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


def test_install_dispatches_to_installer(env, monkeypatch):
    from lesysbot.artifacts.installer import InstallResult
    from lesysbot.artifacts.spec import ToolSource

    calls = {}

    class FakeInstaller:
        def __init__(self, destinations, lock_path, *a, **kw):
            calls["destinations"], calls["lock"] = destinations, lock_path

        def install(self, src, **kw):
            calls["src"], calls["kw"] = src, kw
            return InstallResult([object()], [])

    monkeypatch.setattr("lesysbot.artifacts.installer.ArtifactInstaller", FakeInstaller)
    assert _run(["install", "acme/repo@v2", "--yes"]) == 0
    assert calls["src"] == ToolSource("acme", "repo", ref="v2")
    assert calls["kw"]["yes"] is True
    assert calls["kw"]["install_deps"] is True           # deps are on by default
    assert calls["destinations"][ArtifactKind.TOOL] == env / "tools"
    assert calls["lock"] == env / "lesysbot.lock.json"


def test_no_deps_flag_reaches_the_installer(env, monkeypatch):
    from lesysbot.artifacts.installer import InstallResult

    calls = {}

    class FakeInstaller:
        def __init__(self, *a, **kw):
            pass

        def install(self, src, **kw):
            calls.update(kw)
            return InstallResult([object()], [])

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
