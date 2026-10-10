"""Rendering and provisioning for the installed dashboard package.

A dashboard *package* is source the user owns (``~/.lesysbot/dashboard/installed/``);
the rendered JSON Grafana reads is derived output, rewritten on every render.
Keeping those separate is what lets an edit survive an update — the thing the
pre-refactor stack could not do, since it regenerated its single dashboard on
every start and mounted it read-only.

An install has **one** dashboard. It starts as the bundled default below and is
replaced — not joined — by anything installed from GitHub.

``model`` is re-exported here so a package's ``dashboard.py`` opens with one
readable line — ``from lesysbot.dashboards import Layout, dashboard, sel`` —
rather than reaching into a submodule. It is stdlib-only and imports nothing
else from ``lesysbot``, so this costs a package nothing.
"""

from lesysbot.dashboards.model import (
    DS,
    MODEL_API_VERSION,
    PCT,
    PCT_FREE,
    TEMP,
    Layout,
    dashboard,
    host_variable,
    sel,
    stamp,
)

# The dashboard a fresh install starts with, bundled in the wheel.
#
# Deliberately the *basic* one: CPU, memory, disk and network, the readings a
# stock node_exporter/windows_exporter always has. Anything beyond that —
# temperatures, GPU, per-filesystem detail — depends on hardware this machine
# may not have, and a panel querying a series nobody collects is
# indistinguishable from a broken one. Users who want those install a dashboard
# built for their machine, or fork one and edit it.
DEFAULT_DASHBOARD = "system-overview"

__all__ = [
    "DEFAULT_DASHBOARD",
    "DS",
    "MODEL_API_VERSION",
    "PCT",
    "PCT_FREE",
    "TEMP",
    "Layout",
    "dashboard",
    "host_variable",
    "sel",
    "stamp",
]
