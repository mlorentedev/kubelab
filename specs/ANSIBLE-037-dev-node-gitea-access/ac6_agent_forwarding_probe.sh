#!/usr/bin/env bash
# AC6 — the operator's own access from ace2 works through SSH agent forwarding,
#       with NO key of theirs on the node.
#
# This is what makes D1's "the human half needs no provisioning" a measurement
# rather than a claim. D1 argues the node should authenticate as the machine
# identity because a named human's key must not sit at rest on an on-demand
# shared box; that argument only holds if the human still has a working path.
# If this fails, D1 needs revisiting — not working around.
#
# Two assertions, and the second is the load-bearing one:
#   1. forwarded-agent auth to the forge succeeds and is attributed to the human
#   2. no private key belonging to the human exists on the node
# Assertion 1 passing while 2 fails would mean the convenience was bought with
# exactly the exposure D1 refused.
#
# Usage: bash specs/ANSIBLE-037-dev-node-gitea-access/ac6_agent_forwarding_probe.sh
set -uo pipefail

ACE2="${ACE2_HOST:-ace2}"
GITEA_SSH_HOST="${GITEA_SSH_HOST:-beelink.kubelab.internal}"
GITEA_SSH_PORT="${GITEA_SSH_PORT:-2222}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HUMAN="$(cd "${REPO_ROOT}" && python3 -c '
import yaml
c = yaml.safe_load(open("infra/config/values/common.yaml"))
print(c["apps"]["auth"]["identities"]["superadmin"])')"

echo "=== AC6 agent-forwarding drill — $(date -u +%FT%TZ) ==="
echo "node: ${ACE2}   human identity (SSOT): ${HUMAN}"
echo

echo "--- [0/3] the local agent holds a key to forward ---"
if ! ssh-add -l >/dev/null 2>&1; then
  echo "FAIL — no keys in the local ssh-agent, so there is nothing to forward."
  echo "       This measures the workstation, not the design: run \`ssh-add\` and retry."
  exit 1
fi
ssh-add -l | sed 's/ [^ ]*$//' | head -3   # comment stripped: it can name a path

echo
echo "--- [1/3] forge auth from ace2 over a FORWARDED agent ---"
# -A on this hop only. Nothing is written to the node's ssh config, which is the
# point: the human path needs no provisioning at all.
forwarded="$(ssh -A -o BatchMode=yes "${ACE2}" \
  "ssh -o BatchMode=yes -o IdentityAgent=\$SSH_AUTH_SOCK -o IdentitiesOnly=no \
       -T -p ${GITEA_SSH_PORT} git@${GITEA_SSH_HOST} 2>&1 | head -1")"
echo "${forwarded}"
case "${forwarded}" in
  *"Hi there, ${HUMAN}!"*)
    echo "OK — authenticated as the human, via the forwarded agent" ;;
  *"successfully authenticated"*)
    echo "FAIL — authenticated, but NOT as ${HUMAN}. The forwarded agent was not"
    echo "       what answered; the node's own machine key was. That does not"
    echo "       demonstrate AC6 — it demonstrates the machine path again."
    exit 1 ;;
  *)
    echo "FAIL — the human has no working path from ace2. D1 assumed one exists"
    echo "       (AUTH-004 R2 measured an 'msi-workstation' key on the account),"
    echo "       so D1 must be revisited rather than worked around."
    exit 1 ;;
esac

echo
echo "--- [2/3] no private key of the human's is at rest on the node ---"
# The machine keypair the role provisions is expected and is NOT a finding; it
# belongs to the node, not to a person. Anything else private is.
strays="$(ssh -o BatchMode=yes "${ACE2}" \
  "find ~/.ssh -maxdepth 1 -type f ! -name '*.pub' ! -name 'known_hosts' \
        ! -name 'authorized_keys' ! -name 'config' ! -name 'id_gitea_*' 2>/dev/null")"
if [ -n "${strays}" ]; then
  echo "FAIL — private key material on the node beyond the node's own:"
  echo "${strays}"
  echo "       AC6 asserts the human's access costs no key at rest here."
  exit 1
fi
echo "OK — only the node's own machine keypair is present"

echo
echo "--- [3/3] verdict ---"
echo "PASS — the human authenticates as themselves from ace2 with nothing of"
echo "       theirs stored on it, so D1's 'the human half needs no provisioning'"
echo "       is demonstrated rather than asserted."
