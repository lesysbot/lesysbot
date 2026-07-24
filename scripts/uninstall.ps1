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

# ── 2. Uninstall Python package ───────────────────────────────────────────────
Info "Removing lesysbot package ..."
try {
    $check = & python -m pip show lesysbot 2>&1
    if ($LASTEXITCODE -eq 0) {
        & python -m pip uninstall lesysbot -y --quiet
        Ok "Package uninstalled"
    } else {
        Warn "Package not found in pip — skipping"
    }
} catch {
    Warn "Python not found — package not removed"
}

# ── 3. Per-user data home (config, tools, logs) ──────────────────────────────
$DataDir = if ($env:LESYSBOT_HOME) { $env:LESYSBOT_HOME } else { Join-Path $HOME ".lesysbot" }
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
