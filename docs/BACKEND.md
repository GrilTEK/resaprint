# Backend deployment guide

## Overview

The backend is a FastAPI app (`backend/app`) backed by PostgreSQL,
deployed via `docker-compose.yml` at the repo root as four services:

| Service | Purpose |
|---|---|
| `db` | PostgreSQL 16 |
| `migrate` | One-shot `alembic upgrade head`, runs before `api`/`ingest-worker` start |
| `api` | The FastAPI app (REST API + admin web UI), uvicorn on port 8000 internally |
| `ingest-worker` | Standalone IMAP poll loop (`worker.py`), decoupled from `api` so a stuck IMAP connection can't affect API responsiveness |

## Quick start — Proxmox one-command install (recommended)

`griltek/resaprint` is public, so no token is needed. Run this **on the
Proxmox host itself, as root**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/GrilTEK/resaprint/main/proxmox/install-resaprint-lxc.sh)"
```

This creates a new unprivileged Debian 12 LXC (`nesting=1,keyctl=1` so
Docker works inside it), installs Docker, clones this repo, generates a
random `SECRET_KEY` and `POSTGRES_PASSWORD`, and runs
`docker compose up -d --build`. IMAP is left unconfigured — set it from
the admin UI's **Settings** page (see below) once you've logged in, no
`.env` editing or restart needed.

Override any default (container ID, storage pool, network bridge,
static IP, resources) via environment variables — see the top of
[`proxmox/install-resaprint-lxc.sh`](../proxmox/install-resaprint-lxc.sh)
for the full list, e.g.:

```bash
CTID=150 MEMORY_MB=4096 IP_CONFIG="10.0.0.50/24,gw=10.0.0.1" \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/GrilTEK/resaprint/main/proxmox/install-resaprint-lxc.sh)"
```

If the repo is ever made private again, create a [fine-grained personal
access token](https://github.com/settings/tokens?type=beta) with
`Contents: Read-only` and pass it as both an `Authorization` header on
the outer `curl` and as `GH_TOKEN` for the script's own clone step:

```bash
GH_TOKEN="<your token>" bash -c "$(curl -fsSL -H "Authorization: token $GH_TOKEN" https://raw.githubusercontent.com/GrilTEK/resaprint/main/proxmox/install-resaprint-lxc.sh)"
```

Nginx Proxy Manager configuration and the first admin PIN are
deliberately **not** automated (NPM setup is host-specific and the PIN
should be something you choose) — both are printed as next steps when
the script finishes.

## Manual quick start (any Docker host)

```bash
cp backend/.env.example backend/.env
# edit backend/.env — at minimum set SECRET_KEY, POSTGRES_PASSWORD,
# DATABASE_URL (must match POSTGRES_PASSWORD), and the IMAP_* variables

docker compose up -d --build
```

The API listens on port 8000 inside the `api` container, published to
the host as `8000:8000` by default (see `docker-compose.yml`). This
repo does not manage Nginx Proxy Manager configuration — if you're
running ResaPrint on a private LAN IP behind NPM, add a proxy host
pointing at `<host-ip>:8000` and terminate TLS there; that setup lives
outside this repo.

Local development (hot reload, exposed Postgres port for a DB client):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

## Environment variables (`backend/.env.example`)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs admin session cookies — set to a long random value in production |
| `SESSION_COOKIE_SECURE` | `true` by default — browsers **silently refuse to store** a `Secure`-flagged cookie received over plain http. If you're testing directly against `http://<host-ip>:8000` before Nginx Proxy Manager/TLS is set up, login will appear to succeed (200 response) but the session cookie never sticks, so every page redirects back to `/login`. Set `false` temporarily for that case, and set it back to `true` once you're behind HTTPS. |
| `SESSION_MAX_AGE_SECONDS` | Admin session lifetime (default 12h) |
| `PIN_LOCKOUT_THRESHOLD` / `PIN_LOCKOUT_MINUTES` | Failed-PIN lockout policy |
| `DATABASE_URL` | Full asyncpg connection string, must match `POSTGRES_*` below |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Postgres container credentials |
| `IMAP_HOST` / `IMAP_PORT` / `IMAP_USER` / `IMAP_PASSWORD` | Dedicated reservation mailbox credentials — never commit these |
| `IMAP_FOLDER` | Single shared folder polled for all channels/OTAs (routing is by subject/body match, not folder) |
| `IMAP_PROCESSED_FOLDER` | Where successfully-parsed emails are copied (originals are then marked `\Deleted` + expunged from `IMAP_FOLDER`, not hard-deleted from the mailbox) |
| `IMAP_POLL_SECONDS` | Poll interval, default 60s |
| `LAN_PRINT_TIMEOUT_SECONDS` | Socket timeout for raw ESC/POS sends to LAN printers |

## First admin PIN

Use `scripts/create_admin_pin.py` — it hashes and inserts (or updates,
if the label already exists) the PIN in a single Python process, with
no shell/psql relay involved:

```bash
docker compose exec api python scripts/create_admin_pin.py --label "Front desk" --pin 1234
```

Omit `--pin` to be prompted for it instead (input hidden, doesn't end
up in shell history). Re-running with the same `--label` rotates that
PIN's hash rather than creating a duplicate row.

**Do not** hash and insert the PIN as two separate manual steps through
`bash -c "... INSERT ... '$hash' ..."` — bcrypt hashes contain `$`
characters, and inside double-quoted shell strings `$2b`, `$12`, etc.
are interpreted as (empty) shell variables, silently corrupting the
hash. This exact failure mode produces `passlib.exc.UnknownHashError:
hash could not be identified` in the API logs and a 500 on login. The
script above avoids the problem entirely by never passing the hash
through a shell.

## IMAP setup

Configure IMAP from the admin UI's **Settings** page
(`/settings`) — host, port, username, password, folder, processed
folder, and poll interval are all editable there and take effect on
the `ingest-worker`'s next poll cycle, no restart needed. The password
is encrypted at rest (Fernet, keyed from `SECRET_KEY`) and the admin
UI never displays it back once set (only whether one is configured).

`IMAP_*` in `backend/.env` still exists and seeds the DB-backed
settings the first time they're read (useful for scripted/non-GUI
deployments), but after that first read the DB row is authoritative —
editing `.env` afterward has no effect. Use the Settings page or
`PATCH /api/v1/config` going forward.

Point IMAP at a dedicated mailbox (not a personal inbox) that receives
reservation confirmation emails from your OTAs/channel manager. All
channels are expected to land in a single folder (default `INBOX`) —
the parser registry routes each email to the right parser by matching
its subject (and optionally body), not by folder. If your setup
delivers different channels to different folders today, forward/rule
them into one shared folder.

## Parser field-mapping guide

Reservation email parsing is intentionally not hardcoded to one
hotel or OTA. Two kinds of parsers exist:

1. **Reference parser** (`backend/app/services/parsers/reference_booking_com.py`) —
   a hardcoded, illustrative example targeting a fabricated
   "Booking.com-style" confirmation email layout. It is **not**
   verified against real Booking.com traffic — treat it as a worked
   example of the `ReservationParser` interface, not a production
   integration.
2. **Generic field-mapping parser** — fully admin-configurable from
   the `/parsers` page in the web UI, backed by the
   `parser_field_mappings` / `parser_field_mapping_fields` tables.

To add support for a new email format:

1. Go to **Parsers** in the admin UI, create a new profile with a
   `profile_slug` and (optionally) a `match_subject_regex` that
   identifies emails from this source by subject line.
2. Add one field mapping per reservation field you want to extract
   (`guest_name`, `checkin`, `checkout`, `price_total`, etc.):
   - **regex**: matched against the plain-text body with `re.search`;
     `group_index` picks which capture group to use.
   - **xpath**: matched against the HTML body via `lxml`.
   - **transform**: one of `none`, `strip`, `parse_date_iso`,
     `parse_date_eu`, `parse_decimal`, `upper`, `lower` — a small
     fixed set, deliberately no arbitrary code execution.
   - Mark a field **required**; if a required field can't be
     extracted, the email is left unparsed (logged to the audit log
     as `email.unparsed`) rather than creating a partial reservation.
3. Use the **Test parse** panel on the profile page to paste a sample
   email body and confirm extraction before relying on it for real
   mail — this doesn't persist anything, it's a dry run.

Emails that don't match any parser (or fail required-field
extraction) are left in the mailbox marked `\Seen` (so they aren't
reprocessed every poll) and logged to the audit log with action
`email.unparsed`, including the subject — check there first if a
reservation seems to be missing.

## Printing

- **LAN ESC/POS**: create a `print_stations` row with
  `connection_type=lan_escpos`, `lan_host`, and `lan_port` (default
  9100 — the common ESC/POS raw-socket port, but not universal; adjust
  per your printer/print-server). The backend opens a raw TCP
  connection and writes ESC/POS bytes directly — no OS driver
  involved.
- **USB via Windows Agent**: create a `print_stations` row with
  `connection_type=usb_agent`, then use **Pair** in the Stations page
  to generate a one-time API key for the Windows Agent (see
  [`CLIENT.md`](CLIENT.md)).

## Running tests locally

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate  # or source .venv/bin/activate on Linux/macOS
pip install -r requirements-dev.txt
ruff check .
PYTHONPATH=. pytest -v
```

Tests use an in-memory SQLite database (see `tests/conftest.py`) for
speed; `backend-ci.yml` additionally runs a real Postgres-backed
`alembic upgrade head` on every push to catch migration issues the
SQLite test DB wouldn't.
