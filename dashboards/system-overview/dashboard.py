"""System Overview — the dashboard LeSysBot ships with, as an installable package.

This is deliberately the *first* dashboard package: it is the hardest case in
the repo (three host cuts, hardware-conditional rows, `or`-fallbacks across
OSes), so if the package format can express it, it can express a third-party
one. Its output is byte-identical to what `gen-dashboards.py` produced before —
`tests/test_dashboards.py` pins that, so the format change cannot silently alter
anybody's dashboard.

The panel definitions themselves are **not** copied here. They stay in
`dashboard/scripts/gen-dashboards.py`, which remains the single source of truth
and is still runnable standalone by the stack's start scripts on a machine with
no LeSysBot install. This file only maps LeSysBot's host/capability vocabulary
onto that generator's.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# LeSysBot's GPU vendor names → the capability flags gen-dashboards.py expects.
# NVIDIA needs its exporter; AMD reads straight from hwmon.
_GPU_CAPS = {"nvidia": "nvidia", "amd": "amd_gpu"}


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


def _capabilities(host: str, caps: set[str], generator) -> set[str]:
    """Translate detected capabilities into the ones this host's cut accepts.

    Filtered against the generator's own `CAPABILITIES` table rather than passed
    through: an unknown flag is an argparse error there, and a dashboard that
    refuses to render because the host grew a new GPU vendor would be a worse
    failure than simply omitting that row.
    """
    known = generator.CAPABILITIES.get(host, set())
    translated = {_GPU_CAPS[c] for c in caps if c in _GPU_CAPS}

    # Linux temperature rows are driven by hwmon chips, which the stack's
    # start.sh probes for. Rendering from LeSysBot can't see that probe, so the
    # sensor caps are requested and simply dropped when this host's cut has no
    # such row — a panel with no data is omitted, never emptied.
    translated |= {"cpu_temp", "disk_temp", "thermal_zone", "thermalzone"}
    return translated & known


def build(host: str, caps: set[str], ctx: dict) -> dict:
    """The Grafana model for this host. Signature is the dashboard-package API."""
    generator = _generator()
    if host not in generator.CAPABILITIES:
        # A host the generator has no cut for (BSD, say). The portable dashboard
        # is the honest fallback: it asks for every sensor family, so whatever
        # node_exporter does emit there still lands in a panel.
        return generator.build_node()
    return generator.build_for(host, _capabilities(host, caps, generator))
