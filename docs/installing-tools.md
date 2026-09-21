# Install tools

LeSysBot comes with 15 tools already installed: system info, disk usage,
date and time, temperature, ping, DNS lookup, traceroute, speed test, web fetch,
reboot and power off, and dashboard sharing. `/help` lists them.

## Find more

```bash
lesysbot search              # everything you can install
lesysbot search gpu          # filter by name, description or tag
```

Or open the **Marketplace** tab in the [control panel](management-ui.md).

## Install

By the name `search` shows, or straight from any GitHub repo:

```bash
lesysbot install official                  # a name from lesysbot search
lesysbot install owner/repo                # every package in a repo
lesysbot install owner/repo/tools/gpu      # one package from it
lesysbot install owner/repo@v1.2           # a specific tag, branch or commit
```

LeSysBot shows what it found and asks before writing anything. A running bot
picks up the new tools straight away. Repos can hold
[dashboards](dashboards.md) too; they install the same way.

## Manage

```bash
lesysbot list                # everything installed, and where it came from
lesysbot info ping           # details for one tool
lesysbot update              # re-download installed packages (same branch or tag)
lesysbot remove ping         # delete the tool and its package (asks first)
lesysbot doctor              # what's missing on this machine, and how to fix it
```

To turn a tool off without deleting it, see
[Everyday use](usage.md#turning-tools-on-and-off).

## Before you install

A tool is Python code that runs as you, with no sandbox — the same trust as
`pip install`. So:

- **Install from people you trust.** A tool is usually one short `tool.py`;
  reading it takes a minute.
- **Pin a version** with `@v1.2` or a commit, so you get the same code tomorrow.
- **Read the list** LeSysBot prints before you answer `y`.

More in [Security](security.md).

## Useful flags

| Flag | Effect |
|---|---|
| `--only NAME` | Install one package from a repo that has several |
| `--yes` | Don't ask for confirmation |
| `--no-deps` | Don't install the package's Python dependencies |
| `--force` | Replace a folder LeSysBot didn't install |

For a private repo, set `GITHUB_TOKEN`:

```bash
GITHUB_TOKEN=ghp_… lesysbot install you/private-tools
```

## If it fails

| Message | Fix |
|---|---|
| `Not found: owner/repo@ref` | Check the spelling and the tag or branch. Private repo? Set `GITHUB_TOKEN`. |
| `tools dir already has X` | That folder wasn't installed by LeSysBot, so it's protected. Use `--force` if you're sure. |
| Installed, but not in `/help` | Check the log for an import error: `tail ~/.lesysbot/logs/lesysbot.log` |
