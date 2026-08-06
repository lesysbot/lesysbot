"""Kind resolution and routing — `lesysbot install <uri>` for tools *and* dashboards.

The promise is that a user doesn't have to know or say which kind they are
installing. That rests on two things: the kind being inferable from a package
that never mentions it, and each kind landing in its own directory from a single
command. Both are pinned here.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from lesysbot.artifacts.errors import ToolInstallError
from lesysbot.artifacts.installer import ArtifactInstaller
from lesysbot.artifacts.kinds import ArtifactKind, parse_kind
from lesysbot.artifacts.manifest import discover_packages
from lesysbot.artifacts.spec import ToolSource
from tests.install_utils import FakeFetcher, make_github_zip

HEAD_URL = "https://codeload.github.com/acme/repo/zip/HEAD"

TOOL_PY = 'from lesysbot.mcp import tool\n\n@tool(description="hi")\nasync def hi() -> str:\n    return "hi"\n'
DASH_JSON = '{"title": "Test", "panels": []}'
DASH_PY = "def build(host, caps, ctx):\n    return {'title': 'Test', 'panels': []}\n"


def _readme(name, **fields):
    lines = ["---", f"name: {name}"]
    lines += [f"{k}: {v}" for k, v in fields.items()]
    lines += ["---", f"# {name}"]
    return "\n".join(lines) + "\n"


def _installer(tmp_path, fetcher):
    return ArtifactInstaller(
        {ArtifactKind.TOOL: tmp_path / "tools",
         ArtifactKind.DASHBOARD: tmp_path / "dash" / "installed"},
        tmp_path / "lesysbot.lock.json",
        fetcher,
        confirm=lambda _m: True,
        console=Console(file=io.StringIO(), width=200, record=True),
    )


# -- resolution ----------------------------------------------------------------

def test_parse_kind_accepts_known_values():
    assert parse_kind("dashboard") is ArtifactKind.DASHBOARD
    assert parse_kind("TOOL") is ArtifactKind.TOOL


def test_parse_kind_ignores_unknown_values():
    """A package from a future LeSysBot declaring `kind: pack` must fall through
    to payload detection, not fail the whole install."""
    assert parse_kind("pack") is None
    assert parse_kind("") is None and parse_kind(None) is None


def test_package_with_no_frontmatter_is_a_tool(tmp_path):
    pkg = tmp_path / "greet"
    pkg.mkdir()
    (pkg / "tool.py").write_text(TOOL_PY)
    found = discover_packages(tmp_path, "greet")
    assert [(p.name, p.kind) for p in found] == [("greet", ArtifactKind.TOOL)]


@pytest.mark.parametrize("payload,content",
                         [("dashboard.json", DASH_JSON), ("dashboard.py", DASH_PY)])
def test_payload_alone_makes_a_dashboard(tmp_path, payload, content):
    """A plain Grafana export dropped in a repo is installable as-is — the most
    likely thing someone publishes, and it says nothing about itself."""
    pkg = tmp_path / "cpu"
    pkg.mkdir()
    (pkg / payload).write_text(content)
    found = discover_packages(tmp_path, "cpu")
    assert [(p.name, p.kind) for p in found] == [("cpu", ArtifactKind.DASHBOARD)]


def test_explicit_kind_wins_over_the_payload(tmp_path):
    pkg = tmp_path / "odd"
    pkg.mkdir()
    (pkg / "dashboard.json").write_text(DASH_JSON)
    (pkg / "README.md").write_text(_readme("odd", kind="tool"))
    assert discover_packages(tmp_path, "odd")[0].kind is ArtifactKind.TOOL


def test_collection_dirs_are_both_scanned(tmp_path):
    for sub, payload, content in (("tools", "tool.py", TOOL_PY),
                                  ("dashboards", "dashboard.json", DASH_JSON)):
        pkg = tmp_path / sub / f"a-{sub}"
        pkg.mkdir(parents=True)
        (pkg / payload).write_text(content)
    found = {p.name: p.kind for p in discover_packages(tmp_path, "repo")}
    assert found == {"a-tools": ArtifactKind.TOOL,
                     "a-dashboards": ArtifactKind.DASHBOARD}


# -- routing -------------------------------------------------------------------

def _mixed_repo() -> bytes:
    return make_github_zip("repo-HEAD", {
        "tools/greet/tool.py": TOOL_PY,
        "tools/greet/README.md": _readme("greet"),
        "dashboards/cpu/dashboard.json": DASH_JSON,
        "dashboards/cpu/README.md": _readme("cpu", kind="dashboard"),
    })


def test_one_uri_installs_both_kinds_to_their_own_dirs(tmp_path):
    """The headline behaviour: one command, one repo, each package where it belongs."""
    installer = _installer(tmp_path, FakeFetcher({HEAD_URL: _mixed_repo()}))
    result = installer.install(ToolSource("acme", "repo"), yes=True)

    assert sorted(result.names) == ["cpu", "greet"]
    assert (tmp_path / "tools" / "greet" / "tool.py").is_file()
    assert (tmp_path / "dash" / "installed" / "cpu" / "dashboard.json").is_file()


def test_lock_records_each_kind_separately(tmp_path):
    installer = _installer(tmp_path, FakeFetcher({HEAD_URL: _mixed_repo()}))
    installer.install(ToolSource("acme", "repo"), yes=True)

    lock = installer.lock
    assert set(lock.load()) == {"tool:greet", "dashboard:cpu"}
    assert list(lock.of_kind(ArtifactKind.DASHBOARD)) == ["cpu"]
    assert list(lock.of_kind(ArtifactKind.TOOL)) == ["greet"]


def test_kind_filter_installs_only_that_kind(tmp_path):
    installer = _installer(tmp_path, FakeFetcher({HEAD_URL: _mixed_repo()}))
    result = installer.install(ToolSource("acme", "repo"), yes=True,
                               kind=ArtifactKind.TOOL)

    assert result.names == ["greet"]
    assert not (tmp_path / "dash" / "installed" / "cpu").exists()


def test_kind_filter_errors_when_nothing_matches(tmp_path):
    zipped = make_github_zip("repo-HEAD", {"tools/greet/tool.py": TOOL_PY})
    installer = _installer(tmp_path, FakeFetcher({HEAD_URL: zipped}))
    with pytest.raises(ToolInstallError, match="No dashboard packages"):
        installer.install(ToolSource("acme", "repo"), yes=True,
                          kind=ArtifactKind.DASHBOARD)


def test_same_name_in_both_kinds_does_not_collide(tmp_path):
    """"postgres" is a plausible name for a tool *and* a dashboard; they land in
    different directories, so nothing but the lock key would keep them apart."""
    zipped = make_github_zip("repo-HEAD", {
        "tools/postgres/tool.py": TOOL_PY,
        "dashboards/postgres/dashboard.json": DASH_JSON,
    })
    installer = _installer(tmp_path, FakeFetcher({HEAD_URL: zipped}))
    installer.install(ToolSource("acme", "repo"), yes=True)

    assert (tmp_path / "tools" / "postgres").is_dir()
    assert (tmp_path / "dash" / "installed" / "postgres").is_dir()
    assert set(installer.lock.load()) == {"tool:postgres", "dashboard:postgres"}
