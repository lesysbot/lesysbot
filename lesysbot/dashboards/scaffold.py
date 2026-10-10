"""Create a dashboard package — the ``lesysbot dashboard new`` machinery.

Two routes in, both landing on the same three-file shape:

* **From nothing.** A starter package with real panels against metrics a stock
  ``node_exporter`` always has, so the very first render shows something rather
  than an empty page you have to debug before you have learned anything.
* **From a Grafana export.** The JSON behind *Dashboard settings → JSON Model*,
  or what *Export → Save to file* writes. This is the route most people will
  take, because the honest answer to "how do I design a dashboard" is "in
  Grafana, with the mouse" — LeSysBot's job starts once you want to keep it,
  version it and give it to someone.

The export needs normalising rather than copying: Grafana's *share externally*
mode replaces every datasource with a ``${DS_...}`` placeholder resolved by an
import wizard that LeSysBot has no equivalent of, so a copied export renders as
panels bound to a datasource that does not exist. :func:`from_grafana_export`
binds them to the stack's provisioned Prometheus instead, which is the only
datasource a LeSysBot install has.

Kept out of ``cli/dashboard.py`` so the CLI verb stays a thin dispatcher, the
way ``render`` delegates to :mod:`lesysbot.dashboards.render`.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from lesysbot.dashboards import model as _model

# A Grafana "export for sharing externally" placeholder: `${DS_PROMETHEUS}`.
_PLACEHOLDER = re.compile(r"^\$\{[^}]+\}$")

# Keys an export carries that describe *how to import it into Grafana* rather
# than what the dashboard is. `__inputs`/`__requires` drive an import wizard
# LeSysBot does not have; `id` is the source instance's row id and means
# nothing here; `version` is that instance's edit counter.
_EXPORT_ONLY_KEYS = ("__inputs", "__requires", "__elements", "id", "version")


class ScaffoldError(Exception):
    """A package could not be created — the message is for the user."""


@dataclass
class Scaffolded:
    path: Path
    payload: str                      # "dashboard.json" | "dashboard.py"
    notes: list[str] = field(default_factory=list)


def title_from(name: str) -> str:
    """``"cpu-detail"`` → ``"Cpu Detail"``. A starting point, not a decree."""
    return name.replace("-", " ").replace("_", " ").title()


def valid_name(name: str) -> bool:
    """Package names are kebab-case: they become directory names and lock keys."""
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name))


# ----------------------------------------------------------------- normalising


def from_grafana_export(exported: dict) -> tuple[dict, list[str]]:
    """A Grafana export, rebound to the stack's provisioned Prometheus.

    Returns the cleaned model and a list of human-readable notes describing what
    changed — the CLI prints them, because silently rewriting somebody's
    datasource is exactly the kind of help that becomes a bug report.
    """
    if not isinstance(exported, dict):
        raise ScaffoldError("that JSON is not a Grafana dashboard model (expected an object)")
    if "panels" not in exported and "rows" not in exported:
        raise ScaffoldError(
            "that JSON has no `panels` — it does not look like a Grafana dashboard "
            "model. Use Dashboard settings → JSON Model, or Export → Save to file."
        )

    model = {k: v for k, v in exported.items() if k not in _EXPORT_ONLY_KEYS}
    dropped = [k for k in _EXPORT_ONLY_KEYS if k in exported]

    rewritten = _rebind_datasources(model)

    notes = []
    if dropped:
        notes.append(f"dropped import-wizard keys: {', '.join(dropped)}")
    if rewritten:
        notes.append(
            f"bound {rewritten} datasource reference{'s' if rewritten != 1 else ''} "
            f"to the provisioned Prometheus (uid `{_model.DS['uid']}`)"
        )
    if "uid" not in model:
        model["uid"] = "imported-dashboard"
        notes.append("added a placeholder `uid` — set it to something of your own")
    notes.append(
        "LeSysBot renders whatever is installed at the fixed uid `lesysbot`, so "
        "the `uid` above only matters to someone importing this JSON into "
        "Grafana by hand"
    )
    return model, notes


def _rebind_datasources(node) -> int:
    """Point every Prometheus/placeholder datasource ref at the provisioned one.

    Walks the whole model because a datasource reference can sit on the
    dashboard, on a panel, on a nested row panel, on an individual target, on a
    template variable or on an annotation — and an export that misses one
    renders that panel empty.
    """
    count = 0
    if isinstance(node, list):
        for item in node:
            count += _rebind_datasources(item)
        return count
    if not isinstance(node, dict):
        return count

    for key, value in list(node.items()):
        if key == "datasource" and _is_reboundable(value):
            node[key] = dict(_model.DS)
            count += 1
        else:
            count += _rebind_datasources(value)
    return count


def _is_reboundable(value) -> bool:
    """True for a Prometheus ref or an unresolved export placeholder.

    A dashboard genuinely pointing at some *other* datasource — a Loki panel
    somebody kept — is left alone rather than silently repointed at Prometheus.
    That panel will not fill, but it will say what it wanted, which is the more
    useful failure.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(_PLACEHOLDER.match(value)) or value.lower() == "prometheus"
    if isinstance(value, dict):
        uid = str(value.get("uid", ""))
        return bool(_PLACEHOLDER.match(uid)) or value.get("type") == "prometheus"
    return False


# -------------------------------------------------------------------- creating


def create(name: str, dest_dir: Path, *, from_json: dict | None = None,
           python: bool = False, description: str = "",
           force: bool = False) -> Scaffolded:
    """Write a dashboard package ``dest_dir/name/`` and describe what it wrote."""
    if not valid_name(name):
        raise ScaffoldError(
            f"'{name}' is not a valid package name — use kebab-case "
            "(lowercase letters, digits and single hyphens), e.g. `postgres-health`"
        )
    if from_json is not None and python:
        raise ScaffoldError("--from-json writes a dashboard.json; it cannot be combined with --python")

    target = Path(dest_dir) / name
    if target.exists():
        if not force:
            raise ScaffoldError(f"{target} already exists — pass --force to overwrite it")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    title = title_from(name)
    notes: list[str] = []

    if from_json is not None:
        model, notes = from_grafana_export(from_json)
        payload = "dashboard.json"
        body = json.dumps(model, indent=2) + "\n"
        blurb = description or model.get("description") or f"{title}, imported from Grafana"
    elif python:
        payload = "dashboard.py"
        body = _PY_TEMPLATE.replace("@@NAME@@", name).replace("@@TITLE@@", title)
        blurb = description or f"{title} — CPU utilization, adapting per OS"
    else:
        payload = "dashboard.json"
        body = json.dumps(starter_model(name, title), indent=2) + "\n"
        blurb = description or f"{title} — CPU utilization from node_exporter"

    (target / payload).write_text(body, encoding="utf-8")
    (target / "README.md").write_text(
        _README_TEMPLATE
        .replace("@@NAME@@", name)
        .replace("@@TITLE@@", title)
        .replace("@@DESCRIPTION@@", blurb.replace("\n", " ").strip())
        .replace("@@PAYLOAD@@", payload),
        encoding="utf-8",
    )
    return Scaffolded(path=target, payload=payload, notes=notes)


def starter_model(name: str, title: str) -> dict:
    """The from-nothing starter, built with the same builder a package imports.

    Generating it rather than storing a JSON blob is deliberate: the two
    starters cannot drift, and the JSON a beginner reads is exactly what the
    documented API produces.

    Static JSON cannot branch, so this uses the ``node_exporter`` metric names —
    correct on Linux and macOS. The README says so and points at ``--python``,
    which is the whole reason that route exists.
    """
    cpu = "node_cpu_seconds_total"
    # Hoisted out of the f-strings below: the project floor is Python 3.11,
    # where an f-string may not reuse the outer quote or carry a backslash.
    host = _model.sel()
    idle = _model.sel('mode="idle"')
    busy = _model.sel('mode!="idle"')

    g = _model.Layout()
    g.row("Now")
    g.gauge("CPU busy",
            [(f"100 - (avg(rate({cpu}{idle}[$__rate_interval])) * 100)", "busy")],
            "percent", w=8, decimals=1, thresholds=_model.PCT,
            desc="All non-idle time, averaged across every core.")
    g.stat("Load (1m)", [(f"node_load1{host}", "load1")], "short",
           w=8, decimals=2,
           desc="Runnable plus blocked tasks. Compare against the core count, "
                "not against zero.")
    g.stat("Uptime",
           [(f"node_time_seconds{host} - node_boot_time_seconds{host}", "uptime")],
           "s", w=8, decimals=0)

    g.row("Utilization")
    g.ts("Usage by mode",
         [(f"avg by (mode) (rate({cpu}{busy}[$__rate_interval])) * 100", "{{mode}}")],
         "percent", w=24, stack=True, minv=0,
         desc="Stacked, so the top of the stack is total busy. A tall `system` "
              "band means kernel work — I/O, network or a driver — rather than "
              "your own code.")

    return _model.dashboard(
        {"uid": name, "title": title, "tags": ["lesysbot"]}, g,
        description=f"{title}. Created by `lesysbot dashboard new` — edit it.",
    )


_PY_TEMPLATE = '''"""@@TITLE@@ — a LeSysBot dashboard package.

`build()` returns the Grafana dashboard model as a dict: the same document
Grafana shows under *Dashboard settings → JSON Model*, assembled in code so it
can adapt to the machine it renders on. That adaptation is the only reason to
prefer this over a plain `dashboard.json` — if your panels are the same
everywhere, a static export is less to maintain.
"""
from __future__ import annotations

from lesysbot.dashboards import PCT, Layout, dashboard, sel, stamp

CONFIG = {
    "uid": "@@NAME@@",
    "title": "@@TITLE@@",
    "tags": ["lesysbot"],
    "refresh": "30s",
    "time_from": "now-3h",
}

# node_exporter serves Linux and macOS; windows_exporter spells the same
# reading differently. This disagreement is what `dashboard.py` exists for.
_CPU = {"node": "node_cpu_seconds_total", "windows": "windows_cpu_time_total"}


def build(host: str, caps: set[str], ctx: dict) -> dict:
    """Build the model for this machine.

    host  "linux" | "macos" | "windows" — anything else is a platform LeSysBot
          has no cut for, so fall through to the node_exporter path.
    caps  usable GPU vendors: a subset of {"nvidia", "amd", "apple"}. Only
          vendors whose *reading tool* is present — a card with no driver is
          unscrapeable and does not appear here.
    ctx   {"api_version", "host", "caps", "arch", "os_version"}. `arch` is how
          you tell Apple silicon from an Intel Mac; `host` says "macos" for both.
    """
    cpu = _CPU["windows" if host == "windows" else "node"]
    idle = sel('mode="idle"')
    busy = sel('mode!="idle"')

    g = Layout()

    g.row("Now")
    g.gauge("CPU busy",
            [(f"100 - (avg(rate({cpu}{idle}[$__rate_interval])) * 100)", "busy")],
            "percent", w=8, decimals=1, thresholds=PCT,
            desc="All non-idle time, averaged across every core.")

    g.row("Utilization")
    g.ts("Usage by mode",
         [(f"avg by (mode) (rate({cpu}{busy}[$__rate_interval])) * 100", "{{mode}}")],
         "percent", w=24, stack=True, minv=0,
         desc="Stacked, so the top of the stack is total busy.")

    # Add your own rows here. Never ship a panel that can render blank without
    # saying why: omit it where the reading does not exist on that OS, or
    # explain the empty case in `desc`.

    return dashboard(
        CONFIG, g,
        description=f"@@TITLE@@. Rendered for {stamp(host, ctx)}.",
    )
'''


_README_TEMPLATE = '''---
name: @@NAME@@
kind: dashboard
description: @@DESCRIPTION@@
version: "0.1.0"
platforms: [linux, macos, windows]
prerequisites:
  - service: prometheus
---

# @@TITLE@@

A sentence or two about what someone gets from this dashboard.

## What it shows

- **Now** — CPU busy, load, uptime
- **Utilization** — CPU time by mode

## What it needs

`prerequisites:` above is the important part of this file. A panel querying a
metric nothing collects looks *exactly* like a broken panel, so LeSysBot would
rather withhold the whole dashboard and say why — but it can only do that if
this list is honest. Add a `- metric: <name>` line for anything beyond a stock
host exporter:

```yaml
prerequisites:
  - service: prometheus
  - metric: pg_up
```

`lesysbot doctor @@NAME@@` spells out every unmet line with the fix attached.

> **Windows spells its metrics differently.** `@@PAYLOAD@@` here queries
> `node_exporter` names, which are right on Linux and macOS. To serve Windows
> too, the dashboard has to branch — see
> [Write a dashboard](https://github.com/lesysbot/lesysbot/blob/main/docs/writing-dashboards.md).

## Working on it

```bash
lesysbot dashboard render          # re-provision; Grafana picks it up within 30s
lesysbot dashboard current         # is it installed, and did it reach Grafana?
```

Then open <http://localhost:3000/d/lesysbot>.

## Sharing it

Push this folder to a public GitHub repo and anyone can run:

```bash
lesysbot install you/@@NAME@@
```

Bump `version:` when you change what the dashboard shows.
'''
