#!/usr/bin/env bash
# ANSIBLE-033 f2 — the whole acceptance criterion in executable form.
#
# Clone a PRIVATE repository, commit, push a branch and open a PR from a tmux
# session on ace2, with no human at the keyboard and no agent forwarding.
#
# Runs ON ace2, detached inside tmux. Writes its verdict to $RESULT so the
# caller never has to parse output:
#   F2_OK   — the full flow succeeded
#   F2_FAIL — anything failed (the trap writes this, so a failure is immediate
#             rather than costing the caller its whole poll window)
#
# Lives in the spec folder, not scripts/: it is the acceptance criterion, not
# product code. Inline in features.json it would need three quoting layers
# (ssh -> tmux -> bash) and expand $WORK on the wrong host.

set -euo pipefail

# A dormant 15KB private repo. Small so the clone is fast, untouched since
# 2024-11 so an acceptance branch cannot collide with real work.
REPO="mlorentedev/go-dsa-sample"
WORK="/tmp/ansible-033-f2"
RESULT="/tmp/ansible-033-f2.result"
BRANCH="acceptance/ansible-033-$(date +%s)"
PR_URL=""

# The PAT must do all the work. ace2 runs a long-lived tmux server, whose
# environment can carry a forwarded agent socket from an earlier session — so
# clear it here rather than trusting the caller's ssh flags. Without
# GIT_TERMINAL_PROMPT=0 a missing credential hangs this detached session on a
# username prompt instead of failing.
unset SSH_AUTH_SOCK
export GIT_TERMINAL_PROMPT=0

cleanup() {
    if [ -n "$PR_URL" ]; then
        gh pr close "$PR_URL" --delete-branch >/dev/null 2>&1 || true
    fi
    git -C "$WORK" push origin --delete "$BRANCH" >/dev/null 2>&1 || true
    rm -rf "$WORK"
    [ -f "$RESULT" ] || echo "F2_FAIL" >"$RESULT"
}
trap cleanup EXIT

rm -rf "$WORK"
rm -f "$RESULT"

# 1. The fixture must actually be private, and the token must be able to see it.
#    Guards against the criterion silently weakening if the repo is ever made
#    public — a public clone would prove nothing about private access.
gh api "repos/${REPO}" --jq .private | grep -qx true

# 1b. ...and it must be WRITABLE. An archived repo is read-only no matter what
#     the token grants: the push returns 403 "This repository was archived",
#     which reads exactly like a permissions failure and sends you auditing the
#     credential instead of the fixture. Learned the hard way 2026-08-08, when
#     the first fixture was picked for being dormant — and dormant turned out to
#     mean archived. Fail here, with a verdict that names the real cause.
if [ "$(gh api "repos/${REPO}" --jq .archived)" = "true" ]; then
    echo "F2_FIXTURE_ARCHIVED" >"$RESULT"
    echo "fixture ${REPO} is archived (read-only) — this is a fixture problem, not a token problem" >&2
    exit 1
fi

# 2. Clone over HTTPS explicitly. `gh repo clone` would honour a configured git
#    protocol and could pick SSH, which would test a key instead of the PAT.
git clone --quiet --depth 1 "https://github.com/${REPO}" "$WORK"
cd "$WORK"
git remote get-url origin | grep -q "^https://"

# 3. Commit and push. The push is what exercises `gh auth setup-git`'s
#    credential helper — the "one credential, not two" claim.
git checkout --quiet -b "$BRANCH"
date -u +"ANSIBLE-033 acceptance probe %Y-%m-%dT%H:%M:%SZ" >.acceptance-probe
git add -A
git -c user.name="ace2 dev node" -c user.email="dev-node@kubelab.live" \
    commit --quiet -m "test: ANSIBLE-033 acceptance probe"
git push --quiet -u origin HEAD

# 4. Open the PR. `gh pr create` prints the URL last.
PR_URL="$(gh pr create --fill --draft | tail -1)"
case "$PR_URL" in
    https://github.com/*) ;;
    *) exit 1 ;;
esac

echo "F2_OK" >"$RESULT"
