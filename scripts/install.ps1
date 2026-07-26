#Requires -Version 5.1
# LeSysBot install script — Windows
# Usage: .\scripts\install.ps1
# If blocked by execution policy: powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# Bootstrap only: check Python, pip-install the package, then hand off to the
# Python setup wizard (`lesysbot setup` — one cross-platform implementation with
# arrow-key/Esc navigation; see lesysbot/setup/). Re-run `lesysbot setup` directly
# anytime to reconfigure without reinstalling.

param(
    [switch]$NoService   # Install package only; skip the setup wizard
)

$ErrorActionPreference = 'Stop'

function Ok  ($m) { Write-Host "  v  $m" -ForegroundColor Green }
function Die ($m) { Write-Host "  x  $m" -ForegroundColor Red; exit 1 }
function Hr { Write-Host ("  " + ("─" * 50)) }

# The pixel mark. The banner is raw ANSI, so it needs a host that processes
# virtual-terminal sequences — PowerShell 7+, or Windows Terminal — otherwise
# the escape codes would print as literal garbage. Never fatal: this runs before
# we've checked anything about the machine.
function Logo ($Name = 'banner.txt') {
    if ($env:NO_COLOR) { return }
    $f = Join-Path $RepoDir "assets\brand\$Name"
    if (-not (Test-Path $f)) { return }
    $vt = ($PSVersionTable.PSVersion.Major -ge 6) -or $env:WT_SESSION `
          -or $Host.UI.SupportsVirtualTerminal
    if (-not $vt) { return }
    try { Get-Content -Encoding UTF8 $f | ForEach-Object { Write-Host "  $_" } } catch { }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir   = Split-Path -Parent $ScriptDir

Clear-Host
Write-Host ""
Logo
Hr
Write-Host ""
Write-Host "  LeSysBot Setup" -ForegroundColor White
Hr

# ═══════════════════════════════════════════════════════════════════════════════
# 1. PYTHON
# ═══════════════════════════════════════════════════════════════════════════════
try {
    $pyVer = (& python --version 2>&1).ToString()
    if ($pyVer -match 'Python (\d+)\.(\d+)') {
        if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 11)) {
            Die "Python 3.11+ required. Found: $pyVer`n       Download from https://python.org"
        }
    }
    Ok "Python: $pyVer"
} catch {
    Die "Python not found.`n       Install from https://python.org (check 'Add to PATH' during setup)"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 2. INSTALL PACKAGE
# ═══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  Installing lesysbot package ..."
Set-Location $RepoDir
# .[all] = Telegram + Discord extras, so every option the wizard
# offers below works without a second install step.
& python -m pip install --quiet ".[all]"
if ($LASTEXITCODE -ne 0) { Die 'pip install failed. Run manually: pip install ".[all]"' }
Ok "Package installed"

$LesysbotBin = $null
$found = Get-Command lesysbot -ErrorAction SilentlyContinue
if ($found) {
    $LesysbotBin = $found.Source
} else {
    $ScriptsDir = & python -c "import sys, os; print(os.path.join(sys.prefix, 'Scripts'))"
    $candidate  = Join-Path $ScriptsDir "lesysbot.exe"
    if (Test-Path $candidate) { $LesysbotBin = $candidate }
}
if (-not $LesysbotBin) {
    Die "Cannot locate lesysbot.exe. Ensure Python's Scripts directory is in PATH, then re-run."
}
Ok "Binary: $LesysbotBin"

if ($NoService) {
    Hr
    Ok "Package installed (setup wizard skipped)."
    Write-Host ""
    Write-Host "  Configure later:  lesysbot setup" -ForegroundColor Gray
    Write-Host "  Run manually:     lesysbot" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

# ═══════════════════════════════════════════════════════════════════════════════
# 3. SETUP WIZARD  (Python — lesysbot/setup/; LESYSBOT_HOME passes through)
# ═══════════════════════════════════════════════════════════════════════════════
& $LesysbotBin setup --repo $RepoDir
exit $LASTEXITCODE
