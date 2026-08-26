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
#
# ANSIBLE-054 (#1400): idempotent in EFFECT is not idempotent in REPORT, and the
# difference leaks. `update-oauth` was called unconditionally and its `Updated`
# line logged unconditionally, so the Ansible guard below
#
#     changed_when: "'Created' in stdout or 'Updated' in stdout"
#     notify: Restart gitea
#
# fired on every provision and bounced the forge under whoever was using it.
# The write stays unconditional — it still reconciles anything changed in Gitea
# directly — and only the announcement is conditional now, keyed on a marker
# recording the hash of the configuration last written successfully.
#
# Removing the restart instead would be the defect #1352 repaired: `update-oauth`
# writes SQLite while the running web process keeps the auth source it parsed at
# startup, so a provision without the restart leaves Gitea serving the OLD
# secret while reporting success. Fix the report, never the restart.

set -eu

log() { echo "[gitea-bootstrap] $1"; }

# --- Wait for Gitea to answer ---
# SEC-GITEA-001 (#1389). This probed /api/v1/version, which REQUIRE_SIGNIN_VIEW
# now refuses with 403 to an anonymous caller — and this script is anonymous, it
# runs before any credential exists. The endpoint comes from `health_path` in
# common.yaml, injected as GITEA_HEALTH_PATH by the compose template.
#
# This file is `files/`, not `templates/`, so the value arrives as an env var
# rather than being interpolated. The default below is a fallback for a
# re-imaged node whose compose predates the variable, NOT a second declaration:
# if it ever disagrees with common.yaml, common.yaml is right.
HEALTH_PATH="${GITEA_HEALTH_PATH:-/api/healthz}"

i=0
while [ "$i" -lt 15 ]; do
  if wget -qO- "http://localhost:3000${HEALTH_PATH}" >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 2
done
if ! wget -qO- "http://localhost:3000${HEALTH_PATH}" >/dev/null 2>&1; then
  log "ERROR: Gitea not ready after 30s (probed ${HEALTH_PATH})"
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

OIDC_SCOPES="openid,profile,email,groups"

# Where the last successfully-written configuration is fingerprinted. On /data,
# so it survives container recreation the way the database it describes does.
# Overridable for tests, same shape as GITEA_HEALTH_PATH above: if the default
# ever disagrees with the compose volume, the volume is right.
OIDC_STATE="${GITEA_BOOTSTRAP_STATE:-/data/gitea/.kubelab-oidc-bootstrap.sha256}"

# The client secret cannot be read back out of Gitea, so "has anything changed"
# is not answerable from the live instance — only from what this script last
# wrote. Everything that goes into the call goes into the hash, so a change to
# the discovery URL or the scopes counts as much as a rotated secret.
#
# Known limitation, stated rather than discovered later: a secret changed in
# Gitea directly is invisible here. The unconditional write below is what covers
# that case, which is the reason it stays unconditional.
# Each field is length-prefixed rather than merely separated. A bare separator
# is ambiguous: any character chosen as the delimiter can in principle occur
# inside a field, and two different configurations would then hash the same —
# which in this script means a rotated secret announcing no change, the exact
# lying report the whole ticket exists to remove. Length-prefixing is injective
# whatever the fields contain, so the question stops depending on the alphabet
# the secret generator happens to use. Raised in review of #1421.
OIDC_DESIRED=$(
  for _field in "authelia" "openidConnect" "gitea" \
    "$GITEA_OIDC_CLIENT_SECRET" "$GITEA_OIDC_DISCOVERY_URL" "$OIDC_SCOPES"; do
    printf '%s:%s|' "${#_field}" "$_field"
  done | sha256sum | awk '{print $1}'
)
OIDC_RECORDED=$(cat "$OIDC_STATE" 2>/dev/null || true)

# Written only after the call it describes returns 0. Recording first would make
# every later run report converged over a configuration Gitea never received —
# a false green that outlives the run that created it.
record_oidc_state() {
  printf '%s\n' "$OIDC_DESIRED" > "$OIDC_STATE"
  chmod 600 "$OIDC_STATE"
}

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
    --scopes $OIDC_SCOPES"
  if [ "$OIDC_DESIRED" = "$OIDC_RECORDED" ]; then
    # Neither "Created" nor "Updated": the words the Ansible guard matches on.
    log "OIDC provider already matches recorded state (ID=$AUTH_ID)"
  else
    record_oidc_state
    log "Updated OIDC provider (ID=$AUTH_ID)"
  fi
else
  su git -c "gitea admin auth add-oauth \
    --name authelia \
    --provider openidConnect \
    --key gitea \
    --secret $GITEA_OIDC_CLIENT_SECRET \
    --auto-discover-url $GITEA_OIDC_DISCOVERY_URL \
    --scopes $OIDC_SCOPES"
  record_oidc_state
  log "Created OIDC provider"
fi
