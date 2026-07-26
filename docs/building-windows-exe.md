# Build a Windows .exe

> **Advanced.** You only need this if you're *distributing* LeSysBot to other
> people. To run it on your own Windows machine, follow
> [Getting started](getting-started.md) instead.

This is for maintainers who want to ship LeSysBot as a standalone
`lesysbot.exe` — no Python install, no `pip`, no terminal knowledge required.
The person receiving it unzips a folder, edits `config.yaml`, and double-clicks
the exe.

It uses [PyInstaller](https://pyinstaller.org) to freeze the app and its
dependencies into a self-contained bundle.

---

## 1. What the end user gets

The build produces a folder like this, plus a matching `.zip` to hand out:

```
LeSysBot\
├─ lesysbot.exe          ← double-click or run from a terminal
├─ config.yaml         ← end user edits this (model, provider, tokens)
├─ tools\              ← drop-in tool packages (editable without rebuilding)
│  ├─ system-info\     ← each folder is a self-contained tool (README + tool.py)
│  ├─ network\
│  └─ web\
├─ README.txt
└─ _internal\          ← bundled Python runtime + libraries (don't touch)
```

`lesysbot.exe` reads `config.yaml` and the `tools\` folder **from the directory it
lives in**, so the package is fully relocatable — the user can drop it anywhere.

---

## 2. Prerequisites (build machine)

You build the Windows exe **on Windows** (PyInstaller is not a cross-compiler).

| Requirement | Notes |
|---|---|
| Windows 10/11 x64 | Build on the oldest Windows you intend to support |
| Python 3.11+ | From [python.org](https://python.org), "Add to PATH" checked |
| Git checkout of this repo | `git clone … && cd lesysbot` |
| ~1.5 GB free disk | For the build venv and artifacts |

> **Architecture note:** the exe matches the Python you build with. Use 64-bit
> Python for a 64-bit exe. For ARM64 Windows, build with ARM64 Python.

---

## 3. Quick build (one command)

From the repo root in PowerShell:

```powershell
.\scripts\build-exe.ps1
```

If PowerShell blocks the script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
```

The script is self-contained — it creates an isolated build virtualenv
(`.build-venv\`), installs the package + PyInstaller, runs the build, and
assembles the shippable folder and zip:

```
dist\LeSysBot\                          ← the folder above
dist\LeSysBot-0.1.0-windows-x64.zip     ← zip to distribute
```

Test it before shipping:

```powershell
dist\LeSysBot\lesysbot.exe --provider cli
```

---

## 4. Build options

| Command | Result |
|---|---|
| `.\scripts\build-exe.ps1` | One-folder build (recommended) — fast startup, all providers |
| `.\scripts\build-exe.ps1 -OneFile` | A single `lesysbot.exe` (slower startup, easier to email) |
| `.\scripts\build-exe.ps1 -SkipProviders` | Smaller CLI-only exe (no Telegram/Discord bundled) |
| `.\scripts\build-exe.ps1 -Clean` | Wipe `build\`, `dist\`, `.build-venv\` first |

**One-folder vs one-file:**

- **One-folder** (default) starts instantly and is the most robust for production.
  The user gets a folder; ship the zip.
- **One-file** is a single exe that self-extracts to a temp dir on each launch —
  convenient to share, but slower to start and more likely to trip antivirus
  heuristics. Either way the user still needs `config.yaml` and `tools\` next to it.

---

## 5. How the exe finds config and tools

A frozen build resolves its working files relative to the **executable location**
(`lesysbot/core/paths.py::app_dir`), not the current directory. Lookup order for
config:

1. `--config <path>` if passed on the command line
2. `config.yaml` in the current working directory
3. `config.yaml` next to `lesysbot.exe`  ← the normal case for end users
4. built-in defaults (Ollama on `localhost:11434`)

`logs\` and the `tools\` folder are likewise created/read next to the exe. This
means the package keeps working no matter where the user moves it or how they
launch it (double-click, shortcut, or terminal).

> **Tip:** Ship the exe in a **user-writable** location (e.g. `C:\Users\<name>\LeSysBot`
> or the Desktop), not `C:\Program Files`. The app writes `logs\` next to itself,
> which fails under `Program Files` without admin rights.

---

## 6. Shipping tools that need extra Python packages

Drop-in tools in `tools\*.py` are read from disk at runtime, so users can add or
edit tools **without rebuilding**. But a frozen exe can only import libraries that
were bundled at build time. A tool that does `import pandas` will fail unless
`pandas` was part of the build.

The default build bundles everything in `pyproject.toml` plus `httpx` (used by the
example `web_search` tool). To support tools that need more:

1. Install the extra package into the build venv before building, **or** add it to
   the spec's bundling list:

   ```python
   # packaging/lesysbot.spec
   for _pkg in ("lesysbot", "openai", "pydantic", ..., "pandas"):
       _bundle(_pkg)
   ```

2. Rebuild and ship the new exe.

If you expect users to bring arbitrary dependencies, prefer the `pip install`
distribution (see [Getting Started](getting-started.md)) over a frozen exe.

---

## 7. Production checklist

- [ ] **Version stamp** — bump `version` in `pyproject.toml` and
      `lesysbot/__init__.py`; the build script names the zip from `lesysbot.__version__`.
- [ ] **Icon** — add an `.ico` and set `icon="path\\to\\app.ico"` in both `EXE(...)`
      blocks of `packaging/lesysbot.spec`.
- [ ] **Code signing** — unsigned exes trigger SmartScreen ("Windows protected your
      PC") and many AV products. For real distribution, sign with an Authenticode
      certificate:
      ```powershell
      signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com /td SHA256 dist\LeSysBot\lesysbot.exe
      ```
- [ ] **Antivirus false positives** — PyInstaller exes are sometimes flagged. Signing
      helps; you can also submit the binary to vendors for whitelisting. Avoid UPX
      (already disabled in the spec) as it worsens detection.
- [ ] **Test on a clean machine** — one without Python installed — to catch missing
      bundled dependencies.
- [ ] **Auto-start as a service** — to run the exe in the background / at login, use
      Task Scheduler or NSSM as described in [Running as a Service](service.md). Point the
      service at `dist\LeSysBot\lesysbot.exe` with its folder as the working directory.

---

## 8. Manual build (without the script)

If you'd rather run the steps yourself:

```powershell
# 1. Isolated build environment
python -m venv .build-venv
.\.build-venv\Scripts\Activate.ps1

# 2. Install the app + build tooling
pip install --upgrade pip
pip install .
pip install ".[all]" pyinstaller httpx

# 3. Freeze (one-folder)
pyinstaller --noconfirm --clean packaging\lesysbot.spec

# 4. Assemble the package
Copy-Item config\default.yaml dist\lesysbot\config.yaml
Copy-Item tools dist\lesysbot\tools -Recurse
```

For a single-file exe instead:

```powershell
$env:LESYSBOT_BUILD_ONEFILE = "1"
pyinstaller --noconfirm --clean packaging\lesysbot.spec
```

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` at runtime | The dependency wasn't bundled. Add it to the `_bundle(...)` list in `packaging/lesysbot.spec` (or install it into the build venv) and rebuild. |
| Telegram/Discord provider fails on a `-SkipProviders` build | That build is CLI-only by design. Rebuild without `-SkipProviders`. |
| "Windows protected your PC" (SmartScreen) | Expected for unsigned exes. Click *More info → Run anyway*, or sign the binary (§7). |
| Antivirus quarantines `lesysbot.exe` | Common PyInstaller false positive. Sign the binary and/or submit for whitelisting; ensure UPX is off (it is, in the spec). |
| Exe can't write `logs\` | It's in a read-only location like `Program Files`. Move the folder somewhere user-writable, or set `logging.file: null` in `config.yaml`. |
| Build is huge | Use `-SkipProviders` for a CLI-only exe, or trim the optional packages in the spec. |
| `pyinstaller` not found | Activate `.build-venv` first, or run `python -m PyInstaller …`. |

---

## 10. What gets built (under the hood)

- `packaging/entry.py` — the script PyInstaller freezes; it just calls
  `lesysbot.__main__:main`.
- `packaging/lesysbot.spec` — collects the package and its dependencies, bundles
  optional providers when present, and emits either a one-folder or one-file build.
- `scripts/build-exe.ps1` — orchestrates the venv, the build, and packaging the
  shippable folder + zip.
- `lesysbot/core/paths.py` — makes the frozen exe resolve `config.yaml`, `tools\`
  and `logs\` next to the executable.
