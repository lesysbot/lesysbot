"""Bundled content: what `pip install lesysbot` has to contain to be usable.

`bundled_dir()` is what makes a wheel install and a git checkout behave
identically, and the build hook is what keeps machine-local state — most
importantly the Grafana admin password in `dashboard/.env` — out of a release.
Both are the kind of thing that only fails at publish time, so they are pinned
here rather than discovered by a user.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lesysbot.core.paths import bundled_dir

REPO = Path(__file__).resolve().parents[1]


# -- resolution ----------------------------------------------------------------

def test_checkout_resolves_to_the_repo_root():
    """No `_bundled/` in a dev checkout, so it falls back to where the
    directories actually live — beside the package."""
    assert bundled_dir() == REPO


def test_packaged_layout_wins_when_present(tmp_path, monkeypatch):
    package = tmp_path / "site-packages" / "lesysbot"
    (package / "core").mkdir(parents=True)
    (package / "_bundled").mkdir()
    monkeypatch.setattr("lesysbot.core.paths.__file__",
                        str(package / "core" / "paths.py"))
    assert bundled_dir() == package / "_bundled"


@pytest.mark.parametrize("name", ["tools", "dashboard", "dashboards", "catalog.json"])
def test_everything_the_build_ships_exists(name):
    """The build hook copies exactly these; a rename here would silently ship
    an install with no tools or no dashboards."""
    from hatch_build import BUNDLED

    assert name in BUNDLED
    assert (bundled_dir() / name).exists()


# -- the build hook's exclusions -----------------------------------------------

def test_env_file_is_excluded_from_the_build():
    """`dashboard/.env` holds the Grafana admin password and is git-ignored for
    that reason. Shipping it would hand the packager's password to every user."""
    from hatch_build import _keep

    root = REPO / "dashboard"
    assert not _keep(root / ".env", root)
    assert _keep(root / ".env.example", root)      # the template must ship


@pytest.mark.parametrize("path", ["bin/node_exporter", "run/prom.pid",
                                  "native/prometheus.yml", "__pycache__/x.pyc"])
def test_machine_local_state_is_excluded(path):
    from hatch_build import _keep

    root = REPO / "dashboard"
    assert not _keep(root / path, root)


def test_generated_dashboards_are_excluded():
    """Per-host cuts describe one machine's sensors; they are never portable."""
    from hatch_build import _keep

    root = REPO / "dashboard"
    assert not _keep(root / "grafana" / "dashboards" / "generated-linux.json", root)
    assert _keep(root / "grafana" / "dashboards" / "system-overview.json", root)


# -- the content itself --------------------------------------------------------

def test_bundled_tools_are_loadable_packages():
    """Every bundled tool folder is discoverable by the same rules an installed
    one is — the seeding path runs them through the same manifest parser."""
    from lesysbot.artifacts.manifest import discover_packages

    found = discover_packages(bundled_dir() / "tools", "tools")
    names = {p.name for p in found}
    assert {"temperature", "network", "system-info"} <= names


def test_bundled_dashboards_are_recognised_as_dashboards():
    from lesysbot.artifacts.kinds import ArtifactKind
    from lesysbot.artifacts.manifest import discover_packages

    found = discover_packages(bundled_dir() / "dashboards", "dashboards")
    assert found, "at least System Overview should ship"
    assert all(p.kind is ArtifactKind.DASHBOARD for p in found)


def test_the_stack_ships_its_start_scripts():
    stack = bundled_dir() / "dashboard"
    for rel in ("scripts/start.sh", "scripts/gen-dashboards.py",
                "docker-compose.yml"):
        assert (stack / rel).is_file(), rel
