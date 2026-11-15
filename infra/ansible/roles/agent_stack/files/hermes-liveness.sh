#!/bin/bash
# Static role file, installed root-owned and executed as the agent's uid.
# Only one recent start is graced; every sustained or repeated failure is fatal.
set -eu

GRACE_SECONDS=90
container="${1:-}"
case "$container" in
  ''|-*|*[!A-Za-z0-9_.-]*)
    echo "usage: $(basename "$0") <container-name>" >&2
    exit 64
    ;;
esac

if ! details="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}|{{.State.Running}}|{{.State.StartedAt}}|{{.State.RestartCount}}' "$container")"; then
  echo "Hermes liveness: cannot read $container from the rootless Docker daemon" >&2
  exit 1
fi

status=${details%%|*}
rest=${details#*|}
running=${rest%%|*}
rest=${rest#*|}
started_at=${rest%%|*}
restart_count=${rest##*|}

if [ "$status" = healthy ] && [ "$running" = true ]; then
  exit 0
fi

if [ "$status" != starting ]; then
  echo "Hermes liveness: $container is not healthy (${status:-missing})" >&2
  exit 1
fi

# A stopped container and malformed runtime metadata never qualify for grace.
if [ "$running" != true ]; then
  echo "Hermes liveness: $container is starting but not running" >&2
  exit 1
fi
case "$restart_count" in
  ''|*[!0-9]*)
    echo "Hermes liveness: invalid restart count for $container" >&2
    exit 1
    ;;
esac
if ! started_epoch="$(python3 -c 'import datetime,re,sys; value=re.sub(r"\.(\d{6})\d+",r".\1",sys.argv[1]).replace("Z","+00:00"); print(int(datetime.datetime.fromisoformat(value).timestamp()))' "$started_at")"; then
  echo "Hermes liveness: invalid start time for $container" >&2
  exit 1
fi
age=$(( $(date +%s) - started_epoch ))

# One initial/automatic start may be inside Compose's 60s start_period plus one
# 30s health interval. A second automatic restart is a crash loop, not a blip.
if [ "$restart_count" -le 1 ] && [ "$age" -ge 0 ] && [ "$age" -lt "$GRACE_SECONDS" ]; then
  exit 0
fi

echo "Hermes liveness: $container is not healthy (starting age=${age}s restart_count=$restart_count)" >&2
exit 1
