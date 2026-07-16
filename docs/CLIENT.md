# Windows client guide

## What you download: one file

The only thing you ever need to download is **`ResaPrint.Installer.exe`**
from the repo's Releases page — a single self-contained `win-x64`
build (no .NET runtime needs to be pre-installed on the target
machine). `ResaPrint.Agent.exe` and `ResaPrint.Tray.exe` are bundled
*inside* it as embedded resources and get extracted to
`%ProgramFiles%\ResaPrint\` when you run the installer — there is
nothing else to extract, place side-by-side, or keep around. The same
exe also uninstalls (see below), so the whole client lifecycle — pair,
install, reconfigure, uninstall — is one file.

## What gets installed

- **`ResaPrint.Agent.exe`** — installed as a Windows Service named
  `ResaPrintAgent`, running as `LocalSystem`. This is the actual print
  engine: it polls the backend for queued print jobs targeted at this
  station, renders them, and sends them to a USB-attached receipt
  printer (see "Print modes" below for exactly how). Because it runs
  as `LocalSystem` with `start= delayed-auto` and an explicit `depend=
  Spooler` dependency, it starts automatically on boot — **before or
  without anyone logging into Windows** — and only after the Print
  Spooler service itself is up, so a reboot never leaves it trying to
  print before the spooler is ready. This is what makes printing work
  continuously and unattended, regardless of whether any user session
  is active.
- **`ResaPrint.Tray.exe`** — a status-only tray icon, auto-started at
  logon via a Scheduled Task. It has no printing logic and no way to
  stop the Agent — closing or killing the tray icon has zero effect on
  the service (which keeps running with nobody logged in at all).

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
  Panel → Devices and Printers → Add printer). Which driver to use
  depends on the print mode you pick (see below):
  - **escpos** (default): a generic driver — "Generic / Text Only"
    works well, or the printer manufacturer's driver if it exposes a
    plain queue name — since the Agent sends raw ESC/POS bytes and
    does not rely on driver-side rendering.
  - **gdi_text**: the printer's real Windows driver, since this mode
    prints through the normal Windows GDI printing pipeline instead of
    raw ESC/POS commands.

  You do **not** need to know the exact queue name up front — the
  installer shows a picker (see below).
- An admin PIN for the ResaPrint backend (simplest path — the
  installer pairs the station for you), or a station already created
  and paired manually via the admin UI's Stations page if you prefer
  that route.

## Print modes

The Agent supports two ways of turning a receipt's text into printer
output — pick whichever matches how the printer is installed:

| Mode | How it prints | Font/size | Printer driver needed |
|---|---|---|---|
| `escpos` (default) | Raw ESC/POS bytes sent via `winspool.drv`'s RAW datatype, bypassing the driver entirely | Compact — whatever the printer's own Font A/B + the backend's `receipt_font_size` setting (Normal/Large/Extra large) produce | "Generic / Text Only" or similar |
| `gdi_text` | Rendered through `System.Drawing.Printing` (the normal Windows GDI print pipeline) | Large bold text (Arial/Segoe UI-family, ~40px cell height, generous line spacing) — matches the font/size the operator's previous standalone Python script printed with | The printer's real Windows driver |

Set it with `-PrintMode gdi_text` on `install.ps1`/`install-agent.ps1`,
the **Print mode** dropdown in the GUI installer, or afterward without
reinstalling: `installer\update-local-config.ps1 -PrintMode gdi_text`.
Always send a **Test Print** after switching to confirm the physical
output looks right — `gdi_text` output depends entirely on the printer
driver actually being GDI-capable, not a RAW-passthrough queue.

## Install

This machine is a normal Windows PC on the same LAN as the backend
(the backend itself typically runs in a container on Proxmox
elsewhere) — the Agent only needs network access to the backend's URL
and a USB-connected receipt printer plugged into this PC.

1. Download **`ResaPrint.Installer.exe`** from the repo's Releases page
   — that's the only file you need.
2. Run it (it will prompt for administrator elevation — installing a
   Windows Service requires it).
3. In the window:
   - Enter the **backend URL** (e.g. `http://192.168.1.50:8000`).
   - Pick the **printer** from the dropdown (populated from Windows'
     installed printers — no need to know the exact queue name).
   - Pick the **print mode** — ESC/POS (default, compact) or GDI text
     (larger font, matches the old script's output — see "Print modes"
     above).
   - Click **Test Print** to confirm the printer is wired up correctly
     before installing anything.
   - Either enter the **admin PIN** (the installer creates and pairs a
     new station named after this PC automatically), or switch to "I
     already paired a station manually" and enter the **Station ID**
     and **API key** from the admin UI's Stations page.
   - Click **Install**. Progress and any errors show in the log box.

The installer extracts its bundled `ResaPrint.Agent.exe`/
`ResaPrint.Tray.exe` to `%ProgramFiles%\ResaPrint\` and wires up the
service/scheduled task itself via `sc.exe`/`schtasks.exe` — nothing
needs to sit next to the installer beforehand.

Re-running the installer is safe — it stops the existing service,
replaces the binaries, and re-registers everything.

### Scripted / repeat installs (advanced)

The `.ps1` scripts under `client/` in the repo (`install.ps1`,
`installer\install-agent.ps1`, `installer\update-local-config.ps1`)
still exist for scripted or repeat installs across many PCs, but they
are **not part of the release download** — they operate on the
standalone `ResaPrint.Agent.exe`/`ResaPrint.Tray.exe`, which you'd need
to build from source yourself (`dotnet publish`, see "Building from
source" below) rather than downloading pre-built. For a normal
single-PC install, use `ResaPrint.Installer.exe` instead.

## Changing local settings later (no re-pairing needed)

If you just need to change the printer or poll interval — not the
backend URL or station — use `installer\update-local-config.ps1`
instead of a full reinstall (the existing pairing/API key is left
untouched):

```powershell
installer\update-local-config.ps1                              # shows current config
installer\update-local-config.ps1 -PrinterName "POS-80 Series"
installer\update-local-config.ps1 -PrintMode gdi_text
installer\update-local-config.ps1 -PollIntervalSeconds 10
```

This calls the Agent's own `--show-config`/`--set-printer-name`/
`--set-print-mode`/`--set-poll-interval` and restarts the service. You
can also run these directly:

```powershell
& "$env:ProgramFiles\ResaPrint\Agent\ResaPrint.Agent.exe" --show-config
& "$env:ProgramFiles\ResaPrint\Agent\ResaPrint.Agent.exe" --test-print --printer-name "POS-80 Series"
```

`--test-print` works even if the Agent isn't paired/configured yet —
it talks directly to the Windows print spooler, nothing else.

## Uninstall

Run **`ResaPrint.Installer.exe`** again and click **Uninstall** — the
same single exe handles removal too. It stops and deletes the
`ResaPrintAgent` service, removes the Tray scheduled task, and deletes
`%ProgramFiles%\ResaPrint\`. It then asks separately whether to also
delete the encrypted local config under `%ProgramData%\ResaPrint`
(keep it if you plan to reinstall on this machine with the same
pairing). It does **not** deactivate the station on the backend — do
that from the admin UI's Stations page if you want the station itself
gone too.

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
| `configured: false` in status JSON | Pairing never completed or the DPAPI config is unreadable (e.g. moved to a different machine, or the service is somehow not running as the account that encrypted it) — re-run `ResaPrint.Installer.exe` with a fresh API key |
| Print jobs stay `queued` in the admin UI | Agent isn't polling — check status endpoint's `lastPollAt`; confirm the station's API key hasn't been revoked (re-pairing generates a new one) |
| Printer not found / `WritePrinter failed` | Run `& "$env:ProgramFiles\ResaPrint\Agent\ResaPrint.Agent.exe" --test-print --printer-name "..."` to isolate the problem, then fix the printer name with `installer\update-local-config.ps1 -PrinterName "..."` (or re-run the installer) |
| Need to change printer/poll interval/print mode only | `installer\update-local-config.ps1 -PrinterName "..."`, `-PrintMode gdi_text`, or `-PollIntervalSeconds N` — no re-pairing needed |
| Need to re-pair (new backend URL, station, or API key) | Re-run `ResaPrint.Installer.exe` — it's safe to run again and replaces the existing config |

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

A plain local build like that produces a `ResaPrint.Installer.exe` with
nothing embedded (the `Payload\` folder is empty) — fine for compiling
and testing, but not something you'd actually install with. To produce
a real installer with `ResaPrint.Agent.exe`/`ResaPrint.Tray.exe`
bundled inside it (release-equivalent), either tag a commit
`client-vX.Y.Z` and push the tag — `client-release.yml` does the full
publish-stage-embed sequence and attaches the resulting
`ResaPrint.Installer.exe` to a new GitHub Release — or replicate those
steps locally: `dotnet publish` Agent and Tray, copy both exes into
`ResaPrint.Installer\Payload\`, then `dotnet publish` the Installer
project.
