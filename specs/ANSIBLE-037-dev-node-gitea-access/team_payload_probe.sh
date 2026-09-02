#!/usr/bin/env bash
# TOOL-035 Risk 1 residual — what payload makes `POST /orgs/<org>/teams` produce a
# team that actually reports `permission: write` on Gitea 1.25?
#
# Two measurements bracket this, both real and both wrong to generalise from:
#   2026-08-27: `units` list + `permission: write`  -> created, read back as
#               `permission: none`. `create_team` responded by dropping `units`.
#   2026-09-02: no `units` at all                   -> HTTP 500,
#               "units permission should not be empty". The drop is now fatal.
# So the answer is neither "send units" nor "omit units" -- it is `units_map`,
# which carries a permission PER unit instead of leaving them unset. This script
# is what turns that reading into a measurement.
#
# SANDBOX: the `kubelab` organization, which ADR-065 D3 declares while holding
# nothing. Every team this creates is deleted on the way out, including on
# failure, via the EXIT trap. Teams are created and destroyed, never repos.
#
# CREDENTIAL HANDLING: the admin token reaches curl through `--config` on stdin,
# never `-H` (world-readable in `ps`) and never a file. Never echoed.
# `set -x` must NOT be added -- it would print the config heredoc.
#
# Usage: bash specs/ANSIBLE-037-dev-node-gitea-access/team_payload_probe.sh
set -uo pipefail

GITEA_API="${GITEA_API:-https://gitea.kubelab.live/api/v1}"
ORG="${ORG:-kubelab}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CREATED=()

api() {
  printf 'header = "Authorization: token %s"\n' "${TOKEN}" | curl -s --config - "$@"
}

cleanup() {
  for name in "${CREATED[@]:-}"; do
    [ -z "${name}" ] && continue
    local id
    id="$(api "${GITEA_API}/orgs/${ORG}/teams" | python3 -c '
import json,sys
try: teams = json.load(sys.stdin)
except Exception: raise SystemExit(0)
for t in teams if isinstance(teams, list) else []:
    if t.get("name") == sys.argv[1]: print(t["id"]); break' "${name}")"
    [ -n "${id}" ] && api -o /dev/null -X DELETE "${GITEA_API}/teams/${id}" \
      && echo "cleaned up: ${name}"
  done
}
trap cleanup EXIT

TOKEN="$(cd "${REPO_ROOT}" && poetry run toolkit secrets show \
  apps.services.core.gitea.admin_token --env prod 2>/dev/null)"
if [ -z "${TOKEN}" ]; then
  echo "FATAL: the admin token is unreadable in prod SOPS."
  exit 1
fi

# $1 = label, $2 = JSON body. Prints the created team's EFFECTIVE permission,
# read back rather than taken from the create response -- the create response is
# exactly the artefact the 2026-08-27 measurement showed to be unreliable.
try_payload() {
  local label="$1" body="$2" name
  name="$(printf '%s' "${body}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
  CREATED+=("${name}")
  local created
  created="$(api -X POST -H 'Content-Type: application/json' \
    -d "${body}" "${GITEA_API}/orgs/${ORG}/teams")"
  if printf '%s' "${created}" | grep -q '"message"'; then
    echo "  ${label}: REFUSED -> $(printf '%s' "${created}" | head -c 160)"
    return
  fi
  local effective
  effective="$(api "${GITEA_API}/orgs/${ORG}/teams" | python3 -c '
import json,sys
for t in json.load(sys.stdin):
    if t.get("name") == sys.argv[1]:
        print(t.get("permission")); break' "${name}")"
  if [ "${effective}" = "write" ]; then
    echo "  ${label}: OK -> reads back as permission=${effective}"
  else
    echo "  ${label}: WRONG -> reads back as permission=${effective} (wanted write)"
  fi
}

UNITS='"repo.code":"write","repo.issues":"write","repo.pulls":"write","repo.releases":"write","repo.wiki":"write","repo.projects":"write","repo.packages":"write"'

echo "=== team payload probe — $(date -u +%FT%TZ) ==="
echo "org: ${ORG} (declared empty by ADR-065 D3)"
echo

echo "--- [1/3] current behaviour: permission only, no units (what create_team sends today) ---"
try_payload "permission-only" '{"name":"probe-permission-only","permission":"write"}'

echo
echo "--- [2/3] the 2026-08-27 shape: units list + coarse permission ---"
try_payload "units-list" '{"name":"probe-units-list","permission":"write","units":["repo.code","repo.issues","repo.pulls"]}'

echo
echo "--- [3/3] units_map: a permission PER unit ---"
try_payload "units-map" "{\"name\":\"probe-units-map\",\"permission\":\"write\",\"units_map\":{${UNITS}}}"

echo
echo "=== verdict ==="
echo "Whichever line above reads OK is the payload create_team must send."
