"""Build a Grafana dashboard model without writing Grafana JSON by hand.

This is the **panel builder a dashboard package imports**. Grafana's own mental
model is that a dashboard *is* a JSON document — the thing behind *Dashboard
settings → JSON Model* — and a LeSysBot ``dashboard.py`` is nothing more than a
function that returns that document as a Python dict. This module is the set of
helpers that make writing one bearable: a 24-column auto-flow layout, panel
constructors with the house defaults already applied, and the model envelope.

    from lesysbot.dashboards import Layout, dashboard, sel, PCT

    CONFIG = {"uid": "my-dashboard", "title": "My Dashboard"}

    IDLE = sel('mode="idle"')          # {mode="idle",instance=~"$instance"}
    BUSY = f"100 - avg(rate(node_cpu_seconds_total{IDLE}[$__rate_interval])) * 100"

    def build(host, caps, ctx):
        g = Layout()
        g.row("Now")
        g.gauge("CPU busy", [(BUSY, "busy")], "percent", thresholds=PCT)
        return dashboard(CONFIG, g)

**Why this ships with LeSysBot rather than being copied into each package.**
It used to be a ``_panels.py`` copied byte-identical into every dashboard
package, with a test to police the copies, because the renderer did not put a
package's directory on ``sys.path`` and so ``import _panels`` failed. Tool
packages *are* deliberately copy-paste self-contained — a tool has to survive
being lifted out of its repo — but that argument never transferred to
dashboards: a dashboard package is only ever loaded by LeSysBot's own renderer,
so the library it needs is present by definition. Shipping it here means an
author imports one line instead of vendoring 300, and a fix reaches every
package at once.

Stdlib only, and it imports nothing else from ``lesysbot`` — third-party code
imports this at render time, so it must stay cheap and cycle-free.
"""

from __future__ import annotations

# Bumped when something here changes in a way a package could notice. The
# render context's `api_version` says how old the *renderer* is; this says how
# old the *builder* is, and they move independently.
#
# 1: Layout, sel, dashboard, host_variable, stamp, the three threshold ramps —
# the API as it stood when this was `_panels.py` in the official collection, so
# a package migrated off that copy needs no changes beyond its import line.
MODEL_API_VERSION = 1

# The datasource every panel binds to. Fixed uid, provisioned by the stack in
# `grafana/provisioning/datasources/datasource.yml` — do not template it.
DS = {"type": "prometheus", "uid": "prometheus"}

# Threshold ramps, so a tile means the same thing on every dashboard.
PCT = [
    {"color": "green", "value": None},
    {"color": "yellow", "value": 70},
    {"color": "red", "value": 90},
]
TEMP = [
    {"color": "green", "value": None},
    {"color": "yellow", "value": 70},
    {"color": "red", "value": 85},
]
# Inverted: for "free"/"available" readings, low is the bad end.
PCT_FREE = [
    {"color": "red", "value": None},
    {"color": "yellow", "value": 10},
    {"color": "green", "value": 25},
]


def sel(*matchers: str) -> str:
    """A PromQL selector combining *matchers* with the dashboard's Host filter.

    Every panel is scoped to `$instance` so one dashboard serves a Prometheus
    that scrapes more than this machine. Empty matchers are dropped, so
    `sel()` is a valid "just this host" selector.
    """
    parts = [m for m in matchers if m]
    parts.append('instance=~"$instance"')
    return "{" + ",".join(parts) + "}"


class Layout:
    """24-column auto-flow layout: append panels, rows wrap for you.

    Panels are placed left to right and wrap when the next one would not fit,
    so a build function reads as a list of panels rather than a pile of
    hand-computed `gridPos` coordinates (which is how the first dashboards in
    this project were written, and why none of them ever grew past four panels).
    """

    def __init__(self) -> None:
        self.panels: list[dict] = []
        self._x = 0
        self._y = 0
        self._row_h = 0
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _place(self, w: int, h: int) -> dict:
        if self._x + w > 24:
            self._y += self._row_h
            self._x = 0
            self._row_h = 0
        pos = {"h": h, "w": w, "x": self._x, "y": self._y}
        self._x += w
        self._row_h = max(self._row_h, h)
        return pos

    def _targets(self, targets: list[tuple[str, str]], instant: bool = False) -> list[dict]:
        out = []
        for i, (expr, legend) in enumerate(targets):
            target = {
                "refId": chr(ord("A") + i),
                "datasource": DS,
                "expr": expr,
                "legendFormat": legend,
            }
            if instant:
                target["instant"] = True
                target["format"] = "table"
            out.append(target)
        return out

    # ------------------------------------------------------------------ panels

    def row(self, title: str) -> None:
        """A section header. Starts a fresh line of panels beneath it."""
        if self._x != 0:
            self._y += self._row_h
            self._x = 0
            self._row_h = 0
        self.panels.append({
            "type": "row",
            "title": title,
            "collapsed": False,
            "id": self._next_id(),
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self._y},
            "panels": [],
        })
        self._y += 1

    def stat(self, title, targets, unit, *, w=4, h=4, thresholds=None,
             decimals=None, minv=None, maxv=None, desc=""):
        """A single-value tile with a sparkline behind it."""
        self._value_panel("stat", title, targets, unit, w, h, thresholds,
                          decimals, minv, maxv, desc)

    def gauge(self, title, targets, unit, *, w=4, h=5, thresholds=None,
              decimals=None, minv=0, maxv=100, desc=""):
        """A dial. Use where the value has a real ceiling (a percentage, a limit)."""
        self._value_panel("gauge", title, targets, unit, w, h, thresholds,
                          decimals, minv, maxv, desc)

    def _value_panel(self, kind, title, targets, unit, w, h, thresholds,
                     decimals, minv, maxv, desc):
        defaults: dict = {
            "unit": unit,
            "thresholds": {
                "mode": "absolute",
                "steps": thresholds or [{"color": "green", "value": None}],
            },
        }
        if decimals is not None:
            defaults["decimals"] = decimals
        if minv is not None:
            defaults["min"] = minv
        if maxv is not None:
            defaults["max"] = maxv
        gauge = kind == "gauge"
        self.panels.append({
            "type": kind,
            "title": title,
            "description": desc,
            "id": self._next_id(),
            "datasource": DS,
            "gridPos": self._place(w, h),
            "targets": self._targets(targets),
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "orientation": "auto",
                "colorMode": "none" if gauge else "value",
                "graphMode": "none" if gauge else "area",
                "textMode": "auto",
                "showThresholdLabels": False,
                "showThresholdMarkers": True,
            },
            "fieldConfig": {"defaults": defaults, "overrides": []},
        })

    def ts(self, title, targets, unit, *, w=12, h=8, stack=False, fill=10,
           minv=None, maxv=None, decimals=None, desc=""):
        """A timeseries with a table legend (mean / max / last per series)."""
        custom = {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": fill,
            "gradientMode": "opacity",
            "spanNulls": False,
            "showPoints": "never",
            "stacking": {"mode": "normal" if stack else "none", "group": "A"},
            "axisPlacement": "auto",
        }
        defaults: dict = {"unit": unit, "custom": custom}
        if minv is not None:
            defaults["min"] = minv
        if maxv is not None:
            defaults["max"] = maxv
        if decimals is not None:
            defaults["decimals"] = decimals
        self.panels.append({
            "type": "timeseries",
            "title": title,
            "description": desc,
            "id": self._next_id(),
            "datasource": DS,
            "gridPos": self._place(w, h),
            "targets": self._targets(targets),
            "options": {
                "legend": {"displayMode": "table", "placement": "bottom",
                           "calcs": ["mean", "max", "lastNotNull"]},
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
            "fieldConfig": {"defaults": defaults, "overrides": []},
        })

    def table(self, title, targets, *, w=24, h=8, unit="short", desc="",
              hide=("Time", "job", "__name__")):
        """An instant-query inventory table — one row per series, joined by label.

        Used for the facts that are properties rather than measurements (link
        speed, MTU, mountpoint, GPU model). `hide` names the columns Prometheus
        adds that nobody wants to read.
        """
        self.panels.append({
            "type": "table",
            "title": title,
            "description": desc,
            "id": self._next_id(),
            "datasource": DS,
            "gridPos": self._place(w, h),
            "targets": self._targets(targets, instant=True),
            "options": {"showHeader": True, "footer": {"show": False}},
            "transformations": [
                {"id": "merge", "options": {}},
                {"id": "organize",
                 "options": {"excludeByName": {name: True for name in hide}}},
            ],
            "fieldConfig": {
                "defaults": {"unit": unit, "custom": {"align": "auto"}},
                "overrides": [],
            },
        })

    def note(self, title, text, *, w=24, h=4):
        """A markdown panel. For a caveat that has to be read, not hovered."""
        self.panels.append({
            "type": "text",
            "title": title,
            "id": self._next_id(),
            "gridPos": self._place(w, h),
            "options": {"mode": "markdown", "content": text},
        })


# The Host picker every dashboard carries. `up{job=~"node|windows"}` is how the
# bundled Prometheus names its host-exporter jobs (prometheus/prometheus.yml).
def host_variable() -> dict:
    return {
        "type": "query",
        "name": "instance",
        "label": "Host",
        "datasource": DS,
        "query": {"query": 'label_values(up{job=~"node|windows"}, instance)',
                  "refId": "StandardVariableQuery"},
        "refresh": 2,
        "includeAll": True,
        "multi": True,
        "current": {"text": "All", "value": "$__all"},
        "sort": 1,
    }


def dashboard(config: dict, layout: Layout, *, description: str = "",
              extra_vars: list[dict] | None = None) -> dict:
    """Wrap *layout*'s panels in the Grafana model envelope described by *config*.

    `config` is the package's declared Grafana settings — `uid`, `title`,
    `tags`, `refresh`, `time_from` — kept as data at the top of each
    `dashboard.py` so the model is readable without following the panel code.

    The `uid` here is what someone gets who imports the resulting JSON straight
    into Grafana by hand. LeSysBot itself overwrites it at render time with the
    fixed `lesysbot` uid, because an install keeps one dashboard and `/d/lesysbot`
    has to be a constant address — see `render.DASHBOARD_UID`.
    """
    return {
        "uid": config["uid"],
        "title": config["title"],
        "description": description,
        "tags": config.get("tags", ["lesysbot"]),
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "editable": True,
        "refresh": config.get("refresh", "30s"),
        "time": {"from": config.get("time_from", "now-3h"), "to": "now"},
        "templating": {"list": [host_variable()] + list(extra_vars or [])},
        "panels": layout.panels,
        "annotations": {"list": []},
    }


def stamp(host: str, ctx: dict) -> str:
    """`"macos arm64 14.5"` — which cut of the dashboard a screenshot shows.

    `os_version` is `""` when LeSysBot could not determine it, which means
    unknown and never "old", so it is simply omitted.
    """
    return " ".join(
        part for part in (host, ctx.get("arch", ""), ctx.get("os_version", ""))
        if part
    )
