<#
.SYNOPSIS
  Run the host metric exporters natively on Windows.

.DESCRIPTION
  Downloads (once, into monitoring\bin) and starts in the background:
    * windows_exporter    :9182  — CPU, memory, disk, Ethernet, Wifi
    * nvidia_gpu_exporter :9835  — GPU (only if nvidia-smi is on PATH)

  Prometheus (in Docker Desktop) scrapes these via host.docker.internal.
  PIDs/logs are written under monitoring\run.

.EXAMPLE
  .\run-exporters.ps1            # start
  .\run-exporters.ps1 stop       # stop
  .\run-exporters.ps1 status
#>
[CmdletBinding()]
param([ValidateSet('start','stop','status','restart')][string]$Action = 'start')

$ErrorActionPreference = 'Stop'
$WindowsVersion = '0.30.5'
$NvidiaVersion  = '1.3.2'
$WindowsAddr    = '0.0.0.0:9182'
$NvidiaAddr     = '0.0.0.0:9835'

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
$Bin  = Join-Path $Root 'bin'
$Run  = Join-Path $Root 'run'
New-Item -ItemType Directory -Force -Path $Bin, $Run | Out-Null

function Log([string]$m)  { Write-Host "[exporters] $m" -ForegroundColor Cyan }
function Warn([string]$m) { Write-Host "[exporters] $m" -ForegroundColor Yellow }

$Arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { '386' }
$NvArch = if ([Environment]::Is64BitOperatingSystem) { 'x86_64' } else { 'i386' }

function Ensure-Windows {
  $exe = Join-Path $Bin 'windows_exporter.exe'
  if (Test-Path $exe) { return $exe }
  $url = "https://github.com/prometheus-community/windows_exporter/releases/download/v$WindowsVersion/windows_exporter-$WindowsVersion-$Arch.exe"
  Log "downloading windows_exporter $WindowsVersion"
  Invoke-WebRequest -Uri $url -OutFile $exe
  return $exe
}

function Ensure-Nvidia {
  $exe = Join-Path $Bin 'nvidia_gpu_exporter.exe'
  if (Test-Path $exe) { return $exe }
  $zip = Join-Path $Bin 'nvidia_gpu_exporter.zip'
  $url = "https://github.com/utkuozdemir/nvidia_gpu_exporter/releases/download/v$NvidiaVersion/nvidia_gpu_exporter_${NvidiaVersion}_windows_$NvArch.zip"
  Log "downloading nvidia_gpu_exporter $NvidiaVersion"
  Invoke-WebRequest -Uri $url -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $Bin -Force
  Remove-Item $zip -Force
  return $exe
}

function Start-One([string]$Name, [string]$Exe, [string[]]$Args) {
  $pidFile = Join-Path $Run "$Name.pid"
  if (Test-Path $pidFile) {
    $existing = Get-Process -Id (Get-Content $pidFile) -ErrorAction SilentlyContinue
    if ($existing) { Log "$Name already running (pid $($existing.Id))"; return }
  }
  $logFile = Join-Path $Run "$Name.log"
  $p = Start-Process -FilePath $Exe -ArgumentList $Args -NoNewWindow -PassThru `
        -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
  $p.Id | Out-File -Encoding ascii $pidFile
  Start-Sleep -Milliseconds 600
  if (-not $p.HasExited) { Log "$Name started (pid $($p.Id))" }
  else { Warn "$Name failed to start — see $logFile.err" }
}

function Stop-One([string]$Name) {
  $pidFile = Join-Path $Run "$Name.pid"
  if (-not (Test-Path $pidFile)) { return }
  $procId = Get-Content $pidFile
  Stop-Process -Id $procId -ErrorAction SilentlyContinue
  Remove-Item $pidFile -Force
  Log "$Name stopped (pid $procId)"
}

function Cmd-Start {
  # windows_exporter: enable exactly the collectors the dashboard uses.
  Start-One 'windows_exporter' (Ensure-Windows) @(
    "--web.listen-address=$WindowsAddr",
    "--collectors.enabled=cpu,cs,logical_disk,physical_disk,net,memory,system,os,thermalzone"
  )
  if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Start-One 'nvidia_gpu_exporter' (Ensure-Nvidia) @("--web.listen-address=$NvidiaAddr")
  } else {
    Warn 'nvidia-smi not found — skipping GPU exporter (the GPU dashboard row will be empty)'
  }
  Write-Host ''
  Log 'done. Prometheus scrapes these at host.docker.internal:9182 / :9835'
  Log 'verify:  curl http://localhost:9182/metrics   (and :9835 for GPU)'
}

function Cmd-Status {
  foreach ($n in 'windows_exporter','nvidia_gpu_exporter') {
    $pidFile = Join-Path $Run "$n.pid"
    if ((Test-Path $pidFile) -and (Get-Process -Id (Get-Content $pidFile) -ErrorAction SilentlyContinue)) {
      Write-Host "$n: running (pid $(Get-Content $pidFile))"
    } else { Write-Host "$n: stopped" }
  }
}

switch ($Action) {
  'start'   { Cmd-Start }
  'stop'    { Stop-One 'windows_exporter'; Stop-One 'nvidia_gpu_exporter' }
  'restart' { Stop-One 'windows_exporter'; Stop-One 'nvidia_gpu_exporter'; Cmd-Start }
  'status'  { Cmd-Status }
}
