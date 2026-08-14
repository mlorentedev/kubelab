#!/bin/sh
# Gitea idempotent bootstrap: admin user + Authelia OIDC provider.
#
# Ported from the postStart lifecycle hook that ran while Gitea lived on K3s
# (infra/k8s/base/services/gitea.yaml). Same env-var contract, so the script is
# unchanged in what it reads:
#   GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD, GITEA_ADMIN_EMAIL,
#   GITEA_OIDC_CLIENT_SECRET, GITEA_OIDC_DISCOVERY_URL
#
# Two deliberate differences from the K8s original:
#
#   1. The `admin` -> $GITEA_ADMIN_USER rename branch is gone. It rewrote
#      user/lower_name directly in gitea.db with sqlite3 to repair a specific
#      historical instance. The Beelink install is fresh, so that branch could
#      only ever fire on a database it was not written for.
#   2. It is invoked by Ansible via `docker exec` once the container reports
#      healthy, not by a container lifecycle hook. A postStart hook that fails is
#      easy to miss; a failed Ansible task stops the play.
#
# Idempotent by design: safe to re-run on every provision, which is how it runs.

set -eu

log() { echo "[gitea-bootstrap] $1"; }

# --- Wait for Gitea to answer its own API ---
i=0
while [ "$i" -lt 15 ]; do
  if wget -qO- http://localhost:3000/api/v1/version >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 2
done
if ! wget -qO- http://localhost:3000/api/v1/version >/dev/null 2>&1; then
  log "ERROR: Gitea not ready after 30s"
  exit 1
fi

# --- Admin user (idempotent) ---
# `gitea admin user list` prints a header row plus one row per user; the username
# is column 2. Matching the column rather than grepping the whole line avoids a
# false "exists" when the name appears in some other user's e-mail address.
if su git -c "gitea admin user list" 2>/dev/null \
  | awk 'NR > 1 {print $2}' | grep -qx "$GITEA_ADMIN_USER"; then
  log "Admin user '$GITEA_ADMIN_USER' exists"
else
  su git -c "gitea admin user create --admin \
    --username $GITEA_ADMIN_USER \
    --password $GITEA_ADMIN_PASSWORD \
    --email $GITEA_ADMIN_EMAIL \
    --must-change-password=false"
  log "Created admin user '$GITEA_ADMIN_USER'"
fi

# --- Authelia OIDC provider (idempotent) ---
if [ -z "${GITEA_OIDC_CLIENT_SECRET:-}" ] || [ -z "${GITEA_OIDC_DISCOVERY_URL:-}" ]; then
  log "ERROR: OIDC env vars unset. The K8s original skipped silently here, which"
  log "       is wrong for this deployment: SSO is a declared part of the service"
  log "       (the Authelia client registration and its argon2 hash both exist),"
  log "       so a missing secret is a broken deploy, not an optional feature."
  exit 1
fi

# `gitea admin auth update-oauth`, never delete+add: deleting an auth source with
# linked users breaks those linkages (see configure_oidc.py, which hit this).
AUTH_ID=$(su git -c "gitea admin auth list" 2>/dev/null \
  | grep -i authelia | awk '{print $1}' || true)

if [ -n "$AUTH_ID" ]; then
  su git -c "gitea admin auth update-oauth --id $AUTH_ID \
    --name authelia \
    --provider openidConnect \
    --key gitea \
    --secret $GITEA_OIDC_CLIENT_SECRET \
    --auto-discover-url $GITEA_OIDC_DISCOVERY_URL \
    --scopes openid,profile,email,groups"
  log "Updated OIDC provider (ID=$AUTH_ID)"
else
  su git -c "gitea admin auth add-oauth \
    --name authelia \
    --provider openidConnect \
    --key gitea \
    --secret $GITEA_OIDC_CLIENT_SECRET \
    --auto-discover-url $GITEA_OIDC_DISCOVERY_URL \
    --scopes openid,profile,email,groups"
  log "Created OIDC provider"
fi
