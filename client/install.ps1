#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Guided ResaPrint client installer: picks the printer from a list,
    auto-creates and pairs a station via the admin PIN (no manual
    copy-pasting station id/API key out of the admin UI), offers a
    test print before finalizing, then installs the Agent service and
    Tray app.
.DESCRIPTION
    Two ways to provide station credentials:
      A) -AdminPin (+ optional -StationName): the script logs in,
         creates a new "usb_agent" station named after this PC (or
         -StationName), pairs it, and uses the resulting id/key.
         Simplest path — nothing to copy from the admin UI by hand.
      B) -StationId + -ApiKey: use a station you already created and
         paired yourself via the admin UI's Stations page.
    If -PrinterName is omitted, you'll be shown a numbered list of
    installed Windows printers to choose from instead of having to
    type the exact queue name.
.EXAMPLE
    .\install.ps1 -ApiBaseUrl "http://192.168.1.50:8000" -AdminPin 1234
.EXAMPLE
    .\install.ps1 -ApiBaseUrl "http://192.168.1.50:8000" -StationId 3 -ApiKey "abc..." -PrinterName "POS-80 Series"
#>
param(
    [Parameter(Mandatory = $true)][string]$ApiBaseUrl,

    [string]$AdminPin,
    [string]$StationName = $env:COMPUTERNAME,

    [int]$StationId,
    [string]$ApiKey,

    [string]$PrinterName
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$agentExe = Join-Path $here "ResaPrint.Agent.exe"

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {
    # Older PowerShell/.NET without Tls12 in the enum — fine for a
    # plain http:// LAN backend, which is the common case here.
}

# ---------- 1. Pick the printer ----------
if (-not $PrinterName) {
    $printers = @(Get-Printer | Select-Object -ExpandProperty Name)
    if (-not $printers -or $printers.Count -eq 0) {
        throw "No Windows printers found. Install the USB receipt printer as a Windows printer queue first (Devices and Printers > Add printer, 'Generic / Text Only' driver works well) — see docs/CLIENT.md — then re-run this script."
    }

    Write-Host ""
    Write-Host "Installed printers:"
    for ($i = 0; $i -lt $printers.Count; $i++) {
        Write-Host "  [$i] $($printers[$i])"
    }
    $selection = Read-Host "Select the receipt printer by number"
    $PrinterName = $printers[[int]$selection]
    Write-Host "Using printer: $PrinterName"
}

# ---------- 2. Optional test print before going any further ----------
if (Test-Path $agentExe) {
    $doTest = Read-Host "Send a test print to '$PrinterName' now to confirm it's wired up correctly? (y/n)"
    if ($doTest -eq "y") {
        & $agentExe --test-print --printer-name $PrinterName
        if ($LASTEXITCODE -ne 0) {
            $proceed = Read-Host "Test print failed — continue with install anyway? (y/n)"
            if ($proceed -ne "y") {
                throw "Aborted after failed test print. Fix the printer setup and re-run."
            }
        }
    }
}

# ---------- 3. Get a station id + API key ----------
if (-not $StationId -or -not $ApiKey) {
    if (-not $AdminPin) {
        $securePin = Read-Host "Enter the ResaPrint admin PIN (used once, to auto-create and pair a station)" -AsSecureString
        $AdminPin = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePin)
        )
    }

    Write-Host "Logging in to $ApiBaseUrl ..."
    $session = $null
    try {
        Invoke-RestMethod -Uri "$ApiBaseUrl/login" -Method Post -Body @{ pin = $AdminPin } -SessionVariable session -ErrorAction Stop | Out-Null
    } catch {
        throw "Login failed — check -ApiBaseUrl and the admin PIN. ($($_.Exception.Message))"
    }

    Write-Host "Creating station '$StationName' ..."
    $stationBody = @{ name = $StationName; connection_type = "usb_agent" } | ConvertTo-Json
    try {
        $station = Invoke-RestMethod -Uri "$ApiBaseUrl/api/v1/stations" -Method Post -Body $stationBody -ContentType "application/json" -WebSession $session -ErrorAction Stop
    } catch {
        throw "Could not create station '$StationName' — it may already exist (pick a different -StationName), or check the error: $($_.Exception.Message)"
    }
    $StationId = $station.id

    Write-Host "Pairing station (id $StationId) ..."
    $pairResult = Invoke-RestMethod -Uri "$ApiBaseUrl/api/v1/stations/$StationId/pair" -Method Post -WebSession $session -ErrorAction Stop
    $ApiKey = $pairResult.api_key

    Write-Host "Station '$StationName' created and paired (id $StationId)."
}

# ---------- 4. Install the Agent service + Tray app ----------
& (Join-Path $here "installer\install-agent.ps1") -ApiBaseUrl $ApiBaseUrl -StationId $StationId -ApiKey $ApiKey -PrinterName $PrinterName -SourcePath $here
& (Join-Path $here "installer\install-tray-task.ps1") -SourcePath $here

Write-Host ""
Write-Host "ResaPrint client install complete."
Write-Host "  Station:  $StationName (id $StationId)"
Write-Host "  Printer:  $PrinterName"
Write-Host "  Status:   curl http://127.0.0.1:5990/status"
