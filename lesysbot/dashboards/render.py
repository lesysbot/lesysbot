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
    than the OS name, which is now a constant. An arm64 board exposes its CPU
    sensor as ``cpu_thermal`` where an x86_64 desktop uses ``coretemp``, so a
    temperature row that is correct on one renders permanently blank on the
    other. Exporter metric names likewise move between distro releases.

    ``os_version`` is "" when it can't be determined; a dashboard must treat
    that as "unknown", never as "old".
    """
    from lesysbot.core.host import current_arch, current_os, os_version
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
    report = check(pkg)
    if report is not None and not report.ok and not force:
        _unprovision(ctx, pkg.name)
        return RenderResult(pkg.name, False, reason=report.reason)

    try:
        model = build_model(pkg, context)
    except Exception as e:
        return RenderResult(pkg.name, False, reason=f"render failed: {e}")

    out_dir = generated_dashboards_dir(ctx.settings.config_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{pkg.name}.json"
    # Written whole then replaced, because Grafana's file provider polls this
    # directory and would happily load a half-written file.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return RenderResult(pkg.name, True, path=path)


def _unprovision(ctx, name: str) -> None:
    """Remove a previously rendered copy when a dashboard stops being available.

    Without this, a dashboard that worked yesterday keeps being served after its
    exporter goes away — showing empty panels, which is the failure mode the
    availability check exists to prevent.
    """
    path = generated_dashboards_dir(ctx.settings.config_dir) / f"{name}.json"
    if path.exists():
        path.unlink()


def render_all(ctx, names: list[str] | None = None, *,
               force: bool = False) -> list[RenderResult]:
    packages = installed_packages(ctx)
    if names:
        wanted = set(names)
        packages = [p for p in packages if p.name in wanted]
    context = host_context()
    return [render_one(ctx, pkg, context, force=force) for pkg in packages]


def describe_all(ctx) -> list[dict]:
    """Rows for ``lesysbot dashboard list`` — state without rendering anything."""
    out_dir = generated_dashboards_dir(ctx.settings.config_dir)
    rows = []
    for pkg in installed_packages(ctx):
        report = check(pkg)
        rows.append({
            "name": pkg.name,
            "description": pkg.description,
            "ok": report.ok if report is not None else True,
            "reason": report.reason if report is not None else "",
            "provisioned": (out_dir / f"{pkg.name}.json").exists(),
        })
    return rows
