#!/usr/bin/env bash

# pr-agent-publish-guard.sh: did THIS run of the pr-agent workflow publish a
# review? (mlorentedev/dotfiles#1107, dotfiles AI-045 AC9, mlorentedev/dotfiles#1923)
#
# Ported from mlorentedev/dotfiles scripts/pr-agent-publish-guard.sh at 6d92b561 (TOOL-082, #1843). Kept in step by hand until TOOL-117 (#2295) gives both repositories one source.
#
# One definition of "published", two callers in .github/workflows/pr-agent.yml:
#
#   --probe --output FILE
#       Between the first attempt and the second (one per provider of the
#       review pool, scripts/pr-agent-route.sh). Appends `published=true`,
#       `published=false` or `published=unknown` to FILE and exits 0. Only a
#       measured `false` lets the second attempt run: a second review cannot
#       duplicate a first one that does not exist. `unknown` (the API failed,
#       or no marker is declared) never runs it.
#
#   (no arguments)
#       The final guard. Exits 0 only when a review was published, and names
#       the attempt that ran last when one was not.
#
# PR-Agent swallows a failed inference into a clean exit (dotfiles run 32325012314:
# green job, no review, a NaN concurrency 429). dotfiles ADR-032's top tier "queues or
# escalates, NEVER degrades silently", so a run that published nothing fails.
#
# A review is a comment that is all three of: authored by github-actions[bot]
# (on a public repo anyone can paste the marker text), created or edited at or
# after this run's start stamp (`persistent_comment` edits the earlier Guide,
# which moves `updated_at`), and carrying a marker the reviewer registry
# declares, read at the DEFAULT branch, since a PR could redefine its own.
#
# Env: GH_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, BASE_REF, STARTED, HEAD_SHA
# (empty on issue_comment runs). The final guard also reads ATTEMPTS, one
# `<outcome> <model>` line per attempt in execution order (`skipped` or empty
# for one that did not run), and ROUTE_NOTE (why a pool member was out of the
# draw). GUARD_RETRY_SECONDS shortens the retry backoff in tests.

set -euo pipefail

mode=guard
output=""
while [ $# -gt 0 ]; do
    case "$1" in
        --probe) mode=probe; shift ;;
        --output) output="${2:?--output needs a file}"; shift 2 ;;
        *) echo "usage: $0 [--probe --output FILE]" >&2; exit 2 ;;
    esac
done
if [ "$mode" = probe ] && [ -z "$output" ]; then
    echo "usage: $0 --probe --output FILE" >&2
    exit 2
fi

# A GitHub API call that FAILS is an outage, never "no marker declared" (mlorentedev/dotfiles#2069:
# a read timeout failed a PR that PR-Agent had reviewed). gh_api retries a
# failure, except a 404, which is an answer: the file is absent at that ref. A
# call that still fails leaves its stderr in $api_errors, which the callers
# report instead of a misdiagnosis.
api_errors=$(mktemp)
gh_api() { # gh api arguments; prints the response, or returns 1
    # Each attempt's output is buffered: gh prints an error body on stdout, and
    # a failed attempt's body must not prefix the answer of the next one.
    local attempt out err
    out=$(mktemp); err=$(mktemp)
    for attempt in 1 2 3; do
        if gh api "$@" >"$out" 2>"$err"; then cat "$out"; rm -f "$out" "$err"; return 0; fi
        if grep -q 'HTTP 404' "$err"; then rm -f "$out" "$err"; return 1; fi
        if [ "$attempt" -lt 3 ]; then sleep $((attempt * ${GUARD_RETRY_SECONDS:-5})); fi
    done
    { printf 'gh api %s: ' "$1"; tr '\n' ' ' < "$err"; echo; } >> "$api_errors"
    rm -f "$out" "$err"
    return 1
}

# Every declared marker, as a JSON array: a full review carries "## PR Reviewer
# Guide", an incremental one "## Incremental PR Reviewer Guide" (dotfiles TOOL-023).
# Prints nothing when none is declared, or when the read failed.
read_markers() { # $1 = ref
    local content
    content=$(gh_api "repos/${GITHUB_REPOSITORY}/contents/harness/review-attestation.json?ref=$1" \
        --jq '.content') || return 0
    printf '%s' "$content" | base64 -d 2>/dev/null \
        | jq -c '[.reviewers[] | select(.login == "github-actions") | .review_markers[]?]
                 | select(length > 0)' 2>/dev/null || true
}

# Sets $markers and $found. Returns 0 when $found is an answer, otherwise:
# 2 the API failed while reading the markers, 3 no marker is declared,
# 4 the comment listing answered 404, 5 the API failed while listing comments.
measure() {
    local comments
    markers=$(read_markers "${BASE_REF}")
    if [ -z "$markers" ] && [ -z "${HEAD_SHA:-}" ]; then
        # issue_comment events carry no pull_request payload; ask the API for the head.
        HEAD_SHA=$(gh_api "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}" --jq '.head.sha' || true)
    fi
    if [ -z "$markers" ] && [ -n "${HEAD_SHA:-}" ]; then
        # The default branch has no github-actions entry yet: this is the PR that
        # introduces it. The head registry only proves the entry EXISTS; the marker
        # itself is PR-Agent's own heading, never text a PR could choose (a head-
        # supplied marker such as "#" would match any bot comment, CWE-345). Author
        # and start-stamp binding below still apply. Without this fallback the
        # bootstrap PR of every repository failed with a bare "exit code 1".
        if [ -n "$(read_markers "${HEAD_SHA}")" ]; then
            markers='["PR Reviewer Guide"]'
            echo "::notice::reviewer registry entry found only on the PR head;" \
                "using PR-Agent's own heading as the marker"
        fi
    fi
    if [ -z "$markers" ] && [ -s "$api_errors" ]; then return 2; fi
    if [ -z "$markers" ]; then return 3; fi
    # --paginate emits one JSON array per page; `jq -s` slurps them into one
    # array of arrays so the count spans every page (gh's own --slurp flag is
    # not present on the runner's gh 2.46 and printed usage instead).
    comments=$(gh_api "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" --paginate) || {
        # gh_api records an outage in $api_errors and returns 1 silently on a 404,
        # so no line for this call means the endpoint answered 404.
        if ! grep -q "/issues/${PR_NUMBER}/comments" "$api_errors"; then return 4; fi
        return 5
    }
    found=$(printf '%s' "$comments" \
        | jq -s --arg started "${STARTED}" --argjson markers "${markers}" \
            '[.[][] | select(.user.login == "github-actions[bot]"
                             and (.updated_at >= $started)
                             and (.body as $b | any($markers[]; . as $m | $b | contains($m))))] | length') \
        || found=""
    # measure runs under `||`, where errexit is off: a count that is not a number
    # is an unreadable answer, never zero, or the probe would report an absence.
    case "$found" in
        ''|*[!0-9]*) return 5 ;;
    esac
    return 0
}

markers=""
found=""
if [ "$mode" = probe ]; then
    rc=0
    measure || rc=$?
    if [ "$rc" -eq 0 ] && [ "$found" -gt 0 ]; then
        echo "published=true" >> "$output"
    elif [ "$rc" -eq 0 ]; then
        echo "published=false" >> "$output"
    else
        echo "::warning::whether the first attempt published a review is unknown (probe status ${rc});" \
            "the second attempt runs only on a measured absence."
        if [ -s "$api_errors" ]; then sed 's/^/::warning::/' "$api_errors"; fi
        echo "published=unknown" >> "$output"
    fi
    exit 0
fi

# The final guard judges the LAST attempt that ran. Only a known outcome counts:
# an attempt GitHub never evaluated leaves its outcome empty, and `read` would
# then take the model's name for the outcome.
outcome="" model=""
while read -r line_outcome line_model; do
    case "$line_outcome" in
        success|failure|cancelled) outcome="$line_outcome"; model="$line_model" ;;
    esac
done <<<"${ATTEMPTS:-}"
note() {
    if [ -n "${ROUTE_NOTE:-}" ]; then echo "::error::${ROUTE_NOTE}"; fi
}
case "$outcome" in
    cancelled|failure)
        echo "::error::PR-Agent ended ${outcome} on ${model:-its model}." \
            "Inspect its logs; a second attempt runs only when no review is measured as published."
        note
        exit 1
        ;;
    "")
        if [ "${ROUTE_OUTCOME:-}" = "failure" ]; then
            echo "::error::no review attempt ran: the draw itself failed, so no member was" \
                "chosen. Its step names why (an unknown PR_AGENT_PROVIDER, or a NaN preflight" \
                "that failed on its setup, fails it on purpose)."
        else
            echo "::error::no review attempt ran: no member of the review pool answered its probe" \
                "(the preflight's and the draw's warnings name each one)."
        fi
        note
        exit 1
        ;;
esac

rc=0
measure || rc=$?
case "$rc" in
    2)
        # The failed call may be the registry read or the head-SHA lookup; the
        # detail lines below name it, so the headline names neither.
        echo "::error::the GitHub API failed while determining whether a review marker is" \
            "declared, so that is unknown. Re-run the job once the API answers."
        sed 's/^/::error::/' "$api_errors"
        exit 1
        ;;
    3)
        echo "::error::no review marker declared for github-actions in" \
            "harness/review-attestation.json (checked ${BASE_REF} and the PR head)"
        exit 1
        ;;
    4)
        echo "::error::listing the PR's comments answered 404: the PR, or this token's" \
            "read access to it, is gone, so no published review can be verified."
        exit 1
        ;;
    5)
        echo "::error::the GitHub API failed while listing the PR's comments, so whether" \
            "a review was published is unknown. Re-run the job once the API answers."
        sed 's/^/::error::/' "$api_errors"
        exit 1
        ;;
esac
if [ "$found" -gt 0 ]; then
    echo "review published (markers: ${markers}) on ${model:-its model}"
    exit 0
fi
echo "::error::PR-Agent reported success but published no review" \
    "(no github-actions[bot] comment updated since ${STARTED} carries any of ${markers})."
# The measured causes are NaN's; naming them under an Anthropic attempt would
# send whoever reads this to the wrong provider.
case "$model" in
    anthropic/*)
        echo "::error::No cause is measured yet for the Anthropic attempt. Its step log has the answer"
        echo "::error::PR-Agent received: look for an output cut at DEFAULT_ANTHROPIC_CHAT_MAX_TOKENS"
        echo "::error::or an error PR-Agent logged and then exited cleanly on."
        ;;
    *)
        echo "::error::Three causes are measured here. (1) Saturation: NaN limits concurrency per MODEL,"
        echo "::error::shared with every other client of the key, and a 429 PR-Agent swallows exits clean."
        echo "::error::(2) An empty or truncated body on a 200: the model spent its output budget on"
        echo "::error::reasoning, no exception is raised, so no fallback fires (#1205, #1966)."
        echo "::error::(3) A large diff the model never finishes before the step timeout (#1909)."
        echo "::error::Silence after \"Generating prediction with\" in the step log is (2) or (3)."
        ;;
esac
note
exit 1
