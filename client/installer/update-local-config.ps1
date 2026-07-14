<#
.SYNOPSIS
    Adjust the installed ResaPrint Agent's local settings (printer
    name, poll interval) without re-pairing — no admin PIN or API key
    needed, since the existing pairing is kept as-is.
.EXAMPLE
    .\update-local-config.ps1 -PrinterName "POS-80 Series"
.EXAMPLE
    .\update-local-config.ps1 -PollIntervalSeconds 10
#>
param(
    [string]$PrinterName,
    [int]$PollIntervalSeconds,
    [string]$InstallDir = "$env:ProgramFiles\ResaPrint\Agent"
)

$ErrorActionPreference = "Stop"
$agentExe = Join-Path $InstallDir "ResaPrint.Agent.exe"

if (-not (Test-Path $agentExe)) {
    throw "ResaPrint.Agent.exe not found at $agentExe — is it installed? Pass -InstallDir if it's elsewhere."
}

if (-not $PrinterName -and -not $PollIntervalSeconds) {
    Write-Host "Current configuration:"
    & $agentExe --show-config
    Write-Host ""
    Write-Host "Pass -PrinterName and/or -PollIntervalSeconds to change something."
    exit 0
}

if ($PrinterName) {
    & $agentExe --set-printer-name $PrinterName
}

if ($PollIntervalSeconds) {
    & $agentExe --set-poll-interval $PollIntervalSeconds
}

Write-Host "Restarting ResaPrintAgent service for changes to take effect..."
Restart-Service -Name ResaPrintAgent
Write-Host "Done."
