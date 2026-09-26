#!/bin/sh
# r2-backup-watcher probe (BACKUP-055). Runs in the restic image: busybox sh,
# no jq, no YAML parser -- hence plain-text targets and grep.
#
# For every node in the targets file it asks R2, with a READ-ONLY token:
#   readable  the repository opens (catches a revoked token, a wrong password,
#             a missing repository);
#   snapshots at least one exists;
#   missing   every declared source is a directory in the newest snapshot;
#   sentinel  the snapshot holds the capture's success sentinel, which the node
#             writes last and refuses to ship without -- checked here from the
#             destination, so a regression of that guard is visible.
# It does NOT judge age: each node's Uptime Kuma push monitor owns that.
#
# Output is JSON lines for Vector -> Loki -> Grafana: one `r2_backup_node` per
# node for the operator, then exactly one `r2_backup_health` for the rule. The
# fleet line is healthy only if every node is; a per-node `healthy` under the
# rule's `last_over_time` would let a healthy node probed last mask a broken
# one. Every exit path, including a SIGTERM from activeDeadlineSeconds, prints
# the fleet line: silence would leave the verdict to the rule's 24h noData.
set -u

TARGETS="${WATCHER_TARGETS:-/etc/r2-backup-watcher/targets.txt}"
STAGING="${STAGING_DIR:-/opt/node-backup/staging}"
SENTINEL_NAME="${SENTINEL:-.capture-complete}"
TIMEOUT="${RESTIC_TIMEOUT:-60}"

nodes=0
unhealthy=0
completed=0
error=""
finished=0

finish() {
    [ "$finished" -eq 1 ] && return
    finished=1
    healthy=0
    if [ -z "$error" ] && [ "$completed" -ne 1 ]; then
        error="probe stopped before checking every node"
    fi
    if [ -z "$error" ] && [ "$nodes" -eq 0 ]; then
        error="no nodes in the targets file"
    fi
    if [ -z "$error" ] && [ "$unhealthy" -eq 0 ]; then
        healthy=1
    fi
    printf '{"metric":"r2_backup_health","namespace":"kubelab","nodes":%d,"unhealthy":%d,"healthy":%d,"error":"%s"}\n' \
        "$nodes" "$unhealthy" "$healthy" "$error"
}

trap 'error="${error:-terminated by signal}"; finish; exit 1' INT TERM HUP
trap 'finish' EXIT

fail() {
    error="$1"
    exit 1
}

for var in RESTIC_PASSWORD AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
    eval "value=\${$var:-}"
    [ -n "$value" ] || fail "missing env $var"
done
[ -r "$TARGETS" ] || fail "targets file $TARGETS unreadable"

errfile="$(mktemp)" || fail "cannot create a temp file"

# Every restic call goes through here: never a lock (the token cannot write
# one), never the cache (nothing to keep between Jobs), always a timeout.
restic_read() {
    timeout "$TIMEOUT" restic -r "$repo" --no-lock --no-cache "$@" 2>"$errfile"
}

# First stderr line, stripped of what would break the JSON string.
reason_from_stderr() {
    head -n 1 "$errfile" | tr -d '"\\' | cut -c1-160
}

while read -r node repo services; do
    case "$node" in '' | \#*) continue ;; esac
    nodes=$((nodes + 1))
    readable=0
    snapshots=0
    sentinel=0
    missing=""
    reason=""

    if out="$(restic_read snapshots --json --latest 1)"; then
        readable=1
        snapshots="$(printf '%s' "$out" | grep -o '"short_id"' | wc -l | tr -d ' ')"
        [ "$snapshots" -gt 0 ] || reason="no snapshots"
    else
        reason="unreadable: $(reason_from_stderr)"
    fi

    if [ "$readable" -eq 1 ] && [ "$snapshots" -gt 0 ]; then
        # The staging dir only, not the tree beneath it: a full listing of the
        # Beelink's Gitea took 92 s (R3).
        if listing="$(restic_read ls latest "$STAGING")"; then
            for service in $services; do
                printf '%s\n' "$listing" | grep -Fxq "$STAGING/$service" || missing="$missing $service"
            done
            printf '%s\n' "$listing" | grep -Fxq "$STAGING/$SENTINEL_NAME" && sentinel=1
            [ -z "$missing" ] || reason="missing sources"
            [ "$sentinel" -eq 1 ] || reason="${reason:+$reason, }no capture sentinel"
        else
            reason="listing failed: $(reason_from_stderr)"
        fi
    fi

    missing_json=""
    for service in $missing; do
        missing_json="${missing_json:+$missing_json,}\"$service\""
    done

    healthy=0
    if [ "$readable" -eq 1 ] && [ "$snapshots" -gt 0 ] && [ -z "$missing" ] && [ "$sentinel" -eq 1 ] && [ -z "$reason" ]; then
        healthy=1
    else
        unhealthy=$((unhealthy + 1))
    fi

    printf '{"metric":"r2_backup_node","namespace":"kubelab","node":"%s","readable":%d,"snapshots":%d,"missing":[%s],"sentinel":%d,"healthy":%d,"reason":"%s"}\n' \
        "$node" "$readable" "$snapshots" "$missing_json" "$sentinel" "$healthy" "$reason"
done <"$TARGETS"

rm -f "$errfile"
completed=1
finish
[ "$nodes" -gt 0 ] && [ "$unhealthy" -eq 0 ]
