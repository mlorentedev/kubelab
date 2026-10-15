#!/usr/bin/env bash

# pr-agent-route.sh: draw which pool member reviews this PR first (dotfiles AI-045 AC9,
# mlorentedev/dotfiles#1923).
#
# Ported from mlorentedev/dotfiles scripts/pr-agent-route.sh at 6d92b561 (TOOL-082, #1843). Kept in step by hand until TOOL-117 (#2295) gives both repositories one source.
#
# The CI review pool is harness/reviewer-pool.json's members that carry a
# `pr_agent` block: the NaN chain the preflight declares
# (scripts/pr-agent-model-preflight.sh, a test holds the two equal), Haiku, and
# Sonnet. Members that answered their probe are drawn by their `weight`, so the
# share each one gets is a number in that file, not an accident of how many
# members there are. A member that did not answer (dead, over quota, saturated,
# no credential) is not in the draw, and its weight is shared out among the rest
# in proportion.
#
# Sonnet (`route: risk`) is never drawn. It reviews first when the PR crosses
# `pr_agent_risk`: additions plus deletions at or above `min_changed_lines`, or
# the label. If it does not answer, the PR goes to the draw with a note; the
# quality tier being over its spend limit never means no review.
#
# One PR-Agent attempt talks to ONE provider: PR-Agent's own fallback chain
# shares one transport, and NaN's (`LITELLM__CUSTOM_LLM_PROVIDER: openai`, its
# base URL) would misroute an Anthropic model. So the draw picks the provider of
# the first attempt and, within NaN, the model; the other provider, when one of
# its members answered, is the second attempt. The workflow runs that second
# attempt only on a measured absence of a published review.
#
# The Anthropic models CI may spend on are ALLOWED below, not read from the pool:
# the Console cannot restrict a key to a model, so this list is the allowlist,
# and a pool edit naming another model fails the draw instead of paying for it.
#
# PR_AGENT_PROVIDER (a repository variable) overrides the draw:
#   draw (or unset)  by weight over every member that answered, risk first
#   nan              NaN first, Anthropic second, no risk route
#   anthropic        Anthropic first, NaN second
#   nan-only         NaN only; no Anthropic model is even probed, so this is
#                    the switch that stops all spending on the Anthropic key
# A forced provider with no member that answered falls back to the draw, with a
# warning: forcing is for testing a route, and a review is still worth having.
# An unknown value fails: it may be a misspelt `nan-only`, and spending against
# a switch someone meant to turn off is the one outcome this must not produce.
#
# The key goes to curl on stdin (`-K -`), never on its argv.
#
# Env:
#   POOL_FILE              default harness/reviewer-pool.json
#   NAN_OUTCOME            the preflight step's outcome (`success` when a NaN model answered)
#   NAN_MODEL              the preflight's first NaN model that answered
#   NAN_FALLBACKS          JSON array of the other NaN models that answered, in declared order
#   NAN_PREFLIGHT_EXIT     the preflight's exit code; 2 (a broken setup) fails the draw
#   PR_AGENT_ANTHROPIC_API_KEY  the Anthropic key; empty means no Anthropic member (never printed)
#   PR_AGENT_PROVIDER      the override above
#   PR_CHANGED_LINES       additions plus deletions; empty when unread (risk then by label only)
#   PR_LABELS              JSON array of the PR's label names
#   PR_AGENT_DRAW          tests only: a point in [0, total weight) instead of a random one
#   ANTHROPIC_API_BASE     default https://api.anthropic.com
#   ROUTE_PROBE_TIMEOUT    seconds for each Anthropic probe, default 30
#   GITHUB_REPOSITORY      names the repository in the remedy
#   GITHUB_STEP_SUMMARY    when set, the draw is appended to it
#
# Output, as `key=value` lines to --output (default stdout):
#   first=nan|anthropic|none     the provider of the first attempt
#   second=nan|anthropic|none    the provider of the attempt after it
#   reviewer=<model>             the member that reviews first
#   route=draw|risk              how it was chosen
#   nan_model=<model>            the NaN attempt's model, when NaN is first or second
#   nan_fallbacks=<JSON array>   the NaN attempt's fallback chain
#   anthropic_model=<model>      the Anthropic attempt's model, when Anthropic is first or second
#   anthropic_effort=<effort>    its reasoning effort
#   note=<text>                  why a member was out of the draw, for the final guard
#
# Exit: 0 routed (first may be `none`), 1 unknown PR_AGENT_PROVIDER, a NaN
# preflight that failed on its setup, or a pool naming an Anthropic model
# outside the allowlist; 2 usage.

set -uo pipefail

output="/dev/stdout"
while [ $# -gt 0 ]; do
    case "$1" in
        --output) output="${2:-}"; shift 2 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done
for tool in curl jq; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf '%s is required and was not found\n' "$tool" >&2
        exit 2
    fi
done
pool="${POOL_FILE:-harness/reviewer-pool.json}"
if ! jq -e '.pool | type == "array"' "$pool" >/dev/null 2>&1; then
    printf 'cannot read a pool from %s\n' "$pool" >&2
    exit 2
fi

# The allowlist. Adding a model here is a deliberate cost decision; the pool
# alone cannot make it.
ALLOWED_ANTHROPIC="anthropic/claude-haiku-5-5 anthropic/claude-sonnet-5-5"
allowed() {
    case " $ALLOWED_ANTHROPIC " in *" $1 "*) return 0 ;; esac
    return 1
}

provider="${PR_AGENT_PROVIDER:-draw}"
case "$provider" in
    draw|nan|anthropic|nan-only) ;;
    *)
        printf '::error::PR_AGENT_PROVIDER is %s, which is none of draw, nan, anthropic or nan-only.' "$provider"
        printf ' Nothing is reviewed until it is fixed: a misspelt nan-only must not spend on the Anthropic key.\n'
        exit 1
        ;;
esac

# The preflight's exit 2 is a broken setup (no NAN_API_KEY, a missing tool, a
# bad argument), not a NaN outage. Read as "no NaN member answered", it would
# send every review to the paid member until someone noticed, so it stops here.
if [ "${NAN_PREFLIGHT_EXIT:-}" = "2" ]; then
    printf '::error::The NaN preflight failed on its setup (exit 2), not on NaN: its step names the cause'
    printf ' (a missing NAN_API_KEY, tool or argument). Nothing is drawn, so a broken setup cannot move every'
    printf ' review onto the paid Anthropic key.\n'
    exit 1
fi

# pool_field <model> <jq expr on .pr_agent>: one value of a member's pr_agent block.
pool_field() {
    jq -r --arg m "$1" "first(.pool[] | select(.pr_agent.model == \$m) | .pr_agent | $2) // empty" "$pool"
}

# Every Anthropic model the pool names for PR-Agent must be allowed.
while IFS= read -r m; do
    [ -n "$m" ] || continue
    if ! allowed "$m"; then
        printf '::error::%s names %s for PR-Agent, which is not in the allowlist in %s (%s).' \
            "$pool" "$m" "${0##*/}" "$ALLOWED_ANTHROPIC"
        printf ' Nothing is reviewed until it is fixed: an allowlist edit is a cost decision, made in a reviewed PR.\n'
        exit 1
    fi
done < <(jq -r '.pool[] | .pr_agent.model // empty | select(startswith("anthropic/"))' "$pool")

# The drawn Anthropic member (one weight) and the risk member (route: risk).
drawn_anthropic=$(jq -r '[.pool[] | select((.pr_agent.model // "" | startswith("anthropic/")) and (.pr_agent.weight // 0) > 0)
    | .pr_agent.model] | first // empty' "$pool")
risk_model=$(jq -r '[.pool[] | select(.pr_agent.route == "risk") | .pr_agent.model] | first // empty' "$pool")
risk_lines=$(jq -r '.pr_agent_risk.min_changed_lines // empty' "$pool")
risk_label=$(jq -r '.pr_agent_risk.label // empty' "$pool")

# The NaN members that answered, in declared order.
nan=()
if [ "${NAN_OUTCOME:-}" = "success" ] && [ -n "${NAN_MODEL:-}" ]; then
    nan+=("$NAN_MODEL")
    while IFS= read -r m; do
        [ -n "$m" ] && nan+=("$m")
    done < <(jq -r '.[]?' <<<"${NAN_FALLBACKS:-[]}" 2>/dev/null)
fi

notes=""
add_note() {
    printf '::warning::%s\n' "$1"
    notes="${notes:+$notes }$1"
}

# probe <model>: prints the HTTP status, or 000 when nothing answered in time.
# 64 output tokens: any 2xx is an answer, and a truncated one costs the least.
probe() {
    local body code
    body=$(jq -cn --arg m "${1#anthropic/}" \
        '{model: $m, max_tokens: 64, messages: [{role: "user", content: "Reply with OK."}]}')
    if ! code=$(printf 'header = "x-api-key: %s"\n' "$PR_AGENT_ANTHROPIC_API_KEY" \
        | curl -sS -K - -o /dev/null -w '%{http_code}' -m "${ROUTE_PROBE_TIMEOUT:-30}" \
            -H 'anthropic-version: 2023-06-01' -H 'Content-Type: application/json' \
            -d "$body" "${ANTHROPIC_API_BASE:-https://api.anthropic.com}/v1/messages" 2>/dev/null); then
        code=000
    fi
    printf '%s' "${code:-000}"
}

# answers <model>: probes one Anthropic member; on anything but a 2xx it adds
# the note naming the fix and fails.
answers() {
    local code
    code=$(probe "$1")
    case "$code" in
        2??) return 0 ;;
        401|403) add_note "$1 answered HTTP ${code}: the key is refused. Rotate it: dotf secrets rotate PR_AGENT_ANTHROPIC_API_KEY" ;;
        404) add_note "$1 answered HTTP 404: the model id is wrong. Fix it in harness/reviewer-pool.json" ;;
        000) add_note "$1 gave no answer within ${ROUTE_PROBE_TIMEOUT:-30}s and was out of the review pool for this run." ;;
        *) add_note "$1 answered HTTP ${code} (rate limit, overload or spend limit) and was out of the review pool for this run." ;;
    esac
    return 1
}

key_ok=true
if [ "$provider" != "nan-only" ] && [ -z "${PR_AGENT_ANTHROPIC_API_KEY:-}" ]; then
    key_ok=false
    add_note "PR_AGENT_ANTHROPIC_API_KEY is not set, so no Anthropic model was in the review pool. Remedy: add ci:${GITHUB_REPOSITORY:-<repo>} to its consumers in dotfiles/secrets/registry.yaml, then run: dotf secrets sync ci --repo ${GITHUB_REPOSITORY:-<repo>} PR_AGENT_ANTHROPIC_API_KEY"
fi

anthropic=()
if [ "$provider" != "nan-only" ] && [ "$key_ok" = true ] && [ -n "$drawn_anthropic" ]; then
    if answers "$drawn_anthropic"; then anthropic+=("$drawn_anthropic"); fi
fi

# The risk route: a PR past the line count, or carrying the label.
risky=""
if [ -n "$risk_model" ] && [ "$provider" != "nan" ] && [ "$provider" != "nan-only" ]; then
    case "${PR_CHANGED_LINES:-}" in
        ''|*[!0-9]*)
            if [ -n "$risk_lines" ]; then
                add_note "The PR's size could not be read, so only the ${risk_label:-risk} label could route it to ${risk_model}."
            fi
            ;;
        *)
            if [ -n "$risk_lines" ] && [ "$PR_CHANGED_LINES" -ge "$risk_lines" ]; then
                risky="${PR_CHANGED_LINES} changed lines (at least ${risk_lines})"
            fi
            ;;
    esac
    if [ -z "$risky" ] && [ -n "$risk_label" ] \
        && jq -e --arg l "$risk_label" 'index($l) != null' <<<"${PR_LABELS:-[]}" >/dev/null 2>&1; then
        risky="the ${risk_label} label"
    fi
fi

first=none second=none reviewer="" route=draw nan_model="" nan_fallbacks="[]" anthropic_model=""
if [ -n "$risky" ] && [ "$key_ok" = true ]; then
    if answers "$risk_model"; then
        reviewer="$risk_model" route=risk first=anthropic anthropic_model="$risk_model"
        if [ "${#nan[@]}" -gt 0 ]; then second=nan; fi
    else
        add_note "The PR crossed the risk line (${risky}), but ${risk_model} did not answer, so it was drawn by weight instead."
    fi
fi

# The candidates the draw picks from.
candidates=()
case "$provider" in
    draw) candidates=(${nan[@]+"${nan[@]}"} ${anthropic[@]+"${anthropic[@]}"}) ;;
    nan|nan-only) candidates=(${nan[@]+"${nan[@]}"}) ;;
    anthropic) candidates=(${anthropic[@]+"${anthropic[@]}"}) ;;
esac
if [ "${#candidates[@]}" -eq 0 ] && [ "$provider" != "draw" ] && [ "$provider" != "nan-only" ]; then
    printf '::warning::PR_AGENT_PROVIDER=%s, but no %s member answered; drawing from the rest of the pool.\n' \
        "$provider" "$provider"
    candidates=(${nan[@]+"${nan[@]}"} ${anthropic[@]+"${anthropic[@]}"})
fi

# The weighted draw: each candidate holds `weight` points of [0, total). A
# member that answered but has no weight in the pool is never drawn first; it
# stays in the NaN chain as a fallback.
if [ "$route" = draw ] && [ "${#candidates[@]}" -gt 0 ]; then
    weights=() total=0
    for m in "${candidates[@]}"; do
        w=$(pool_field "$m" '.weight')
        case "$w" in ''|*[!0-9]*) w=0 ;; esac
        weights+=("$w")
        total=$((total + w))
    done
    if [ "$total" -gt 0 ]; then
        if [ -n "${PR_AGENT_DRAW:-}" ]; then
            case "$PR_AGENT_DRAW" in
                *[!0-9]*) printf 'PR_AGENT_DRAW must be a point, got: %s\n' "$PR_AGENT_DRAW" >&2; exit 2 ;;
            esac
            if [ "$PR_AGENT_DRAW" -ge "$total" ]; then
                printf 'PR_AGENT_DRAW %s is outside the total weight %s\n' "$PR_AGENT_DRAW" "$total" >&2
                exit 2
            fi
            point=$PR_AGENT_DRAW
        else
            point=$(( (RANDOM * 32768 + RANDOM) % total ))
        fi
        acc=0 i=0
        while [ "$i" -lt "${#candidates[@]}" ]; do
            acc=$((acc + weights[i]))
            if [ "$point" -lt "$acc" ]; then reviewer="${candidates[$i]}"; break; fi
            i=$((i + 1))
        done
        case "$reviewer" in
            anthropic/*)
                first=anthropic
                if [ "${#nan[@]}" -gt 0 ]; then second=nan; fi
                ;;
            *)
                first=nan
                # Empty under nan-only, which never probes it.
                if [ "${#anthropic[@]}" -gt 0 ]; then second=anthropic; fi
                ;;
        esac
    else
        add_note "No member that answered has a weight in ${pool}, so nothing was drawn."
    fi
fi

# The NaN attempt starts on the drawn model when it was drawn, and on the first
# NaN member otherwise; the rest stay behind it in declared order.
if [ "$first" != none ] && [ "${#nan[@]}" -gt 0 ]; then
    nan_model="${nan[0]}"
    if [ "$first" = "nan" ]; then nan_model="$reviewer"; fi
    nan_fallbacks=$(printf '%s\n' "${nan[@]}" \
        | jq -Rsc --arg m "$nan_model" 'split("\n") | map(select(. != "" and . != $m))')
fi
# The Anthropic attempt runs the risk member when it was routed there, and the
# drawn member otherwise (first or second).
if [ -z "$anthropic_model" ] && { [ "$first" = anthropic ] || [ "$second" = anthropic ]; }; then
    anthropic_model="${anthropic[0]}"
fi
anthropic_effort=""
if [ -n "$anthropic_model" ]; then
    anthropic_effort=$(pool_field "$anthropic_model" '.reasoning_effort')
    anthropic_effort="${anthropic_effort:-medium}"
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    # The backticks are Markdown, not command substitution.
    # shellcheck disable=SC2016
    {
        printf '### PR-Agent review pool\n\n'
        members=$(printf '`%s` ' ${nan[@]+"${nan[@]}"} ${anthropic[@]+"${anthropic[@]}"} | sed 's/ $//')
        printf 'Override: `%s`. Members that answered: %s.\n\n' "$provider" "${members:-none}"
        if [ "$first" = "none" ]; then
            printf 'No member answered, so no review attempt runs.\n'
        elif [ "$route" = risk ]; then
            printf 'Routed by risk (%s) to `%s`. Second attempt, only if nothing is published: %s.\n' \
                "$risky" "$reviewer" "$second"
        else
            printf 'Drawn to review first: `%s`. Second attempt, only if nothing is published: %s.\n' \
                "$reviewer" "$second"
        fi
        if [ -n "$notes" ]; then printf '\n%s\n' "$notes"; fi
    } >> "$GITHUB_STEP_SUMMARY"
fi
if [ "$first" != "none" ]; then
    printf '::notice::PR-Agent reviews first on %s (%s, override: %s); second attempt: %s.\n' \
        "$reviewer" "$route" "$provider" "$second"
fi

{
    printf 'first=%s\nsecond=%s\nreviewer=%s\nroute=%s\n' "$first" "$second" "$reviewer" "$route"
    printf 'nan_model=%s\nnan_fallbacks=%s\n' "$nan_model" "$nan_fallbacks"
    printf 'anthropic_model=%s\nanthropic_effort=%s\n' "$anthropic_model" "$anthropic_effort"
    printf 'note=%s\n' "$notes"
} >> "$output"
