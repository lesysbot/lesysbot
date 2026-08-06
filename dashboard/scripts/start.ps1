<#
.SYNOPSIS
  One command to bring up the whole system-overview stack on Windows.

.DESCRIPTION
  Starts the native host exporters (windows_exporter + nvidia_gpu_exporter if an
  NVIDIA card is present), then Prometheus + Grafana in Docker Desktop, which
  scrape the exporters through host.docker.internal.

.EXAMPLE
  .\start.ps1          # start everything
  .\start.ps1 down     # stop and remove the stack
#>
[CmdletBinding()]
param([ValidateSet('up','down')][string]$Action = 'up')

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
Set-Location $Root

$port = (Select-String -Path (Join-Path $Root '.env') -Pattern '^GRAFANA_PORT=(.+)$' -ErrorAction SilentlyContinue |
         ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1)
if (-not $port) { $port = '3000' }

# Preflight: fail early with a helpful message, not a stack trace.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Error 'Docker is not installed. Install Docker Desktop — see dashboard\README.md.'
  return
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Error 'Docker Desktop is not running. Start it, wait for the whale icon, then retry.'
  return
}

if ($Action -eq 'down') {
  docker compose down
  & (Join-Path $Here 'run-exporters.ps1') stop
  Write-Host 'stack stopped.'
  return
}

Write-Host '==> Windows: starting native host exporters'
& (Join-Path $Here 'run-exporters.ps1') start

# --- what can this machine actually report? ----------------------------------
# Whether windows_exporter returns anything for `thermalzone` is a property of
# the firmware, not of Windows — common on laptops, rare on desktops — so there
# is no static rule that gets it right. Ask the exporter we just started.
# Anything it can't answer is left out of the dashboard rather than provisioned
# as an empty panel, which is indistinguishable from a broken one.
$caps = @()
$missing = @()

$metrics = $null
foreach ($attempt in 1..10) {
  try {
    $metrics = (Invoke-WebRequest -Uri 'http://127.0.0.1:9182/metrics' -UseBasicParsing `
                  -TimeoutSec 3).Content
    break
  } catch { Start-Sleep -Seconds 1 }
}

if ($null -eq $metrics) {
  Write-Warning 'windows_exporter did not answer on :9182 — using the portable dashboard.'
} else {
  if ($metrics -match '(?m)^windows_thermalzone_temperature_celsius\{') {
    $caps += 'thermalzone'
  } else {
    $missing += @'
No ACPI thermal-zone temperature. Most desktops expose none, and Windows has
    no per-component CPU/disk sensor of its own. For real CPU/disk temperatures
    install LibreHardwareMonitor and enable its Prometheus exporter:
    https://github.com/LibreHardwareMonitor/LibreHardwareMonitor
'@
  }
}

# nvidia_gpu_exporter works by shelling out to nvidia-smi, so that tool — not the
# card — is what decides whether GPU metrics are possible. Win32_VideoController
# tells the two apart, so "no driver installed" gets advice instead of silence.
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  $caps += 'nvidia'
} else {
  $gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue)
  if ($gpus | Where-Object { $_.Name -match 'NVIDIA' }) {
    $missing += @'
An NVIDIA GPU is present but nvidia-smi is not on PATH, so its metrics cannot
    be read. Install the NVIDIA driver (it ships nvidia-smi) and re-run this
    script. AMD and Intel GPUs have no exporter in this stack.
'@
  }
}

# Fill grafana\dashboards\generated — the directory the compose mounts. Three
# routes, best first: lesysbot renders every installed dashboard package;
# gen-dashboards.py generates one for this host; the committed portable JSON is
# copied in when there is no python3 at all. The directory is created either
# way, because Docker creates a missing bind-mount source as root-owned.
$generated = Join-Path $Root 'grafana\dashboards\generated'
New-Item -ItemType Directory -Force -Path $generated | Out-Null
$out = Join-Path $generated 'system-overview.json'
$portable = Join-Path $Root 'grafana\dashboards\system-overview-windows.json'
$gen = Join-Path $Here 'gen-dashboards.py'

$rendered = $false
if (Get-Command lesysbot -ErrorAction SilentlyContinue) {
  & lesysbot dashboard render *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host '==> dashboards rendered by lesysbot'
    $rendered = $true
  }
}

if (-not $rendered) {
  # Resolved in order: on Windows a bare `python` is often the Store stub that
  # only opens the Store, so prefer python3 when both exist.
  $python = $null
  foreach ($name in @('python3', 'python')) {
    $found = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $python = $found; break }
  }
  if ($python -and (Test-Path $gen)) {
    # `--have=` as one token on purpose: an empty $caps would otherwise pass an
    # empty argument that PowerShell drops, and argparse would then read `--out`
    # as the value of `--have`.
    & $python.Source $gen --host windows "--have=$($caps -join ',')" --out $out *> $null
    if ($LASTEXITCODE -eq 0) {
      $shown = if ($caps.Count) { $caps -join ',' } else { 'no optional sensors detected' }
      Write-Host "==> dashboard generated for this host [$shown]"
    } else {
      Copy-Item $portable $out -Force
      Write-Host '==> using the portable dashboard (could not generate one)'
    }
  } else {
    Copy-Item $portable $out -Force
    Write-Host '==> using the portable dashboard (no python3 to generate one)'
  }
}

Write-Host '==> starting Prometheus + Grafana (Docker Desktop)'
docker compose up -d

Write-Host ''
Write-Host "  Grafana:    http://localhost:$port      (admin / admin - change it)"
Write-Host '  Prometheus: http://localhost:9090/targets (all your exporters should be up)'
Write-Host ''
Write-Host '  Dashboards are under the "LeSysBot" folder in Grafana.'
Write-Host '  Stop with:  .\scripts\start.ps1 down'

if ($missing.Count) {
  Write-Host ''
  Write-Host '  Optional add-ons that would fill in more panels:' -ForegroundColor Yellow
  foreach ($m in $missing) { Write-Host "  * $m" -ForegroundColor Yellow }
  Write-Host '  Everything else is already being recorded — these are additions, not errors.'
}
