<#
.SYNOPSIS
    Installs the ResaPrint Tray status app and registers it to
    auto-start at logon via a Scheduled Task (not the Startup folder).
.DESCRIPTION
    Does not require admin rights — the tray app runs with the
    logged-on user's own privileges and talks only to the Agent's
    localhost status endpoint. Safe to re-run (idempotent).
#>
param(
    [string]$SourcePath = $PSScriptRoot,
    [string]$InstallDir = "$env:ProgramFiles\ResaPrint\Tray"
)

$ErrorActionPreference = "Stop"
$taskName = "ResaPrint Tray"
$exeName = "ResaPrint.Tray.exe"

$sourceExe = Join-Path $SourcePath $exeName
if (-not (Test-Path $sourceExe)) {
    throw "Could not find $exeName in $SourcePath. Run this script from the extracted release zip, or pass -SourcePath."
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path $sourceExe -Destination $InstallDir -Force
$installedExe = Join-Path $InstallDir $exeName

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Existing scheduled task '$taskName' found — replacing."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $installedExe
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -DisallowStartIfOnBatteries:$false -StopIfGoingOnBatteries:$false -AllowStartIfOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null

Write-Host "ResaPrint Tray installed and will start at next logon."
Write-Host "To start it immediately: Start-Process `"$installedExe`""
