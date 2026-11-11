#!/bin/sh
# r2-backup-watcher sizing step (BACKUP-075). Runs in the watcher's init
# container, in the pinned rclone image (busybox sh), before probe.sh.
#
# It measures what R2 STORES, by listing objects (S3 ListObjectsV2), and writes
# it for the probe to report:
#   bucket <name> <bytes|null> <seconds>   each bucket the targets name, listed
#                                          once at its root: what R2 bills,
#                                          including anything outside a node's
#                                          prefix. The fleet line sums these.
#   node <node> <bytes|null> <seconds>     each node's repository prefix. The
#                                          shrink rule reads these. A repository
#                                          at its bucket's root reuses that
#                                          bucket's entry rather than being
#                                          listed a second time.
#   packs <node> <count|null> <seconds>    the objects under the repository's
#                                          `data/`: the packs the weekly check
#                                          reads 1/t of (BACKUP-081). Always its
#                                          own listing, whatever the root.
#
# Not `restic stats --mode raw-data`, which this replaced: that walks every tree
# of every snapshot, so its cost follows the snapshot count (the Beelink passed
# 600 s on 2026-10-04), and it counts only referenced blobs, while unreferenced
# packs, index and snapshot files are stored and billed too. A listing costs one
# Class A call per 1 000 objects, whatever the history.
#
# The script ALWAYS exits 0. An init container that fails stops the health probe
# from running, so a listing fault would cost a health run. Every failure here
# is a `null` entry and a `size unknown:` line on stderr, never a zero, which
# would read as "fits". This covers the script only: a failure of the container
# itself (image pull, OOM) still ends the pod before the probe; the manifest
# says what pages then.
set -u

TARGETS="${WATCHER_TARGETS:-/etc/r2-backup-watcher/targets.txt}"
OUT="${WATCHER_SIZES:-/var/run/r2-sizes/sizes.txt}"
SIZE_TIMEOUT="${SIZE_TIMEOUT:-120}"

tmp="$OUT.partial"
: >"$tmp" 2>/dev/null || { echo "r2-backup-watcher: cannot write $tmp; the probe reports every size null" >&2; exit 0; }
errfile="$OUT.err"

credentials=1
for var in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
    eval "value=\${$var:-}"
    [ -n "$value" ] || { echo "r2-backup-watcher: missing env $var; every size is null" >&2; credentials=0; }
done

# One field (`bytes` or `count`) of `rclone size --json` for one bucket or
# bucket/prefix, or a failure.
# The remote is an on-the-fly S3 backend: no config file, the token from AWS_*
# (`env_auth`), the endpoint from the target, and `no_check_bucket` because a
# read-only token cannot create the bucket rclone would otherwise try to make.
list_field() {
    [ "$credentials" -eq 1 ] || { echo "no credentials" >"$errfile"; return 1; }
    out="$(timeout "$SIZE_TIMEOUT" rclone size --json --fast-list \
        ":s3,provider=Cloudflare,env_auth=true,no_check_bucket=true,endpoint='https://$1':$2" 2>"$errfile")" || return 1
    value="$(printf '%s\n' "$out" | sed -n "s/^.*\"$3\": *\([0-9][0-9]*\).*$/\1/p" | head -n 1)"
    [ -n "$value" ] || { echo "rclone returned no $3" >"$errfile"; return 1; }
    printf '%s\n' "$value"
}

# One entry: `<kind> <name> <value|null> <seconds>`, from the arguments only:
# POSIX sh has no `local`, so this sets no variable the caller's loop reads.
# A `packs` entry reads the listing's `count`, every other kind its `bytes`.
measure() {
    started="$(date +%s)"
    field=bytes what=size
    [ "$1" = packs ] && field=count what="pack count"
    if value="$(list_field "$3" "$4" "$field")"; then :; else
        value=null
        echo "r2-backup-watcher: $2: $what unknown: $(head -n 1 "$errfile" | cut -c1-160)" >&2
    fi
    echo "$1 $2 $value $(($(date +%s) - started))" >>"$tmp"
}

[ -r "$TARGETS" ] || { echo "r2-backup-watcher: targets file $TARGETS unreadable; every size is null" >&2; mv "$tmp" "$OUT"; exit 0; }

buckets=""
# `|| [ -n "$node" ]`: `read` fails on a last line with no newline.
while read -r node repo _ || [ -n "$node" ]; do
    case "$node" in '' | \#*) continue ;; esac
    # s3:https://<host>/<bucket>/<prefix>
    rest="${repo#*://}"
    host="${rest%%/*}"
    path="${rest#*/}"
    bucket="${path%%/*}"
    case " $buckets " in
        *" $bucket "*) ;;
        *)
            buckets="$buckets $bucket"
            measure bucket "$bucket" "$host" "$bucket" </dev/null
            ;;
    esac
    if [ "$path" = "$bucket" ]; then
        # A repository at its bucket's root (every node since BACKUP-057's
        # sitting): the bucket listing covered exactly these objects, so the
        # node line reuses it instead of listing them again (#2123).
        # No bucket line means the write of it failed; list the node itself
        # rather than emit an entry with no size.
        root="$(grep "^bucket $bucket " "$tmp" | head -n 1)"
    else
        root=""
    fi
    if [ -n "$root" ]; then
        echo "node $node ${root#"bucket $bucket "}" >>"$tmp"
    else
        measure node "$node" "$host" "$path" </dev/null
    fi
    measure packs "$node" "$host" "$path/data" </dev/null
done <"$TARGETS"

rm -f "$errfile"
# Renamed into place whole, so the probe never reads half a file.
mv "$tmp" "$OUT"
exit 0
