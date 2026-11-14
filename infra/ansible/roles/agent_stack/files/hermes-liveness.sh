#!/bin/bash
# {{ ansible_managed }} is intentionally absent: this is a static role file.
# Return success only for a healthy gateway. The systemd caller owns notification.
set -eu

container="${1:-}"
case "$container" in
  ''|-*|*[!A-Za-z0-9_.-]*)
    echo "usage: $(basename "$0") <container-name>" >&2
    exit 64
    ;;
esac

if ! status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container")"; then
  echo "Hermes liveness: cannot read $container from the rootless Docker daemon" >&2
  exit 1
fi

if [ "$status" != healthy ]; then
  echo "Hermes liveness: $container is not healthy (${status:-missing})" >&2
  exit 1
fi
