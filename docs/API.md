# REST API reference

Base path for machine/JSON endpoints: `/api/v1`. Server-rendered admin
UI pages live at unprefixed paths (`/`, `/reservations`, `/login`,
etc.) and are documented briefly at the end.

## Authentication

Two independent auth mechanisms:

- **Admin session** — `POST /login` (form-encoded, field `pin`) sets a
  signed, httponly session cookie (`resaprint_session`). All
  `/api/v1/*` admin endpoints below require this cookie except the
  station-authenticated ones. `POST /logout` clears it.
- **Station API key** — USB-agent stations authenticate to the
  poll/ack endpoints with `Authorization: Bearer <api_key>`, issued
  once via the pairing endpoint (see Stations below) and stored
  bcrypt-hashed server-side.

Failed admin logins count toward a per-PIN lockout
(`PIN_LOCKOUT_THRESHOLD` failures locks the PIN for
`PIN_LOCKOUT_MINUTES`); the API returns a generic "invalid PIN" for
both wrong-PIN and locked-PIN cases to avoid leaking lockout state.

### Roles

Every PIN has a `role`: `admin` (full access) or `reception`
(reservations + print jobs only). Reception-role requests to
admin-only endpoints (stations, parsers, config, users, audit-log)
return `403 Forbidden`; the equivalent HTML pages redirect to `/`
instead. In `docs/API.md`'s tables below, "admin" in the Auth column
means admin-role specifically (via `require_admin_role`/
`require_admin_role_html`); plain "any role" means both admin and
reception can call it.

## Users

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/users` | admin | Never returns `pin_hash` |
| POST | `/api/v1/users` | admin | `{"label", "pin", "role"}` — `role` defaults to `reception` |
| PATCH | `/api/v1/users/{id}` | admin | `pin` is write-only (omit to leave unchanged); rejects demoting/deactivating the last active admin |
| DELETE | `/api/v1/users/{id}` | admin | Hard delete; rejects deleting the last active admin |

## Reservations

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/reservations` | admin | Filters: `status_filter`, `source_channel`, `checkin_from`, `checkin_to`, `q` (free-text search across guest name/email/phone/external ref/room type, case-insensitive substring) |
| GET | `/api/v1/reservations/{id}` | admin | |
| POST | `/api/v1/reservations` | admin | Manual creation, `status` forced to `manual`. If `room_auto_assign_enabled` is on (see Config below, default off), a room is auto-assigned on creation (see Rooms below) |
| PATCH | `/api/v1/reservations/{id}` | admin | Partial update; logged to audit log as `reservation.manual_override` |
| DELETE | `/api/v1/reservations/{id}` | admin | Soft-cancel (`status = cancelled`), does not delete the row |
| POST | `/api/v1/reservations/{id}/print` | admin | Body: `{"station_id": <int>}`. Renders a receipt and enqueues (and, for LAN stations, immediately sends) a print job |
| POST | `/api/v1/reservations/{id}/reassign-room` | admin | Clears any current room assignment and re-runs auto-assignment — use after adding new rooms or freeing up a conflicting stay |
| POST | `/api/v1/reservations/{id}/assign-room` | admin | Body: `{"room_id": <int\|null>, "room_line_id": <int\|null>}`. Manual override — sets (or clears with `room_id: null`) the assigned room directly, bypassing the availability check. Targets a specific room line for multi-room bookings, otherwise the reservation itself |

## Rooms

Physical rooms in the property, each with a free-text `category` that
is matched (exact string) against `Reservation.room_type` /
`ReservationRoomLine.room_type` to auto-assign a free room whenever a
reservation is created — either via manual creation (`POST
/api/v1/reservations`) or on email ingestion. A room is "free" for a
given stay if no other non-cancelled reservation (or room line, for
multi-room bookings) already assigned to it has overlapping dates.
Assignment is best-effort: if no room of the matching category is
free, the reservation/room-line is simply left unassigned and can be
fixed later (add a room, cancel the conflicting stay, then call
`reassign-room`).

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/rooms` | admin | |
| POST | `/api/v1/rooms` | admin | `{"room_number", "category", "floor"?, "notes"?}` |
| PATCH | `/api/v1/rooms/{id}` | admin | Partial update, incl. `is_active` |
| DELETE | `/api/v1/rooms/{id}` | admin | Hard delete; any reservation/room-line assigned to it is unassigned (not deleted) |

## Print jobs

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/print-jobs` | admin | Filters: `status_filter`, `station_id` |
| GET | `/api/v1/print-jobs/{id}` | admin | |
| POST | `/api/v1/print-jobs` | admin | Manual/test print — arbitrary `payload_text`, no reservation required |
| POST | `/api/v1/print-jobs/{id}/retry` | admin | Resets to `queued`; LAN stations are dispatched immediately |
| POST | `/api/v1/print-jobs/{id}/cancel` | admin | Sets `status = cancelled` |
| GET | `/api/v1/print-jobs/poll` | **station key** | Returns this station's `queued` jobs, marks them `sent` |
| POST | `/api/v1/print-jobs/{id}/ack` | **station key** | Body: `{"status": "printed"|"failed", "error": "..."}` |

## Print stations

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/stations` | admin | |
| POST | `/api/v1/stations` | admin | `connection_type`: `lan_escpos` or `usb_agent` |
| POST | `/api/v1/stations/{id}/pair` | admin | Generates a fresh API key, returned **once** in the response — only its hash is stored |
| DELETE | `/api/v1/stations/{id}` | admin | Hard delete — the row is removed and its print job history cascade-deletes with it. Returns 204. |
| GET | `/api/v1/stations/{id}/status` | admin | Includes `last_seen_at`, updated on every successful poll |

## Parsers (field-mapping profiles)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/parsers` | admin | |
| POST | `/api/v1/parsers` | admin | Creates a mapping profile (`profile_slug`, optional `match_subject_regex`) |
| PATCH / DELETE | `/api/v1/parsers/{id}` | admin | |
| POST | `/api/v1/parsers/{id}/fields` | admin | Adds a field extraction rule (regex/xpath + transform) |
| PATCH / DELETE | `/api/v1/parsers/{id}/fields/{field_id}` | admin | |
| POST | `/api/v1/parsers/{id}/test` | admin | Dry-run parse of pasted sample text — does not persist anything |

## Config (IMAP + auto-print + room assignment + receipt settings)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/config` | admin | Returns IMAP host/port/user/folders/poll interval and `imap_has_password` (bool) — the password itself is never returned. Also returns `auto_print_enabled`/`auto_print_station_id`, `room_auto_assign_enabled`, and the `receipt_*` layout fields |
| PATCH | `/api/v1/config` | admin | Partial update; `imap_password` is write-only — omit or send blank to leave the existing password unchanged. Encrypted at rest (Fernet, keyed from `SECRET_KEY`). Row is seeded from `backend/.env`'s `IMAP_*` on first access, then the DB is authoritative. `room_auto_assign_enabled` (default `false`) gates only the automatic-on-creation assignment path (manual creation and email ingestion) — the arrivals sheet and `assign-room`/`reassign-room` always work regardless of this setting |

## Audit log

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/audit-log` | admin | Filters: `actor`, `action`; returns most recent 500 entries |

## Health

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/healthz` | none | Liveness only |
| GET | `/readyz` | none | Executes `SELECT 1` against the database |

## Admin UI pages (server-rendered, not JSON)

`/login`, `/` (dashboard), `/reservations` (accepts `?q=` for the same
free-text search as the JSON API), `/reservations/{id}`,
`/reservations/sheet` (accepts `?date=YYYY-MM-DD`, default today — the
"arrivals sheet": one row per booked room for that check-in date, with
inline room-assignment + station dropdowns and a single "Assign &
print" button per row that does both in one action, backed by `POST
/reservations/{id}/assign-and-print`), `/print-jobs` (+
`/print-jobs/table` HTMX partial), `/stations`, `/parsers` (+
`/parsers/{id}`), `/rooms`, `/audit-log`, `/settings`, `/users`. These
use the same underlying data as the JSON API but return HTML, and some
accept form-encoded POSTs directly (e.g. `/reservations/{id}/print`,
`/stations`, `/parsers/{id}/test`) for HTMX interactions rather than
JSON bodies.
