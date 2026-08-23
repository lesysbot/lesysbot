"""Turn an installed dashboard package into JSON Grafana will provision.

Two payload shapes, and the difference is whether the dashboard needs to know
anything about the machine:

* ``dashboard.json`` — a plain Grafana model. Portable, and exactly what the
  Grafana UI's "export" button gives you, so anything from grafana.com or a
  colleague's instance drops straight in.
* ``dashboard.py`` — ``build(host, caps, ctx) -> dict``. For dashboards that
  must adapt: drop the NVIDIA row on a machine with no NVIDIA driver, pick the
  right metric names per OS.

**An unavailable dashboard is not written.** That is a deliberate asymmetry with
tools — an unavailable tool stays visible with a stub, because you should know
the capability exists — but a dashboard that renders as empty panels is
indistinguishable from a broken one, so it is withheld and explained instead.

**There is exactly one dashboard.** It renders to one file at one fixed uid, so
the Grafana address is a constant that documentation, the status screen and
``share_dashboard`` can all point at without asking which dashboard is meant.
Installing a dashboard replaces the current one (``artifacts/installer.py``);
this module is what makes the result a single page rather than a pile.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from lesysbot.artifacts.manifest import _package_from
from lesysbot.core.paths import generated_dashboards_dir

# Passed to a dashboard.py `build()` so it can adapt without probing the host
# itself — one detection path, shared, rather than one per dashboard.
#
# 2: `arch` and `os_version` added. Additive, so a `build()` written against
# version 1 keeps working — which is why the context is a dict and not
# positional arguments.
RENDER_API_VERSION = 2

# The one dashboard's Grafana uid and filename. Fixed, not derived from the
# package: the link is quoted in the docs, returned by `share_dashboard` and
# shown on the status screen, so a package must not be able to move it. A
# package's own `uid` is overwritten at render time.
DASHBOARD_UID = "lesysbot"
OUTPUT_NAME = f"{DASHBOARD_UID}.json"


@dataclass
class RenderResult:
    name: str
    written: bool
    path: Path | None = None
    reason: str = ""


def installed_packages(ctx) -> list:
    """Every installed dashboard package, read without importing its code."""
    directory = ctx.dashboards_dir
    if not directory.is_dir():
        return []
    return [
        _package_from(sub, sub.name)
        for sub in sorted(directory.iterdir())
        if sub.is_dir() and not sub.name.startswith((".", "_"))
    ]


def host_context() -> dict:
    """What a host-adaptive dashboard is allowed to branch on.

    ``arch`` and ``os_version`` are here because the right panels depend on more
    than the OS name. The sharpest case is Apple Silicon: no unprivileged die
    temperature exists there, so a temperature row that is correct on an Intel
    Mac renders permanently blank on an M-series one — and ``host`` says
    "macos" for both. Exporter metric names likewise move between OS releases.

    ``os_version`` is "" when it can't be determined; a dashboard must treat
    that as "unknown", never as "old".
    """
    from lesysbot.mcp.platform import current_arch, current_os, os_version
    from lesysbot.prereq import gpu

    caps = {info.vendor for info in gpu.detect_all() if info.usable}
    return {
        "api_version": RENDER_API_VERSION,
        "host": current_os(),
        "caps": sorted(caps),
        "arch": current_arch(),
        "os_version": os_version(),
    }


def _load_builder(path: Path):
    """Import a package's ``dashboard.py`` and return its ``build`` callable.

    Imported under a unique module name so two dashboards can each have a
    ``dashboard.py`` without the second one getting the first from sys.modules.
    """
    spec = importlib.util.spec_from_file_location(
        f"_lesysbot_dashboards.{path.parent.name}.dashboard", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    build = getattr(module, "build", None)
    if not callable(build):
        raise ImportError(f"{path} defines no build(host, caps, ctx)")
    return build


def build_model(pkg, context: dict) -> dict:
    """The Grafana dashboard model for *pkg*."""
    payload_json = pkg.path / "dashboard.json"
    payload_py = pkg.path / "dashboard.py"
    if payload_py.is_file():
        build = _load_builder(payload_py)
        return build(context["host"], set(context["caps"]), context)
    if payload_json.is_file():
        return json.loads(payload_json.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"{pkg.name} has neither dashboard.json nor dashboard.py"
    )


def check(pkg):
    """Prerequisite report for a dashboard package (metrics, services, GPU…)."""
    from lesysbot.prereq import check_package

    return check_package(pkg)


def render_one(ctx, pkg, context: dict, *, force: bool = False) -> RenderResult:
    out_dir = generated_dashboards_dir(ctx.settings.config_dir)

    report = check(pkg)
    if report is not None and not report.ok and not force:
        _sweep(out_dir, keep=None)
        return RenderResult(pkg.name, False, reason=report.reason)

    try:
        model = build_model(pkg, context)
    except Exception as e:
        return RenderResult(pkg.name, False, reason=f"render failed: {e}")

    # The uid is ours, not the package's. Everything that links to the dashboard
    # — docs, `share_dashboard`, the status screen — hardcodes it, so a fork
    # that kept its parent's uid (or invented one) must not be able to break
    # those links just by being installed.
    model["uid"] = DASHBOARD_UID

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / OUTPUT_NAME
    # Written whole then replaced, because Grafana's file provider polls this
    # directory and would happily load a half-written file.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    _sweep(out_dir, keep=OUTPUT_NAME)
    return RenderResult(pkg.name, True, path=path)


def _sweep(out_dir: Path, keep: str | None) -> None:
    """Delete every provisioned dashboard except *keep*.

    Two kinds of leftover end up here, and both would show as a second page in
    Grafana beside the real one:

    * per-package files from before dashboards became a singleton, named after
      whichever package rendered them;
    * the standalone stack's own output — the docker stack runs without LeSysBot
      and writes its cut here, so a machine that started that way and *then*
      installed LeSysBot has one of each.

    Sweeping on every render (rather than once, at migration) is what makes both
    self-correcting: whatever appears in this directory, the next render leaves
    exactly one dashboard. ``keep=None`` withdraws even ours, which is how an
    exporter going away stops a dashboard that has quietly gone blank.
    """
    if not out_dir.is_dir():
        return
    for path in out_dir.glob("*.json"):
        if path.name != keep:
            path.unlink()


def current_package(ctx):
    """The installed dashboard package, or ``None`` when none is installed.

    Normally there is exactly one directory and this is trivial. When there is
    more than one — a home that predates the singleton rule, or a folder placed
    by hand — the **lock decides**, so this and ``lesysbot dashboard current``
    can never name different dashboards while the user is trying to work out
    which one they have. Falling back to the first sorted name keeps the answer
    deterministic when the lock is silent; arbitrary-but-stable beats arbitrary.
    """
    packages = installed_packages(ctx)
    if len(packages) <= 1:
        return packages[0] if packages else None
    lock = getattr(ctx, "lock", None)
    entry = lock.current_dashboard() if lock is not None else None
    named = entry.get("name") if entry else None
    return next((p for p in packages if p.name == named), packages[0])


def render_all(ctx, *, force: bool = False) -> list[RenderResult]:
    """Render the installed dashboard. A list of 0 or 1 results.

    Still a list because every caller reports per-dashboard outcomes and the
    "nothing installed" case has to stay distinguishable from "installed but
    withheld" — a bare ``None`` collapses those two into one silence.
    """
    pkg = current_package(ctx)
    if pkg is None:
        _sweep(generated_dashboards_dir(ctx.settings.config_dir), keep=None)
        return []
    return [render_one(ctx, pkg, host_context(), force=force)]


def render_installed(ctx, names: list[str]) -> list[RenderResult]:
    """Render dashboards that were just installed, for the install path itself.

    "Install it, then go run render" was one step too many: a dashboard you
    just chose is not in Grafana until you notice a second instruction, in the
    CLI epilogue or in a different tab of the panel. Installing renders.

    Never raises. The install already succeeded and is on disk — a renderer
    failure must be *reported* against that, not turned into a failed install
    that the lock now disagrees with. An empty list means "nothing renderable
    here", which is the normal answer for a tools-only repo.
    """
    if not names:
        return []
    try:
        pkg = current_package(ctx)
        # A tools-only install must not re-render: it would be work nobody asked
        # for, and it could withdraw a dashboard whose exporter went away since
        # — a surprising thing for `lesysbot install some-tool` to do.
        if pkg is None or pkg.name not in set(names):
            return []
        return [render_one(ctx, pkg, host_context())]
    except Exception as e:                    # pragma: no cover - defensive
        return [RenderResult(name, False, reason=f"render failed: {e}")
                for name in names]


def describe_all(ctx) -> list[dict]:
    """Rows for ``lesysbot dashboard current`` — state without rendering anything.

    Normally one row. A second row means more than one package is on disk, which
    the singleton rule forbids — ``lesysbot doctor`` reports it, and showing both
    here is how the user sees which one is live (``provisioned``) and which is
    the leftover.
    """
    provisioned = (generated_dashboards_dir(ctx.settings.config_dir) / OUTPUT_NAME).exists()
    live = current_package(ctx)
    rows = []
    for pkg in installed_packages(ctx):
        report = check(pkg)
        rows.append({
            "name": pkg.name,
            "description": pkg.description,
            "ok": report.ok if report is not None else True,
            "reason": report.reason if report is not None else "",
            "provisioned": provisioned and live is not None and pkg.name == live.name,
        })
    return rows
