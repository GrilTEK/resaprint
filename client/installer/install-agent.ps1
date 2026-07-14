#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Installs the ResaPrint Agent as a Windows Service.
.DESCRIPTION
    Copies the published ResaPrint.Agent.exe into
    %ProgramFiles%\ResaPrint\Agent, pairs it with the backend using the
    supplied API key, registers it as an auto-start Windows Service
    running as LocalSystem with restart-on-failure recovery options,
    and starts it. Safe to re-run (idempotent).
.PARAMETER ApiBaseUrl
    Base URL of the ResaPrint backend, e.g. https://resaprint.example.internal
.PARAMETER StationId
    The print_stations.id this Agent was paired to in the admin UI.
.PARAMETER ApiKey
    The one-time API key shown by the admin UI's "Pair" action.
.PARAMETER PrinterName
    The Windows printer queue name the Agent should send raw ESC/POS
    bytes to (install the USB receipt printer as a generic/text or
    "Generic / Text Only" printer first — see docs/CLIENT.md).
.PARAMETER SourcePath
    Directory containing the published ResaPrint.Agent.exe. Defaults to
    the script's own directory (i.e. run this from the extracted
    release zip).
#>
param(
    [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
    [Parameter(Mandatory = $true)][int]$StationId,
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [Parameter(Mandatory = $true)][string]$PrinterName,
    [string]$SourcePath = $PSScriptRoot,
    [string]$InstallDir = "$env:ProgramFiles\ResaPrint\Agent"
)

$ErrorActionPreference = "Stop"
$serviceName = "ResaPrintAgent"
$exeName = "ResaPrint.Agent.exe"

Write-Host "Installing ResaPrint Agent to $InstallDir ..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$sourceExe = Join-Path $SourcePath $exeName
if (-not (Test-Path $sourceExe)) {
    throw "Could not find $exeName in $SourcePath. Run this script from the extracted release zip, or pass -SourcePath."
}

$existingService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "Existing $serviceName service found — stopping before upgrade."
    Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
}

Copy-Item -Path $sourceExe -Destination $InstallDir -Force

$installedExe = Join-Path $InstallDir $exeName

Write-Host "Pairing with backend and writing encrypted local config..."
& $installedExe --configure --api-base-url $ApiBaseUrl --station-id $StationId --api-key $ApiKey --printer-name $PrinterName
if ($LASTEXITCODE -ne 0) {
    throw "Agent --configure step failed (exit code $LASTEXITCODE)."
}

if (-not $existingService) {
    Write-Host "Creating $serviceName service..."
    $binPath = "`"$installedExe`""
    sc.exe create $serviceName binPath= $binPath start= auto obj= LocalSystem | Out-Null
    sc.exe description $serviceName "ResaPrint receipt printing agent" | Out-Null
}

# Recovery options: restart after 5s, 30s, then 60s on repeated
# failures, resetting the failure count after 1 day of stability — so
# a transient crash self-heals without manual intervention.
sc.exe failure $serviceName reset= 86400 actions= restart/5000/restart/30000/restart/60000 | Out-Null

# The status endpoint (127.0.0.1:5990) is loopback-only by design —
# no inbound firewall rule is created or needed for it.

Write-Host "Starting $serviceName service..."
Start-Service -Name $serviceName

Write-Host "ResaPrint Agent installed and running."
Write-Host "Status endpoint (local only): http://127.0.0.1:5990/status"
