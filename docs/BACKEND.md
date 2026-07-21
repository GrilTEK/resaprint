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
     `parse_date_eu`, `parse_date_long` (weekday-prefixed long-form
     dates like `"Friday, July 31, 2026"` — Cubilis/Stardekk IBE
     confirmation emails use this), `parse_decimal`, `upper`, `lower`
     — a small fixed set, deliberately no arbitrary code execution.
   - Mark a field **required**; if a required field can't be
     extracted, the email is left unparsed (logged to the audit log
     as `email.unparsed`) rather than creating a partial reservation.
3. Use the **Test parse** panel on the profile page to paste a sample
   email body and confirm extraction before relying on it for real
   mail — this doesn't persist anything, it's a dry run.

### Cancellation notices

A profile has a **Kind**: `reservation` (default — a match creates a
new booking) or `cancellation`. Use `cancellation` for an OTA's
"booking cancelled" email, which often reuses a template very similar
to the original confirmation — routing it through a normal
`reservation` profile would silently create a duplicate booking
instead of cancelling the real one. A cancellation profile only needs
one field mapped: whichever one targets `external_ref`, used to look
up the existing `Reservation` by that reference and mark it
`cancelled`. Other mapped fields on a cancellation profile are
ignored. If the reference doesn't match any known reservation (or
can't be extracted), the email is left unparsed with a reason, same
as any other parse failure — nothing is silently dropped.

Emails that don't match any parser (or fail required-field
extraction) are left in the mailbox marked `\Seen` (so they aren't
reprocessed every poll), logged to the audit log with action
`email.unparsed`, and — unlike the audit log, which only records the
subject — saved in full (subject + body + content type + failure
reason) to the **Unparsed emails** admin page. After fixing or adding
a parser mapping for the format that was missed, open the entry there
and click **Reparse**: it re-runs the *current* parser registry against
that exact stored email and, on success, creates the reservation (and
auto-prints it, if auto-print is enabled) exactly as live ingestion
would have — no need to wait for the sender to resend the email. An
entry that still doesn't match anything keeps its `pending` status and
records the new failure reason (any parsing failure — including an
unexpected one, not just the usual "field not found" — is caught and
recorded rather than left to crash the request). Entries can also be
deleted outright via **Ignore** if the missed email doesn't need a
reservation after all (the deletion itself is still audit-logged as
`email.ignored`).

### Multi-room bookings (room lines)

A single `guest_name`/`checkin`/`checkout` field mapping only captures
one `room_type`/`price_total` per email — fine for most bookings, but
a reservation covering several room types/rates in one email needs
more than one line item. Set **Room line pattern** on the profile page:
one regex with named groups, matched repeatedly (`re.finditer`, not
`re.search`) so every room in the email becomes its own
`ReservationRoomLine` row instead of only the first one being kept.

- Required group: `(?P<room_type>...)`
- Optional groups: `(?P<nights>...)`, `(?P<price_per_night>...)`,
  `(?P<price_total>...)`. If the pattern has no `nights` group (the
  common case — most emails state the stay's dates once, not per
  room), each line's nights defaults to the reservation's own
  checkout minus checkin. Only bother capturing `(?P<nights>...)`
  yourself for the rare booking where one room's stay genuinely
  differs from the others.

Example, for an email with repeated blocks like:
```
Type: ECONOMY DOUBLE ROOM WITH BREAKFAST
...
Guest: jane doePrice: 150.00
```
a pattern like
`^Type:\s*(?P<room_type>.+)$\n(?:.*\n)*?^Guest:.*?Price:\s*(?P<price_total>[\d.]+)`
extracts one line per `Type:`/`Guest:...Price:` block. Receipts print
each room line plus the reservation's overall total and an "Avg/night"
line (`price_total / nights`, computed — not re-extracted per line
unless you capture `price_per_night` yourself).

## Reservations UI

- **Filters**: the `/reservations` list can be filtered by status,
  source channel (substring match), and check-in date range, on top
  of the existing free-text search (guest name/email/phone/ref#/room
  type). All filters are query params, so a filtered view is a
  shareable/bookmarkable URL.
- **Arrivals sheet** (`/reservations/sheet`) stays focused on "who's
  actually arriving today" — it excludes cancelled reservations, but
  still includes manually-entered and walk-in reservations, so a
  same-day walk-in still shows up for room assignment/printing.
- **Plahta** (`/room-plan`) — a room-by-date grid: active rooms down
  the left, dates across the top (default 14-day window, paginated
  with prev/next), each occupied cell links to the reservation
  occupying that room that day. Built from
  `room_assignment.py::room_plan_grid`, which reads both assignment
  paths (the reservation-level `assigned_room_id` and the per-room-line
  one) once for the whole date range rather than querying per day.
- **Manual / walk-in entry** (`/reservations/new`, also linked as
  "New reservation" / "Walk-in" from the reservations list) — a plain
  HTML form over the same `POST /api/v1/reservations` behavior every
  other manual reservation creation already used (`status=manual`).
  "Walk-in" is just a pre-filled shortcut (today's date, `walkin` as
  the source channel) — there's no separate walk-in status or table.
- **Status changes**: a reservation's detail page has a "Change to"
  status dropdown (any admin or reception session), including
  cancelling it — this previously only existed as a raw API call
  (`DELETE /api/v1/reservations/{id}`) with no UI. Once a reservation
  is `cancelled`, an admin-role session also gets a **Delete
  reservation** button that hard-deletes it — guarded server-side to
  only ever delete a `cancelled` reservation, never an active one, so
  it can't be used to silently remove a real booking.
- **Cancellation via email**: see the "Cancellation notices" parser
  guide above — an incoming email routed to a `cancellation`-kind
  parser profile marks the matching reservation cancelled the same
  way the manual status change does (`reservation.cancelled_by_email`
  in the audit log instead of `reservation.status_changed`).
- **Email source view**: a reservation's detail page renders its
  stored raw email in a sandboxed `<iframe>` (no scripts/forms/
  navigation — `sandbox=""`) when the stored source looks like an
  HTML document, with a "View raw" toggle to see the original text.
  Plain-text sources render as before, with no toggle.

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
- **Cancelled reservations**: a reservation cancelled via
  `DELETE /api/v1/reservations/{id}` keeps its `status` as `cancelled`
  rather than being deleted, so it stays visible (with a red
  "cancelled" badge) on the reservations list and its own detail page
  — where it can still be printed manually. The arrivals sheet
  excludes cancelled reservations (it's an operational "who's arriving
  today" view), so a cancelled booking won't show up there. Printing a
  cancelled reservation adds "— PREKLICANO" to the receipt header plus
  a large bold "*** PREKLICANO ***" banner at both the top and bottom
  of the printed receipt (`printing.py::build_reservation_receipt`),
  so it's unmistakable on the physical paper even if a printer doesn't
  honor the large-text ESC/POS command.

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
