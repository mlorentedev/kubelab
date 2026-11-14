#!/usr/bin/env bash
# AC3: the Gitea host key is pinned by the role, so a first connection
#      produces no interactive prompt, demonstrated on a node whose
#      `known_hosts` was cleared.
#
# Both halves are captured, for the reason AC4 gives. With the entry removed,
# a strict connection must REFUSE (otherwise something other than the role is
# supplying trust). After re-provisioning, the same strict, non-interactive
# connection must succeed. BatchMode turns any prompt into a failure, so a
# greeting proves there was no prompt.
#
# Only the forge's own entry is removed (`ssh-keygen -R <host>`), not the
# whole file. The role's ssh_config already sets `StrictHostKeyChecking yes`
# for the forge host; it is repeated here so that a later change to the role
# cannot make the refusal half pass vacuously.
#
# No credential is handled: the node uses its own key, as in AC4.
#
# Usage: bash specs/ANSIBLE-037-dev-node-gitea-access/ac3_host_key_probe.sh
set -uo pipefail

ACE2="${ACE2_HOST:-ace2}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

gitea() {
  (cd "${REPO_ROOT}" && python3 -c "import sys, yaml; print(yaml.safe_load(open('infra/config/values/common.yaml'))['apps']['services']['core']['gitea'][sys.argv[1]])" "$1")
}
identity() {
  (cd "${REPO_ROOT}" && python3 -c "import sys, yaml; print(yaml.safe_load(open('infra/config/values/common.yaml'))['apps']['auth']['identities'][sys.argv[1]])" "$1")
}

GITEA_SSH_HOST="${GITEA_SSH_HOST:-$(gitea ssh_host)}"
GITEA_SSH_PORT="${GITEA_SSH_PORT:-$(gitea ssh_port)}"
ENTRY="[${GITEA_SSH_HOST}]:${GITEA_SSH_PORT}"
AGENT="$(identity agent)"

strict_access() {
  ssh -o BatchMode=yes "${ACE2}" \
    "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -T -p ${GITEA_SSH_PORT} git@${GITEA_SSH_HOST} 2>&1 | head -1"
}
pinned_count() {
  ssh -o BatchMode=yes "${ACE2}" "ssh-keygen -F '${ENTRY}' 2>/dev/null | grep -vc '^#'"
}

echo "=== AC3 host-key pinning drill — $(date -u +%FT%TZ) ==="
echo "node: ${ACE2}   entry: ${ENTRY}"
echo

echo "--- [1/5] baseline: the entry is pinned and a strict connection works ---"
echo "pinned lines: $(pinned_count)"
before="$(strict_access)"
echo "${before}"
case "${before}" in
  *"Hi there, ${AGENT}!"*) echo "OK" ;;
  *) echo "FAIL — no working baseline; provision the node first."; exit 1 ;;
esac

echo
echo "--- [2/5] remove the forge's entry from known_hosts ---"
ssh -o BatchMode=yes "${ACE2}" "ssh-keygen -R '${ENTRY}' >/dev/null 2>&1"
left="$(pinned_count)"
echo "pinned lines: ${left}"
[ "${left}" = "0" ] || { echo "FAIL — the entry is still present."; exit 1; }

echo
echo "--- [3/5] a strict connection now refuses ---"
cleared="$(strict_access)"
echo "${cleared}"
case "${cleared}" in
  *"Host key verification failed"*|*"No "*"host key is known"*) echo "OK — nothing else supplies trust" ;;
  *) echo "FAIL — the connection did not refuse; trust comes from somewhere other than the role."; exit 1 ;;
esac

echo
echo "--- [4/5] re-provision to restore the pin ---"
out="$(cd "${REPO_ROOT}" && make provision NODE="${ACE2}" ENV=staging TAGS=gitea 2>&1)"
rc=$?
printf '%s\n' "${out}" | tail -5
if [ "${rc}" -ne 0 ]; then
  echo "FAIL — the provision run failed (exit ${rc}); the pin is NOT restored."
  echo "Fix the cause, then: make provision NODE=${ACE2} ENV=staging TAGS=gitea"
  exit 1
fi

echo
echo "--- [5/5] a strict, non-interactive first connection succeeds ---"
echo "pinned lines: $(pinned_count)"
restored="$(strict_access)"
echo "${restored}"
case "${restored}" in
  *"Hi there, ${AGENT}!"*) echo "PASS — both halves demonstrated" ;;
  *) echo "FAIL — re-provisioning did not restore a prompt-free connection."; exit 1 ;;
esac
