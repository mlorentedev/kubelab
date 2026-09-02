#!/usr/bin/env bash
# AC4 — removing the node's key from Gitea makes the access fail, and
#       re-provisioning restores it.
#
# BOTH halves, captured. A credential that works proves only half the claim:
# AUTH-004 AC5 recorded a run where every call returned 403 because the account
# was in a rejected state, so its "refused" half proved nothing — an
# account-level rejection and a scope-level one are the same status code.
#
# Codified rather than performed: the drill is the artifact, so it can be re-run
# after any change to the role instead of being remembered as a sequence.
#
# R3 measured revocation as effective within one second, so this deliberately
# does NOT sleep between the DELETE and the retry. If that ever changes, the
# fix is an explicit wait here, not a longer one everywhere.
#
# CREDENTIAL HANDLING: the bot token reaches curl through `--config` on stdin,
# never `-H` (which is world-readable in ps) and never a file. Never echoed.
# `set -x` must NOT be added.
#
# Usage: bash specs/ANSIBLE-037-dev-node-gitea-access/ac4_revocation_probe.sh
set -uo pipefail

ACE2="${ACE2_HOST:-ace2}"
GITEA_API="${GITEA_API:-https://gitea.kubelab.live/api/v1}"
GITEA_SSH_HOST="${GITEA_SSH_HOST:-beelink.kubelab.internal}"
GITEA_SSH_PORT="${GITEA_SSH_PORT:-2222}"
KEY_TITLE="${KEY_TITLE:-kubelab-${ACE2}-dev-node}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

api() {
  printf 'header = "Authorization: token %s"\n' "${TOKEN}" | curl -s --config - "$@"
}

# The node's own key, used from the node. The banner is the verdict: a
# successful git auth greets and exits non-zero, since no shell is provided.
node_access() {
  ssh -o BatchMode=yes "${ACE2}" \
    "ssh -o BatchMode=yes -T -p ${GITEA_SSH_PORT} git@${GITEA_SSH_HOST} 2>&1 | head -1"
}

echo "=== AC4 revocation drill — $(date -u +%FT%TZ) ==="
echo "node: ${ACE2}   key title: ${KEY_TITLE}"
echo

TOKEN="$(cd "${REPO_ROOT}" && poetry run toolkit secrets show \
  apps.services.core.gitea.bot_token --env prod 2>/dev/null)"
if [ -z "${TOKEN}" ]; then
  echo "FATAL: the bot token is unreadable in prod SOPS."
  exit 1
fi

echo "--- [1/5] baseline: the node's access works ---"
before="$(node_access)"
echo "${before}"
case "${before}" in
  *"successfully authenticated"*) echo "OK — provisioned access is live" ;;
  *) echo "FAIL — no working access to revoke; provision the node first."; exit 1 ;;
esac

echo
echo "--- [2/5] find this node's key by title ---"
KEY_ID="$(api "${GITEA_API}/user/keys" | python3 -c '
import json, sys
title = sys.argv[1]
try:
    keys = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
for k in keys if isinstance(keys, list) else []:
    if k.get("title") == title:
        print(k["id"]); break' "${KEY_TITLE}")"
if [ -z "${KEY_ID}" ]; then
  echo "FAIL — no key titled '${KEY_TITLE}' on the machine account."
  exit 1
fi
echo "key id=${KEY_ID}"

echo
echo "--- [3/5] revoke it, and retry with no wait (R3: effective in <1s) ---"
api -o /dev/null -w "DELETE /user/keys/${KEY_ID} -> %{http_code}\n" \
  -X DELETE "${GITEA_API}/user/keys/${KEY_ID}"
after_revoke="$(node_access)"
echo "${after_revoke}"
case "${after_revoke}" in
  *"Permission denied"*) echo "OK — access failed closed" ;;
  *) echo "FAIL — access survived revocation. Fail-closed is not holding."; exit 1 ;;
esac

echo
echo "--- [4/5] re-provision to restore it ---"
# The role re-registers because its idempotence key is the KEY MATERIAL: the
# node's keypair still exists, the account no longer lists it, so the POST runs.
(cd "${REPO_ROOT}" && make provision NODE="${ACE2}" ENV=staging TAGS=dev_node) \
  | tail -5

echo
echo "--- [5/5] access is restored ---"
restored="$(node_access)"
echo "${restored}"
case "${restored}" in
  *"successfully authenticated"*) echo "PASS — both halves demonstrated" ;;
  *) echo "FAIL — re-provisioning did not restore access."; exit 1 ;;
esac
