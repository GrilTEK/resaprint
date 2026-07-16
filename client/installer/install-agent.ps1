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
    The Windows printer queue name the Agent should print to. With the
    default -PrintMode escpos, install the USB receipt printer as a
    generic/text or "Generic / Text Only" printer first (see
    docs/CLIENT.md); with -PrintMode gdi_text, install it with its real
    Windows driver instead.
.PARAMETER PrintMode
    "escpos" (default): render receipts as compact ESC/POS bytes sent
    RAW to the printer queue. "gdi_text": print through the Windows GDI
    printing pipeline instead, using a large bold font — matches the
    font/size the operator's previous standalone script printed with.
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
    [ValidateSet("escpos", "gdi_text")][string]$PrintMode = "escpos",
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

Write-Host "Pairing with backend and writing encrypted local config (print mode: $PrintMode)..."
& $installedExe --configure --api-base-url $ApiBaseUrl --station-id $StationId --api-key $ApiKey --printer-name $PrinterName --print-mode $PrintMode
if ($LASTEXITCODE -ne 0) {
    throw "Agent --configure step failed (exit code $LASTEXITCODE)."
}

if (-not $existingService) {
    Write-Host "Creating $serviceName service..."
    $binPath = "`"$installedExe`""
    # start= delayed-auto (not plain auto) + depend= Spooler: the Print
    # Spooler service isn't guaranteed to be up yet when a plain
    # auto-start service launches at boot, which can make the Agent's
    # first OpenPrinter call fail right after a reboot. Delayed-auto
    # start plus an explicit dependency makes Windows wait for Spooler
    # first, so printing works unattended after every reboot without
    # anyone logging in. obj= LocalSystem is what makes the service run
    # with no interactive session at all.
    sc.exe create $serviceName binPath= $binPath start= delayed-auto obj= LocalSystem depend= Spooler | Out-Null
    sc.exe description $serviceName "ResaPrint receipt printing agent" | Out-Null
} else {
    # Re-running the installer (upgrade path) — make sure an
    # already-existing service picks up the same startup hardening.
    sc.exe config $serviceName start= delayed-auto depend= Spooler | Out-Null
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
