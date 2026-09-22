"""The marketplace catalog: discovery metadata that resolves only to GitHub links.

The trust model rests on the catalog being a *list*, not a resolver — every
entry's `source` is an ordinary github.com link that goes through the same
parser and the same consent prompt as one typed by hand. If that ever stopped
being true, "you can read the repo before you install it" would stop being true
with it, so it is asserted here rather than left as documentation.
"""

from __future__ import annotations

import json

import pytest

from lesysbot.artifacts.catalog import (
    CATALOG_NAME,
    Catalog,
    CatalogEntry,
    bundled_path,
    load_catalog,
    parse_catalog,
    refresh,
)
from lesysbot.artifacts.kinds import ArtifactKind
from lesysbot.artifacts.spec import parse_source


def _catalog(**entry) -> dict:
    base = {"id": "x", "name": "X", "source": "acme/x"}
    return {"version": 1, "entries": [{**base, **entry}]}


# -- parsing -------------------------------------------------------------------

def test_parses_entries():
    catalog = parse_catalog(_catalog(kind="dashboard", description="d",
                                     platforms=["macos"], official=True))
    entry = catalog.entries[0]
    assert entry.id == "x" and entry.kind is ArtifactKind.DASHBOARD
    assert entry.platforms == ("macos",) and entry.official is True


def test_kind_defaults_to_tool():
    assert parse_catalog(_catalog()).entries[0].kind is ArtifactKind.TOOL


@pytest.mark.parametrize("bad", [{"id": "x"}, {"source": "acme/x"}, {}])
def test_entries_without_id_or_source_are_dropped(bad):
    """One malformed row must not take `lesysbot search` down — it's fetched
    from the network, so bad data is a matter of when, not if."""
    assert parse_catalog({"version": 1, "entries": [bad]}).entries == []


def test_non_dict_entries_are_dropped():
    assert parse_catalog({"entries": ["nope", 3, None]}).entries == []


def test_empty_input_is_an_empty_catalog():
    assert parse_catalog({}).entries == [] and parse_catalog(None).entries == []


# -- lookup and search ---------------------------------------------------------

def _many() -> Catalog:
    return parse_catalog({"version": 1, "entries": [
        {"id": "linux-tools", "name": "Linux Tools", "source": "a/linux",
         "platforms": ["linux"], "official": True, "tags": ["network"]},
        {"id": "macos-tools", "name": "macOS Tools", "source": "a/macos",
         "platforms": ["macos"], "official": True},
        {"id": "zz-community", "name": "Community", "source": "b/zz",
         "description": "network graphs"},
    ]})


def test_find_by_id_and_by_name():
    catalog = _many()
    assert catalog.find("linux-tools").source == "a/linux"
    assert catalog.find("Linux Tools").source == "a/linux"
    assert catalog.find("nope") is None


def test_search_matches_description_and_tags():
    ids = [e.id for e in _many().search("network")]
    assert set(ids) == {"linux-tools", "zz-community"}


def test_search_filters_by_kind():
    catalog = parse_catalog({"entries": [
        {"id": "t", "name": "t", "source": "a/t", "kind": "tool"},
        {"id": "d", "name": "d", "source": "a/d", "kind": "dashboard"},
    ]})
    assert [e.id for e in catalog.search(kind="dashboard")] == ["d"]


def test_search_can_restrict_to_this_machine(monkeypatch):
    monkeypatch.setattr("lesysbot.core.host.current_os", lambda: "linux")
    ids = [e.id for e in _many().search(here_only=True)]
    assert "linux-tools" in ids and "macos-tools" not in ids
    # An entry that names no platform runs anywhere.
    assert "zz-community" in ids


def test_official_entries_sort_first():
    """Searching "temperature" should meet the maintained collection before
    somebody's fork of it."""
    results = _many().search()
    assert [e.official for e in results] == [True, True, False]


# -- the GitHub-links-only guarantee -------------------------------------------

def test_every_bundled_entry_is_a_parseable_github_link():
    catalog = load_catalog(bundled_path())
    assert catalog.entries, "the bundled catalog should not be empty"
    for entry in catalog.entries:
        source = parse_source(entry.source)      # raises if it isn't one
        assert source.owner and source.repo


def test_bundled_catalog_is_valid_json_with_a_version():
    data = json.loads(bundled_path().read_text())
    assert data["version"] == 1 and isinstance(data["entries"], list)


def test_bundled_entries_have_unique_ids():
    ids = [e["id"] for e in json.loads(bundled_path().read_text())["entries"]]
    assert len(ids) == len(set(ids))


def test_the_official_collection_is_findable_by_id():
    entry = load_catalog(bundled_path()).find("official")
    assert entry is not None
    assert entry.source == "lesysbot/lesysbot/tools"


def test_every_bundled_entry_points_into_this_repo():
    """The catalog used to list a separate ``lesysbot-packages-official`` repo.
    Nothing tied those listings to anything real, so when that repo was retired
    the entries stayed valid-looking and `lesysbot install official` got a 404
    from an index with no way of knowing it was wrong.

    Every entry now names a subdirectory of *this* repo, which makes the tree
    itself the check: delete or rename one and this fails here, rather than on
    somebody's machine.
    """
    root = bundled_path().parent
    for entry in load_catalog(bundled_path()).entries:
        source = parse_source(entry.source)
        assert source.slug == "lesysbot/lesysbot", entry.source
        assert source.subdir, f"{entry.source} names no subdirectory"
        assert (root / source.subdir).is_dir(), f"{entry.source} is not in the tree"


def test_dashboards_are_searchable_by_kind():
    """`lesysbot search --kind dashboard` returning nothing reads as
    "dashboards aren't a thing you install" — so the bundled catalog must
    always list at least one."""
    results = load_catalog(bundled_path()).search(kind="dashboard")
    assert results, "no dashboard entries in the bundled catalog"


# -- source precedence and refresh ---------------------------------------------

def test_cached_copy_wins_over_the_bundled_one(tmp_path, monkeypatch):
    """A refreshed catalog is newer by definition; the bundled copy is a floor."""
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    (tmp_path / CATALOG_NAME).write_text(json.dumps(_catalog(id="cached")))
    assert [e.id for e in load_catalog().entries] == ["cached"]


def test_unreadable_catalog_falls_back_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    (tmp_path / CATALOG_NAME).write_text("{ not json")
    assert load_catalog().entries          # fell through to the bundled copy


def test_refresh_failure_keeps_the_existing_catalog(tmp_path, monkeypatch):
    """Being offline degrades discovery; it must not break it."""
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))

    def boom(*_a, **_kw):
        raise OSError("no network")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    catalog, error = refresh(dest=tmp_path / CATALOG_NAME)
    assert "could not refresh" in error
    assert catalog.entries                 # the bundled copy is still there


def test_refresh_writes_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    payload = json.dumps(_catalog(id="fresh")).encode()

    class _Response:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: _Response())
    catalog, error = refresh(dest=tmp_path / CATALOG_NAME)
    assert error is None
    assert [e.id for e in catalog.entries] == ["fresh"]
    assert (tmp_path / CATALOG_NAME).exists()


def test_refresh_rejects_an_empty_published_catalog(tmp_path, monkeypatch):
    """An index that parsed to nothing is more likely broken than genuinely
    empty — keep what works rather than caching the emptiness."""
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))

    class _Response:
        def read(self):
            return b'{"version": 1, "entries": []}'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: _Response())
    _catalog_out, error = refresh(dest=tmp_path / CATALOG_NAME)
    assert "no usable entries" in error
    assert not (tmp_path / CATALOG_NAME).exists()


def test_entry_runs_here_with_no_platforms():
    assert CatalogEntry("i", "n", "a/b").runs_here() is True
