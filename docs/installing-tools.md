# Install tools

Any GitHub repo holding a tool package installs with one command. There's no
registry to search and nothing to sign up for — the link *is* the package name.

```bash
lesysbot tools install owner/repo
```

LeSysBot downloads the repo, shows you what it found — package names, versions,
the files that will land on your disk — and asks before writing anything. A
running bot picks the new tools up straight away, no restart.

The tools LeSysBot ships with are already there — `lesysbot tools list` shows
them. This page is about adding more.

---

## Installing a tool

```bash
lesysbot tools install owner/repo                  # everything in the repo
lesysbot tools install owner/repo/tools/disk-temp  # just one package from it
lesysbot tools install owner/repo@v1.2             # pin to a tag, branch, or commit
lesysbot tools install https://github.com/owner/repo
```

Useful flags:

| Flag | What it does |
|---|---|
| `--only NAME` | Install just one package from a multi-package repo (repeatable) |
| `--yes` | Skip the confirmation prompt |
| `--force` | Overwrite a folder LeSysBot didn't install |
| `--install-deps` | Run the package's `requirements.txt` instead of just printing it |

---

## Before you install: what you're agreeing to

A tool package is **Python code that runs as you, on your machine**, the moment
the bot loads it. There's no sandbox. This is the same deal as `pip install` —
worth thinking about for a moment, then not agonising over:

- **Install from people you trust.** Tool files are small; reading `tool.py` is
  a minute's work and tells you everything.
- **Pin what you depend on.** `@v1.2` or `@<commit-sha>` means you get the same
  code tomorrow. Either way, the exact commit you received is recorded.
- **Read the plan.** The list printed before the y/N prompt is every file that
  will land in your tools directory. `--yes` skips that prompt, so keep it for
  scripts you already trust.

If a package needs Python libraries, LeSysBot **prints** the `pip install -r`
command rather than running it — you decide.

---

## Managing what you've installed

```bash
lesysbot tools list             # everything, with status and where it came from
lesysbot tools info temperature    # parameters, requirements, provenance
lesysbot tools disable temperature # keep it, but switch it off
lesysbot tools enable temperature  # back on
lesysbot tools remove temperature  # delete it (asks first)
```

`list` and `info` show `acme/repo@commit` for installed packages and `local` for
ones you wrote. Disabling applies to a running bot within a second; removing
deletes the whole package folder, including any sibling tools in it — they're
listed before you confirm.

To **update** a package, install it again. To update to a newer pinned version,
install it again with the new ref.

You can do all of this from the [control panel](management-ui.md) too.

---

## Private repos

Set a token and it's sent as a bearer credential:

```bash
GITHUB_TOKEN=ghp_… lesysbot tools install you/private-tools
```

`GH_TOKEN` works too.

---

## When it goes wrong

| Message | What to do |
|---|---|
| `Not found: owner/repo@ref` | Check the spelling and the ref. For a private repo, set `GITHUB_TOKEN`. |
| `tools dir already has X` | That folder wasn't installed by LeSysBot, so it's protected. `--force` if you're sure. |
| Installed but not in `/help` | Restart if hot reload is off; otherwise check the log for an import error. |
| Complains about a missing Python package | Re-run with `--install-deps`, or run the `pip install -r` line it printed. |

More in [Troubleshooting](troubleshooting.md).

---

## Under the hood

<details>
<summary><b>Every way to write a source</b></summary>

```
owner/repo                       the default branch
owner/repo@ref                   a branch, tag, or 40-character commit SHA
owner/repo/sub/dir[@ref]         one package inside a bigger repo
https://github.com/owner/repo[.git]
https://github.com/owner/repo/tree/REF[/sub/dir]
git@github.com:owner/repo
```

A branch name containing `/` is ambiguous inside a `/tree/` URL — use the short
form for those: `owner/repo/subdir@feature/x`.

Bare words aren't accepted. Installs are by GitHub link only, deliberately —
there's no catalog that could go stale or be taken over.

</details>

<details>
<summary><b>What counts as a package inside a repo</b></summary>

- **The repo root contains a `.py` file** (any name not starting with `_`) → the
  repo itself is one package, named after the repo.
- **Otherwise** → every immediate subdirectory containing a `.py` file is a
  package. If the repo has a `tools/` folder with packages in it, those are used;
  otherwise the repo root is scanned. `tests/`, `docs/`, and anything starting
  with `.` or `_` is skipped.

Package code is never imported while LeSysBot is working out what's in the repo
— only the README frontmatter is read, so nothing runs before you consent.

</details>

<details>
<summary><b>Where things are written</b></summary>

```yaml
mcp:
  tools_dir: "./tools"          # packages are installed and loaded here
  lock_file: tools.lock.json    # which repo and commit each package came from
```

Both are relative to your active config, so a normal install puts them under
`~/.lesysbot/`. The installer and the bot resolve them the same way, which is
why `lesysbot tools install` always writes to the directory the bot is actually
reading.

The download is a plain HTTPS zip fetch — no `git` binary needed and no GitHub
API calls. Extraction guards against path-traversal entries, symlinks, and
zip bombs, and the exact commit SHA is read out of the archive itself.

</details>
