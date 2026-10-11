# Install tools

LeSysBot comes with 15 tools already installed: system info, disk usage,
date and time, temperature, ping, DNS lookup, traceroute, speed test, web fetch,
reboot and power off, and dashboard sharing. `/help` lists them.

**A tool is a folder.** Put one in `~/.lesysbot/tools/` and it works — that is
the whole format. There is no registry to publish to and nothing to sign up for.

## Copy a folder

```bash
cp -r my-tool ~/.lesysbot/tools/
```

That's it. A running bot picks it up within a second; type `/help` to see it.

## Or let LeSysBot do it

```bash
lesysbot install ./my-tool        # a folder
lesysbot install ~/my-tool.zip    # or a .zip of one
```

Same result, with the checks: it reads the package's `README.md`, shows you what
it found and where it will go, installs any Python dependencies the tool needs,
and records where it came from so `lesysbot list` can tell you later.

Re-run the same command to update after you edit the folder.

## From GitHub

```bash
lesysbot install owner/repo                # every package in a repo
lesysbot install owner/repo/tools/gpu      # one package from it
lesysbot install owner/repo@v1.2           # a specific tag, branch or commit
```

LeSysBot shows what it found and asks before writing anything. Dashboards
aren't installed this way — to use a different one, see
[Change the dashboard](dashboards.md#change-it).

## Manage

```bash
lesysbot list                # everything installed, and where it came from
lesysbot info ping           # details for one tool
lesysbot update              # re-download packages installed from GitHub
lesysbot remove ping         # delete the tool and its package (asks first)
lesysbot doctor              # what's missing on this machine, and how to fix it
```

`update` re-fetches at the tag or branch a package was installed from, so it
only applies to GitHub packages. To update a local one, install it again.

To turn a tool off without deleting it, see
[Everyday use](usage.md#turning-tools-on-and-off).

## Before you install

A tool is Python code that runs as you, with no sandbox — the same trust as
`pip install`. So:

- **Install from people you trust.** A tool is usually one short `tool.py`;
  reading it takes a minute.
- **Pin a version** with `@v1.2` or a commit when installing from GitHub, so you
  get the same code tomorrow.
- **Read the list** LeSysBot prints before you answer `y`.

More in [Security](security.md).

## Useful flags

| Flag | Effect |
|---|---|
| `--only NAME` | Install one package from a folder or repo that has several |
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
| `is neither a path on this machine nor a GitHub link` | Check the path. A relative one is read from the directory you're in. |
| `No packages found in …` | The folder needs a `tool.py` in it (or packages in subfolders). See [Write a tool](writing-tools.md). |
| `Not found: owner/repo@ref` | Check the spelling and the tag or branch. Private repo? Set `GITHUB_TOKEN`. |
| `already present and not installed by lesysbot` | That folder wasn't installed by LeSysBot, so it's protected. Use `--force` if you're sure. |
| Installed, but not in `/help` | Check the log for an import error: `tail ~/.lesysbot/logs/lesysbot.log` |
