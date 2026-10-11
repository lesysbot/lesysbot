"""Kinds after dashboards stopped being packages.

Only tools install now. What is pinned here is the upgrade edge: an old lock or
an old repo may still say "dashboard", and that must read as "not something
this version installs" — never as a crash, and never as a tool.
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


def _installer(tmp_path, fetcher):
    return ArtifactInstaller(
        {ArtifactKind.TOOL: tmp_path / "tools"},
        tmp_path / "lesysbot.lock.json",
        fetcher,
        confirm=lambda _m: True,
        console=Console(file=io.StringIO(), width=200, record=True),
    )


def test_parse_kind_reads_tool_and_nothing_else():
    assert parse_kind("TOOL") is ArtifactKind.TOOL
    assert parse_kind("dashboard") is None
    assert parse_kind("") is None and parse_kind(None) is None


def test_package_with_no_frontmatter_is_a_tool(tmp_path):
    pkg = tmp_path / "greet"
    pkg.mkdir()
    (pkg / "tool.py").write_text(TOOL_PY)
    found = discover_packages(tmp_path, "greet")
    assert [(p.name, p.kind) for p in found] == [("greet", ArtifactKind.TOOL)]


def test_a_repo_holding_tools_and_dashboards_installs_only_the_tools(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: make_github_zip("repo-HEAD", {
        "tools/greet/tool.py": TOOL_PY,
        "dashboards/cpu/dashboard.json": DASH_JSON,
    })})
    installer = _installer(tmp_path, fetcher)
    result = installer.install(ToolSource("acme", "repo"), yes=True)
    assert [p.name for p in result.installed] == ["greet"]
    assert set(installer.lock.load()) == {"tool:greet"}


def test_a_dashboard_only_repo_is_refused_with_directions(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: make_github_zip("repo-HEAD", {"dashboard.json": DASH_JSON})})
    with pytest.raises(ToolInstallError, match="dashboard customize"):
        _installer(tmp_path, fetcher).install(ToolSource("acme", "repo"), yes=True)
