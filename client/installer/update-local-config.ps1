<#
.SYNOPSIS
    Adjust the installed ResaPrint Agent's local settings (printer
    name, print mode, poll interval) without re-pairing — no admin PIN
    or API key needed, since the existing pairing is kept as-is.
.EXAMPLE
    .\update-local-config.ps1 -PrinterName "POS-80 Series"
.EXAMPLE
    .\update-local-config.ps1 -PollIntervalSeconds 10
.EXAMPLE
    .\update-local-config.ps1 -PrintMode gdi_text
#>
param(
    [string]$PrinterName,
    [ValidateSet("escpos", "gdi_text")][string]$PrintMode,
    [int]$PollIntervalSeconds,
    [string]$InstallDir = "$env:ProgramFiles\ResaPrint\Agent"
)

$ErrorActionPreference = "Stop"
$agentExe = Join-Path $InstallDir "ResaPrint.Agent.exe"

if (-not (Test-Path $agentExe)) {
    throw "ResaPrint.Agent.exe not found at $agentExe — is it installed? Pass -InstallDir if it's elsewhere."
}

if (-not $PrinterName -and -not $PrintMode -and -not $PollIntervalSeconds) {
    Write-Host "Current configuration:"
    & $agentExe --show-config
    Write-Host ""
    Write-Host "Pass -PrinterName, -PrintMode, and/or -PollIntervalSeconds to change something."
    exit 0
}

if ($PrinterName) {
    & $agentExe --set-printer-name $PrinterName
}

if ($PrintMode) {
    & $agentExe --set-print-mode $PrintMode
}

if ($PollIntervalSeconds) {
    & $agentExe --set-poll-interval $PollIntervalSeconds
}

Write-Host "Restarting ResaPrintAgent service for changes to take effect..."
Restart-Service -Name ResaPrintAgent
Write-Host "Done."
