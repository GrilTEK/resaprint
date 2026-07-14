# Windows client guide

## What gets installed

Three Windows executables, all self-contained single-file `net8.0-windows`
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
- **`ResaPrint.Installer.exe`** — an optional graphical setup wizard
  (see below) as an alternative to running `install.ps1` by hand.

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
  ESC/POS bytes and does not rely on driver-side rendering. You do
  **not** need to know the exact queue name up front — the installer
  shows a picker (see below).
- An admin PIN for the ResaPrint backend (simplest path — the
  installer pairs the station for you), or a station already created
  and paired manually via the admin UI's Stations page if you prefer
  that route.

## Install (GUI — recommended)

This machine is a normal Windows PC on the same LAN as the backend
(the backend itself typically runs in a container on Proxmox
elsewhere) — the Agent only needs network access to the backend's URL
and a USB-connected receipt printer plugged into this PC.

1. Download the release zip from the repo's Releases page and extract
   it anywhere.
2. Run **`ResaPrint.Installer.exe`** (it will prompt for administrator
   elevation — installing a Windows Service requires it).
3. In the window:
   - Enter the **backend URL** (e.g. `http://192.168.1.50:8000`).
   - Pick the **printer** from the dropdown (populated from Windows'
     installed printers — no need to know the exact queue name).
   - Click **Test Print** to confirm the printer is wired up correctly
     before installing anything.
   - Either enter the **admin PIN** (the installer creates and pairs a
     new station named after this PC automatically), or switch to "I
     already paired a station manually" and enter the **Station ID**
     and **API key** from the admin UI's Stations page.
   - Click **Install**. Progress and any errors show in the log box.

`ResaPrint.Agent.exe` and `ResaPrint.Tray.exe` must be in the same
folder as `ResaPrint.Installer.exe` (they ship together in the release
zip) — the installer copies them into `%ProgramFiles%\ResaPrint\` and
wires up the service/scheduled task itself, using the same
`sc.exe`/`schtasks.exe` commands `install.ps1` uses under the hood.

Re-running the installer is safe — it stops the existing service,
replaces the binaries, and re-registers everything.

## Install (PowerShell — scripted/repeat installs)

Prefer a scriptable, non-interactive install (e.g. for rolling out to
several PCs), or don't want to run a GUI exe? Use `install.ps1`
instead — it does exactly the same steps as the GUI installer.

1. Download the release zip from the repo's Releases page (built by
   `.github/workflows/client-release.yml` on every `client-v*` tag).
2. Extract it anywhere.
3. Open an elevated PowerShell prompt in the extracted folder and run:

   ```powershell
   .\install.ps1 -ApiBaseUrl "http://192.168.1.50:8000" -AdminPin 1234
   ```

   This one command:
   - shows a numbered list of installed Windows printers to pick from
     (no need to type the exact queue name)
   - optionally sends a test print right there, before anything is
     installed, so a printer/queue problem is caught immediately
   - logs in with the admin PIN, creates a new station named after
     this PC (override with `-StationName "Front Desk PC"`), and pairs
     it — no manual copy-pasting a station ID/API key out of the admin
     UI
   - installs and starts the `ResaPrintAgent` service, and registers
     the Tray app to start at the next logon

   Prefer to pair manually via the admin UI's Stations page instead?
   Skip `-AdminPin`/`-StationName` and pass `-StationId`/`-ApiKey`
   directly:

   ```powershell
   .\install.ps1 -ApiBaseUrl "http://192.168.1.50:8000" -StationId 3 -ApiKey "<paste the API key here>"
   ```

   Either way, `-PrinterName "POS-80 Series"` can be passed up front to
   skip the interactive picker (useful for scripted/repeat installs).

   To start the Tray immediately without logging out:
   `Start-Process ".\ResaPrint.Tray.exe"`.

Re-running `install.ps1` is safe — it stops the existing service,
replaces the binary, and re-registers everything.

## Changing local settings later (no re-pairing needed)

If you just need to change the printer or poll interval — not the
backend URL or station — use `installer\update-local-config.ps1`
instead of a full reinstall (the existing pairing/API key is left
untouched):

```powershell
installer\update-local-config.ps1                              # shows current config
installer\update-local-config.ps1 -PrinterName "POS-80 Series"
installer\update-local-config.ps1 -PollIntervalSeconds 10
```

This calls the Agent's own `--show-config`/`--set-printer-name`/
`--set-poll-interval` and restarts the service. You can also run these
directly:

```powershell
& "$env:ProgramFiles\ResaPrint\Agent\ResaPrint.Agent.exe" --show-config
& "$env:ProgramFiles\ResaPrint\Agent\ResaPrint.Agent.exe" --test-print --printer-name "POS-80 Series"
```

`--test-print` works even if the Agent isn't paired/configured yet —
it talks directly to the Windows print spooler, nothing else.

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
| Printer not found / `WritePrinter failed` | Run `ResaPrint.Agent.exe --test-print --printer-name "..."` to isolate the problem, then fix the printer name with `installer\update-local-config.ps1 -PrinterName "..."` |
| Need to change printer/poll interval only | `installer\update-local-config.ps1 -PrinterName "..."` or `-PollIntervalSeconds N` — no re-pairing needed |
| Need to re-pair (new backend URL, station, or API key) | Re-run `install.ps1` — it's safe to run again and replaces the existing config |

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
