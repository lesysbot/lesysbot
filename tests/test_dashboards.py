"""Dashboard rendering: availability gating, and System Overview as a package.

Two things are load-bearing here.

**An unavailable dashboard is not provisioned.** This is a deliberate asymmetry
with tools — an unavailable tool stays visible with an explaining stub, because
you should know the capability exists — but a dashboard of blank panels is
indistinguishable from a broken one, which is the ambiguity this whole design
exists to remove.

**System Overview renders byte-identically to the old generator.** It is the
first dashboard package and the hardest case in the repo, so if converting it
changed anybody's dashboard by a single byte, the format change would have been
a silent regression rather than a refactor.
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


# -- payload shapes ------------------------------------------------------------

def test_renders_a_plain_json_dashboard(ctx):
    """A Grafana export dropped in a repo, installed as-is."""
    _package(ctx)
    results = render.render_all(ctx)
    assert [r.written for r in results] == [True]
    assert json.loads((_generated(ctx) / "demo.json").read_text())["title"] == "Demo"


def test_renders_a_host_adaptive_python_dashboard(ctx):
    _package(ctx, payload="dashboard.py",
             content="def build(host, caps, ctx):\n"
                     "    return {'title': host, 'caps': sorted(caps)}\n")
    render.render_all(ctx)
    model = json.loads((_generated(ctx) / "demo.json").read_text())

    from lesysbot.core.host import current_os

    assert model["title"] == current_os()


def test_context_carries_arch_and_os_version():
    """A dashboard must be able to tell an arm64 board from an x86_64 one.

    `host` says "linux" for both, but a Raspberry Pi exposes its CPU sensor as
    cpu_thermal where a desktop uses coretemp — so a temperature row that is
    right on one renders permanently blank on the other. That distinction lives
    in `arch`, and `os_version` carries the distro release for the same reason.
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
    assert json.loads((_generated(ctx) / "demo.json").read_text())["title"] == "v1-style"


def test_a_dashboard_can_branch_on_arch(ctx, monkeypatch):
    monkeypatch.setattr(render, "host_context", lambda: {
        "api_version": 2, "host": "linux", "caps": [],
        "arch": "arm64", "os_version": "24.04",
    })
    _package(ctx, payload="dashboard.py",
             content="def build(host, caps, ctx):\n"
                     "    panels = ['cpu']\n"
                     "    if ctx['arch'] != 'arm64':\n"
                     "        panels.append('die-temp')\n"
                     "    return {'title': ctx['os_version'], 'panels': panels}\n")
    render.render_all(ctx)
    model = json.loads((_generated(ctx) / "demo.json").read_text())
    assert model["panels"] == ["cpu"]        # no die-temp panel on this arm64 board
    assert model["title"] == "24.04"


def test_python_payload_wins_over_json(ctx):
    """A package shipping both is host-adaptive; the JSON is its fallback export."""
    folder = ctx.dashboards_dir / "demo"
    folder.mkdir(parents=True)
    (folder / "dashboard.json").write_text('{"title": "static"}')
    (folder / "dashboard.py").write_text(
        "def build(host, caps, ctx):\n    return {'title': 'dynamic'}\n")
    render.render_all(ctx)
    assert json.loads((_generated(ctx) / "demo.json").read_text())["title"] == "dynamic"


def test_two_packages_can_each_have_a_dashboard_py(ctx):
    """Imported under unique module names — otherwise the second gets the first."""
    for name, title in (("one", "first"), ("two", "second")):
        _package(ctx, name, payload="dashboard.py",
                 content=f"def build(host, caps, ctx):\n    return {{'title': '{title}'}}\n")
    render.render_all(ctx)
    assert json.loads((_generated(ctx) / "one.json").read_text())["title"] == "first"
    assert json.loads((_generated(ctx) / "two.json").read_text())["title"] == "second"


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
    assert not (_generated(ctx) / "demo.json").exists()


def test_becoming_unavailable_un_provisions_a_previous_render(ctx, monkeypatch):
    """A dashboard that worked yesterday must not keep being served after its
    exporter goes away — that is the empty-panel failure, arrived at slowly."""
    _package(ctx)
    render.render_all(ctx)
    assert (_generated(ctx) / "demo.json").exists()

    monkeypatch.setattr(render, "check", lambda pkg: _report(ok=False))
    render.render_all(ctx)
    assert not (_generated(ctx) / "demo.json").exists()


def test_force_renders_despite_missing_prerequisites(ctx, monkeypatch):
    _package(ctx)
    monkeypatch.setattr(render, "check", lambda pkg: _report(ok=False))
    assert render.render_all(ctx, force=True)[0].written is True


def test_render_can_target_one_dashboard(ctx):
    _package(ctx, "one")
    _package(ctx, "two")
    results = render.render_all(ctx, names=["one"])
    assert [r.name for r in results] == ["one"]
    assert not (_generated(ctx) / "two.json").exists()


def test_describe_all_reports_state_without_rendering(ctx):
    _package(ctx)
    rows = render.describe_all(ctx)
    assert rows[0]["name"] == "demo" and rows[0]["provisioned"] is False
    assert not (_generated(ctx) / "demo.json").exists()


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


@pytest.mark.parametrize("host,caps", [
    ("linux", set()),
    ("linux", {"nvidia"}),
    ("linux", {"amd"}),
])
def test_system_overview_matches_the_generator_exactly(host, caps, bundled_generator):
    """Byte-identical output, per capability cut. The package is a *mapping* onto
    gen-dashboards.py, not a copy of it — if this drifts, converting the bundled
    dashboard into a package silently changed everybody's graphs."""
    build = _load_build()
    generator = _load_generator()

    produced = build(host, caps, {"host": host, "caps": sorted(caps)})
    translated = _translate(host, caps, generator)
    expected = generator.build_for(host, translated)

    assert json.dumps(produced, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_system_overview_falls_back_for_an_unknown_host(bundled_generator):
    """A host the generator has no cut for still gets the portable dashboard."""
    build = _load_build()
    generator = _load_generator()
    produced = build("freebsd", set(), {})
    assert json.dumps(produced, sort_keys=True) == \
        json.dumps(generator.build_node(), sort_keys=True)


def _translate(host, caps, generator):
    """Mirror of dashboard.py's capability mapping, kept separate on purpose so
    the test compares two independent derivations rather than one."""
    gpu = {"nvidia": "nvidia", "amd": "amd_gpu"}
    wanted = {gpu[c] for c in caps if c in gpu}
    wanted |= {"cpu_temp", "disk_temp", "thermal_zone", "thermalzone"}
    return wanted & generator.CAPABILITIES.get(host, set())


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


# -- the two dashboards folded in from the retired packages repo ---------------
#
# `network-traffic` and `gpu-detail` used to live in `lesysbot-packages-official`
# and were the only content there that Linux still wanted. They came home when
# that repo was retired; these are their tests, minus the per-OS branching the
# Linux-only refactor removed.

def _build_package(name: str, host: str = "linux", caps=(), **ctx_extra) -> dict:
    """Call one bundled dashboard package's `build()` with a v2 render context."""
    import importlib.util

    path = bundled_dir() / "dashboards" / name / "dashboard.py"
    spec = importlib.util.spec_from_file_location(
        f"_test_{name.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = {"api_version": render.RENDER_API_VERSION, "host": host,
           "caps": list(caps), "arch": "x86_64", "os_version": "", **ctx_extra}
    return module.build(host, set(caps), ctx)


def _exprs(model: dict) -> str:
    return json.dumps([t["expr"] for p in model["panels"] for t in p["targets"]])


def test_network_traffic_queries_node_exporter():
    """The windows_exporter branch went with Windows support; what is left must
    still be node_exporter's names and not a half-removed hybrid."""
    exprs = _exprs(_build_package("network-traffic"))
    assert "node_network_receive_bytes_total" in exprs
    assert "node_network_transmit_bytes_total" in exprs
    assert "windows_net" not in exprs


def test_network_traffic_description_records_the_rendered_machine():
    """A shared screenshot should say which machine's cut it shows."""
    model = _build_package("network-traffic", arch="arm64", os_version="24.04")
    assert "linux arm64 24.04" in model["description"]


def test_network_traffic_is_serializable_with_a_stable_uid():
    model = _build_package("network-traffic")
    assert json.dumps(model)
    assert model["uid"] == "lesysbot-network-traffic"


def test_gpu_detail_covers_the_four_vitals():
    model = _build_package("gpu-detail")
    exprs = _exprs(model)
    for metric in ("utilization_gpu_ratio", "memory_used_bytes",
                   "temperature_gpu", "power_draw_watts"):
        assert metric in exprs
    assert len(model["panels"]) == 4
    assert json.dumps(model)


@pytest.mark.parametrize("name,requirement", [
    ("network-traffic", ("service", "prometheus")),
    ("gpu-detail", ("gpu", "nvidia")),
])
def test_both_declare_what_they_need_to_be_provisioned(name, requirement):
    """Withholding only works if the package says what it depends on — a
    dashboard with no prerequisites is provisioned unconditionally."""
    from lesysbot.artifacts.kinds import ArtifactKind

    pkg = _package_from(bundled_dir() / "dashboards" / name, name)
    assert pkg.kind is ArtifactKind.DASHBOARD
    assert requirement in pkg.prerequisites
