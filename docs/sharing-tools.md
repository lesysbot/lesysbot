# Share your tools

Any public GitHub repo containing a tool folder package is installable by
anyone with one command — there is nothing to register or publish beyond
pushing the repo:

```bash
lesysbot install you/lesysbot-gpu-tools
```

## 1. A single-tool repo

The simplest shareable unit — the repo *is* the package:

```
lesysbot-gpu-temp/
├── README.md        # frontmatter: name, description, version, requires
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
`tools/` directory (LeSysBot's own repo does) — the installer looks there
first when the root holds no packages.

## 3. Versioning & refs

- Tag releases (`git tag v1.0.0`) so users can pin: `lesysbot install you/repo@v1.0.0`.
- The installer records the exact commit SHA it extracted in the user's lock
  file, whatever ref they asked for.
- Bump `version:` in the README frontmatter with each release — it's what
  `lesysbot list` displays.

## 4. Checklist before you share

- [ ] `tool.py` imports only stdlib + declared `requirements.txt` deps, and
      handles `ImportError` with a friendly message.
- [ ] Destructive actions use `confirm=` on the `@tool` decorator.
- [ ] `requires=[...]` declared for every program the tool shells out to.
- [ ] README frontmatter filled in (name, description, version).
- [ ] Test locally: copy the package into your own tools dir, or
      `lesysbot install you/repo@your-branch`.

See [Writing Tools](writing-tools.md) for the tool code itself.
