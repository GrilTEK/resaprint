# Windows client guide

## What gets installed

Two Windows executables, both self-contained single-file `net8.0-windows`
`win-x64` builds (no .NET runtime needs to be pre-installed on the
target machine):

- **`ResaPrint.Agent.exe`** — installed as a Windows Service named
  `ResaPrintAgent`, running as `LocalSystem`. This is the actual print
  engine: it polls the backend for queued print jobs targeted at this
  station, renders them to ESC/POS bytes, and sends them to a
  USB-attached receipt printer via the Windows print spooler's RAW
  datatype (bypassing GDI rendering entirely).
- **`ResaPrint.Tray.exe`** — a status-only tray icon, auto-started at
  logon via a Scheduled Task. It has no printing logic and no way to
  stop the Agent — closing or killing the tray icon has zero effect on
  the service.

### What "cannot be closed" actually means

A Windows Service is not literally unkillable — an administrator can
always stop or delete it via the Services console, `sc.exe`, or
PowerShell's `Stop-Service`/`Remove-Service`. The real guarantee here
is narrower and more useful in practice: **a reception employee
without administrator rights has no path to stop print jobs from
flowing**, because:

- `ResaPrint.Tray.exe` has no Exit/Stop menu item, and even if killed
  via Task Manager, the Agent service is unaffected.
- Stopping `ResaPrintAgent` requires either the Services console (which
  itself requires elevation to make changes) or an elevated
  `sc.exe`/PowerShell session.
- Service recovery options (configured by `install-agent.ps1`) restart
  it automatically after a crash.

## Prerequisites

- Windows 10/11 or Windows Server, x64.
- The USB receipt printer installed as a Windows printer (Control
  Panel → Devices and Printers → Add printer). Use a generic driver —
  "Generic / Text Only" works well, or the printer manufacturer's
  driver if it exposes a plain queue name — since the Agent sends raw
  ESC/POS bytes and does not rely on driver-side rendering. Note the
  exact **printer queue name** as it appears in Windows; you'll need it
  during install.
- The station must already exist in the ResaPrint admin UI (Stations
  page) with `connection_type = usb_agent`, and you'll need its
  **station ID** and a **paired API key** (see below).

## Install

1. Download the release zip from the repo's Releases page (built by
   `.github/workflows/client-release.yml` on every `client-v*` tag).
2. Extract it anywhere.
3. In the admin web UI, go to **Stations**, create (or select) a
   `usb_agent` station, and click **Pair** — copy the API key shown
   (it is shown once and not recoverable afterward; re-pair if lost).
4. Open an elevated PowerShell prompt in the extracted folder and run:

   ```powershell
   .\install.ps1 -ApiBaseUrl "https://resaprint.example.internal" `
                 -StationId 3 `
                 -ApiKey "<paste the API key here>" `
                 -PrinterName "POS-80 Series"
   ```

   This installs and starts the `ResaPrintAgent` service and registers
   the Tray app to start at the next logon. To start the Tray
   immediately without logging out: `Start-Process ".\ResaPrint.Tray.exe"`.

Re-running `install.ps1` is safe — it stops the existing service,
replaces the binary, and re-registers everything.

## Uninstall

```powershell
.\uninstall.ps1              # keeps the DPAPI-encrypted config for a future reinstall
.\uninstall.ps1 -PurgeConfig # also deletes %ProgramData%\ResaPrint
```

## Troubleshooting

**Check the Agent's local status** (from the machine it's installed
on — this endpoint only listens on `127.0.0.1`, never externally):

```powershell
curl http://127.0.0.1:5990/status
```

Returns JSON: `running`, `configured`, `backendReachable`, `lastPollAt`,
`lastJobAt`, `lastJobResult`, `queueDepth`.

| Symptom | Likely cause / fix |
|---|---|
| Tray icon is red | `ResaPrintAgent` service isn't running — check `Get-Service ResaPrintAgent`, then Windows Event Viewer / service logs |
| Tray icon is yellow/gold | Service is running but can't reach the backend — check `ApiBaseUrl`, network/DNS, and that the backend container is up |
| `configured: false` in status JSON | Pairing never completed or the DPAPI config is unreadable (e.g. moved to a different machine, or the service is somehow not running as the account that encrypted it) — re-run `install-agent.ps1` with a fresh API key |
| Print jobs stay `queued` in the admin UI | Agent isn't polling — check status endpoint's `lastPollAt`; confirm the station's API key hasn't been revoked (re-pairing generates a new one) |
| Printer not found / `WritePrinter failed` | Confirm the exact Windows printer queue name matches `-PrinterName` used at install (`Get-Printer` lists installed queues); reinstall with the corrected name via `--configure` (see below) |
| Need to change config without a full reinstall | Re-run `ResaPrint.Agent.exe --configure --api-base-url ... --station-id ... --api-key ... --printer-name ...` directly, then `Restart-Service ResaPrintAgent` |

Service recovery is configured via `sc.exe failure` during install:
restart after 5s, 30s, then 60s on repeated failures, so transient
crashes self-heal without manual intervention — persistent crash-looping
still indicates a real problem worth checking Event Viewer for.

## Building from source

No local `.NET` SDK is required for day-to-day use of the client — the
release workflow builds and publishes it. To build locally (if you do
have the .NET 8 SDK installed):

```powershell
cd client
dotnet build ResaPrint.sln -c Release
dotnet test ResaPrint.Agent.Tests\ResaPrint.Agent.Tests.csproj
```

To produce a release-equivalent self-contained single-file build, tag
a commit `client-vX.Y.Z` and push the tag — `client-release.yml` does
the rest and attaches the zip to a new GitHub Release.
