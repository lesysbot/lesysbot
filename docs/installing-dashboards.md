# Install dashboards

A dashboard is a page of graphs in Grafana. LeSysBot ships one — **System
Overview**, covering CPU, memory, disk, network, temperatures and GPU — and you
can install more the same way you install tools.

```bash
lesysbot search --kind dashboard      # see what's available
lesysbot install owner/their-dashboard
lesysbot dashboard render             # write it out for Grafana
```

Grafana picks up the change within 30 seconds. Or use the **Dashboards** tab in
the control panel at <http://127.0.0.1:8700> and click Render.

## Why a dashboard sometimes doesn't appear

Because it would have been empty, and we would rather tell you than show you a
page of blank panels:

```
$ lesysbot dashboard render
○ postgres — 'pg_up' is not being scraped (+1 more)

0/1 provisioned.
```

A panel querying a metric nothing collects looks *exactly* like a panel that's
broken. So a dashboard whose metrics aren't there is not written at all, and
`lesysbot dashboard list` says why. Install the exporter it needs, run render
again, and it appears.

`lesysbot doctor` gives the same answer with the fix attached.

This also works in reverse: if a dashboard was working and its exporter goes
away, the next render **removes** it rather than leaving Grafana serving
something that has quietly gone blank.

## Changing a dashboard

Every installed dashboard is a folder you own:

```
~/.lesysbot/dashboard/installed/system-overview/
  README.md        what it needs
  dashboard.py     the panels
```

Edit it, run `lesysbot dashboard render`, done. **Your edit survives
`lesysbot update`** — that is the point of it being a file rather than something
you changed in Grafana's UI. (Editing in the Grafana UI looks like it works: the
save is accepted, stored, and then reverted the next time the dashboard is
provisioned. That has always been true and is not something this fixes — it's
why editing the package is the supported route.)

## Writing one

Two shapes, and the difference is whether the dashboard needs to know anything
about the machine.

**A plain Grafana export** — `dashboard.json`. Hit "Export" in Grafana, drop the
JSON in a folder, push it to GitHub. That's the whole thing.

```
my-dashboard/
  README.md
  dashboard.json
```

**Host-adaptive** — `dashboard.py`, when the right panels depend on the hardware:

```python
def build(host, caps, ctx):
    """host: always "linux". caps: {'nvidia', 'amd'} — what's usable here."""
    panels = [cpu_panel(), memory_panel()]
    if "nvidia" in caps:
        panels.append(nvidia_panel())      # only where a driver can answer
    return {"title": f"My dashboard — {host}", "panels": panels}
```

Declare what it needs in the README frontmatter, and LeSysBot checks it against
your live Prometheus before provisioning:

```yaml
---
name: postgres
kind: dashboard
description: PostgreSQL connections, cache hit rate, replication lag
version: "1.0.0"
prerequisites:
  - service: prometheus
  - metric: pg_up
preserve: [".env"]        # your file; an update won't overwrite it
---
```

`kind: dashboard` is optional — a folder holding `dashboard.json` or
`dashboard.py` is recognised as a dashboard regardless.

Share it by pushing to GitHub. Anyone can then run
`lesysbot install yourname/your-repo`.

## A repo can hold both

If your repo has `tools/` and `dashboards/` folders, one command installs
everything in it, each part going where it belongs:

```bash
lesysbot install yourname/your-repo
```

---

<details>
<summary><b>Where the files actually go</b></summary>

```
~/.lesysbot/dashboard/
  installed/<name>/                    the package — source, yours to edit
  grafana/dashboards/generated/        rendered JSON, what Grafana reads
  prometheus/  grafana/  scripts/      the stack itself
  .env                                 ports and the Grafana login
```

`generated/` is derived output, rewritten on every render — edit the package,
never that. The stack provisions from that one directory, so an installed
dashboard shows up whether you start it with `start.sh` or `docker compose`.

</details>
