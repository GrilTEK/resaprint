#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Convenience wrapper: uninstalls both the ResaPrint Agent service
    and the Tray status app.
.PARAMETER PurgeConfig
    Also delete the DPAPI-encrypted local Agent config.
#>
param(
    [switch]$PurgeConfig
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

& (Join-Path $here "installer\uninstall-tray-task.ps1")
& (Join-Path $here "installer\uninstall-agent.ps1") -PurgeConfig:$PurgeConfig

Write-Host ""
Write-Host "ResaPrint client uninstall complete."
