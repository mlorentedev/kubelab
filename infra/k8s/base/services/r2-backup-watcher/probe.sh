#!/bin/sh
# r2-backup-watcher probe (BACKUP-055). Runs in the restic image: busybox sh,
# no jq, no YAML parser -- hence plain-text targets and grep.
#
# For every node in the targets file it asks R2, with a READ-ONLY token:
#   readable  the repository opens (catches a revoked token, a wrong password,
#             a missing repository);
#   snapshots at least one exists;
#   missing   every declared source is a directory in the newest snapshot, not
#             a file of that name (#1865);
#   sentinel  the snapshot holds the capture's success sentinel, which the node
#             writes last and refuses to ship without -- checked here from the
#             destination, so a regression of that guard is visible;
#   identity  the repository id (`restic cat config`) equals the one declared in
#             `backup.r2.repository_ids` (BACKUP-058). A deleted repository that
#             was re-created, or swapped for another, opens and holds snapshots
#             like the real one; its id is the only thing that differs. A node
#             with no declared id is unhealthy too: accepting a new history is a
#             reviewed change, never a default.
# It MEASURES age and judges none (BACKUP-032): `snapshot_age_seconds` is for
# the freshness rule in Grafana, which knows the ADR-028 class. Always-on nodes
# keep their Uptime Kuma push monitor; on-demand ones, whose monitor is muted,
# are judged by that rule, and only while `reachable` says they are up.
#
# reachable  a TCP connect to the node's tailnet address and probe port. It is
#            what tells "off" from "up and not shipping". On an always-on node
#            it is also the probe's positive control: that node is never off,
#            so 0 there means the probe cannot see the fleet, and the node is
#            reported unhealthy rather than every on-demand node reading "off".
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
REACH_TIMEOUT="${REACH_TIMEOUT:-5}"
# A path, so a test can stand in for it: a busybox shell built as a standalone
# shell runs its own `nc` applet before anything on PATH.
NC="${NC:-nc}"

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

# The epoch of one restic `time`, or a failure when the stamp is not the shape
# restic writes. restic stamps a snapshot with the SOURCE node's offset and a
# fraction of 8 or 9 digits (measured 2026-10-02: `+02:00` on the homelab, `Z`
# on the VPS), and busybox `date -d` takes neither, so both are split off here.
epoch_of() {
    # shellcheck disable=SC2046 # the split into fields is the point
    set -- $(printf '%s\n' "$1" | sed -nE 's/^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]+)?(Z|([+-])([0-9]{2}):([0-9]{2}))$/\1 \2 \5 \6 \7/p')
    [ $# -eq 2 ] || [ $# -eq 5 ] || return 1
    seconds="$(date -u -d "$1 $2" +%s 2>/dev/null)" && [ -n "$seconds" ] || return 1
    if [ $# -eq 5 ]; then
        # `${4#0}`: `$((08))` is an octal error in busybox and dash alike.
        offset=$((${4#0} * 3600 + ${5#0} * 60))
        if [ "$3" = "+" ]; then seconds=$((seconds - offset)); else seconds=$((seconds + offset)); fi
    fi
    printf '%s\n' "$seconds"
}

# The newest epoch among every snapshot in a `snapshots --json` answer: one per
# path group, so not the first. Fails if any stamp is unreadable, because a
# skipped one could be the newest.
newest_epoch_of() {
    newest=""
    stamps="$(printf '%s' "$1" | grep -o '"time": *"[^"]*"' | cut -d'"' -f4)"
    [ -n "$stamps" ] || return 1
    while IFS= read -r stamp; do
        epoch="$(epoch_of "$stamp")" || return 1
        if [ -z "$newest" ] || [ "$epoch" -gt "$newest" ]; then newest="$epoch"; fi
    done <<STAMPS
$stamps
STAMPS
    printf '%s\n' "$newest"
}

# Whether `$listing` (one `ls --json` entry per line) holds an entry of type
# $1 at exactly path $2. The closing `",` pins the whole path, so `n8n-old`
# is not `n8n`; restic writes `type` and `path` into the same line.
has_entry() {
    printf '%s\n' "$listing" | grep -F "\"path\":\"$2\"," | grep -Fq "\"type\":\"$1\""
}

# First stderr line, stripped of what would break the JSON string.
reason_from_stderr() {
    head -n 1 "$errfile" | tr -d '"\\' | cut -c1-160
}

# `|| [ -n "$node" ]`: `read` fails on a last line with no newline, and that
# node would silently drop out of a fleet reported healthy.
while read -r node repo declared_id address port class services || [ -n "$node" ]; do
    case "$node" in '' | \#*) continue ;; esac
    nodes=$((nodes + 1))
    readable=0
    snapshots=0
    sentinel=0
    missing=""
    reason=""
    repository_id=""
    size=null
    newest_snapshot=null
    snapshot_age=null
    reachable=0

    if out="$(restic_read snapshots --json --latest 1)"; then
        readable=1
        snapshots="$(printf '%s' "$out" | grep -o '"short_id"' | wc -l | tr -d ' ')"
        if [ "$snapshots" -gt 0 ]; then
            # Fails closed: a time the probe cannot read would leave the
            # freshness rule blind for this node with nothing paging.
            if newest="$(newest_epoch_of "$out")"; then
                newest_snapshot="\"$(date -u -d "@$newest" +%Y-%m-%dT%H:%M:%SZ)\""
                snapshot_age=$((${PROBE_NOW:-$(date +%s)} - newest))
            else
                reason="snapshot time unreadable"
            fi
        else
            reason="no snapshots"
        fi
    else
        reason="unreadable: $(reason_from_stderr)"
    fi

    if [ "$readable" -eq 1 ] && [ "$snapshots" -gt 0 ]; then
        # The staging dir only, not the tree beneath it: a full listing of the
        # Beelink's Gitea took 92 s (R3). `--json`, because a plain listing
        # prints a file and a directory alike, and a source counts only as a
        # directory (#1865).
        if listing="$(restic_read ls --json latest "$STAGING")"; then
            for service in $services; do
                has_entry dir "$STAGING/$service" || missing="$missing $service"
            done
            has_entry file "$STAGING/$SENTINEL_NAME" && sentinel=1
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

    # Independent of R2: an unreadable repository on a node that is up is a
    # different page from one on a node that is off. `</dev/null`: the loop's
    # stdin is the targets file, and nothing may read from it but `read`.
    if timeout $((REACH_TIMEOUT + 2)) "$NC" -z -w "$REACH_TIMEOUT" "$address" "$port" </dev/null >/dev/null 2>&1; then
        reachable=1
    elif [ "$class" = "always-on" ]; then
        reason="${reason:+$reason, }probe cannot reach an always-on node"
    fi

    # After every health check, so a slow `stats` cannot starve them of the
    # timeout. Its failure is logged, not judged.
    if [ "$readable" -eq 1 ]; then
        started="$(date +%s)"
        # A `stats` that exits 0 leaves nothing on stderr, so a missing
        # `total_size` names itself rather than logging an empty reason.
        if stats="$(restic_stats)"; then
            size="$(printf '%s\n' "$stats" | sed -n 's/^.*"total_size": *\([0-9][0-9]*\).*$/\1/p' | head -n 1)"
            why="stats returned no total_size"
        else
            why="$(reason_from_stderr)"
        fi
        if [ -z "$size" ] || [ "$size" = null ]; then
            size=null
            echo "r2-backup-watcher: $node: size unknown: $why" >&2
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

    printf '{"metric":"r2_backup_node","namespace":"kubelab","node":"%s","class":"%s","readable":%d,"snapshots":%d,"missing":[%s],"sentinel":%d,"repository_id":"%s","newest_snapshot":%s,"snapshot_age_seconds":%s,"reachable":%d,"raw_bytes":%s,"healthy":%d,"reason":"%s"}\n' \
        "$node" "$class" "$readable" "$snapshots" "$missing_json" "$sentinel" "$repository_id" "$newest_snapshot" "$snapshot_age" "$reachable" "$size" "$healthy" "$reason"
done <"$TARGETS"

rm -f "$errfile"
completed=1
finish
[ "$nodes" -gt 0 ] && [ "$unhealthy" -eq 0 ]
