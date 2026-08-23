# Your dashboard

LeSysBot has **one** Grafana dashboard. It arrives with a basic one already
working, and you change it by installing a different one from GitHub — the same
command you use for tools.

```bash
lesysbot dashboard current      # what you have
lesysbot install owner/repo     # replace it with theirs
lesysbot dashboard reset        # go back to the default
```

Open it at <http://localhost:3000/d/lesysbot>. That address never changes, no
matter which dashboard is installed.

## Why only one?

Because there is no one-size-fits-all dashboard, and pretending otherwise makes
a worse one.

Operating systems differ. Within one OS the hardware differs — NVIDIA, Apple
Silicon, or no GPU at all; hwmon, the SMC, or WMI thermal zones; NTFS with no
inodes. A dashboard that tried to cover every combination would show blank
panels on almost every machine, and **a blank panel is indistinguishable from a
broken one**. You'd spend your afternoon debugging an exporter that was never
supposed to have data.

So instead: one dashboard, deliberately basic by default, replaced wholesale
with one built for *your* machine. Same trust model as tools — you install from
a GitHub link you can read first, and nothing decides for you.

## What you get by default

**System Overview** — CPU load and per-core usage, memory and swap, disk space
and I/O, per-interface network throughput. Recorded every 15 seconds, kept for
15 days.

That's it, on purpose. It's what a stock `node_exporter` / `windows_exporter`
can always fill, on any machine, with no extra collectors. Temperatures, GPU
detail and per-filesystem breakdowns are **not** included — those depend on
hardware you may not have.

It's installed for you by `lesysbot setup`. You don't have to do anything.

## Installing a different one

```bash
lesysbot search --kind dashboard        # see what's available
lesysbot install lesysbot/lesysbot-packages-official --only thermals
lesysbot install yourname/your-dashboard
```

Any GitHub link works — `owner/repo`, a full URL, a subdirectory, a tag:

```bash
lesysbot install owner/repo
lesysbot install owner/repo@v2.1
lesysbot install owner/repo/dashboards/gpu-nvidia
lesysbot install https://github.com/owner/repo
```

**This replaces the dashboard you have.** LeSysBot says so before it does
anything, and asks:

```
acme/nvidia-dash @ 3f2a91b0c4de
  gpu-nvidia v1.2.0 (dashboard) — NVIDIA utilization, VRAM, thermals
    → ~/.lesysbot/dashboard/installed/gpu-nvidia

  ! this replaces your current dashboard (system-overview) —
    `lesysbot dashboard reset` restores the default

Install 1 package(s) from acme/nvidia-dash? Packages run arbitrary code as your user [y/N]
```

**Installing renders it.** Grafana has it within 30 seconds, with nothing else
to run.

### If a repo offers several dashboards

You get asked which, rather than getting whichever one sorted first. The repo's
**tools install normally** — only the dashboard part waits for a decision:

```
$ lesysbot install official

  ! 7 dashboards here and LeSysBot installs one — none will be, unless you pick:
      cpu-detail — utilization by mode and core, load, saturation, frequency
      gpu-nvidia — utilization, VRAM, thermals, power, fan, exporter health
      thermals   — CPU, disk, GPU and ambient temperatures
      …
    …re-run with --only NAME to pick one

✔ Installed network (tool) → ~/.lesysbot/tools/network
```

Then pick one:

```bash
lesysbot install official --only thermals
```

A repo containing **nothing but** several dashboards has no unambiguous part to
install, so that one stops with the same list and installs nothing.

## Updating

```bash
lesysbot update                 # everything, at each recorded ref
lesysbot update --check         # what would change, without changing it
lesysbot update gpu-nvidia      # just that one
```

`update` re-fetches from the ref recorded when you installed, so a dashboard
pinned at `@v2.1` stays on `v2.1`. To move, install again at the new ref.

**Your local edits survive** if the package's `README.md` lists them under
`preserve:`. Anything else in the folder is replaced by the incoming version —
see [Modifying it](#modifying-it) for the route that always survives.

The default dashboard isn't updated this way: it ships inside LeSysBot and moves
when LeSysBot does. `lesysbot dashboard reset` reinstalls it.

## Modifying it

Three routes, shortest first. Pick by how long you want the change to last.

### Edit the file (quick, local)

Every installed dashboard is a folder you own:

```
~/.lesysbot/dashboard/installed/system-overview/
  README.md        what it needs, and what to preserve
  dashboard.py     the panels  (or dashboard.json)
```

Edit it and render:

```bash
lesysbot dashboard render
```

Grafana picks the change up within 30 seconds.

**This is lost when the package is next updated or reset**, unless the README's
`preserve:` names the file. Good for trying something; not where you want a
change you care about.

### Fork it and install your fork (durable — the recommended route)

This is the "just like a tool" path, and the one that actually holds:

```bash
# 1. Fork the repo on GitHub (or copy the folder into a repo of your own)
# 2. Edit dashboard.py / dashboard.json there, and push
# 3. Install your fork:
lesysbot install yourname/your-dashboard
```

Now your dashboard **is** the source. `lesysbot update` pulls *your* changes.
Nothing overwrites it, because there's nothing upstream of it.

Starting from the default is a good way in — `build(host, caps, ctx)` already
receives the detected capabilities, so adding a row for hardware you actually
have is a few lines. See [Write a dashboard](writing-dashboards.md).

### Edit in Grafana's UI (temporary — read this before you spend an hour there)

You *can* rearrange panels in Grafana and hit Save. The save is accepted and
stored — **and then reverted the next time the dashboard is provisioned.**

That's not a bug being reported here, it's how file-provisioned dashboards
work: the file on disk is the source of truth, and LeSysBot rewrites it on every
render. If you build something you want to keep, use Grafana's **Save as** to
store it under a different name — that copy sits outside the file provider and
is yours permanently.

For anything you want to survive, edit the package or fork it.

## Going back to the default

```bash
lesysbot dashboard reset
```

Removes whatever is installed and reinstalls the one that ships with LeSysBot.
Use it when a dashboard turns out to be for someone else's hardware, or when a
fork you're editing stops rendering. The control panel has the same button under
**Dashboards → Reset to default**.

## Why a dashboard sometimes doesn't appear

Because it would have been empty, and we would rather tell you than show you a
page of blank panels:

```
$ lesysbot dashboard render
○ postgres — 'pg_up' is not being scraped (+1 more)
```

A panel querying a metric nothing collects looks *exactly* like a panel that's
broken. So a dashboard whose metrics aren't there is not written at all, and
`lesysbot dashboard current` says why. Install the exporter it needs, run render
again, and it appears.

`lesysbot doctor` gives the same answer with the fix attached.

This works in reverse too: if a dashboard was working and its exporter goes
away, the next render **removes** it rather than leaving Grafana serving
something that has quietly gone blank.

## Writing your own

Two files — a README and the JSON Grafana's **Export** button gives you — and
it's installable by anyone. No Python needed, and nothing to register:

```
my-dashboard/
  README.md        # name, description, version, prerequisites
  dashboard.json   # exactly what Export gave you
```

**[Write a dashboard](writing-dashboards.md)** is the full walkthrough: making
one, testing it locally, declaring what it needs, publishing it to GitHub, and
the `dashboard.py` route for a dashboard whose panels change per machine.

## Commands

| | |
|---|---|
| `lesysbot dashboard current` | which dashboard, where from, and its state |
| `lesysbot dashboard render` | rewrite the JSON Grafana reads |
| `lesysbot dashboard reset` | restore the default |
| `lesysbot dashboard start` / `stop` | the Grafana + Prometheus stack |
| `lesysbot install owner/repo` | replace the dashboard |
| `lesysbot update` | re-fetch at the recorded ref |
| `lesysbot doctor` | what's missing, with the fix |

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

`generated/` holds exactly one file, `lesysbot.json`, rewritten on every render.
It is derived output — edit the package, never that. Any other JSON that turns
up there is swept away on the next render, which is how leftovers from an older
LeSysBot (one file per dashboard) and from running the stack standalone clean
themselves up.

All three ways of running the stack (Docker on Linux, Docker Desktop on
macOS/Windows, and the Docker-free Homebrew path on macOS) provision from that
one directory, so your dashboard shows up however you run it.

</details>

<details>
<summary><b>Why the URL never changes</b></summary>

LeSysBot stamps `uid: "lesysbot"` onto whatever model the package produced,
overriding anything the package declared. So
<http://localhost:3000/d/lesysbot> is a constant: the docs quote it, the status
screen links to it, and the `share_dashboard` tool publishes it.

A dashboard package can't move that address — which matters most for a fork,
since a fork inherits its parent's `uid` and two dashboards claiming one uid is
a mess Grafana resolves arbitrarily.

</details>

<details>
<summary><b>"But I want two dashboards"</b></summary>

You can have as many as you like in Grafana — LeSysBot just only *manages* one.
Use Grafana's **Save as** on the provisioned dashboard to make a permanent copy
under its own name, then install a different one with LeSysBot. The copy is
outside the file provider, so nothing LeSysBot does will touch it.

What you lose is `lesysbot update` for that copy: it's yours now, not a package.
If you want updates, fork the repo instead and install the fork.

</details>

<details>
<summary><b>More than one dashboard installed?</b></summary>

That shouldn't happen — the installer replaces rather than adds — but a home
that predates this rule, or a folder copied in by hand, can end up with two.
`lesysbot doctor` reports it:

```
dashboard
  dashboard exactly one installed   missing   2 installed: system-overview, gpu-nvidia
                                              → lesysbot dashboard reset  (or remove the ones you don't want)
```

Only one is ever provisioned, so Grafana keeps showing one page; the other is
dead weight in `installed/`. `lesysbot dashboard reset` clears it.

</details>

---

**See also:** [Write a dashboard](writing-dashboards.md) ·
[Install tools](installing-tools.md) · [Troubleshooting](troubleshooting.md) ·
[The control panel](management-ui.md)
