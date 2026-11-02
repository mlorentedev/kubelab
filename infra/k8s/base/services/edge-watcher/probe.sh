#!/bin/sh
# edge-watcher probe (NET-005 AC12). Runs in busybox: sh, nc and timeout, no
# JSON or YAML parser -- hence plain-text targets.
#
# For every target it makes one TCP connect to the node's tailnet address and
# probe port, and prints one line, `up` 1 or 0, for Vector -> Loki -> Grafana.
# That single signal covers a dead uplink, a captive portal that came back, a
# dead RPi4, and an rpi3 that went silent behind it (ADR-075 D6).
#
# Every target gets its line on every run, whatever happened to it: refused,
# timed out, a malformed row, no `nc` at all. The rule groups by node, and a
# node missing from the output is a series that stops, which Grafana resolves
# as MissingSeries. A probe that skipped a target would close its alert.
#
# `nc -w` bounds the connect; `timeout` bounds an nc that ignores it, so one
# hung target cannot run the Job into its deadline and cost the others' lines.
#
# No targets at all is a broken render or mount, never a healthy edge: the
# Job fails, prints no line, and the rule's no-data path pages.
set -u

TARGETS="${EDGE_TARGETS:-/etc/edge-watcher/targets.txt}"
REACH_TIMEOUT="${REACH_TIMEOUT:-5}"
# A path, so a test can stand in for it: a busybox shell built as a standalone
# shell runs its own `nc` applet before anything on PATH.
NC="${NC:-nc}"

if [ ! -r "$TARGETS" ]; then
    echo "edge-watcher: cannot read the targets file $TARGETS" >&2
    exit 1
fi

targets=0
while read -r node address port _rest; do
    case "$node" in '' | '#'*) continue ;; esac
    targets=$((targets + 1))
    up=0
    if [ -n "${address:-}" ] && [ -n "${port:-}" ] &&
        timeout $((REACH_TIMEOUT + 2)) "$NC" -z -w "$REACH_TIMEOUT" "$address" "$port" </dev/null >/dev/null 2>&1; then
        up=1
    fi
    printf '{"metric":"edge_probe","namespace":"kubelab","node":"%s","up":%d}\n' "$node" "$up"
done <"$TARGETS"

if [ "$targets" -eq 0 ]; then
    echo "edge-watcher: no targets in $TARGETS" >&2
    exit 1
fi
