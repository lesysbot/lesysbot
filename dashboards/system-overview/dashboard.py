"""System Overview — the dashboard LeSysBot ships with, as an installable package.

This is the **default**, and it is deliberately the *basic* one: the Overview,
CPU, Memory, Disk and Network rows, which is what a stock `node_exporter` /
`windows_exporter` can always fill. Nothing here depends on hardware the machine
may not have.

That restraint is the whole point. There is no one-size-fits-all dashboard —
OSes differ, and within one OS the hardware differs (NVIDIA vs Apple Silicon vs
no GPU; hwmon vs the SMC vs WMI thermal zones; NTFS with no inodes). A default
that tried to cover all of it would render as blank panels on most machines, and
a blank panel is indistinguishable from a broken one. So temperatures, GPU
detail and per-filesystem breakdowns are **not** here: install a dashboard built
for your machine, or fork this one and add the rows you want.

The panel definitions themselves are **not** copied here. They stay in
`dashboard/scripts/gen-dashboards.py`, which remains the single source of truth
and is still runnable standalone by the stack's start scripts on a machine with
no LeSysBot install. This file maps LeSysBot's host vocabulary onto that
generator's, and then keeps the basic rows.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Row titles the default keeps, matched as prefixes. Everything the generator
# emits beyond these — "Temperatures — …", "GPU — …" — is hardware-dependent and
# belongs in a dashboard chosen for that hardware.
BASIC_ROWS = ("Overview", "CPU", "Memory", "Disk", "Network")


def _generator():
    """Load `gen-dashboards.py` from the installed stack.

    Imported by path rather than `import`ed: the stack deliberately sits outside
    the Python package (it runs from shell scripts on whatever `python3` exists,
    outside any virtualenv), so there is no module name to import it under.
    """
    for candidate in _generator_candidates():
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "_lesysbot_gen_dashboards", candidate)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError(
        "gen-dashboards.py not found — is the dashboard stack installed? "
        "Run `lesysbot setup`."
    )


def _generator_candidates() -> list[Path]:
    from lesysbot.core.paths import bundled_dir, dashboard_dir

    return [
        dashboard_dir() / "scripts" / "gen-dashboards.py",      # installed stack
        bundled_dir() / "dashboard" / "scripts" / "gen-dashboards.py",
    ]


def basic_rows(model: dict) -> dict:
    """Keep only the rows a stock exporter always fills.

    The generator appends its hardware sections *after* the core ones, so the
    panels kept here are always a **prefix** of what it produced — which is why
    no `gridPos` reflow is needed and none is done. `tests/test_dashboards.py`
    asserts that prefix property: if a future generator ever interleaves a
    hardware row among the basic ones, that test fails rather than this quietly
    leaving a vertical hole in the middle of somebody's dashboard.
    """
    kept, dropping = [], False
    for panel in model.get("panels", []):
        if panel.get("type") == "row":
            dropping = not panel.get("title", "").startswith(BASIC_ROWS)
        if not dropping:
            kept.append(panel)
    return {**model, "panels": kept}


def build(host: str, caps: set[str], ctx: dict) -> dict:
    """The Grafana model for this host. Signature is the dashboard-package API.

    `caps` is accepted and deliberately unused: the default does not branch on
    hardware, it *omits* everything that would. A fork that wants an NVIDIA row
    has the argument ready — that is the intended way to specialise this.
    """
    generator = _generator()
    if host not in generator.CAPABILITIES:
        # A host the generator has no cut for (BSD, say). The portable
        # Linux/macOS dashboard is the honest fallback: its `or`-fallbacks cover
        # the metric names node_exporter actually emits there.
        return basic_rows(generator.build_node())
    return basic_rows(generator.build_for(host, set()))
