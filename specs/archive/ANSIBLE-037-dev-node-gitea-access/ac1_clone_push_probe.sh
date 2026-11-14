#!/usr/bin/env bash
# AC1 — ace2 can clone and push to a Gitea repository with no manual step.
#
# Runs on ace2, with only what the role provisioned: the node's own key, the
# ssh_config drop-in and the pinned host key. Nothing here supplies a credential
# or trust, so a pass means the provision did.
#
# The push is real and is undone: an empty commit on a probe branch, pushed,
# then deleted on the forge. The working copy lives in a temporary directory
# that is removed on exit, whatever happens.
#
# Exit 0 only when the account greets as the agents' identity, the clone
# succeeds, the push creates the branch and the delete removes it.
#
# Usage: bash specs/ANSIBLE-037-dev-node-gitea-access/ac1_clone_push_probe.sh
set -uo pipefail

ACE2="${ACE2_HOST:-ace2}"
REPO="${PROBE_REPO:-personal/resume}"
BRANCH="probe/ace2-agent-key-$(date -u +%Y%m%dT%H%M%SZ)"
# The repository root by git, not by depth: the spec moves to specs/archive/ on archive.
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel 2>/dev/null)"
if [ ! -f "${REPO_ROOT}/infra/config/values/common.yaml" ]; then
  echo "FATAL: cannot find the repository root from $(dirname "${BASH_SOURCE[0]}")."
  exit 1
fi

# Same SSOT as the playbook: the forge's own env (prod) over common.
read -r SSH_HOST SSH_PORT AGENT < <(cd "${REPO_ROOT}" && python3 -c "
import yaml
c = yaml.safe_load(open('infra/config/values/common.yaml'))
p = yaml.safe_load(open('infra/config/values/prod.yaml')) or {}
g = {**c['apps']['services']['core']['gitea'], **(((p.get('apps') or {}).get('services') or {}).get('core') or {}).get('gitea', {})}
print(g['ssh_host'], g['ssh_port'], c['apps']['auth']['identities']['agent'])
")
URL="ssh://git@${SSH_HOST}:${SSH_PORT}/${REPO}.git"

echo "=== AC1 clone/push drill — $(date -u +%FT%TZ) ==="
echo "node: ${ACE2}   repo: ${REPO}   branch: ${BRANCH}"
echo

# One remote script, so the temp dir and its cleanup live on the node.
# BatchMode and StrictHostKeyChecking=yes: no prompt can stand in for the role.
# The script arrives on stdin, so every command in it that could read stdin is
# given /dev/null: the first draft's inner ssh read the rest of the script and
# the drill exited 0 having checked nothing. For the same reason the verdict is
# the PASS line, never the exit code alone.
output="$(ssh -o BatchMode=yes "${ACE2}" bash -s -- "${URL}" "${BRANCH}" "${AGENT}" "${SSH_HOST}" "${SSH_PORT}" <<'REMOTE'
set -uo pipefail
URL="$1"; BRANCH="$2"; AGENT="$3"; HOST="$4"; PORT="$5"
export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "--- [1/4] the forge greets the agents' account ---"
greeting="$(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -T -p "${PORT}" "git@${HOST}" </dev/null 2>&1 | head -1)"
echo "${greeting}"
case "${greeting}" in
  "Hi there, ${AGENT}!"*) ;;
  *) echo "FAIL: expected a greeting for ${AGENT}"; exit 1 ;;
esac

echo "--- [2/4] clone ---"
git clone -q --depth 1 "${URL}" "${WORK}/repo" </dev/null || { echo "FAIL: clone"; exit 1; }
echo "cloned: $(git -C "${WORK}/repo" rev-parse --short HEAD)"

echo "--- [3/4] push an empty commit to ${BRANCH} ---"
git -C "${WORK}/repo" -c user.name="${AGENT}" -c user.email="${AGENT}@probe.invalid" \
  commit -q --allow-empty --no-verify -m "chore(probe): ANSIBLE-037 AC1 push check" || { echo "FAIL: commit"; exit 1; }
out="$(git -C "${WORK}/repo" push origin "HEAD:refs/heads/${BRANCH}" </dev/null 2>&1)"; rc=$?
echo "${out}" | grep -E 'new branch|rejected|error' || true
[ "${rc}" -eq 0 ] || { echo "FAIL: push (rc=${rc})"; exit 1; }

echo "--- [4/4] delete the probe branch ---"
out="$(git -C "${WORK}/repo" push origin --delete "${BRANCH}" </dev/null 2>&1)"; rc=$?
echo "${out}" | grep -E 'deleted|error' || true
[ "${rc}" -eq 0 ] || { echo "FAIL: delete (rc=${rc}); remove ${BRANCH} by hand"; exit 1; }
echo
echo "PASS — clone and push as ${AGENT}, with only what the role provisioned"
REMOTE
)"
rc=$?
echo "${output}"
if [ "${rc}" -eq 0 ] && printf '%s\n' "${output}" | grep -q '^PASS — '; then
  exit 0
fi
echo "FAIL: no PASS line from the node (ssh rc=${rc})"
exit 1
