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
#             destination, so a regression of that guard is visible;
#   identity  the repository id (`restic cat config`) equals the one declared in
#             `backup.r2.repository_ids` (BACKUP-058). A deleted repository that
#             was re-created, or swapped for another, opens and holds snapshots
#             like the real one; its id is the only thing that differs. A node
#             with no declared id is unhealthy too: accepting a new history is a
#             reviewed change, never a default.
# It does NOT judge age: each node's Uptime Kuma push monitor owns that.
#
# It also reports each repository's size (BACKUP-057 Q3), `restic stats --mode
# raw-data`: the stored, compressed bytes of every blob the snapshots reference.
# That is what the bucket lock multiplies, and what the free tier is billed on,
# less index and snapshot files and packs not yet pruned. A size is never a
# health check: `stats` failing leaves the node healthy and its size `null`,
# never 0, which would read as "fits". The fleet sum is `null` unless every
# node was sized, because a partial sum understates the fleet.
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
STATS_TIMEOUT="${STATS_TIMEOUT:-600}"

nodes=0
unhealthy=0
fleet_bytes=0
unsized=0
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
    fleet_size=null
    if [ "$completed" -eq 1 ] && [ "$nodes" -gt 0 ] && [ "$unsized" -eq 0 ]; then
        fleet_size="$fleet_bytes"
    fi
    printf '{"metric":"r2_backup_health","namespace":"kubelab","nodes":%d,"unhealthy":%d,"healthy":%d,"raw_bytes":%s,"error":"%s"}\n' \
        "$nodes" "$unhealthy" "$healthy" "$fleet_size" "$error"
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

# `stats --mode raw-data` walks every tree of every snapshot, so it needs a
# budget of its own: the Beelink's Gitea tree outran RESTIC_TIMEOUT (2026-09-30).
restic_stats() {
    timeout "$STATS_TIMEOUT" restic -r "$repo" --no-lock --no-cache stats --mode raw-data --json 2>"$errfile"
}

# First stderr line, stripped of what would break the JSON string.
reason_from_stderr() {
    head -n 1 "$errfile" | tr -d '"\\' | cut -c1-160
}

# `|| [ -n "$node" ]`: `read` fails on a last line with no newline, and that
# node would silently drop out of a fleet reported healthy.
while read -r node repo declared_id services || [ -n "$node" ]; do
    case "$node" in '' | \#*) continue ;; esac
    nodes=$((nodes + 1))
    readable=0
    snapshots=0
    sentinel=0
    missing=""
    reason=""
    repository_id=""
    size=null

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

    # Checked whenever the repository opens, snapshots or not: an empty
    # replacement is still a replacement.
    if [ "$readable" -eq 1 ]; then
        if config="$(restic_read cat config --json)"; then
            # Same extraction as the node's node-backup-ship.sh (role
            # node_backup): the two must agree on which field is the id.
            repository_id="$(printf '%s\n' "$config" | sed -n 's/^.*"id": *"\([0-9a-f]*\)".*$/\1/p' | head -n 1)"
            if [ -z "$repository_id" ]; then
                reason="${reason:+$reason, }repository id unreadable"
            elif [ "$declared_id" = "-" ]; then
                reason="${reason:+$reason, }repository id not declared"
            elif [ "$repository_id" != "$declared_id" ]; then
                reason="${reason:+$reason, }repository id changed"
            fi
        else
            reason="${reason:+$reason, }config unreadable: $(reason_from_stderr)"
        fi
    fi

    # After every health check, so a slow `stats` cannot starve them of the
    # timeout. Its failure is logged, not judged.
    if [ "$readable" -eq 1 ]; then
        started="$(date +%s)"
        if stats="$(restic_stats)"; then
            size="$(printf '%s\n' "$stats" | sed -n 's/^.*"total_size": *\([0-9][0-9]*\).*$/\1/p' | head -n 1)"
        fi
        if [ -z "$size" ] || [ "$size" = null ]; then
            size=null
            echo "r2-backup-watcher: $node: size unknown: $(reason_from_stderr)" >&2
        fi
        echo "r2-backup-watcher: $node: stats took $(($(date +%s) - started))s" >&2
    fi
    if [ "$size" = null ]; then
        unsized=$((unsized + 1))
    else
        fleet_bytes=$((fleet_bytes + size))
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

    printf '{"metric":"r2_backup_node","namespace":"kubelab","node":"%s","readable":%d,"snapshots":%d,"missing":[%s],"sentinel":%d,"repository_id":"%s","raw_bytes":%s,"healthy":%d,"reason":"%s"}\n' \
        "$node" "$readable" "$snapshots" "$missing_json" "$sentinel" "$repository_id" "$size" "$healthy" "$reason"
done <"$TARGETS"

rm -f "$errfile"
completed=1
finish
[ "$nodes" -gt 0 ] && [ "$unhealthy" -eq 0 ]
