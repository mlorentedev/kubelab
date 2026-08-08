#!/usr/bin/env bash
# ANSIBLE-033 f3 — prove the refused permission is actually refused.
#
# `Workflows: write` is the single largest privilege jump available to this
# token: CI runs on a self-hosted runner with access to secrets, so a token that
# can rewrite a workflow can execute arbitrary code with those secrets. The
# proposal refuses it. This probe turns that from a claim about the settings
# page into an observed behaviour: a push touching .github/workflows/ must be
# rejected BY GITHUB, for the right reason.
#
# Verdicts written to $RESULT:
#   F3_OK               — push rejected, and the message names the workflow scope
#   F3_UNEXPECTED_ACCEPT— push SUCCEEDED: the token is over-privileged
#   F3_WRONG_REASON     — push failed for some other reason (network, auth,
#                         protected branch). Not evidence either way.
#   F3_FAIL             — the probe itself broke before reaching the push
#
# Distinguishing the last two matters: a bare non-zero exit would let a network
# blip masquerade as a passing security control.

set -euo pipefail

REPO="mlorentedev/go-dsa-sample"
WORK="/tmp/ansible-033-f3"
RESULT="/tmp/ansible-033-f3.result"
PUSH_ERR="/tmp/ansible-033-f3.stderr"
BRANCH="acceptance/ansible-033-workflow-$(date +%s)"

unset SSH_AUTH_SOCK
export GIT_TERMINAL_PROMPT=0

cleanup() {
    git -C "$WORK" push origin --delete "$BRANCH" >/dev/null 2>&1 || true
    rm -rf "$WORK"
    [ -f "$RESULT" ] || echo "F3_FAIL" >"$RESULT"
}
trap cleanup EXIT

rm -rf "$WORK"
rm -f "$RESULT" "$PUSH_ERR"

# Fine-grained tokens are `github_pat_`; classic ones are `ghp_`. The expiry and
# the repository scope are NOT machine-readable for fine-grained PATs — those
# stay a manual check against the token's settings page (see features.json f3).
gh auth token | grep -q "^github_pat_"

git clone --quiet --depth 1 "https://github.com/${REPO}" "$WORK"
cd "$WORK"
git checkout --quiet -b "$BRANCH"

mkdir -p .github/workflows
cat >.github/workflows/ansible-033-probe.yml <<'YAML'
name: ansible-033-probe
on: workflow_dispatch
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - run: "true"
YAML

git add -A
git -c user.name="ace2 dev node" -c user.email="dev-node@kubelab.live" \
    commit --quiet -m "test: ANSIBLE-033 workflow-write refusal probe"

if git push --quiet -u origin HEAD 2>"$PUSH_ERR"; then
    echo "F3_UNEXPECTED_ACCEPT" >"$RESULT"
    exit 1
fi

# GitHub's refusal reads: "refusing to allow a Personal Access Token to create
# or update workflow `.github/workflows/...` without `workflow` scope".
if grep -qi "workflow" "$PUSH_ERR"; then
    echo "F3_OK" >"$RESULT"
else
    echo "F3_WRONG_REASON" >"$RESULT"
    exit 1
fi
