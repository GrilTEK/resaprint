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

## Reservations

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/reservations` | admin | Filters: `status_filter`, `source_channel`, `checkin_from`, `checkin_to` |
| GET | `/api/v1/reservations/{id}` | admin | |
| POST | `/api/v1/reservations` | admin | Manual creation, `status` forced to `manual` |
| PATCH | `/api/v1/reservations/{id}` | admin | Partial update; logged to audit log as `reservation.manual_override` |
| DELETE | `/api/v1/reservations/{id}` | admin | Soft-cancel (`status = cancelled`), does not delete the row |
| POST | `/api/v1/reservations/{id}/print` | admin | Body: `{"station_id": <int>}`. Renders a receipt and enqueues (and, for LAN stations, immediately sends) a print job |

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
| DELETE | `/api/v1/stations/{id}` | admin | Deactivates and revokes the station's API key |
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

`/login`, `/` (dashboard), `/reservations`, `/reservations/{id}`,
`/print-jobs` (+ `/print-jobs/table` HTMX partial), `/stations`,
`/parsers` (+ `/parsers/{id}`), `/audit-log`. These use the same
underlying data as the JSON API but return HTML, and some accept
form-encoded POSTs directly (e.g. `/reservations/{id}/print`,
`/stations`, `/parsers/{id}/test`) for HTMX interactions rather than
JSON bodies.
