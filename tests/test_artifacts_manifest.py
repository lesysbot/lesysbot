from lesysbot.artifacts.manifest import discover_packages, parse_frontmatter


def test_parse_frontmatter_ok():
    fm = parse_frontmatter(
        "---\nname: gpu-temp\ndescription: GPU temps\nplatforms: [linux]\n---\n# hi\n"
    )
    assert fm["name"] == "gpu-temp"
    assert fm["platforms"] == ["linux"]


def test_parse_frontmatter_missing_or_bad():
    assert parse_frontmatter("# just a readme") == {}
    assert parse_frontmatter("") == {}
    assert parse_frontmatter("---\n- not\n- a dict\n---\n") == {}
    assert parse_frontmatter("---\nname: [unclosed\n---\n") == {}


def _mkpkg(root, name, frontmatter=True, tool="tool.py"):
    d = root / name
    d.mkdir(parents=True)
    (d / tool).write_text("x = 1")
    if frontmatter:
        (d / "README.md").write_text(
            f"---\nname: {name}\ndescription: pkg {name}\nversion: 2.0\n---\n"
        )
    return d


def test_discover_root_package(tmp_path):
    (tmp_path / "tool.py").write_text("x = 1")
    (tmp_path / "README.md").write_text("---\ndescription: root pkg\n---\n")
    pkgs = discover_packages(tmp_path, "fallback-name")
    assert len(pkgs) == 1
    assert pkgs[0].name == "fallback-name"  # no `name:` in frontmatter
    assert pkgs[0].description == "root pkg"
    assert pkgs[0].tool_files == ["tool.py"]


def test_discover_multi_package_repo(tmp_path):
    _mkpkg(tmp_path, "alpha")
    _mkpkg(tmp_path, "beta", frontmatter=False)
    # Ignored: helpers-only, hidden, underscore, tests/docs, no .py
    (tmp_path / "_shared").mkdir()
    (tmp_path / "_shared" / "helper.py").write_text("h = 1")
    _mkpkg(tmp_path, "tests")
    _mkpkg(tmp_path, "docs")
    _mkpkg(tmp_path, ".hidden")
    (tmp_path / "empty").mkdir()
    helpers_only = tmp_path / "helpers-only"
    helpers_only.mkdir()
    (helpers_only / "_util.py").write_text("u = 1")

    pkgs = discover_packages(tmp_path, "repo")
    assert [p.name for p in pkgs] == ["alpha", "beta"]
    assert pkgs[0].version == "2.0"
    assert pkgs[1].version is None
    assert pkgs[1].description == ""


def test_discover_tools_dir_layout(tmp_path):
    """Collection repos keep packages under tools/ — discovery descends into it."""
    _mkpkg(tmp_path / "tools", "alpha")
    _mkpkg(tmp_path / "tools", "beta")
    (tmp_path / "README.md").write_text("# collection\n")
    (tmp_path / "_tests").mkdir()
    (tmp_path / "_tests" / "test_alpha.py").write_text("t = 1")

    pkgs = discover_packages(tmp_path, "repo")
    assert [p.name for p in pkgs] == ["alpha", "beta"]


def test_discover_empty_tools_dir_falls_back_to_root(tmp_path):
    """A tools/ folder with no packages doesn't hide root-level packages."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "README.md").write_text("# catalog\n")
    _mkpkg(tmp_path, "gamma")

    pkgs = discover_packages(tmp_path, "repo")
    assert [p.name for p in pkgs] == ["gamma"]


def test_discover_requirements_flag(tmp_path):
    d = _mkpkg(tmp_path, "with-deps")
    (d / "requirements.txt").write_text("httpx\n")
    pkgs = discover_packages(tmp_path, "repo")
    assert pkgs[0].has_requirements is True


def test_frontmatter_name_wins(tmp_path):
    d = tmp_path / "folder-name"
    d.mkdir()
    (d / "tool.py").write_text("x = 1")
    (d / "README.md").write_text("---\nname: real-name\n---\n")
    pkgs = discover_packages(tmp_path, "repo")
    assert pkgs[0].name == "real-name"
