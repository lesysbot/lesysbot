#Requires -Version 5.1
<#
.SYNOPSIS
    LeSysBot installer — Windows.

.DESCRIPTION
    Finds (or installs) a Python 3.11+, builds an isolated virtual environment,
    installs LeSysBot into it, puts a `lesysbot` command on your PATH, gets
    Ollama and a model ready, then hands off to `lesysbot setup --yes`.

    Nothing here prompts: every decision is a default, a parameter or a
    LESYSBOT_* environment variable, so it works piped from the web with no
    terminal interaction at all. Needs no administrator rights.

.EXAMPLE
    irm https://lesysbot.github.io/install.ps1 | iex

.EXAMPLE
    # A bare `irm | iex` cannot take parameters. To pass them, either set
    # environment variables:
    $env:LESYSBOT_SKIP_DASHBOARD = 1; irm https://lesysbot.github.io/install.ps1 | iex
    # or invoke the downloaded script as a scriptblock:
    & ([scriptblock]::Create((irm https://lesysbot.github.io/install.ps1))) -SkipDashboard

.EXAMPLE
    .\scripts\install.ps1 -SkipOllama      # from a checkout

.EXAMPLE
    & "$env:USERPROFILE\.local\share\lesysbot\install.ps1" -Uninstall
#>
param(
    [string]$Version    = $env:LESYSBOT_VERSION,
    [string]$Ref        = $env:LESYSBOT_REF,
    [string]$Prefix     = $(if ($env:LESYSBOT_INSTALL_DIR) { $env:LESYSBOT_INSTALL_DIR }
                           else { Join-Path $env:USERPROFILE '.local\share\lesysbot' }),
    [string]$BinDir     = $(if ($env:LESYSBOT_BIN_DIR) { $env:LESYSBOT_BIN_DIR }
                            else { Join-Path $env:USERPROFILE '.local\bin' }),
    [string]$Model      = $(if ($env:LESYSBOT_MODEL) { $env:LESYSBOT_MODEL } else { 'qwen3.5:4b' }),
    [string]$Provider   = $env:LESYSBOT_SETUP_PROVIDER,
    [switch]$NoModifyPath,
    [switch]$SkipOllama,
    [switch]$NoModel,
    [switch]$SkipDashboard,
    [switch]$SkipSetup,
    [switch]$Uninstall,
    [switch]$Purge
)

$ErrorActionPreference = 'Stop'

$Repo         = 'lesysbot/lesysbot'
$UvInstaller  = 'https://astral.sh/uv/install.ps1'
$OllamaDocs   = 'https://ollama.com/download'

if ($env:LESYSBOT_NO_MODIFY_PATH) { $NoModifyPath = $true }
if ($env:LESYSBOT_SKIP_OLLAMA)    { $SkipOllama = $true }
if ($env:LESYSBOT_SKIP_DASHBOARD) { $SkipDashboard = $true }
if ($env:LESYSBOT_SKIP_SETUP)     { $SkipSetup = $true }
if ($Purge)                       { $Uninstall = $true }

# ── output ────────────────────────────────────────────────────────────────────
function Write-Ok    ($Message) { Write-Host "  [ok] $Message" -ForegroundColor Green }
function Write-Step  ($Message) { Write-Host "  ->   $Message" -ForegroundColor White }
function Write-Warn  ($Message) { Write-Host "  [!]  $Message" -ForegroundColor Yellow }
function Write-Note  ($Message) { Write-Host "       $Message" -ForegroundColor DarkGray }
function Write-Rule  { Write-Host ('  ' + ('-' * 50)) }
function Write-Value ($Label, $Detail) {
    Write-Host ("  [ok] {0,-26} " -f $Label) -ForegroundColor Green -NoNewline
    Write-Host $Detail -ForegroundColor DarkGray
}
function Stop-WithError ($Message) {
    Write-Host ""
    Write-Host "  [x]  $Message" -ForegroundColor Red
    Write-Host ""
    exit 1
}

function Test-Command ($Name) {
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

# ── source ────────────────────────────────────────────────────────────────────
# The checkout this script lives in, if any. $PSScriptRoot is empty when the
# script is piped from the web, which is exactly the signal we want: only a real
# checkout passes --repo to setup, and only a checkout installs itself.
function Get-RepoDir {
    if (-not $PSScriptRoot) { return $null }
    $parent = Split-Path -Parent $PSScriptRoot
    if (Test-Path (Join-Path $parent 'pyproject.toml')) { return $parent }
    return $null
}

$RepoDir = Get-RepoDir
$ResolvedRef = $null

# Which ref to install. An explicit -Version/-Ref wins; otherwise the latest
# release, so a bad merge to main can't break every new install. Falls back to
# main when there is no release yet or the API can't be reached.
function Resolve-Ref {
    if ($Version) { return "refs/tags/v$($Version.TrimStart('v'))" }
    if ($Ref)     { return $Ref }
    if ($script:ResolvedRef) { return $script:ResolvedRef }
    try {
        $latest = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" `
                                    -UseBasicParsing -TimeoutSec 10
        if ($latest.tag_name) { $script:ResolvedRef = "refs/tags/$($latest.tag_name)" }
    } catch {
        Write-Verbose "Release lookup failed: $_"
    }
    if (-not $script:ResolvedRef) { $script:ResolvedRef = 'refs/heads/main' }
    return $script:ResolvedRef
}

function Test-UsesCheckout {
    $RepoDir -and -not $Ref -and -not $Version
}

# The pip requirement to install. When LeSysBot is published to PyPI the URL
# branch becomes "lesysbot[telegram,discord]==$Version" and nothing else changes.
# The leaf extras are named rather than [all] because `all` is defined as
# lesysbot[telegram,discord] — a self-referential extra combined with a PEP 508
# direct-URL requirement is the one pip corner that has misbehaved.
function Get-PackageSpec {
    if (Test-UsesCheckout) { return "$RepoDir[telegram,discord]" }
    return "lesysbot[telegram,discord] @ https://github.com/$Repo/archive/$(Resolve-Ref).zip"
}

function Get-SourceLabel {
    if (Test-UsesCheckout) { return 'from this checkout' }
    return (Resolve-Ref)
}

# ── Python ────────────────────────────────────────────────────────────────────
function Test-PythonUsable ($Exe) {
    try {
        # `import venv` is part of the test so a Python that cannot build a
        # virtual environment is rejected here, with a message, rather than
        # several steps later with one about ensurepip.
        & $Exe -c 'import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-Python {
    foreach ($candidate in @('python3.13', 'python3.12', 'python3.11', 'python3', 'python')) {
        if ((Test-Command $candidate) -and (Test-PythonUsable $candidate)) {
            return (Get-Command $candidate).Source
        }
    }
    # The py launcher is how a normal Windows install exposes several versions.
    if (Test-Command 'py') {
        foreach ($v in @('-3.13', '-3.12', '-3.11')) {
            try {
                & py $v -c 'import sys, venv' 2>$null
                if ($LASTEXITCODE -eq 0) {
                    return (& py $v -c 'import sys; print(sys.executable)')
                }
            } catch { continue }
        }
    }
    return $null
}

# No usable Python: install uv (a single static binary, no admin) and let it
# fetch one. UV_NO_MODIFY_PATH because this script owns PATH handling.
function Install-UvPython {
    Write-Step 'No Python 3.11+ found - fetching a private one with uv ...'
    $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (Test-Command 'uv') { $uv = (Get-Command uv).Source }
    if (-not (Test-Path $uv)) {
        try {
            $env:UV_NO_MODIFY_PATH = '1'
            Invoke-RestMethod -Uri $UvInstaller -UseBasicParsing | Invoke-Expression
        } catch {
            return $null
        }
    }
    if (-not (Test-Path $uv)) { return $null }
    try {
        & $uv python install 3.12 | Out-Null
        $found = & $uv python find 3.12
        if ($found -and (Test-Path $found)) { return $found }
    } catch {
        Write-Verbose "uv python failed: $_"
    }
    return $null
}

# ── install ───────────────────────────────────────────────────────────────────
$Venv = Join-Path $Prefix 'venv'
$FreshVenv = $true

function New-LesysbotVenv ($Python) {
    $script:Venv = Join-Path $Prefix 'venv'
    if (Test-Path (Join-Path $Venv 'Scripts\python.exe')) {
        $script:FreshVenv = $false
    } else {
        New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
        if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
        & $Python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { Stop-WithError "Could not create a virtual environment at $Venv" }
    }
    Write-Value 'Environment' $Venv
}

function Install-Lesysbot {
    Write-Step "Installing LeSysBot ($(Get-SourceLabel)) ..."
    $py = Join-Path $Venv 'Scripts\python.exe'
    $pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '--quiet')
    if (-not $FreshVenv) {
        # The version string is static between releases, so pip would call a
        # moving branch archive "already satisfied" and install nothing at all.
        # Re-running the installer is the documented upgrade path.
        $pipArgs += '--force-reinstall'
    }
    & $py @pipArgs (Get-PackageSpec)
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Installing LeSysBot failed - the pip output above says why.`n       Report it at https://github.com/$Repo/issues"
    }
    if (-not (Test-Path (Join-Path $Venv 'Scripts\lesysbot.exe'))) {
        Stop-WithError 'The package installed but the lesysbot command is missing.'
    }
    Write-Ok 'LeSysBot installed'
}

# A .cmd shim rather than a symlink: symlinks on Windows need either developer
# mode or elevation, and this installer requires neither.
function New-Shim {
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $shim = Join-Path $BinDir 'lesysbot.cmd'
    $target = Join-Path $Venv 'Scripts\lesysbot.exe'
    Set-Content -Path $shim -Encoding ASCII -Value @(
        '@echo off',
        "`"$target`" %*"
    )
    Write-Value 'Command' $shim
    $env:Path = "$BinDir;$env:Path"
}

function Test-OnUserPath {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { return $false }
    return ($userPath -split ';' | Where-Object { $_.TrimEnd('\') -eq $BinDir.TrimEnd('\') }).Count -gt 0
}

# User scope, never Machine: no administrator rights, and nothing outside this
# account is touched.
function Add-ToUserPath {
    if (Test-OnUserPath) {
        Write-Value 'PATH' "already includes $BinDir"
        return
    }
    if ($NoModifyPath) {
        Write-Warn "$BinDir is not on your PATH (-NoModifyPath)."
        Write-Note "Add it yourself, or run commands as $BinDir\lesysbot.cmd"
        return
    }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $updated = if ($userPath) { "$userPath;$BinDir" } else { $BinDir }
    [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
    Write-Value 'PATH' "added $BinDir (new terminals see it)"
}

# ── Ollama ────────────────────────────────────────────────────────────────────
# winget or nothing: silently downloading and running an .exe from the internet
# is not something an installer should do behind your back.
function Install-Ollama {
    if ($SkipOllama) { Write-Note 'Skipping Ollama (-SkipOllama).'; return }
    if (Test-Command 'ollama') { Write-Value 'Ollama' 'already installed'; return }
    if (Test-Command 'winget') {
        Write-Step 'Installing Ollama with winget ...'
        try {
            & winget install --id Ollama.Ollama -e --silent `
                --accept-package-agreements --accept-source-agreements | Out-Null
        } catch {
            Write-Verbose "winget failed: $_"
        }
        if (Test-Command 'ollama') { Write-Ok 'Ollama installed'; return }
    }
    Write-Warn "Ollama isn't installed, and LeSysBot won't install it for you here."
    Write-Note "Get it from $OllamaDocs, then run:  ollama pull $Model"
    Write-Note 'Using OpenAI or another endpoint instead? `lesysbot setup` has it.'
}

function Get-Model {
    if ($NoModel -or $SkipOllama) { return }
    if (-not (Test-Command 'ollama')) { return }
    try {
        $installed = & ollama list 2>$null | Select-Object -Skip 1 |
                     ForEach-Object { ($_ -split '\s+')[0] }
        if ($installed -contains $Model) {
            Write-Value "Model $Model" 'already downloaded'
            return
        }
    } catch {
        Write-Verbose "ollama list failed: $_"
    }
    Write-Step "Pulling $Model - this can take a few minutes ..."
    try {
        & ollama pull $Model | Out-Null
        Write-Ok "Model $Model ready"
    } catch {
        Write-Warn "Could not pull $Model. Do it later with:  ollama pull $Model"
    }
}

# ── setup ─────────────────────────────────────────────────────────────────────
function Invoke-Setup {
    if ($SkipSetup) {
        Write-Note 'Skipping configuration (-SkipSetup). Run `lesysbot setup` when ready.'
        return
    }
    if ($SkipDashboard) { $env:LESYSBOT_SKIP_DASHBOARD = '1' }
    if ($Provider)      { $env:LESYSBOT_SETUP_PROVIDER = $Provider }

    Write-Host ''
    Write-Step 'Configuring LeSysBot ...'
    if (-not $SkipDashboard) {
        Write-Note '(this also sets up the Grafana dashboard - skip it with -SkipDashboard)'
    }
    Write-Host ''

    $cmd = Join-Path $BinDir 'lesysbot.cmd'
    if ($RepoDir) { & $cmd setup --yes --repo $RepoDir } else { & $cmd setup --yes }
}

function Write-Epilogue {
    Write-Host ''
    Write-Rule
    Write-Host '  LeSysBot is installed.' -ForegroundColor White
    Write-Host ''
    Write-Host '    lesysbot chat  ' -ForegroundColor White -NoNewline
    Write-Host '   talk to it in this terminal'
    Write-Host '    lesysbot       ' -ForegroundColor White -NoNewline
    Write-Host '   health, links, and where everything lives'
    Write-Host '    lesysbot setup ' -ForegroundColor White -NoNewline
    Write-Host '   change any of the answers above'
    Write-Host ''
    Write-Host '  Open a new terminal first so PATH takes effect.'
    Write-Host '  Docs:  https://lesysbot.github.io'
    Write-Host ''
}

# Leave a copy behind so -Uninstall works with no network and no checkout.
function Copy-Self {
    if (-not $PSCommandPath) { return }
    $dest = Join-Path $Prefix 'install.ps1'
    if ($PSCommandPath -eq $dest) { return }
    try { Copy-Item -Force $PSCommandPath $dest } catch { Write-Verbose "Self-copy failed: $_" }
}

# ── uninstall ─────────────────────────────────────────────────────────────────
# The scheduled task lives at a fixed per-user name that -Prefix does not move,
# so a sandboxed test run would otherwise remove the real machine's service.
function Remove-Service {
    if ($env:LESYSBOT_SKIP_SERVICE) {
        Write-Note 'Leaving the background task alone (LESYSBOT_SKIP_SERVICE set).'
        return
    }
    try {
        if (Get-ScheduledTask -TaskName 'LeSysBot' -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName 'LeSysBot' -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName 'LeSysBot' -Confirm:$false
            Write-Ok 'Scheduled task removed'
        }
    } catch {
        Write-Warn "Could not remove the scheduled task: $_"
    }
}

function Remove-FromUserPath {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { return }
    $kept = $userPath -split ';' | Where-Object { $_.TrimEnd('\') -ne $BinDir.TrimEnd('\') }
    $updated = ($kept -join ';')
    if ($updated -ne $userPath) {
        [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
        Write-Ok 'PATH entry removed'
    }
}

function Invoke-Uninstall {
    $dataDir = if ($env:LESYSBOT_HOME) { $env:LESYSBOT_HOME }
               else { Join-Path $env:USERPROFILE '.lesysbot' }
    Write-Host ''
    Write-Host '  Uninstalling LeSysBot' -ForegroundColor White
    Write-Rule
    Remove-Service
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $BinDir 'lesysbot.cmd')
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Prefix
    Write-Ok 'Command and environment removed'
    Remove-FromUserPath
    if ($Purge) {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $dataDir
        Write-Ok "$dataDir deleted"
    } else {
        Write-Host ''
        Write-Host "  Your settings, tools and logs are still in $dataDir"
        Write-Host '  Delete them too with:  -Purge'
    }
    Write-Host ''
}

# ── main ──────────────────────────────────────────────────────────────────────
if ($Uninstall) {
    Invoke-Uninstall
    exit 0
}

Write-Host ''
Write-Host '  LeSysBot installer' -ForegroundColor White
Write-Rule
Write-Host ''

$python = Find-Python
if (-not $python) { $python = Install-UvPython }
if (-not $python) {
    Stop-WithError @"
No Python 3.11+ found, and the fallback installer (uv) could not run.
       Install Python 3.11 or newer and re-run this command:
         https://www.python.org/downloads/  (tick "Add Python to PATH")
"@
}
$pyVersion = & $python -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'
Write-Value "Python $pyVersion" $python

New-LesysbotVenv $python
Install-Lesysbot
New-Shim
Copy-Self
Add-ToUserPath
Install-Ollama
Get-Model
Invoke-Setup
Write-Epilogue
