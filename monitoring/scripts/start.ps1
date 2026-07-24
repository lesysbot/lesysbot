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
  Write-Error 'Docker is not installed. Install Docker Desktop — see monitoring\README.md.'
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

Write-Host '==> starting Prometheus + Grafana (Docker Desktop)'
$env:DASH_JSON = 'system-overview-windows.json'   # provision the Windows dashboard only
docker compose up -d

Write-Host ''
Write-Host "  Grafana:    http://localhost:$port      (admin / admin - change it)"
Write-Host '  Prometheus: http://localhost:9090/targets (all your exporters should be up)'
Write-Host ''
Write-Host '  Dashboards are under the "LeSysBot" folder in Grafana.'
Write-Host '  Stop with:  .\scripts\start.ps1 down'
