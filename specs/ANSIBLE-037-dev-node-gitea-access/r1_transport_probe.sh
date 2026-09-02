#!/usr/bin/env bash
# R1 — is Gitea's SSH transport usable from ace2?
#
# The Beelink compose publishes "<tailscale_ip>:2222:22" against the official
# image's OpenSSH and advertises it through GITEA__server__SSH_DOMAIN. On paper
# that works over the tailnet. The template's own comment is the reason not to
# trust paper: the K8s manifest it replaced published a port with nothing behind
# it, so the advertised clone URL had never connected.
#
# Three checks, in order, because they fail differently and the difference is
# the answer:
#   1. TCP reachability      — separates "nothing listening" from "listening and rejecting"
#   2. SSH banner            — proves a server answers, and which one
#   3. git transport as hefesto — proves the account's keys are honoured for git
#
# Read-only. Registers nothing, changes no state on either node.
#
# Usage: bash specs/ANSIBLE-037-dev-node-gitea-access/r1_transport_probe.sh
set -uo pipefail

ACE2="${ACE2_HOST:-ace2}"
GITEA_SSH_HOST="${GITEA_SSH_HOST:-beelink.kubelab.internal}"
GITEA_SSH_PORT="${GITEA_SSH_PORT:-2222}"

echo "=== R1 transport probe — $(date -u +%FT%TZ) ==="
echo "from:   ${ACE2}"
echo "target: ${GITEA_SSH_HOST}:${GITEA_SSH_PORT}"
echo

echo "--- [1/3] TCP reachability from ace2 ---"
ssh -o BatchMode=yes "${ACE2}" \
  "timeout 5 bash -c '</dev/tcp/${GITEA_SSH_HOST}/${GITEA_SSH_PORT}' \
   && echo 'OPEN — something is listening' \
   || echo 'CLOSED/FILTERED — nothing listening, or unreachable'"
tcp_rc=$?
echo "(exit ${tcp_rc})"
echo

echo "--- [2/3] SSH banner (which server answers) ---"
# `ssh -v` to a port, reading its own identification-string log line, rather than
# hand-rolling a /dev/tcp read: the nested quoting made the first version emit
# nothing at all, and a diagnostic that silently returns empty is worse than no
# diagnostic. Check 3 is the verdict either way; this only names the server.
ssh -o BatchMode=yes "${ACE2}" \
  "timeout 5 ssh -v -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
       -p ${GITEA_SSH_PORT} git@${GITEA_SSH_HOST} 2>&1 \
   | grep -i 'remote protocol version\\|remote software version' | head -2 \
   || echo '(no banner)'"
echo

echo "--- [3/3] git transport as the machine identity ---"
# -T: no shell wanted. Gitea/OpenSSH answers a successful git auth with a
# greeting and a non-zero exit, so the BANNER is the verdict, never the code.
ssh -o BatchMode=yes "${ACE2}" \
  "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
       -T -p ${GITEA_SSH_PORT} git@${GITEA_SSH_HOST} 2>&1 | head -5" \
  || true
echo
echo "=== verdict ==="
echo "SSH is usable  → keep proposal.md D2 as written (per-node key, repo-only blast radius)."
echo "SSH is not     → fall back to HTTPS + credential helper, and RE-RECORD D2:"
echo "                 a scoped token at rest on the node is a different posture,"
echo "                 not an implementation detail."
