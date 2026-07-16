# ResaPrint

Reservation-to-receipt printing for hotel front desks. An IMAP-fed backend
parses reservation emails (format is admin-configurable, not tied to one
hotel or channel) and dispatches print jobs to either a LAN ESC/POS receipt
printer or a Windows PC with a USB receipt printer, via a small always-on
Windows Service ("ResaPrint Agent") and a tray status indicator.

## Architecture

```mermaid
flowchart LR
    subgraph Mailbox
        IMAP[IMAP mailbox]
    end
    subgraph Backend[Backend - Docker on Proxmox]
        Worker[ingest-worker]
        API[FastAPI api]
        DB[(PostgreSQL)]
        Admin[Admin web UI\nJinja2 + HTMX]
    end
    subgraph LAN
        LANPrinter[LAN ESC/POS printer]
    end
    subgraph WindowsPC[Windows PC]
        Agent[ResaPrint.Agent\nWindows Service]
        Tray[ResaPrint.Tray\nstatus icon]
        USBPrinter[USB receipt printer]
    end

    IMAP -->|poll| Worker
    Worker -->|parse + store| DB
    API --> DB
    Admin --> API
    API -->|raw socket :9100| LANPrinter
    Agent -->|poll /print-jobs| API
    Agent -->|winspool RAW| USBPrinter
    Tray -->|localhost status| Agent
```

## Quick start

- **Backend deploy on Proxmox (one command)**: run on the Proxmox host as root —
  ```bash
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/GrilTEK/resaprint/main/proxmox/install-resaprint-lxc.sh)"
  ```
  Creates a new LXC, installs Docker, and starts the stack. See [`proxmox/install-resaprint-lxc.sh`](proxmox/install-resaprint-lxc.sh) for override variables and [`docs/BACKEND.md`](docs/BACKEND.md) for manual `docker compose` deploy, env vars, IMAP setup, and the parser field-mapping guide.
- **Windows client install**: see [`docs/CLIENT.md`](docs/CLIENT.md) — download `ResaPrint.Installer.exe` (the only file needed), run it as admin, pair the station.
- **API reference**: see [`docs/API.md`](docs/API.md).

## Repository layout

- `backend/` — FastAPI + SQLAlchemy + PostgreSQL backend, admin web UI, email ingestion, printing.
- `client/` — .NET 8 Windows Service (`ResaPrint.Agent`) + tray app (`ResaPrint.Tray`).
- `docs/` — deployment and usage documentation.
- `.github/workflows/` — CI (backend tests, client build/test) and client release packaging.

## License

MIT — see [`LICENSE`](LICENSE).
