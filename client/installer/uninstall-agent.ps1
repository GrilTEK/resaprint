#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Stops and removes the ResaPrint Agent Windows Service.
.PARAMETER PurgeConfig
    Also delete the DPAPI-encrypted local config
    (%ProgramData%\ResaPrint). Omit this to keep the config so a
    reinstall doesn't require re-pairing.
#>
param(
    [switch]$PurgeConfig,
    [string]$InstallDir = "$env:ProgramFiles\ResaPrint\Agent"
)

$ErrorActionPreference = "Stop"
$serviceName = "ResaPrintAgent"

$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($service) {
    Write-Host "Stopping $serviceName..."
    Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
    sc.exe delete $serviceName | Out-Null
} else {
    Write-Host "$serviceName service not found — nothing to stop."
}

if (Test-Path $InstallDir) {
    Write-Host "Removing $InstallDir..."
    Remove-Item -Recurse -Force -Path $InstallDir
}

if ($PurgeConfig) {
    $configDir = "$env:ProgramData\ResaPrint"
    if (Test-Path $configDir) {
        Write-Host "Purging local config at $configDir..."
        Remove-Item -Recurse -Force -Path $configDir
    }
}

Write-Host "ResaPrint Agent uninstalled."
