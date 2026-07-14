#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Convenience wrapper: installs both the ResaPrint Agent service and
    the Tray status app. See installer/install-agent.ps1 and
    installer/install-tray-task.ps1 for the individual steps.
#>
param(
    [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
    [Parameter(Mandatory = $true)][int]$StationId,
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [Parameter(Mandatory = $true)][string]$PrinterName
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

& (Join-Path $here "installer\install-agent.ps1") -ApiBaseUrl $ApiBaseUrl -StationId $StationId -ApiKey $ApiKey -PrinterName $PrinterName -SourcePath $here
& (Join-Path $here "installer\install-tray-task.ps1") -SourcePath $here

Write-Host ""
Write-Host "ResaPrint client install complete."
