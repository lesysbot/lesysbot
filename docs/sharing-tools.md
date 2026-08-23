# Share your tools and dashboards

Any public GitHub repo containing a tool or dashboard folder package is
installable by anyone with one command — there is nothing to register or
publish beyond pushing the repo:

```bash
lesysbot install you/lesysbot-gpu-tools
```

## 1. A single-tool repo

The simplest shareable unit — the repo *is* the package:

```
lesysbot-gpu-temp/
├── README.md        # frontmatter: name, description, version, platforms, requires
├── tool.py          # the tools (@tool functions / CLITool instances)
├── _helpers.py      # optional, ignored by the loader, importable by tool.py
└── requirements.txt # optional pip deps (printed, not auto-installed)
```

`README.md` frontmatter is optional but recommended — it names and describes
the package without executing any code:

```markdown
---
name: gpu-temp
description: Read NVIDIA GPU temperature
version: 1.0.0
platforms: [linux, windows]
requires: [nvidia-smi]
---
```

`name` overrides the folder/repo name; `version` shows up in
`lesysbot list/info`. `platforms`/`requires` document the gating your
`tool.py` declares (the code is what's enforced).

## 2. A multi-tool repo

Put each package in its own subdirectory:

```
lesysbot-tools/
├── gpu-temp/
│   ├── README.md
│   └── tool.py
└── net-check/
    ├── README.md
    └── tool.py
```

`lesysbot install you/lesysbot-tools` offers all of them; users can cherry-pick
with `--only gpu-temp` or install a single one directly via
`you/lesysbot-tools/gpu-temp`. Directories named `tests/`, `docs/`, or starting
with `.`/`_` are ignored. A repo may also nest the package folders under a
`tools/` directory (the official collections do) — the installer looks there
first when the root holds no packages.

## 3. A dashboard repo

Dashboards share this whole story — same command, same "nothing to register",
same repo layout. The difference is the payload file, and **the simple form
needs no Python at all**:

```
lesysbot-my-dashboard/
├── README.md        # frontmatter: name, description, version, platforms
└── dashboard.json   # exactly what Grafana's Export button gives you
```

Build the dashboard in Grafana, hit **Export**, save the JSON as
`dashboard.json`, push the repo. `kind: dashboard` in the frontmatter is
optional — a folder holding `dashboard.json` (or `dashboard.py`) is recognised
as a dashboard regardless.

```bash
lesysbot install you/lesysbot-my-dashboard
```

Installing renders it, so it is in Grafana within 30 seconds. Nothing else to run.

Declare what it needs so it is withheld rather than shown empty:

```yaml
prerequisites:
  - service: prometheus
  - metric: node_cpu_seconds_total
```

A dashboard whose metrics aren't being scraped is **not written at all** —
`lesysbot dashboard current` names the reason, and it appears by itself once the
exporter is running. A panel querying a metric nothing collects looks exactly
like a broken panel, which is the confusion this avoids.

**[Write a dashboard](writing-dashboards.md)** covers the rest: testing yours
before you publish, the full frontmatter, and the `dashboard.py` route for a
dashboard whose queries must differ per OS. Most never need that one.

## 4. Getting listed in the marketplace

**You do not have to be.** Anyone can install your repo by name today; listing
only makes it findable through `lesysbot search` and the control panel's
Marketplace tab.

To be listed, open a PR adding a row to [`catalog.json`](../catalog.json):

```json
{
  "id": "my-dashboard",
  "name": "My Dashboard",
  "kind": "dashboard",
  "description": "One line — this is what search shows",
  "source": "you/lesysbot-my-dashboard",
  "homepage": "https://github.com/you/lesysbot-my-dashboard",
  "platforms": ["linux", "macos", "windows"],
  "tags": ["grafana"],
  "official": false
}
```

`id`, `name` and `source` are required; the rest default. `source` is an
ordinary GitHub link — the catalog is a **list, not a resolver**, so installing
an entry goes through the same parser and the same consent prompt as a link you
typed yourself. `platforms` filters the entry out of `lesysbot search` on
machines it can't run on, and `official` is reserved for the maintained
collections. CI checks that every `source` actually resolves.

## 5. Versioning & refs

- Tag releases (`git tag v1.0.0`) so users can pin: `lesysbot install you/repo@v1.0.0`.
- The installer records the exact commit SHA it extracted in the user's lock
  file, whatever ref they asked for.
- Bump `version:` in the README frontmatter with each release — it's what
  `lesysbot list` displays.

## 6. Checklist before you share

- [ ] `tool.py` imports only stdlib + declared `requirements.txt` deps, and
      handles `ImportError` with a friendly message.
- [ ] Destructive actions use `confirm=` on the `@tool` decorator.
- [ ] `platforms=[...]`/`requires=[...]` declared where the tool isn't universal.
- [ ] README frontmatter filled in (name, description, version).
- [ ] Test locally: copy the package into your own tools dir, or
      `lesysbot install you/repo@your-branch`.

See [Write a tool](writing-tools.md) for the tool code itself, and
[Write a dashboard](writing-dashboards.md) for the panels.
