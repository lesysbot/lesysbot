"""The artifact lock: entry keying, and `preserve:` across updates.

An update must not eat a file the user edited — one of the two ways a package
manager loses somebody's trust permanently.
"""

from __future__ import annotations

import io

from rich.console import Console

from lesysbot.artifacts.installer import ArtifactInstaller
from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.artifacts.lockfile import ArtifactLock, drop_entries
from lesysbot.artifacts.spec import ToolSource
from tests.install_utils import FakeFetcher, make_github_zip

HEAD_URL = "https://codeload.github.com/acme/repo/zip/HEAD"
TOOL_PY = 'from lesysbot.mcp import tool\n\n@tool(description="hi")\nasync def hi() -> str:\n    return "hi"\n'


# -- drop ----------------------------------------------------------------------

def test_drop_removes_one_kind_when_told(tmp_path):
    lock = ArtifactLock(tmp_path / "lesysbot.lock.json")
    lock.put(ArtifactKind.TOOL, "pg", {"name": "pg", "kind": "tool"})
    lock.put(ArtifactKind.DASHBOARD, "pg", {"name": "pg", "kind": "dashboard"})

    assert drop_entries(tmp_path / "lesysbot.lock.json", ["pg"], ArtifactKind.TOOL) == ["pg"]
    assert set(lock.load()) == {"dashboard:pg"}


def test_drop_without_a_kind_removes_every_match(tmp_path):
    lock = ArtifactLock(tmp_path / "lesysbot.lock.json")
    lock.put(ArtifactKind.TOOL, "pg", {"name": "pg", "kind": "tool"})
    lock.put(ArtifactKind.DASHBOARD, "pg", {"name": "pg", "kind": "dashboard"})

    assert drop_entries(tmp_path / "lesysbot.lock.json", ["pg"]) == ["pg", "pg"]
    assert lock.load() == {}


def test_drop_reports_only_what_was_present(tmp_path):
    lock = ArtifactLock(tmp_path / "lesysbot.lock.json")
    lock.put(ArtifactKind.TOOL, "pg", {"name": "pg", "kind": "tool"})
    assert drop_entries(tmp_path / "lesysbot.lock.json", ["pg", "nope"]) == ["pg"]


# -- preserve across updates ---------------------------------------------------

def _installer(tmp_path, fetcher):
    return ArtifactInstaller(
        {ArtifactKind.TOOL: tmp_path / "tools"},
        tmp_path / "lesysbot.lock.json",
        fetcher,
        confirm=lambda _m: True,
        console=Console(file=io.StringIO(), width=200, record=True),
    )


def _repo(tool_body: str, preserve: str = "") -> bytes:
    readme = "---\nname: alpha\n" + (f"preserve: [{preserve}]\n" if preserve else "") + "---\n"
    return make_github_zip("repo-HEAD", {
        "alpha/tool.py": tool_body,
        "alpha/README.md": readme,
    })


def test_preserved_file_survives_an_update(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo(TOOL_PY, preserve='".env"')})
    installer = _installer(tmp_path, fetcher)
    installer.install(ToolSource("acme", "repo"), yes=True)

    env = tmp_path / "tools" / "alpha" / ".env"
    env.write_text("MY_TOKEN=secret\n")

    # A newer release of the same package.
    fetcher.responses[HEAD_URL] = _repo(TOOL_PY + "\n# v2\n", preserve='".env"')
    installer.install(ToolSource("acme", "repo"), yes=True)

    assert env.read_text() == "MY_TOKEN=secret\n"
    assert "# v2" in (tmp_path / "tools" / "alpha" / "tool.py").read_text()


def test_unpreserved_file_is_replaced_by_an_update(tmp_path):
    """Only what the manifest names survives; everything else is program code."""
    fetcher = FakeFetcher({HEAD_URL: _repo(TOOL_PY)})
    installer = _installer(tmp_path, fetcher)
    installer.install(ToolSource("acme", "repo"), yes=True)
    (tmp_path / "tools" / "alpha" / "scratch.txt").write_text("mine")

    installer.install(ToolSource("acme", "repo"), yes=True)
    assert not (tmp_path / "tools" / "alpha" / "scratch.txt").exists()


def test_preserve_cannot_escape_the_package(tmp_path):
    """A manifest is written by somebody else — `../../.ssh/id_rsa` must not copy."""
    outside = tmp_path / "secret.txt"
    outside.write_text("do not touch")

    fetcher = FakeFetcher({HEAD_URL: _repo(TOOL_PY, preserve='"../../secret.txt"')})
    installer = _installer(tmp_path, fetcher)
    installer.install(ToolSource("acme", "repo"), yes=True)
    installer.install(ToolSource("acme", "repo"), yes=True)

    assert outside.read_text() == "do not touch"
    # Nothing was copied *into* the package either — the entry is refused
    # outright rather than resolved to something harmless-looking.
    contents = sorted(p.name for p in (tmp_path / "tools" / "alpha").iterdir())
    assert contents == ["README.md", "tool.py"]
    assert "escapes the package" in installer.console.export_text()


def test_missing_preserve_entry_is_not_an_error(tmp_path):
    """A `.env` the user never created must not fail the update."""
    fetcher = FakeFetcher({HEAD_URL: _repo(TOOL_PY, preserve='".env"')})
    installer = _installer(tmp_path, fetcher)
    installer.install(ToolSource("acme", "repo"), yes=True)
    result = installer.install(ToolSource("acme", "repo"), yes=True)
    assert result.names == ["alpha"]


def test_reinstall_keeps_installed_at_and_moves_updated_at(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo(TOOL_PY)})
    installer = _installer(tmp_path, fetcher)
    installer.install(ToolSource("acme", "repo"), yes=True)
    first = installer.lock.get(ArtifactKind.TOOL, "alpha")

    installer.install(ToolSource("acme", "repo"), yes=True)
    second = installer.lock.get(ArtifactKind.TOOL, "alpha")

    assert second["installed_at"] == first["installed_at"]
    assert second["updated_at"] >= first["updated_at"]
