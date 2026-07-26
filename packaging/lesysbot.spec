# PyInstaller spec for LeSysBot — build with:  pyinstaller packaging/lesysbot.spec
#
# Produces a one-folder distribution in dist/lesysbot/ containing lesysbot.exe and an
# _internal/ folder. The build script (scripts/build-exe.ps1) then drops a
# default config.yaml and a tools/ folder next to the exe to make a ready-to-ship
# package. See docs/building-windows-exe.md.
#
# Set the env var LESYSBOT_BUILD_ONEFILE=1 to produce a single lesysbot.exe instead.

import os

from PyInstaller.utils.hooks import collect_all

ONEFILE = os.environ.get("LESYSBOT_BUILD_ONEFILE") == "1"
SKIP_PROVIDERS = os.environ.get("LESYSBOT_BUILD_SKIP_PROVIDERS") == "1"

datas = []
binaries = []
hiddenimports = []


def _bundle(pkg, optional=False):
    """Collect everything a dependency needs. Optional packages (telegram/discord)
    are skipped with a warning if they aren't installed, so the build never breaks."""
    try:
        d, b, h = collect_all(pkg)
    except Exception as exc:  # noqa: BLE001 — build-time best effort
        if optional:
            print(f"[lesysbot.spec] optional package {pkg!r} not bundled: {exc}")
            return
        raise
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# Core runtime — always required.
for _pkg in ("lesysbot", "openai", "pydantic", "pydantic_settings", "yaml", "rich", "watchfiles"):
    _bundle(_pkg)

# Optional providers / tool dependencies — bundled if present on the build machine
# so a single exe can serve CLI, Telegram and Discord. Set LESYSBOT_BUILD_SKIP_PROVIDERS=1
# for a smaller CLI-only executable.
if not SKIP_PROVIDERS:
    for _pkg in ("telegram", "discord", "aiohttp", "httpx"):
        _bundle(_pkg, optional=True)


a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "ruff"],
    noarchive=False,
)

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="lesysbot",
        console=True,
        disable_windowed_traceback=False,
        upx=False,
        icon=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="lesysbot",
        console=True,
        disable_windowed_traceback=False,
        upx=False,
        icon=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        name="lesysbot",
        upx=False,
    )
