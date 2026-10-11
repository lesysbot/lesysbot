import io
import json

import pytest
from rich.console import Console

from lesysbot.mcp import ToolRegistry
from lesysbot.artifacts.errors import ToolInstallError
from lesysbot.artifacts.installer import ArtifactInstaller
from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.artifacts.spec import ToolSource
from tests.install_utils import SHA, FakeFetcher, make_github_zip, package_files


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, record=True)


def _manager(tmp_path, fetcher, confirm=lambda _msg: True):
    return ArtifactInstaller(
        {ArtifactKind.TOOL: tmp_path / "tools"},
        tmp_path / "lesysbot.lock.json",
        fetcher,
        confirm=confirm,
        console=_console(),
    )


def _lock(tmp_path) -> dict:
    """Lock entries keyed by bare name, for assertions."""
    raw = json.loads((tmp_path / "lesysbot.lock.json").read_text())["artifacts"]
    return {key.split(":", 1)[-1]: entry for key, entry in raw.items()}


def _repo_zip(*names: str, extra: dict[str, str] | None = None) -> bytes:
    files: dict[str, str] = dict(extra or {})
    for name in names:
        for rel, content in package_files(name).items():
            files[f"{name}/{rel}"] = content
    return make_github_zip("repo-HEAD", files)


HEAD_URL = "https://codeload.github.com/acme/repo/zip/HEAD"


def test_install_multi_package(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha", "beta")})
    mgr = _manager(tmp_path, fetcher)
    installed = mgr.install(ToolSource("acme", "repo"), yes=True)

    assert installed.names == ["alpha", "beta"]
    assert (tmp_path / "tools" / "alpha" / "tool.py").exists()
    assert (tmp_path / "tools" / "beta" / "README.md").exists()

    lock = _lock(tmp_path)
    assert lock["alpha"]["repo"] == "acme/repo"
    assert lock["alpha"]["subdir"] == "alpha"
    assert lock["alpha"]["commit"] == SHA
    assert lock["alpha"]["version"] == "1.2.0"
    # No stray staging dirs left behind.
    assert not list(tmp_path.glob(".lesysbot-stage-*"))


def test_install_subdir_single_package(tmp_path):
    files = {f"tools/gpu/{rel}": c for rel, c in package_files("gpu").items()}
    fetcher = FakeFetcher({HEAD_URL: make_github_zip("repo-HEAD", files)})
    mgr = _manager(tmp_path, fetcher)
    installed = mgr.install(ToolSource("acme", "repo", subdir="tools/gpu"), yes=True)

    assert installed.names == ["gpu"]
    lock = _lock(tmp_path)
    assert lock["gpu"]["subdir"] == "tools/gpu"


def test_install_only_filter(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha", "beta")})
    mgr = _manager(tmp_path, fetcher)
    installed = mgr.install(ToolSource("acme", "repo"), only=["beta"], yes=True)
    assert installed.names == ["beta"]
    assert not (tmp_path / "tools" / "alpha").exists()

    with pytest.raises(ToolInstallError, match="not found"):
        mgr.install(ToolSource("acme", "repo"), only=["nope"], yes=True)


def test_install_empty_repo_errors(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: make_github_zip("repo-HEAD", {"README.md": "hi"})})
    mgr = _manager(tmp_path, fetcher)
    with pytest.raises(ToolInstallError, match="No packages found"):
        mgr.install(ToolSource("acme", "repo"), yes=True)


def test_install_declined_confirmation(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher, confirm=lambda _msg: False)
    assert mgr.install(ToolSource("acme", "repo")).names == []
    assert not (tmp_path / "tools" / "alpha").exists()
    assert not list(tmp_path.glob(".lesysbot-stage-*"))


def test_collision_with_unmanaged_dir(tmp_path):
    (tmp_path / "tools" / "alpha").mkdir(parents=True)
    (tmp_path / "tools" / "alpha" / "tool.py").write_text("mine = 1")
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)

    with pytest.raises(ToolInstallError, match="--force"):
        mgr.install(ToolSource("acme", "repo"), yes=True)
    assert (tmp_path / "tools" / "alpha" / "tool.py").read_text() == "mine = 1"

    mgr.install(ToolSource("acme", "repo"), yes=True, force=True)
    assert "hello" in (tmp_path / "tools" / "alpha" / "tool.py").read_text()


def test_reinstall_of_managed_package(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)
    first = _lock(tmp_path)["alpha"]

    # Same name again — owned by the lock, so no --force needed.
    mgr.install(ToolSource("acme", "repo"), yes=True)
    second = _lock(tmp_path)["alpha"]
    assert second["installed_at"] == first["installed_at"]


def test_requirements_are_installed_by_default(tmp_path, monkeypatch):
    """Dependencies now install as part of the same consent, rather than being
    printed for the user to run — the package is usable when the command ends."""
    from lesysbot.artifacts import deps

    monkeypatch.delenv(deps.SKIP_ENV, raising=False)
    calls = []
    monkeypatch.setattr(deps, "can_install", lambda: (True, None))
    monkeypatch.setattr(
        deps.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or _completed(cmd),
    )

    fetcher = FakeFetcher(
        {HEAD_URL: _repo_zip("alpha", extra={"alpha/requirements.txt": "httpx\n"})}
    )
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)

    assert any("install" in c and "httpx" in c for c in calls), calls
    assert (tmp_path / "tools" / "alpha" / "requirements.txt").exists()
    # Recorded, so `lesysbot info` can say what was pulled in on your behalf.
    assert _lock(tmp_path)["alpha"]["deps"] == ["httpx"]


def _completed(cmd):
    import subprocess

    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_requirements_print_the_command_when_pip_is_unavailable(tmp_path):
    """A frozen build has no pip; the package still installs and says what to run."""
    fetcher = FakeFetcher(
        {HEAD_URL: _repo_zip("alpha", extra={"alpha/requirements.txt": "httpx\n"})}
    )
    mgr = _manager(tmp_path, fetcher)          # conftest sets SKIP_ENV
    mgr.install(ToolSource("acme", "repo"), yes=True)
    out = mgr.console.export_text()
    assert "pip install" in out and "httpx" in out
    assert (tmp_path / "tools" / "alpha" / "requirements.txt").exists()


def test_registry_remove_plus_drop_entries_clears_lock(tmp_path):
    """Removal contract: registry deletes the package, drop_entries cleans the lock."""
    from lesysbot.artifacts.lockfile import drop_entries

    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)

    registry = ToolRegistry()
    registry.load_directory(tmp_path / "tools")
    info = registry.remove_tool("hello")
    assert not (tmp_path / "tools" / "alpha").exists()
    assert drop_entries(tmp_path / "lesysbot.lock.json", [info["unit"]]) == ["alpha"]
    assert _lock(tmp_path) == {}


def test_installed_package_loads_in_registry(tmp_path):
    """Contract with the existing loader: an installed package's tools register."""
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)

    registry = ToolRegistry()
    registry.load_directory(tmp_path / "tools")
    assert "hello" in registry.names


# -- installing from a path on this machine ------------------------------------
# The copy-paste story with the checks kept. Everything past staging is the same
# code the GitHub path runs, so these pin the two things that genuinely differ:
# how a payload reaches staging, and what provenance gets recorded.

def _write_package(root, name: str) -> None:
    pkg = root / name
    pkg.mkdir(parents=True)
    for rel, content in package_files(name).items():
        (pkg / rel).write_text(content)


def test_install_path_from_a_folder(tmp_path):
    _write_package(tmp_path / "src", "greet")
    mgr = _manager(tmp_path, FakeFetcher())

    installed = mgr.install_path(tmp_path / "src" / "greet", yes=True)

    assert installed.names == ["greet"]
    assert (tmp_path / "tools" / "greet" / "tool.py").exists()


def test_install_path_records_the_path_and_no_repo(tmp_path):
    """No `repo` is what keeps `lesysbot update` (a re-fetch) away from it."""
    _write_package(tmp_path / "src", "greet")
    mgr = _manager(tmp_path, FakeFetcher())
    mgr.install_path(tmp_path / "src" / "greet", yes=True)

    entry = _lock(tmp_path)["greet"]
    assert entry["path"] == str((tmp_path / "src" / "greet").resolve())
    assert "repo" not in entry
    assert entry["version"] == "1.2.0"          # frontmatter is still read


def test_install_path_from_a_repo_shaped_folder(tmp_path):
    """A folder holding `tools/` installs every package under it, like a repo."""
    _write_package(tmp_path / "src" / "tools", "alpha")
    _write_package(tmp_path / "src" / "tools", "beta")
    mgr = _manager(tmp_path, FakeFetcher())

    installed = mgr.install_path(tmp_path / "src", yes=True)

    assert sorted(installed.names) == ["alpha", "beta"]
    assert (tmp_path / "tools" / "alpha" / "tool.py").exists()
    assert (tmp_path / "tools" / "beta" / "tool.py").exists()


def test_install_path_from_a_zip(tmp_path):
    """A plain `zip -r greet.zip greet/` — one top-level dir, like a zipball."""
    archive = tmp_path / "greet.zip"
    archive.write_bytes(make_github_zip("greet", package_files("greet"),
                                        comment_sha=None))
    mgr = _manager(tmp_path, FakeFetcher())

    assert mgr.install_path(archive, yes=True).names == ["greet"]
    assert (tmp_path / "tools" / "greet" / "tool.py").exists()


def test_reinstalling_a_local_package_is_an_update(tmp_path):
    """Re-running it must not need --force: the lock knows it put that dir there."""
    _write_package(tmp_path / "src", "greet")
    mgr = _manager(tmp_path, FakeFetcher())
    mgr.install_path(tmp_path / "src" / "greet", yes=True)

    (tmp_path / "src" / "greet" / "tool.py").write_text(
        package_files("greet")["tool.py"] + "\n# edited\n"
    )
    assert mgr.install_path(tmp_path / "src" / "greet", yes=True).names == ["greet"]
    assert "# edited" in (tmp_path / "tools" / "greet" / "tool.py").read_text()


def test_install_path_refuses_a_hand_copied_dir_without_force(tmp_path):
    """Same rule as a GitHub install: never clobber what the lock never placed."""
    _write_package(tmp_path / "src", "greet")
    _write_package(tmp_path / "tools", "greet")
    mgr = _manager(tmp_path, FakeFetcher())

    with pytest.raises(ToolInstallError, match="--force"):
        mgr.install_path(tmp_path / "src" / "greet", yes=True)

    assert mgr.install_path(tmp_path / "src" / "greet", yes=True, force=True)


def test_install_path_skips_pycache_and_git(tmp_path):
    _write_package(tmp_path / "src", "greet")
    (tmp_path / "src" / "greet" / "__pycache__").mkdir()
    (tmp_path / "src" / "greet" / "__pycache__" / "tool.pyc").write_text("junk")
    (tmp_path / "src" / "greet" / ".gitignore").write_text("*.pyc")
    mgr = _manager(tmp_path, FakeFetcher())

    mgr.install_path(tmp_path / "src" / "greet", yes=True)

    assert not (tmp_path / "tools" / "greet" / "__pycache__").exists()
    assert not (tmp_path / "tools" / "greet" / ".gitignore").exists()


def test_install_path_rejects_a_missing_path(tmp_path):
    mgr = _manager(tmp_path, FakeFetcher())
    with pytest.raises(ToolInstallError, match="No such file or directory"):
        mgr.install_path(tmp_path / "nope")


def test_install_path_rejects_a_plain_file(tmp_path):
    loose = tmp_path / "tool.py"
    loose.write_text("x = 1\n")
    mgr = _manager(tmp_path, FakeFetcher())
    with pytest.raises(ToolInstallError, match="not a folder or a .zip"):
        mgr.install_path(loose)


def test_install_path_honours_the_consent_prompt(tmp_path):
    _write_package(tmp_path / "src", "greet")
    seen = []

    def refuse(message):
        seen.append(message)
        return False

    mgr = _manager(tmp_path, FakeFetcher(), confirm=refuse)
    result = mgr.install_path(tmp_path / "src" / "greet")

    assert not result and result.skipped
    assert not (tmp_path / "tools" / "greet").exists()
    assert str(tmp_path / "src" / "greet") in seen[0]
