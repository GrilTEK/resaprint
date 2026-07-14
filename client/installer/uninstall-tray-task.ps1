<#
.SYNOPSIS
    Removes the ResaPrint Tray Scheduled Task and stops any running
    instance.
#>
param(
    [string]$InstallDir = "$env:ProgramFiles\ResaPrint\Tray"
)

$ErrorActionPreference = "Stop"
$taskName = "ResaPrint Tray"

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing scheduled task '$taskName'..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
} else {
    Write-Host "Scheduled task '$taskName' not found — nothing to remove."
}

Get-Process -Name "ResaPrint.Tray" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

if (Test-Path $InstallDir) {
    Write-Host "Removing $InstallDir..."
    Remove-Item -Recurse -Force -Path $InstallDir
}

Write-Host "ResaPrint Tray uninstalled."
