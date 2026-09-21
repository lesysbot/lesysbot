# Dashboards

Graphs of your machine over time — CPU, memory, disk, network, temperatures and
GPU — in Grafana at:

```
http://localhost:3000
```

The installer set this up. Log in with the username and password you chose
during setup (`admin` by default; an unattended install generated one and saved
it in `~/.lesysbot/grafana.env`). Your dashboards are in the **LeSysBot** folder.

## Start and stop

```bash
lesysbot dashboard start
lesysbot dashboard stop
```

It needs Docker. Everything listens on `127.0.0.1` only, and nothing needs
`sudo`.

<details>
<summary><b>Don't have Docker yet?</b></summary>

Install [Docker Engine](https://docs.docker.com/engine/install/) for your
distribution, then let your user run it without `sudo`:

```bash
sudo usermod -aG docker $USER      # then log out and back in
docker compose version             # should print v2.x
lesysbot dashboard start
```

</details>

## What's included

| Dashboard | Shows |
|---|---|
| **System Overview** | CPU, memory, disk, network per interface, temperatures, NVIDIA GPU |
| **Network Traffic** | Throughput per network interface |
| **GPU Detail** | NVIDIA utilization, memory, temperature and power |

Panels your hardware can't fill are left out, so an empty panel means something
is actually wrong. A dashboard whose data isn't available — GPU Detail on a
machine without an NVIDIA driver, say — isn't shown at all.
`lesysbot dashboard list` tells you why.

## Share a snapshot

Ask the bot:

```
You: share me the dashboard for a day
Bot: 📊 Dashboard shared — expires in 1d:
     https://snapshots.raintank.io/dashboard/snapshot/…
```

Anyone with the link can see a copy of your graphs. Links can last from an hour
to a month. Say *"list my shared dashboards"* to see them, and *"delete snapshot
1"* to take one down (a cached copy may linger for up to an hour).

## Add more dashboards

```bash
lesysbot search --kind dashboard     # see what's available
lesysbot install owner/repo          # install one from GitHub
lesysbot dashboard render            # show it in Grafana
```

Grafana picks it up within 30 seconds. The **Dashboards** tab in the
[control panel](management-ui.md) does the same.

## Change or write one

Installed dashboards live in `~/.lesysbot/dashboard/installed/<name>/`. Edit the
files there, then run `lesysbot dashboard render`. Changes made in Grafana's own
editor are lost on the next render, so edit the files instead.

The simplest dashboard is a Grafana export: click **Export** in Grafana, save the
JSON as `dashboard.json` in a folder with a `README.md`, and push it to GitHub.
Anyone can then install it with `lesysbot install`.

<details>
<summary><b>Declare what a dashboard needs</b></summary>

Put the requirements in the README frontmatter. LeSysBot checks them against
Prometheus before showing the dashboard:

```yaml
---
name: postgres
kind: dashboard
description: PostgreSQL connections, cache hit rate, replication lag
version: "1.0.0"
prerequisites:
  - service: prometheus
  - metric: pg_up
---
```

For panels that depend on the hardware, use `dashboard.py` instead of JSON:

```python
def build(host, caps, ctx):
    panels = [cpu_panel(), memory_panel()]
    if "nvidia" in caps:
        panels.append(nvidia_panel())
    return {"title": "My dashboard", "panels": panels}
```

</details>

Ports, `.env` settings and the stack's internals are in
[`dashboard/README.md`](../dashboard/README.md). Empty panels? See
[Troubleshooting](troubleshooting.md#dashboards).
