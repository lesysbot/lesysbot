# Write a dashboard

A dashboard is a page of graphs in Grafana. Writing one and giving it to other
people takes two files and one `git push` — **no Python, no build step, and
nothing to register anywhere.**

This page goes from "I made some nice panels in Grafana" to "anyone can run
`lesysbot install you/my-dashboard`".

---

## Your first dashboard

**Build it in Grafana first.** Open <http://localhost:3000>, add panels until
the page tells you what you wanted to know. That's the creative part, and
LeSysBot isn't involved in it.

Then hit **Export → Save to file**. Put the JSON you get in a folder next to a
README:

```
my-dashboard/            # kebab-case folder name
  README.md
  dashboard.json         # exactly what Export gave you
```

`README.md` starts with a small block that names the package:

```markdown
---
name: my-dashboard
description: Postgres connections, cache hit rate and replication lag
version: "1.0.0"
---

# My dashboard

A sentence or two about what someone gets from it.
```

That's the whole package. Two files, one of which you didn't write.

> **`kind: dashboard` is optional.** A folder holding `dashboard.json` is
> recognised as a dashboard already. Add the line if you like being explicit.

---

## Try it before you publish

An install has **one** dashboard, so testing yours means taking the slot. Note
what's there first — `lesysbot dashboard reset` puts the default back when
you're done:

```bash
rm -rf ~/.lesysbot/dashboard/installed/*        # the slot holds one
cp -r my-dashboard ~/.lesysbot/dashboard/installed/
lesysbot dashboard render
```

```
✔ my-dashboard → ~/.lesysbot/dashboard/grafana/dashboards/generated/lesysbot.json

Grafana picks changes up within 30s.
```

Grafana picks it up within 30 seconds — no restart. Edit the package, run
`render` again, refresh the page at <http://localhost:3000/d/lesysbot>. That's
the whole loop.

**Don't set a `uid` and expect it to stick.** LeSysBot stamps `uid: "lesysbot"`
onto whatever you produce, so the address stays constant whichever dashboard is
installed — which also means a fork can't collide with its parent.

`lesysbot dashboard current` shows what's installed and whether it made it to
Grafana:

```
name          state  provisioned  description
my-dashboard  ready  yes          Postgres connections, cache hit rate…
```

> **Don't edit it in Grafana's UI and expect it to stick.** The save is
> accepted and stored, then overwritten the next time the dashboard is
> provisioned. Use the UI to *try a panel out*; put the result in the package.
> That is also what makes your changes survive `lesysbot update`.

---

## Say what it needs

A panel querying a metric nothing collects looks *exactly* like a broken panel.
So LeSysBot would rather not show your dashboard at all than show it empty —
but it can only do that if you tell it what "working" means:

```yaml
---
name: my-dashboard
description: Postgres connections, cache hit rate and replication lag
version: "1.0.0"
prerequisites:
  - service: prometheus
  - metric: pg_up
---
```

On a machine that can't satisfy that — no Prometheus, or no Postgres exporter
feeding it — the dashboard is **not written**, and the reason is right there:

```
$ lesysbot dashboard render
○ my-dashboard — nothing listening on 127.0.0.1:9090 (+1 more)

0/1 provisioned.
```

`lesysbot doctor my-dashboard` spells out every unmet line with the fix attached
(that's what `+1 more` is hiding). Once
the exporter is running, the dashboard appears by itself — and if the exporter
later goes away, the next render *removes* it rather than leaving Grafana
serving a page that has quietly gone blank.

Testing on a machine that can't satisfy your own prerequisites? `lesysbot
dashboard render --force` writes it anyway.

**The prerequisite types you'll actually use:**

| Write | Means |
|---|---|
| `service: prometheus` | Prometheus is up. Also `grafana`, `ollama`, or `host:port` |
| `metric: pg_up` | That metric returns at least one series right now |
| `gpu: nvidia` | A usable GPU of that vendor — `nvidia`, `amd`, `apple` |
| `binary: nvidia-smi` | That program is on `PATH` |
| `os: linux` | Also `arch:`, `os_version:`, `python:`, `pip:`, `docker:`, `port:` |

Two things to know before you design around them: prerequisites are **ANDed**
(there's no "either/or"), and **one list serves every OS** the package claims.
So a dashboard that spans Linux and Windows gates on `service: prometheus` and
lets its panels explain their own gaps — a `metric:` gate is only right when
that metric exists everywhere the dashboard claims to run.

---

## Share it

Push the folder to a public GitHub repo. That's the publishing step; there is
nothing else.

```bash
lesysbot install you/my-dashboard
```

Installing **renders it**, so it's in the other person's Grafana within 30
seconds with nothing else to run.

**Two repo shapes work.** Either the repo *is* the package:

```
my-dashboard/            ← the repo root
  README.md
  dashboard.json
```

…or it holds several, each in its own folder:

```
my-dashboards/
  dashboards/
    postgres/
      README.md
      dashboard.json
    redis/
      README.md
      dashboard.json
```

`lesysbot install you/my-dashboards` **asks which one**, because an install has
room for exactly one dashboard. People choose with `--only postgres`, or install
one directly as `you/my-dashboards/dashboards/postgres`.

A collection is still worth shipping — it's one repo to maintain, and the
refusal names every dashboard in it, which is how people discover the others.
But if your dashboards are variants of one idea (per-OS cuts, say), prefer a
single package that adapts via [`dashboard.py`](#when-the-panels-differ-per-machine):
one install, no choice to make.

**Tag your releases** so people can pin to one:

```bash
git tag v1.0.0 && git push --tags
```

```bash
lesysbot install you/my-dashboard@v1.0.0
```

The installer records the exact commit it took, whatever ref was asked for, so
`lesysbot update` re-fetches the same thing later. Bump `version:` in the
frontmatter when you change what the dashboard shows — that's the number
`lesysbot list` displays.

### Making it findable

**You don't have to.** Anyone can install your repo by name today. Listing only
adds it to `lesysbot search` and the control panel's Marketplace tab.

To be listed, open a PR adding a row to [`catalog.json`](../catalog.json):

```json
{
  "id": "my-dashboard",
  "name": "My Dashboard",
  "kind": "dashboard",
  "description": "One line — this is what search shows",
  "source": "you/my-dashboard",
  "homepage": "https://github.com/you/my-dashboard",
  "platforms": ["linux", "macos", "windows"],
  "tags": ["grafana", "postgres"],
  "official": false
}
```

`id`, `name` and `source` are required; the rest default. The catalog is a
**list, not a gatekeeper** — nothing decides what you may install, and a catalog
entry resolves through the same parser and the same consent prompt as a link you
typed by hand.

### Before you push

- [ ] `README.md` frontmatter has `name`, `description` and `version`.
- [ ] `prerequisites:` declared, so it's withheld with a reason rather than blank.
- [ ] Every metric name verified against a Prometheus you actually ran — a
      plausible-looking wrong name renders as an empty panel.
- [ ] Tested by copying into `~/.lesysbot/dashboard/installed/` and rendering.

---

## When the panels differ per machine

Everything above is the common case and you can stop there. Read on only if
your dashboard needs to *change shape* depending on the machine — because
node_exporter and windows_exporter genuinely disagree about metric names, or
because an NVIDIA row makes no sense on a box with no NVIDIA driver.

Swap `dashboard.json` for a `dashboard.py` that builds the same model as a
Python dict:

```python
def build(host: str, caps: set[str], ctx: dict) -> dict:
    """host: linux|macos|windows.  caps: GPU vendors usable here."""
    panels = [cpu_panel(), memory_panel()]
    if "nvidia" in caps:
        panels.append(nvidia_panel())        # only where a driver can answer
    return {"title": f"My dashboard — {host}", "panels": panels}
```

Return value is a plain Grafana dashboard model — the same JSON as before, just
assembled in code. `dashboard.py` wins if both files are present.

**`host`** is `"linux"`, `"macos"` or `"windows"`. Anything else is a platform
LeSysBot has no cut for (a BSD, say) — fall back to the node_exporter path
rather than raising.

**`caps`** is **GPU vendors only**, and only those whose *reading tool* is
present:

| Value | Present when |
|---|---|
| `"nvidia"` | `nvidia-smi` is on `PATH`. A card with no driver is unscrapeable and does **not** appear |
| `"amd"` | `rocm-smi` on `PATH`, or an AMD/Radeon device on Linux |
| `"apple"` | macOS on `arm64` — Intel Macs don't get this |

That's the whole vocabulary. There's no capability string for anything else; to
branch on something else, branch on `host` and explain the empty case in the
panel description.

**`ctx`** carries the rest:

```python
{"api_version": 2, "host": "macos", "caps": ["apple"],
 "arch": "arm64", "os_version": "26.5.2"}
```

`arch` is how you tell Apple silicon from an Intel Mac — `host` says `"macos"`
for both. `os_version` is `""` when it can't be determined; treat that as
*unknown*, never as *old*. New keys are only ever added, so a `build()` written
against an older `api_version` keeps working.

### Splitting it across files

Put helpers in `_`-prefixed files next to `dashboard.py`. **A plain
`import _panels` will not work** — unlike the tool loader, the dashboard
renderer doesn't put your package's folder on `sys.path`, and you'd get:

```
○ my-dashboard — render failed: No module named '_panels'
```

Load them by path instead. Copy this verbatim:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


def _sibling(name: str):
    """Import a package-local helper by path (the renderer does not extend sys.path)."""
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        f"_lesysbot_dash_{here.name}_{name}", here / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_p = _sibling("_panels")
```

The module name includes the folder name, so a dashboard replacing another that
also shipped a `_panels.py` gets its own — not the previous one left behind in
`sys.modules`.

### Don't start from a blank file

Writing Grafana panel JSON by hand is miserable. The
[official collection](https://github.com/lesysbot/lesysbot-packages-official/tree/main/dashboards)
ships a `_panels.py` — a small builder that lays panels out on Grafana's
24-column grid for you — copied into every package so each one installs alone:

```python
g = _p.Layout()
g.row("Now")
g.gauge("Fullest filesystem", [("max(...) * 100", "used")], "percent", w=6)
g.ts("Throughput", [("rate(node_disk_read_bytes_total[$__rate_interval])",
                     "{{device}} read")], "Bps")
return _p.dashboard(CONFIG, g, description="…")
```

Copy the package closest to what you want, edit its panels, and you have the
layout helper and the house conventions for free. That repo's
[dashboards/README.md](https://github.com/lesysbot/lesysbot-packages-official/blob/main/dashboards/README.md)
documents the builder API and carries a **metric reference** — what each
exporter actually emits, per OS — which is the table to write queries against.

### Rules worth following

1. **Never ship a panel that can be blank without saying why.** Omit it where
   the concept doesn't exist on that OS, explain it in the panel `description`
   where it depends on hardware, or replace the whole row with a note.
2. **Don't invent metric names.** If you can't verify a name against a running
   Prometheus or the exporter's own docs, leave the panel out and say so.
3. **Scope panels to the host** and filter the noise — loopback interfaces,
   `tmpfs` filesystems, loop devices. None of them are ever the answer.
4. **Use `$__rate_interval`, not a fixed `[5m]`.** Grafana matches the window to
   the panel's resolution; a hardcoded one gives flat or spiky graphs depending
   on the time range.
5. **No root, ever.** If a reading needs `sudo`, the answer is text explaining
   the unprivileged alternative, not a privileged collector.

---

## Frontmatter reference

Everything you can put in the README block. Every key is optional.

| Key | What it does |
|---|---|
| `name` | The package name. Defaults to the folder (or repo) name; set it to override |
| `description` | One line — what `lesysbot search` and `list` show |
| `version` | Shown by `lesysbot list/info`. Bump it on each release |
| `kind` | `dashboard`. Optional — inferred from `dashboard.json`/`dashboard.py` |
| `platforms` | `[linux, macos, windows]` or `all`. **Immutable gate**: a collection install skips the package where it fails |
| `prerequisites` | **Fixable gate**: installs anyway, withheld from Grafana with a reason until met |
| `preserve` | Files an update must not overwrite, e.g. `[".env"]` |

---

## Under the hood

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
never that. All three ways of running the stack (Docker on Linux, Docker Desktop
on macOS/Windows, and the Docker-free Homebrew path on macOS) provision from
that one directory, so an installed dashboard shows up however you run it.

Each file is written whole and then moved into place, because Grafana polls that
directory and would happily load a half-written one.

</details>

<details>
<summary><b>A repo holding both tools and dashboards</b></summary>

If your repo has `tools/` and `dashboards/` folders, one command installs
everything in it and each part goes where it belongs:

```bash
lesysbot install you/your-repo
```

Kind is decided per package — from `kind:` in the frontmatter, else from the
payload file, else `tool`. That's why a plain Grafana export dropped in a repo
installs correctly with no metadata at all, and why every tool package written
before dashboards existed still installs unchanged.

</details>

<details>
<summary><b>Editing an installed dashboard you didn't write</b></summary>

Every installed dashboard is a folder you own, so editing someone else's is the
same loop: change `~/.lesysbot/dashboard/installed/<name>/`, run `lesysbot
dashboard render`.

The catch is `lesysbot update`, which re-fetches the package at its recorded ref
and overwrites your edit. Either add the file to `preserve:` in the frontmatter,
or work in a clone of their repo and install from that instead.

</details>

<details>
<summary><b>Why an unavailable dashboard is deleted, not stubbed</b></summary>

An unavailable *tool* stays visible and returns an explanation when called —
you should know the capability exists even where it can't run.

Dashboards go the other way, because the failure modes aren't symmetrical: a
tool that explains itself is useful, while a dashboard of empty panels is
indistinguishable from a broken one. So it's withheld, the reason goes in
`lesysbot dashboard current`, and a previously rendered copy is removed when its
exporter goes away.

</details>

---

**See also:** [Your dashboard](dashboards.md) ·
[Write a tool](writing-tools.md) · [Share your tools](sharing-tools.md)
