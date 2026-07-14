#!/usr/bin/env bash
#
# One-command ResaPrint installer for Proxmox VE.
#
# griltek/resaprint is a public repo, so no token is needed. Run this
# ON THE PROXMOX HOST as root:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/GrilTEK/resaprint/main/proxmox/install-resaprint-lxc.sh)"
#
# It creates a new unprivileged Debian 12 LXC container, installs Docker
# inside it, clones this repo, generates a secure .env (SECRET_KEY and
# POSTGRES_PASSWORD are random; IMAP_* is left for you to fill in), and
# starts the full stack (db, migrate, api, ingest-worker) via
# `docker compose up -d --build`.
#
# Override any default by exporting the variable before running, e.g.:
#   CTID=150 MEMORY_MB=4096 bash -c "$(curl -fsSL .../install-resaprint-lxc.sh)"
#
# If the repo is ever made private again, set GH_TOKEN (a fine-grained
# PAT with Contents: Read-only) and pass it as an Authorization header
# to the outer curl too — see docs/BACKEND.md.
#
# This script does NOT configure Nginx Proxy Manager or create the first
# admin PIN — both are one-off manual steps printed at the end (also
# documented in docs/BACKEND.md).

set -euo pipefail

# ---------- defaults (override via env vars) ----------
CTID="${CTID:-}"
HOSTNAME="${HOSTNAME:-resaprint}"
STORAGE="${STORAGE:-}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
BRIDGE="${BRIDGE:-vmbr0}"
IP_CONFIG="${IP_CONFIG:-dhcp}"           # or e.g. "10.0.0.50/24,gw=10.0.0.1"
DISK_SIZE_GB="${DISK_SIZE_GB:-8}"
MEMORY_MB="${MEMORY_MB:-2048}"
CORES="${CORES:-2}"
TEMPLATE_PATTERN="${TEMPLATE_PATTERN:-debian-12-standard}"
REPO_URL="${REPO_URL:-https://github.com/GrilTEK/resaprint.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
GH_TOKEN="${GH_TOKEN:-}"

log() { echo -e "\033[1;32m[resaprint]\033[0m $*"; }
err() { echo -e "\033[1;31m[resaprint]\033[0m $*" >&2; }

# GH_TOKEN is optional now that the repo is public — only needed again
# if the repo is made private in the future.
AUTH_REPO_URL="$REPO_URL"
if [[ -n "$GH_TOKEN" ]]; then
  AUTH_REPO_URL="$(echo "$REPO_URL" | sed "s|https://|https://x-access-token:${GH_TOKEN}@|")"
fi

if [[ $EUID -ne 0 ]]; then
  err "Run this as root on the Proxmox host."
  exit 1
fi

if ! command -v pct >/dev/null 2>&1; then
  err "pct not found — this script must run on a Proxmox VE host, not inside a container/VM."
  exit 1
fi

# ---------- pick a free container ID ----------
if [[ -z "$CTID" ]]; then
  CTID="$(pvesh get /cluster/nextid)"
fi
log "Using container ID: $CTID"

if pct status "$CTID" >/dev/null 2>&1; then
  err "Container $CTID already exists. Set CTID to a free ID and re-run."
  exit 1
fi

# ---------- pick a storage pool for the rootfs if not given ----------
if [[ -z "$STORAGE" ]]; then
  STORAGE="$(pvesm status -content rootdir | awk 'NR==2{print $1}')"
  if [[ -z "$STORAGE" ]]; then
    err "Could not auto-detect a storage pool with 'rootdir' content. Set STORAGE=<pool> and re-run."
    exit 1
  fi
fi
log "Using storage pool: $STORAGE"

# ---------- ensure the LXC template is downloaded ----------
log "Refreshing template list..."
pveam update >/dev/null 2>&1 || true

TEMPLATE="$(pveam available --section system | awk -v p="$TEMPLATE_PATTERN" '$0 ~ p {print $2}' | sort -V | tail -1)"
if [[ -z "$TEMPLATE" ]]; then
  err "Could not find a template matching '$TEMPLATE_PATTERN'. Run 'pveam available' to see options and set TEMPLATE_PATTERN."
  exit 1
fi

if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  log "Downloading template $TEMPLATE to $TEMPLATE_STORAGE..."
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

# ---------- create the container ----------
log "Creating LXC $CTID ($HOSTNAME)..."
pct create "$CTID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" \
  --memory "$MEMORY_MB" \
  --swap 512 \
  --rootfs "${STORAGE}:${DISK_SIZE_GB}" \
  --net0 "name=eth0,bridge=${BRIDGE},ip=${IP_CONFIG}" \
  --unprivileged 1 \
  --features "nesting=1,keyctl=1" \
  --onboot 1 \
  --start 0

log "Starting container..."
pct start "$CTID"

log "Waiting for network..."
for _ in $(seq 1 30); do
  if pct exec "$CTID" -- getent hosts github.com >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

CTIP="$(pct exec "$CTID" -- hostname -I | awk '{print $1}')"
log "Container network IP: ${CTIP:-unknown}"

# ---------- install Docker inside the container ----------
log "Installing Docker inside the container..."
pct exec "$CTID" -- bash -c "curl -fsSL https://get.docker.com | sh"

# ---------- clone the repo and configure ----------
log "Cloning ResaPrint ($REPO_BRANCH)..."
pct exec "$CTID" -- bash -c "git clone --branch '$REPO_BRANCH' --depth 1 '$AUTH_REPO_URL' /opt/resaprint"
# Drop the token from the remote URL once cloned so it doesn't linger
# in .git/config inside the container.
pct exec "$CTID" -- bash -c "cd /opt/resaprint && git remote set-url origin '$REPO_URL'"

SECRET_KEY="$(openssl rand -hex 32)"
PG_PASSWORD="$(openssl rand -hex 16)"

log "Generating backend/.env with a random SECRET_KEY and POSTGRES_PASSWORD..."
pct exec "$CTID" -- bash -c "
  cd /opt/resaprint/backend
  cp .env.example .env
  sed -i 's|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|' .env
  sed -i 's|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASSWORD}|' .env
  sed -i \"s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://resaprint:${PG_PASSWORD}@db:5432/resaprint|\" .env
"

log "Starting ResaPrint (docker compose up -d --build)... this can take a few minutes on first run."
pct exec "$CTID" -- bash -c "cd /opt/resaprint && docker compose up -d --build"

log "Waiting for the API to come up..."
for _ in $(seq 1 30); do
  if pct exec "$CTID" -- bash -c "curl -fsS http://localhost:8000/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

cat <<EOF

============================================================
 ResaPrint LXC $CTID is up.
============================================================

 Container IP:   ${CTIP:-<unknown, run 'pct exec $CTID -- hostname -I'>}
 Backend port:   8000  (http://${CTIP:-<container-ip>}:8000)

 Still to do:

 1. Edit IMAP settings (mailbox for incoming reservation emails):
      pct exec $CTID -- nano /opt/resaprint/backend/.env
    then restart the affected services:
      pct exec $CTID -- bash -c "cd /opt/resaprint && docker compose up -d --build ingest-worker api"

 2. Point Nginx Proxy Manager at ${CTIP:-<container-ip>}:8000
    (not managed by this script or the repo).

 3. Create the first admin PIN:
      pct exec $CTID -- bash -c "docker compose -f /opt/resaprint/docker-compose.yml exec api python -c \"
from passlib.context import CryptContext
print(CryptContext(schemes=['bcrypt']).hash('1234'))
\""
    then insert it:
      pct exec $CTID -- bash -c "docker compose -f /opt/resaprint/docker-compose.yml exec db psql -U resaprint -d resaprint -c \"INSERT INTO admin_pins (label, pin_hash) VALUES ('Recepcija', '<hash>');\""

 Full docs: https://github.com/GrilTEK/resaprint/blob/main/docs/BACKEND.md
============================================================
EOF
