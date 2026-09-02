#!/usr/bin/env bash
# TOOL-035 Risk 1 residual, part 2 — does `permission: none` actually mean the
# team grants nothing?
#
# `team_payload_probe.sh` measured all three payload shapes and none produced a
# team reading back as `permission: write`: the coarse field is REFUSED when
# empty and `none` when units carry their own modes. That leaves two readings,
# and they demand opposite fixes:
#
#   (a) the team really grants nothing -> the payload is still wrong
#   (b) `permission` is the team's COARSE access mode, which Gitea sets to `none`
#       precisely BECAUSE the grant now lives per-unit -> the payload is right and
#       `ensure_team`'s assertion is reading the wrong field
#
# A field cannot settle this; only a consequence can. So: build the team the
# reconciler would build, put the bot in it, and have THE BOT try to create a
# repository in that organization. 201 means (b) and the assertion is the defect.
# 403 means (a) and the payload is.
#
# This is the same discipline that caught the token scope an hour ago, applied to
# the same failure shape: a status that looks authoritative while answering a
# different question than the one asked.
#
# SANDBOX: the `kubelab` organization (empty by ADR-065 D3). The team AND any
# repository this creates are removed by the EXIT trap, on success and failure.
#
# CREDENTIAL HANDLING: both tokens reach curl through `--config` on stdin, never
# `-H` and never a file. Never echoed. `set -x` must NOT be added.
#
# Usage: bash specs/ANSIBLE-037-dev-node-gitea-access/team_consequence_probe.sh
set -uo pipefail

GITEA_API="${GITEA_API:-https://gitea.kubelab.live/api/v1}"
ORG="${ORG:-kubelab}"
TEAM="probe-consequence"
REPO="probe-consequence-repo"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEAM_ID=""

as_admin() { printf 'header = "Authorization: token %s"\n' "${ADMIN}" | curl -s --config - "$@"; }
as_bot()   { printf 'header = "Authorization: token %s"\n' "${BOT}"   | curl -s --config - "$@"; }
# Basic auth, because organization OWNERSHIP is not expressible as a token scope
# -- see the note in cleanup(). `--config` keeps the password off argv exactly as
# the token forms do.
as_owner() { printf 'user = "%s:%s"\n' "${OWNER_USER}" "${OWNER_PASS}" | curl -s --config - "$@"; }

cleanup() {
  # The repository delete needs the superadmin's PASSWORD, not either token, and
  # the reason is worth recording: deleting a repository requires ownership of
  # the organization, which neither token has. The admin token carries
  # `read:repository` and the bot's team grants units, not ownership -- both
  # return 403. Measured after the first run of this script left
  # `kubelab/probe-consequence-repo` behind while PRINTING "cleaned up", because
  # the DELETE's status was discarded. A cleanup that cannot fail loudly is not a
  # cleanup; the status is now checked and reported.
  local rc
  rc="$(as_owner -o /dev/null -w '%{http_code}' -X DELETE "${GITEA_API}/repos/${ORG}/${REPO}")"
  echo "cleanup: DELETE repo ${ORG}/${REPO} -> ${rc}"
  if [ -n "${TEAM_ID}" ]; then
    rc="$(as_admin -o /dev/null -w '%{http_code}' -X DELETE "${GITEA_API}/teams/${TEAM_ID}")"
    echo "cleanup: DELETE team ${TEAM} -> ${rc}"
  fi
  case "${rc}" in 20*) ;; *) echo "  WARNING: something was left behind on the forge — check ${ORG}" ;; esac
}
trap cleanup EXIT

cd "${REPO_ROOT}" || exit 1
ADMIN="$(poetry run toolkit secrets show apps.services.core.gitea.admin_token --env prod 2>/dev/null)"
BOT="$(poetry run toolkit secrets show apps.services.core.gitea.bot_token --env prod 2>/dev/null)"
OWNER_PASS="$(poetry run toolkit secrets show apps.services.core.gitea.admin_password --env prod 2>/dev/null)"
read -r BOT_USER OWNER_USER <<<"$(python3 -c '
import yaml
i = yaml.safe_load(open("infra/config/values/common.yaml"))["apps"]["auth"]["identities"]
print(i["machine"], i["superadmin"])')"
if [ -z "${ADMIN}" ] || [ -z "${BOT}" ] || [ -z "${OWNER_PASS}" ]; then
  echo "FATAL: a prod Gitea credential is unreadable."
  exit 1
fi

UNITS='"repo.code":"write","repo.issues":"write","repo.pulls":"write","repo.releases":"write","repo.wiki":"write","repo.projects":"write","repo.packages":"write"'

echo "=== team consequence probe — $(date -u +%FT%TZ) ==="
echo "org: ${ORG}   bot identity (SSOT): ${BOT_USER}"
echo

echo "--- [1/4] admin creates the team with units_map ---"
created="$(as_admin -X POST -H 'Content-Type: application/json' \
  -d "{\"name\":\"${TEAM}\",\"permission\":\"write\",\"can_create_org_repo\":true,\"units_map\":{${UNITS}}}" \
  "${GITEA_API}/orgs/${ORG}/teams")"
TEAM_ID="$(printf '%s' "${created}" | python3 -c '
import json,sys
try: print(json.load(sys.stdin).get("id",""))
except Exception: print("")')"
if [ -z "${TEAM_ID}" ]; then
  echo "FAIL — team not created: $(printf '%s' "${created}" | head -c 200)"
  exit 1
fi
# %-formatting, not an f-string: inside a single-quoted `python3 -c '...'` the
# double quotes are literal and escaping them is a syntax error, not a string.
# Cost the first run of this script its most informative line.
printf '%s' "${created}" | python3 -c '
import json, sys
t = json.load(sys.stdin)
print("  team id=%s  coarse permission=%r" % (t.get("id"), t.get("permission")))
print("  units_map as stored: %s" % (t.get("units_map"),))'

echo
echo "--- [2/4] admin adds the bot to it ---"
code="$(as_admin -o /dev/null -w '%{http_code}' -X PUT "${GITEA_API}/teams/${TEAM_ID}/members/${BOT_USER}")"
echo "  PUT /teams/${TEAM_ID}/members/${BOT_USER} -> ${code}"

echo
echo "--- [3/4] THE BOT tries to create a repository in that org ---"
body="$(as_bot -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d "{\"name\":\"${REPO}\",\"private\":true}" "${GITEA_API}/orgs/${ORG}/repos")"
status="$(printf '%s' "${body}" | tail -1)"
echo "  POST /orgs/${ORG}/repos -> ${status}"
printf '%s' "${body}" | head -n -1 | head -c 220; echo

echo
echo "--- [4/4] verdict ---"
case "${status}" in
  201)
    echo "READING (b): the team GRANTS WRITE despite reporting permission=none."
    echo "  => the units_map payload is correct, and ensure_team's assertion is"
    echo "     reading the team's COARSE access mode, which Gitea sets to none"
    echo "     exactly because the grant moved per-unit. The fix is in the check,"
    echo "     not in the payload: assert by units_map, or by this consequence." ;;
  403)
    # A 403 is TWO different answers and the status code cannot tell them apart
    # -- exactly what AUTH-004 AC5 recorded, and what the first run of this very
    # script then walked into: it read a scope refusal as a team-permission
    # refusal and reported the payload wrong when the payload was never reached.
    # Gitea puts the distinguishing text in the BODY, so the body is what decides.
    if printf '%s' "${body}" | grep -q 'required scope'; then
      echo "INCONCLUSIVE — refused on TOKEN SCOPE, never on the team."
      printf '%s' "${body}" | grep -o 'required=\[[^]]*\][^"]*' | sed 's/^/  /'
      echo "  => the bot's LIVE token predates the scope it now needs. The declared"
      echo "     grant in common.yaml can be correct while the minted credential is"
      echo "     old, because Gitea cannot edit a token's scopes after minting."
      echo "     Fix: make gitea-rotate-token TOKEN=bot ENV=prod APPLY=1, then"
      echo "     make provision NODE=bee ENV=prod TAGS=gitea, then re-run this."
    else
      echo "READING (a): the team really grants nothing."
      echo "  => the payload is still wrong; ensure_team's assertion was right to"
      echo "     refuse and the units_map shape is not what Gitea 1.25 wants."
    fi ;;
  *)
    echo "INCONCLUSIVE — status ${status} is neither 201 nor 403. Read the body"
    echo "  above before concluding anything; a 401/422 is about the request, not"
    echo "  about the team's grant." ;;
esac
