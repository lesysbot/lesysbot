#Requires -Version 5.1
# LeSysBot — build a standalone Windows executable
# Usage:   .\scripts\build-exe.ps1 [-OneFile] [-SkipProviders] [-Clean]
# If blocked by execution policy:
#   powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
#
# Output: dist\LeSysBot\            ready-to-ship folder (lesysbot.exe + config.yaml + tools\)
#         dist\LeSysBot-<ver>-windows-x64.zip   the same folder, zipped for distribution
#
# See docs/building-windows-exe.md for the full guide.

param(
    [switch]$OneFile,        # produce a single lesysbot.exe instead of a one-folder build
    [switch]$SkipProviders,  # smaller CLI-only exe (no Telegram/Slack bundled)
    [switch]$Clean           # remove build/, dist/ and the build venv first
)

$ErrorActionPreference = 'Stop'

function Ok      ($m) { Write-Host "  v  $m" -ForegroundColor Green }
function Warn    ($m) { Write-Host "  !  $m" -ForegroundColor Yellow }
function Die     ($m) { Write-Host "  x  $m" -ForegroundColor Red; exit 1 }
function Section ($m) { Write-Host ""; Write-Host "  $m" -ForegroundColor Cyan; Write-Host ("  " + ("-" * 50)) }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir   = Split-Path -Parent $ScriptDir
Set-Location $RepoDir

$VenvDir  = Join-Path $RepoDir ".build-venv"
$DistDir  = Join-Path $RepoDir "dist"
$BuildDir = Join-Path $RepoDir "build"
$Staging  = Join-Path $DistDir "LeSysBot"

# ── Python ────────────────────────────────────────────────────────────────────
Section "Python"
try {
    $pyVer = (& python --version 2>&1).ToString()
    if ($pyVer -match 'Python (\d+)\.(\d+)') {
        if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 11)) {
            Die "Python 3.11+ required. Found: $pyVer"
        }
    }
    Ok "Python: $pyVer"
} catch {
    Die "Python not found. Install from https://python.org (check 'Add to PATH')."
}

# ── Clean ─────────────────────────────────────────────────────────────────────
if ($Clean) {
    Section "Clean"
    foreach ($p in @($BuildDir, $DistDir, $VenvDir)) {
        if (Test-Path $p) { Remove-Item -Recurse -Force $p; Ok "removed $p" }
    }
}

# ── Build virtual environment ─────────────────────────────────────────────────
Section "Build environment"
if (-not (Test-Path $VenvDir)) {
    & python -m venv $VenvDir
    Ok "created venv at .build-venv"
}
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { Die "venv python not found at $VenvPy" }

& $VenvPy -m pip install --quiet --upgrade pip
# .[all] pulls Telegram and Slack (incl. aiohttp); the bare
# install is the CLI-only build.
if ($SkipProviders) { & $VenvPy -m pip install --quiet . }
else                { & $VenvPy -m pip install --quiet ".[all]" }
& $VenvPy -m pip install --quiet pyinstaller
if (-not $SkipProviders) {
    # httpx powers example tools; the provider deps came from the [all] extra.
    & $VenvPy -m pip install --quiet httpx
}
Ok "dependencies installed"

# ── Run PyInstaller ───────────────────────────────────────────────────────────
Section "PyInstaller"
$env:LESYSBOT_BUILD_ONEFILE        = if ($OneFile)        { "1" } else { "" }
$env:LESYSBOT_BUILD_SKIP_PROVIDERS = if ($SkipProviders)  { "1" } else { "" }

& $VenvPy -m PyInstaller --noconfirm --clean (Join-Path "packaging" "lesysbot.spec")
if ($LASTEXITCODE -ne 0) { Die "PyInstaller build failed." }
Ok "executable built"

# ── Assemble the shippable package ────────────────────────────────────────────
Section "Package"
if (Test-Path $Staging) { Remove-Item -Recurse -Force $Staging }
New-Item -ItemType Directory -Path $Staging | Out-Null

if ($OneFile) {
    Copy-Item (Join-Path $DistDir "lesysbot.exe") $Staging
} else {
    # one-folder build lands in dist\lesysbot\ — move its contents into dist\LeSysBot\
    Copy-Item (Join-Path $DistDir "lesysbot\*") $Staging -Recurse
}

# Ship an editable config and the example tools next to the exe.
Copy-Item (Join-Path $RepoDir "config\default.yaml") (Join-Path $Staging "config.yaml")
Copy-Item (Join-Path $RepoDir "tools") (Join-Path $Staging "tools") -Recurse

# A short read-me so end users know what to do.
# Single-quoted here-string: no variable/backtick interpolation, text stays literal.
@'
LeSysBot - standalone Windows build

1. Edit config.yaml to set your model and messaging provider.
   (Default: Ollama at http://localhost:11434/v1 - install Ollama, then run: ollama pull qwen3.5)
2. Double-click lesysbot.exe, or run it from a terminal:  .\lesysbot.exe
3. Add your own tools by dropping .py files into the tools\ folder.

Full docs: https://github.com/lesysbot/lesysbot
'@ | Set-Content -Path (Join-Path $Staging "README.txt") -Encoding UTF8

Ok "assembled $Staging"

# ── Zip ───────────────────────────────────────────────────────────────────────
Section "Archive"
$ver = (& $VenvPy -c "import lesysbot; print(lesysbot.__version__)").Trim()
$zip = Join-Path $DistDir "LeSysBot-$ver-windows-x64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $Staging -DestinationPath $zip
Ok "created $zip"

Write-Host ""
Write-Host "  Done." -ForegroundColor Green
Write-Host "  Folder : $Staging"
Write-Host "  Zip    : $zip"
Write-Host "  Test   : `"$Staging\lesysbot.exe`" --provider cli"
Write-Host ""
