#Requires -Version 5.1
# LeSysBot uninstall script — Windows
# Usage (PowerShell): .\scripts\uninstall.ps1
# If execution policy blocks it: powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1

$ErrorActionPreference = 'Stop'

function Info ($msg) { Write-Host "  ->  $msg" -ForegroundColor Cyan }
function Ok   ($msg) { Write-Host "  v  $msg"  -ForegroundColor Green }
function Warn ($msg) { Write-Host "  !  $msg"  -ForegroundColor Yellow }
function Hr   ()     { Write-Host ("─" * 60) }

# The compact 8-row cut; see the note in install.ps1 for the VT guard.
function Logo {
    if ($env:NO_COLOR) { return }
    $f = Join-Path $RepoDir "assets\brand\banner-small.txt"
    if (-not (Test-Path $f)) { return }
    $vt = ($PSVersionTable.PSVersion.Major -ge 6) -or $env:WT_SESSION `
          -or $Host.UI.SupportsVirtualTerminal
    if (-not $vt) { return }
    try {
        Write-Host ""
        Get-Content -Encoding UTF8 $f | ForEach-Object { Write-Host "  $_" }
        Write-Host ""
    } catch { }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir   = Split-Path -Parent $ScriptDir

Logo
Hr
Write-Host "  LeSysBot Uninstaller" -ForegroundColor White
Hr

# ── 1. Remove Task Scheduler entry ───────────────────────────────────────────
$TaskName = "LeSysBot"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask  -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Ok "Scheduled task '$TaskName' removed"
} else {
    Warn "No scheduled task '$TaskName' found — skipping"
}

# ── 2. Remove the program ─────────────────────────────────────────────────────
# The counterpart to the same section in uninstall.sh, and it exists for the
# same reason: install.ps1 builds a venv at $Prefix\venv and writes a
# lesysbot.cmd shim into $BinDir, and this only ever ran `pip uninstall` against
# the *system* python — where a pre-installer `pip install` used to land. On a
# one-command install that matches nothing, so the uninstall reported success
# and left a working `lesysbot` on PATH.
$Prefix = $(if ($env:LESYSBOT_INSTALL_DIR) { $env:LESYSBOT_INSTALL_DIR }
            else { Join-Path $env:USERPROFILE '.local\share\lesysbot' })
$BinDir = $(if ($env:LESYSBOT_BIN_DIR) { $env:LESYSBOT_BIN_DIR }
            else { Join-Path $env:USERPROFILE '.local\bin' })
$Venv   = Join-Path $Prefix 'venv'

# Drop the shim only when it really points into the venv being removed — a
# lesysbot.cmd from somewhere else is not ours to delete. The shim is a .cmd
# wrapper, not a symlink, so this reads it rather than resolving a link.
$Shim = Join-Path $BinDir 'lesysbot.cmd'
if (Test-Path $Shim) {
    $target = Join-Path $Venv 'Scripts\lesysbot.exe'
    if ((Get-Content -Raw $Shim) -like "*$target*") {
        Remove-Item -Force $Shim
        Ok "Removed $Shim"
    } else {
        Warn "$Shim does not point at $Venv — left alone"
    }
}

if (Test-Path $Venv) {
    Remove-Item -Recurse -Force $Venv
    Ok "Removed the venv at $Venv"
}

# install.ps1 leaves a copy of itself here so an update needs no re-download.
$SelfCopy = Join-Path $Prefix 'install.ps1'
if (Test-Path $SelfCopy) { Remove-Item -Force $SelfCopy }
if ((Test-Path $Prefix) -and -not (Get-ChildItem -Force $Prefix)) {
    Remove-Item -Recurse -Force $Prefix
    Ok "Removed $Prefix"
}

# Legacy fallback: installs that predate install.ps1 went into the user's python.
try {
    $null = & python -m pip show lesysbot 2>&1
    if ($LASTEXITCODE -eq 0) {
        Info "Removing an older pip-installed lesysbot ..."
        & python -m pip uninstall lesysbot -y --quiet
        Ok "Package uninstalled"
    }
} catch {
    # No python on PATH — nothing of the legacy kind to remove.
}

# ── 2b. Dashboard stack (Grafana/Prometheus containers) ──────────────────────
# Setup starts this by default, so uninstall offers to take it down. `start.ps1
# down` stops the containers without removing the Docker volumes, so stored
# history survives unless you delete them yourself.
$DataDir = if ($env:LESYSBOT_HOME) { $env:LESYSBOT_HOME } else { Join-Path $HOME ".lesysbot" }
$StackDir = Join-Path $DataDir "dashboard"
$MonStart = Join-Path $StackDir "scripts\start.ps1"
if ((Test-Path $MonStart) -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    $resp = Read-Host "  Stop the Grafana dashboard stack (docker containers)? [y/N]"
    if ($resp -match '^[Yy]') {
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $MonStart down
            Ok "Dashboard stack stopped"
        } catch {
            Warn "Could not stop the dashboard stack (is Docker running?)"
        }
    } else {
        Info "Left the dashboard stack running"
    }
}

# ── 3. Per-user data home (config, tools, logs) ──────────────────────────────
if (Test-Path $DataDir) {
    $resp = Read-Host "  Remove your config, tools and logs in $DataDir? [y/N]"
    if ($resp -match '^[Yy]') {
        Remove-Item -Recurse -Force $DataDir
        Ok "Removed $DataDir"
    } else {
        Info "Kept $DataDir (edit or delete it manually later)"
    }
}

Hr
Ok "LeSysBot has been uninstalled."
Write-Host ""
Write-Host "  Optional cleanup:"
Write-Host "    Remove-Item -Recurse -Force $DataDir     # config, tools and logs"
Write-Host ""
