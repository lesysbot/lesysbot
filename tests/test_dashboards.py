"""Dashboard rendering: availability gating, and System Overview as a package.

Two things are load-bearing here.

**An unavailable dashboard is not provisioned.** This is a deliberate asymmetry
with tools — an unavailable tool stays visible with an explaining stub, because
you should know the capability exists — but a dashboard of blank panels is
indistinguishable from a broken one, which is the ambiguity this whole design
exists to remove.

**The default dashboard is basic on every host.** It carries only rows a stock
exporter always fills, because there is no one-size-fits-all dashboard — and a
default that reached for hardware this machine may not have would render as the
very blank panels the gating above exists to prevent. Its panels are still the
generator's, selected rather than reimplemented, so `gen-dashboards.py` stays
the single source of truth for the standalone stack.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from lesysbot.artifacts.manifest import _package_from
from lesysbot.core.paths import bundled_dir
from lesysbot.dashboards import render

SYSTEM_OVERVIEW = bundled_dir() / "dashboards" / "system-overview"


@dataclass
class FakeSettings:
    config_dir: Path


@dataclass
class FakeCtx:
    """The bits of CLIContext that render.py actually uses."""

    dashboards_dir: Path
    settings: FakeSettings


@pytest.fixture
def ctx(tmp_path):
    installed = tmp_path / "dashboard" / "installed"
    installed.mkdir(parents=True)
    return FakeCtx(installed, FakeSettings(tmp_path))


def _package(ctx, name="demo", *, payload="dashboard.json",
             content='{"title": "Demo", "panels": []}', readme=""):
    folder = ctx.dashboards_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / payload).write_text(content)
    if readme:
        (folder / "README.md").write_text(readme)
    return _package_from(folder, name)


def _generated(ctx) -> Path:
    from lesysbot.core.paths import generated_dashboards_dir

    return generated_dashboards_dir(ctx.settings.config_dir)


def _output(ctx) -> Path:
    """The one file Grafana provisions, whatever package produced it."""
    return _generated(ctx) / render.OUTPUT_NAME


# -- payload shapes ------------------------------------------------------------

def test_renders_a_plain_json_dashboard(ctx):
    """A Grafana export dropped in a repo, installed as-is."""
    _package(ctx)
    results = render.render_all(ctx)
    assert [r.written for r in results] == [True]
    assert json.loads(_output(ctx).read_text())["title"] == "Demo"


def test_renders_a_host_adaptive_python_dashboard(ctx):
    _package(ctx, payload="dashboard.py",
             content="def build(host, caps, ctx):\n"
                     "    return {'title': host, 'caps': sorted(caps)}\n")
    render.render_all(ctx)
    model = json.loads(_output(ctx).read_text())

    from lesysbot.mcp.platform import current_os

    assert model["title"] == current_os()


def test_context_carries_arch_and_os_version():
    """A dashboard must be able to tell Apple Silicon from an Intel Mac.

    `host` says "macos" for both, but no unprivileged die temperature exists on
    M-series — so a temperature row that is right on one renders permanently
    blank on the other. That distinction lives in `arch`.
    """
    context = render.host_context()
    assert context["api_version"] == 2
    assert set(context) == {"api_version", "host", "caps", "arch", "os_version"}
    assert context["arch"]                      # always determinable
    assert isinstance(context["os_version"], str)   # "" when unknown


def test_a_build_written_against_api_v1_still_works(ctx):
    """The context grew; the signature did not. That is why it is a dict."""
    _package(ctx, payload="dashboard.py",
             content="def build(host, caps, ctx):\n"
                     "    return {'title': 'v1-style', 'panels': []}\n")
    results = render.render_all(ctx)
    assert [r.written for r in results] == [True]
    assert json.loads(_output(ctx).read_text())["title"] == "v1-style"


def test_a_dashboard_can_branch_on_arch(ctx, monkeypatch):
    monkeypatch.setattr(render, "host_context", lambda: {
        "api_version": 2, "host": "macos", "caps": [],
        "arch": "arm64", "os_version": "14.5",
    })
    _package(ctx, payload="dashboard.py",
             content="def build(host, caps, ctx):\n"
                     "    panels = ['cpu']\n"
                     "    if ctx['arch'] != 'arm64':\n"
                     "        panels.append('die-temp')\n"
                     "    return {'title': ctx['os_version'], 'panels': panels}\n")
    render.render_all(ctx)
    model = json.loads(_output(ctx).read_text())
    assert model["panels"] == ["cpu"]        # no die-temp panel on Apple Silicon
    assert model["title"] == "14.5"


def test_python_payload_wins_over_json(ctx):
    """A package shipping both is host-adaptive; the JSON is its fallback export."""
    folder = ctx.dashboards_dir / "demo"
    folder.mkdir(parents=True)
    (folder / "dashboard.json").write_text('{"title": "static"}')
    (folder / "dashboard.py").write_text(
        "def build(host, caps, ctx):\n    return {'title': 'dynamic'}\n")
    render.render_all(ctx)
    assert json.loads(_output(ctx).read_text())["title"] == "dynamic"


def test_a_replacing_dashboard_is_not_served_the_previous_ones_module(ctx):
    """Each `dashboard.py` imports under a unique module name.

    Both packages are called `dashboard.py`, so a shared module name would let
    the first one linger in `sys.modules` and be handed back for the second —
    the user installs a new dashboard and Grafana keeps showing the old one.
    Replacement (rather than two coexisting packages) is how this arises now
    that an install has exactly one dashboard.
    """
    import shutil

    _package(ctx, "one", payload="dashboard.py",
             content="def build(host, caps, ctx):\n    return {'title': 'first'}\n")
    render.render_all(ctx)
    assert json.loads(_output(ctx).read_text())["title"] == "first"

    shutil.rmtree(ctx.dashboards_dir / "one")
    _package(ctx, "two", payload="dashboard.py",
             content="def build(host, caps, ctx):\n    return {'title': 'second'}\n")
    render.render_all(ctx)
    assert json.loads(_output(ctx).read_text())["title"] == "second"


def test_a_broken_payload_is_reported_not_raised(ctx):
    _package(ctx, payload="dashboard.py", content="raise RuntimeError('boom')\n")
    result = render.render_all(ctx)[0]
    assert result.written is False and "boom" in result.reason


def test_a_package_with_no_payload_is_reported(ctx):
    folder = ctx.dashboards_dir / "empty"
    folder.mkdir(parents=True)
    (folder / "README.md").write_text("---\nname: empty\nkind: dashboard\n---\n")
    result = render.render_all(ctx)[0]
    assert result.written is False and "dashboard.json" in result.reason


# -- availability gating -------------------------------------------------------

UNSATISFIABLE = ("---\nname: demo\nkind: dashboard\n"
                 "prerequisites:\n  - metric: definitely_not_scraped_xyz\n---\n")


def test_an_unavailable_dashboard_is_not_written(ctx, monkeypatch):
    _package(ctx, readme=UNSATISFIABLE)
    monkeypatch.setattr(render, "check", lambda pkg: _report(ok=False))

    result = render.render_all(ctx)[0]
    assert result.written is False
    assert "not scraped" in result.reason
    assert not _output(ctx).exists()


def test_becoming_unavailable_un_provisions_a_previous_render(ctx, monkeypatch):
    """A dashboard that worked yesterday must not keep being served after its
    exporter goes away — that is the empty-panel failure, arrived at slowly."""
    _package(ctx)
    render.render_all(ctx)
    assert _output(ctx).exists()

    monkeypatch.setattr(render, "check", lambda pkg: _report(ok=False))
    render.render_all(ctx)
    assert not _output(ctx).exists()


def test_force_renders_despite_missing_prerequisites(ctx, monkeypatch):
    _package(ctx)
    monkeypatch.setattr(render, "check", lambda pkg: _report(ok=False))
    assert render.render_all(ctx, force=True)[0].written is True


# -- one dashboard per install -------------------------------------------------

def test_the_uid_is_ours_not_the_packages(ctx):
    """A fork must not be able to move the link everything else points at."""
    _package(ctx, content='{"title": "Demo", "uid": "someone-elses", "panels": []}')
    render.render_all(ctx)
    assert json.loads(_output(ctx).read_text())["uid"] == render.DASHBOARD_UID


def test_only_one_dashboard_is_provisioned(ctx):
    """Two packages on disk still yield exactly one file for Grafana."""
    _package(ctx, "one")
    _package(ctx, "two")
    results = render.render_all(ctx)
    assert len(results) == 1
    assert [p.name for p in _generated(ctx).glob("*.json")] == [render.OUTPUT_NAME]


def test_stale_dashboards_are_swept(ctx):
    """Leftovers from the per-package era, and from the standalone stack.

    Both would show in Grafana as a second page beside the real one, and neither
    is something the user put there deliberately — so any render clears them.
    """
    generated = _generated(ctx)
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "cpu-detail.json").write_text("{}")
    (generated / "system-overview-linux-macos.json").write_text("{}")

    _package(ctx)
    render.render_all(ctx)
    assert [p.name for p in generated.glob("*.json")] == [render.OUTPUT_NAME]


def test_removing_the_last_dashboard_withdraws_the_file(ctx):
    """Nothing installed means nothing provisioned — not a stale page."""
    import shutil

    _package(ctx)
    render.render_all(ctx)
    assert _output(ctx).exists()

    shutil.rmtree(ctx.dashboards_dir / "demo")
    assert render.render_all(ctx) == []
    assert not _output(ctx).exists()


def test_describe_all_reports_state_without_rendering(ctx):
    _package(ctx)
    rows = render.describe_all(ctx)
    assert rows[0]["name"] == "demo" and rows[0]["provisioned"] is False
    assert not _output(ctx).exists()


def _report(*, ok: bool):
    from lesysbot.prereq.report import Report, Requirement, Result

    requirement = Requirement("metric", "definitely_not_scraped_xyz")
    return Report("demo", [Result(requirement, ok,
                                  "'definitely_not_scraped_xyz' is not scraped")])


# -- System Overview as the first dashboard package ----------------------------

def test_system_overview_ships_as_a_dashboard_package():
    from lesysbot.artifacts.kinds import ArtifactKind

    pkg = _package_from(SYSTEM_OVERVIEW, "system-overview")
    assert pkg.kind is ArtifactKind.DASHBOARD
    assert ("metric", "node_cpu_seconds_total") in pkg.prerequisites


@pytest.fixture
def bundled_generator(monkeypatch, tmp_path):
    """Force the package to resolve the *bundled* generator, not the installed one.

    `dashboard.py` deliberately prefers `~/.lesysbot/dashboard/scripts/` — at
    runtime the installed stack is the one Grafana actually reads, so rendering
    against anything else would be wrong. But that makes these comparisons depend
    on whatever release the developer happens to have installed, which is how
    this test first failed: against a `~/.lesysbot` a few commits behind.
    """
    monkeypatch.setattr("lesysbot.core.paths.dashboard_dir", lambda *a, **kw: tmp_path)


BASIC_ROWS = ("Overview", "CPU", "Memory", "Disk", "Network")


@pytest.mark.parametrize("host", ["linux", "macos", "windows", "freebsd"])
@pytest.mark.parametrize("caps", [set(), {"nvidia"}, {"amd"}])
def test_the_default_dashboard_is_basic_on_every_host(host, caps, bundled_generator):
    """The default carries only rows a stock exporter always fills.

    Not a style preference: a panel querying a series nobody collects renders
    empty, and an empty panel is indistinguishable from a broken one. macOS is
    the case that bites — its cut carries a Temperatures row and an Apple GPU row
    unconditionally, and neither has data without the extra collector.

    Parametrised over `caps` because detecting an NVIDIA card must *not* add a
    GPU row here: the exporter that fills it is a separate install, so a machine
    with a card but no exporter would get blank panels. GPU detail is what
    `gpu-nvidia` and friends are for.
    """
    produced = _load_build()(host, caps, {"host": host, "caps": sorted(caps)})
    rows = [p["title"] for p in produced["panels"] if p.get("type") == "row"]
    assert rows, "the default must have some rows"
    assert all(r.startswith(BASIC_ROWS) for r in rows), rows


@pytest.mark.parametrize("host", ["linux", "macos", "windows", "freebsd"])
def test_the_default_is_a_prefix_of_the_generators_output(host, bundled_generator):
    """No vertical hole where a dropped row used to be.

    The package keeps the basic rows by dropping the rest, and does **not**
    reflow `gridPos`. That is only correct while the generator appends its
    hardware sections after the core ones, so the kept panels are a prefix of
    what it produced. If that ever stops being true this fails here — rather
    than silently leaving a gap in the middle of somebody's dashboard.
    """
    generator = _load_generator()
    full = (generator.build_for(host, set()) if host in generator.CAPABILITIES
            else generator.build_node())
    produced = _load_build()(host, set(), {})

    kept, original = produced["panels"], full["panels"]
    assert kept == original[:len(kept)]


def test_the_default_still_maps_onto_the_generator(bundled_generator):
    """The panels are the generator's, not a copy that can drift from it.

    `gen-dashboards.py` stays the single source of truth — it is what the stack
    runs standalone on a machine with no LeSysBot — so the package must be a
    *selection* from its output, never a reimplementation.
    """
    generator = _load_generator()
    produced = _load_build()("linux", set(), {})
    expected = generator.build_for("linux", set())

    assert produced["panels"] == expected["panels"]
    assert produced["title"] == expected["title"]


def test_the_standalone_generator_keeps_its_hardware_rows(bundled_generator):
    """Slimming the default must not slim the generator.

    Someone running the docker stack without LeSysBot gets whatever their host
    can fill, and the richer dashboard packages are built from these sections
    too. Only the *default package* is deliberately basic.
    """
    generator = _load_generator()
    rows = [p["title"] for p in generator.build_node()["panels"]
            if p.get("type") == "row"]
    assert any(r.startswith("Temperature") for r in rows)
    assert any(r.startswith("GPU") for r in rows)


def _load_build():
    import importlib.util
    import sys

    # dashboard.py caches the generator in sys.modules under a fixed name, so a
    # previous test's copy would survive the fixture that redirects where it is
    # loaded from.
    sys.modules.pop("_lesysbot_gen_dashboards", None)
    spec = importlib.util.spec_from_file_location(
        "_test_system_overview", SYSTEM_OVERVIEW / "dashboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build


def _load_generator():
    import importlib.util

    path = bundled_dir() / "dashboard" / "scripts" / "gen-dashboards.py"
    spec = importlib.util.spec_from_file_location("_test_gen_dashboards", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
