#!/usr/bin/env bash
# R2 — does the image's OpenSSH honour a key registered through Gitea's API for
#      the machine identity?
# R3 — does removing that key fail closed, and immediately?
#
# Both questions are about Gitea's behaviour, not about ace2's reachability
# (R1 settled that), so the git transport is attempted from wherever this runs.
# The throwaway private key therefore never lands on the shared node.
#
# CREDENTIAL HANDLING: the bot token is read from SOPS into a shell variable and
# reaches curl through `--config -` on STDIN. Not `-H`, which would put it in
# `ps` output for the life of each call; not a config file, which would put it on
# disk. `printf` is a shell builtin, so the pipe's writer is not a process
# either. It is never echoed. `set -x` must NOT be added to this script.
#
# The registered key is removed by an EXIT trap, so a failure mid-probe cannot
# leave a live credential on the bot account.
#
# Usage: bash specs/ANSIBLE-037-dev-node-gitea-access/r2_r3_key_lifecycle_probe.sh
set -uo pipefail

GITEA_API="${GITEA_API:-https://gitea.kubelab.live/api/v1}"
GITEA_SSH_HOST="${GITEA_SSH_HOST:-beelink.kubelab.internal}"
GITEA_SSH_PORT="${GITEA_SSH_PORT:-2222}"
SECRET_KEY="apps.services.core.gitea.bot_token"
SECRET_ENV="${SECRET_ENV:-prod}"
KEY_TITLE="ansible-037-r2-probe-$(date -u +%Y%m%dT%H%M%SZ)"

TMPDIR_PROBE="$(mktemp -d)"
chmod 700 "${TMPDIR_PROBE}"
KEY_ID=""

# api <curl-args...> — authenticated call with the token off the command line.
api() {
  printf 'header = "Authorization: token %s"\n' "${TOKEN}" \
    | curl -s --config - "$@"
}

cleanup() {
  if [ -n "${KEY_ID}" ]; then
    echo
    echo "--- cleanup: removing probe key id=${KEY_ID} ---"
    api -o /dev/null -w "DELETE /user/keys/${KEY_ID} -> %{http_code}\n" \
      -X DELETE "${GITEA_API}/user/keys/${KEY_ID}" \
      || echo "CLEANUP FAILED — remove the key titled '${KEY_TITLE}' by hand"
  fi
  rm -rf "${TMPDIR_PROBE}"
}
trap cleanup EXIT

ssh_probe() {
  # A successful git auth greets and exits non-zero (no shell is provided), so
  # the BANNER is the verdict, never the exit code.
  ssh -i "${TMPDIR_PROBE}/probe_key" -o IdentitiesOnly=yes -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new -T -p "${GITEA_SSH_PORT}" \
      "git@${GITEA_SSH_HOST}" 2>&1 | head -2
}

echo "=== R2/R3 key lifecycle probe — $(date -u +%FT%TZ) ==="
echo "api:    ${GITEA_API}"
echo "target: ${GITEA_SSH_HOST}:${GITEA_SSH_PORT}"
echo

TOKEN="$(poetry run toolkit secrets show "${SECRET_KEY}" --env "${SECRET_ENV}" 2>/dev/null)"
if [ -z "${TOKEN}" ]; then
  echo "FATAL: ${SECRET_KEY} is empty or unreadable in ${SECRET_ENV} SOPS."
  exit 1
fi
echo "token: read from ${SECRET_ENV} SOPS (${#TOKEN} chars, value not printed)"

echo
echo "--- [1/5] the token authenticates, and as whom ---"
# %-formatting, not an f-string: the f-string version needed escaped quotes
# inside a single-quoted shell argument, which bash passes through literally and
# python rejects. It cost nothing here (check [4] names the account anyway) but a
# broken diagnostic still reads as a measured negative.
api "${GITEA_API}/user" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("FAILED to parse /user response"); raise SystemExit(0)
print("login=%s  id=%s  is_admin=%s" % (d.get("login"), d.get("id"), d.get("is_admin")))'

ssh-keygen -t ed25519 -N "" -C "${KEY_TITLE}" -f "${TMPDIR_PROBE}/probe_key" >/dev/null 2>&1

echo
echo "--- [2/5] baseline: git transport BEFORE registering the key ---"
ssh_probe

echo
echo "--- [3/5] register the public half via POST /user/keys (R2) ---"
python3 -c '
import json, sys
title, path = sys.argv[1], sys.argv[2]
json.dump({"title": title, "key": open(path).read().strip(), "read_only": False}, sys.stdout)
' "${KEY_TITLE}" "${TMPDIR_PROBE}/probe_key.pub" > "${TMPDIR_PROBE}/key.json"

KEY_ID="$(api -X POST -H "Content-Type: application/json" \
  -d "@${TMPDIR_PROBE}/key.json" "${GITEA_API}/user/keys" \
  | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
if isinstance(d, dict) and d.get("id"):
    print(d["id"])')"
echo "registered key id=${KEY_ID:-<NONE — registration failed>}  title=${KEY_TITLE}"

echo
echo "--- [4/5] git transport WITH the registered key (R2 verdict) ---"
ssh_probe

echo
echo "--- [5/5] revoke, then retry immediately (R3 verdict) ---"
if [ -n "${KEY_ID}" ]; then
  t0=$(date +%s)
  api -o /dev/null -w "DELETE /user/keys/${KEY_ID} -> %{http_code}\n" \
    -X DELETE "${GITEA_API}/user/keys/${KEY_ID}"
  revoked_id="${KEY_ID}"
  KEY_ID=""   # deleted; stop the trap from double-deleting
  ssh_probe
  t1=$(date +%s)
  echo "(retry ran $((t1 - t0))s after the DELETE; revoked id was ${revoked_id})"
else
  echo "SKIPPED — nothing was registered in [3], so there is nothing to revoke."
fi

echo
echo "=== how to read this ==="
echo "R2 passes when [2] is 'Permission denied' and [4] greets as the bot."
echo "R3 passes when [5] is 'Permission denied' again, with no wait needed."
echo "If [5] still greets, authorized_keys is cached: AC4's test must wait for"
echo "that cache explicitly rather than racing it."
