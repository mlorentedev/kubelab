#!/usr/bin/env bash

# pr-agent-model-preflight.sh: before PR-Agent runs, find the first model of its
# DECLARED chain that NaN answers (dotfiles AI-045, mlorentedev/dotfiles#1763).
#
# Ported from mlorentedev/dotfiles scripts/pr-agent-model-preflight.sh at 6d92b561 (TOOL-082, #1843). Kept in step by hand until TOOL-117 (#2295) gives both repositories one source.
#
# Measured 2026-09-30. NaN retired `mimo-v2.5`, PR-Agent's primary. For hours
# it accepted the diff and never answered, and PR-Agent then exited cleanly
# with nothing published: a green `review` job and no review, on every PR
# (mlorentedev/dotfiles#1107). After that it answered 401, "This API key does not have access to
# the requested model". PR-Agent's own fallback handles a refusal. It does not
# handle a hang, which holds the run for the full inference timeout on each
# retry. Neither case tells anyone that the declared model is dead.
#
# This probes each model once, with a small request and a timeout. It hands
# PR-Agent the first model that answers, followed by the remaining models that
# answered, in declared order. Every model that did not answer becomes a
# `::warning::` and a line in the job summary, naming the files to fix. If
# none answers, it warns and exits 1: the step is `continue-on-error`, NaN
# leaves the review pool for this run, and the draw hands the review to the
# pool's other provider. The publish guard fails the job if nothing is
# published.
#
# It never CHOOSES a model. The chain is declared in the workflow and in
# .pr_agent.toml (a test holds the two equal), and this only skips dead entries
# in that order. The draw among the members that answered is
# scripts/pr-agent-route.sh's (dotfiles AI-045 AC9). Anything outside the chain is never considered, whatever NaN
# serves: `GET /v1/models` lists what the cluster runs, not what the key may
# call (https://nan.builders/docs/choose-a-model), so only a real call counts.
#
# The key goes to curl on stdin (`-K -`), never on its argv, where any process
# on the runner could read it.
#
# Usage:
#   pr-agent-model-preflight.sh --model openai/<id> --fallbacks '["openai/<id>", ...]'
#                               [--output FILE]
#
# Env:
#   NAN_API_KEY        the key (required; never printed)
#   NAN_API_BASE       default https://api.nan.builders/v1
#   PREFLIGHT_TIMEOUT  seconds per model, default 90
#   GITHUB_STEP_SUMMARY  when set, a table of the probe results is appended
#
# Output, as `key=value` lines to --output (default stdout):
#   model=<first model that answered>
#   fallbacks=<JSON array of the other models that answered, in declared order>
#
# Exit:
#   0  a model answered
#   1  no declared model answered (the review pool continues without NaN)
#   2  usage or setup error

set -uo pipefail

usage() {
    printf 'usage: %s --model openai/<id> --fallbacks JSON_ARRAY [--output FILE]\n' "${0##*/}"
}

model="" fallbacks="" output="/dev/stdout"
while [ $# -gt 0 ]; do
    case "$1" in
        --model) model="${2:-}"; shift 2 ;;
        --fallbacks) fallbacks="${2:-}"; shift 2 ;;
        --output) output="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

for tool in curl jq; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf '%s is required and was not found\n' "$tool" >&2
        exit 2
    fi
done
if [ -z "$model" ] || [ -z "$fallbacks" ]; then
    usage >&2
    exit 2
fi
if [ -z "${NAN_API_KEY:-}" ]; then
    printf 'NAN_API_KEY is not set\n' >&2
    exit 2
fi
if ! chain=$(jq -r --arg m "$model" '[$m] + . | .[]' <<<"$fallbacks" 2>/dev/null); then
    printf -- '--fallbacks must be a JSON array of model ids, got: %s\n' "$fallbacks" >&2
    exit 2
fi

base="${NAN_API_BASE:-https://api.nan.builders/v1}"
timeout="${PREFLIGHT_TIMEOUT:-90}"

# probe ID: prints the HTTP status, or 000 when nothing answered in time.
# A reasoning model spends tokens thinking before it answers; 512 covers the
# shortest reply on every NaN chat model (mimo-v2.6-flash asks for >= 300).
# A status line is not an answer: headers can arrive and the body never, and
# curl then prints 200 and exits 28. Only a completed transfer counts.
probe() {
    local body code
    body=$(jq -cn --arg m "$1" \
        '{model: $m, max_tokens: 512, messages: [{role: "user", content: "Reply with OK."}]}')
    if ! code=$(printf 'header = "Authorization: Bearer %s"\n' "$NAN_API_KEY" \
        | curl -sS -K - -o /dev/null -w '%{http_code}' -m "$timeout" \
            -H 'Content-Type: application/json' -d "$body" "$base/chat/completions" 2>/dev/null); then
        code=000
    fi
    printf '%s' "${code:-000}"
}

# remedy CODE: what the reader should do about a model that did not answer.
# Only a refusal means the chain is wrong. Quota and NaN's per-model
# concurrency limit (mlorentedev/dotfiles#1107) pass on their own, and so does an outage; telling
# the reader to edit the chain for those would be wrong advice.
remedy() {
    case "$1" in
        401|403|404) printf 'this key cannot call it. Fix the chain in .pr_agent.toml and .github/workflows/pr-agent.yml' ;;
        402|429) printf 'quota or concurrency limit reached. Nothing to fix; it passes, or the quota resets' ;;
        *) printf 'NaN did not serve it this time. Nothing to fix unless it persists; check https://nan.builders/docs/models' ;;
    esac
}

answered=() summary=()
while IFS= read -r declared; do
    [ -n "$declared" ] || continue
    code=$(probe "${declared#openai/}")
    case "$code" in
        2??)
            answered+=("$declared")
            summary+=("| \`$declared\` | answered (HTTP $code) |")
            ;;
        000)
            printf '::warning::PR-Agent model %s gave no answer within %ss and is skipped for this run: %s.\n' \
                "$declared" "$timeout" "$(remedy "$code")"
            summary+=("| \`$declared\` | no answer within ${timeout}s |")
            ;;
        *)
            printf '::warning::PR-Agent model %s answered HTTP %s and is skipped for this run: %s.\n' \
                "$declared" "$code" "$(remedy "$code")"
            summary+=("| \`$declared\` | HTTP $code |")
            ;;
    esac
done <<<"$chain"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        printf '### PR-Agent model preflight\n\n| Model | Result |\n|---|---|\n'
        printf '%s\n' "${summary[@]}"
        if [ "${#answered[@]}" -gt 0 ]; then
            printf '\nReviewing with %s.\n' "\`${answered[0]}\`"
        else
            printf '\nNo declared model answered, so NaN is out of the review pool for this run.\n'
        fi
    } >> "$GITHUB_STEP_SUMMARY"
fi

if [ "${#answered[@]}" -eq 0 ]; then
    # A warning, not an error: NaN is out of the review pool for this run, and
    # the pool's Anthropic member may still review (scripts/pr-agent-route.sh).
    # The final guard fails the job if nothing was published.
    printf '::warning::No model in PR-Agent'\''s declared NaN chain answered, so NaN is out of the review pool for this run.'
    printf ' The warnings above give each model'\''s status and what to do about it.\n'
    exit 1
fi

if [ "${answered[0]}" != "$model" ]; then
    printf '::warning::PR-Agent reviews this PR with %s, not the declared primary %s.\n' \
        "${answered[0]}" "$model"
fi

{
    printf 'model=%s\n' "${answered[0]}"
    printf 'fallbacks=%s\n' "$(printf '%s\n' "${answered[@]:1}" | jq -Rsc 'split("\n") | map(select(. != ""))')"
} >> "$output"
