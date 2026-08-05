import io
import zipfile

import pytest

from lesysbot.artifacts import archive
from lesysbot.artifacts.archive import extract_tree, zip_commit_sha, zip_root
from lesysbot.artifacts.errors import ArchiveError
from tests.install_utils import SHA, make_github_zip


def test_zip_commit_sha_from_comment():
    data = make_github_zip("repo-main", {"a.txt": "hi"})
    assert zip_commit_sha(data) == SHA


def test_zip_commit_sha_missing_or_junk():
    assert zip_commit_sha(make_github_zip("r", {"a": "x"}, comment_sha=None)) is None
    assert zip_commit_sha(make_github_zip("r", {"a": "x"}, comment_sha="not-a-sha")) is None
    assert zip_commit_sha(b"not a zip") is None


def test_extract_full_tree(tmp_path):
    data = make_github_zip("repo-main", {"tool.py": "x = 1", "sub/helper.txt": "h"})
    dest = tmp_path / "out"
    extract_tree(data, None, dest)
    assert (dest / "tool.py").read_text() == "x = 1"
    assert (dest / "sub" / "helper.txt").read_text() == "h"


def test_extract_subdir_only(tmp_path):
    data = make_github_zip(
        "repo-main",
        {"tools/a/tool.py": "a", "tools/b/tool.py": "b", "README.md": "root"},
    )
    dest = tmp_path / "out"
    extract_tree(data, "tools/a", dest)
    assert (dest / "tool.py").read_text() == "a"
    assert not (dest / "README.md").exists()
    assert not (dest / "b").exists()


def test_extract_missing_subdir(tmp_path):
    data = make_github_zip("repo-main", {"tool.py": "x"})
    with pytest.raises(ArchiveError, match="not found"):
        extract_tree(data, "nope", tmp_path / "out")


def test_pycache_and_git_skipped(tmp_path):
    data = make_github_zip(
        "repo-main",
        {"tool.py": "x", "__pycache__/tool.cpython-311.pyc": "junk", ".github/ci.yml": "y"},
    )
    dest = tmp_path / "out"
    extract_tree(data, None, dest)
    assert (dest / "tool.py").exists()
    assert not (dest / "__pycache__").exists()
    assert not (dest / ".github").exists()


def test_zip_slip_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("root/ok.txt", "ok")
        zf.writestr("root/../evil.txt", "evil")
    with pytest.raises(ArchiveError, match="unsafe|top-level"):
        extract_tree(buf.getvalue(), None, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_nested_dotdot_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("root/sub/../../../evil.txt", "evil")
    with pytest.raises(ArchiveError):
        extract_tree(buf.getvalue(), None, tmp_path / "out")


def test_absolute_path_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/etc/evil.txt", "evil")
    with pytest.raises(ArchiveError, match="unsafe"):
        extract_tree(buf.getvalue(), None, tmp_path / "out")


def test_symlink_entry_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("root/ok.txt", "ok")
        link = zipfile.ZipInfo("root/link")
        link.external_attr = 0o120777 << 16
        zf.writestr(link, "/etc/passwd")
    with pytest.raises(ArchiveError, match="symlink"):
        extract_tree(buf.getvalue(), None, tmp_path / "out")


def test_entry_count_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MAX_ENTRIES", 3)
    data = make_github_zip("r", {f"f{i}.txt": "x" for i in range(5)})
    with pytest.raises(ArchiveError, match="entries"):
        extract_tree(data, None, tmp_path / "out")


def test_uncompressed_size_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MAX_UNCOMPRESSED_BYTES", 10)
    data = make_github_zip("r", {"big.txt": "x" * 100})
    with pytest.raises(ArchiveError, match="expands"):
        extract_tree(data, None, tmp_path / "out")


def test_multiple_roots_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/x.txt", "1")
        zf.writestr("b/y.txt", "2")
    with pytest.raises(ArchiveError, match="top-level"):
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            zip_root(z)


def test_not_a_zip(tmp_path):
    with pytest.raises(ArchiveError, match="not a valid zip"):
        extract_tree(b"garbage", None, tmp_path / "out")
