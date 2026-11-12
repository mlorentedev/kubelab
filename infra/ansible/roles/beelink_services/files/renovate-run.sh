#!/bin/sh
# One Renovate run against the Gitea forge (IDP-036 AC2), started by
# kubelab-renovate.service. Every value arrives from the unit's Environment= or
# its EnvironmentFile=, and none has a default here: a second declaration of
# the same value is one that drifts, and `:?` fails the run naming the missing
# one instead of running with a guess.
#
# The run is skipped, with exit 0, when Gitea does not answer. On-demand nodes
# are the norm here (ADR-028), so a stack that is down on a node that is up is
# an ordinary state: it is not a failed run, and a unit left `failed` pages
# nobody useful and blocks nothing. The next tick tries again.

set -eu

: "${RENOVATE_IMAGE:?not set: the unit reads it from renovate.env}"
: "${KUBELAB_RENOVATE_HEALTH_URL:?not set}"
: "${KUBELAB_RENOVATE_NETWORK:?not set}"
: "${KUBELAB_RENOVATE_MEMORY:?not set}"
: "${KUBELAB_RENOVATE_NAME:?not set}"
: "${KUBELAB_RENOVATE_ENV_FILE:?not set}"
: "${KUBELAB_RENOVATE_CONFIG:?not set}"
: "${KUBELAB_RENOVATE_CONFIG_MOUNT:?not set}"

# The probe is host curl (base_system installs it). Without it every probe would
# read "command not found" as "Gitea did not answer", and the run would skip
# itself, exit 0, every hour: a green unit that never ran. That is a failure.
command -v curl >/dev/null 2>&1 || {
  echo "kubelab-renovate: curl is not installed, cannot probe Gitea" >&2
  exit 1
}

# 15 probes of at most 1 s, each followed by a 1 s pause: about 30 s, the same
# bound gitea-bootstrap.sh gives the forge. A forge that is merely still starting
# gets its run; one that is stopped costs half a minute and one line.
tries=15
i=0
until curl -fsS -o /dev/null --connect-timeout 1 --max-time 1 "$KUBELAB_RENOVATE_HEALTH_URL" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge "$tries" ]; then
    echo "kubelab-renovate: skipped, Gitea did not answer at $KUBELAB_RENOVATE_HEALTH_URL within 30 s"
    exit 0
  fi
  sleep 1
done

# A run killed at TimeoutStartSec can leave its container behind, and its fixed
# name would then refuse the next run. systemd starts a oneshot unit once at a
# time, so nothing here can be a run still in progress.
docker rm -f "$KUBELAB_RENOVATE_NAME" >/dev/null 2>&1 || true

# --pull never: the provision pulled the engine, under the lab edge's bounded and
# retried pull. A pull here is cut at the unit's timeout on a slow link and starts
# from nothing each time; a missing image fails the unit instead, which is
# the honest report. The token reaches the container through --env-file, never the
# command line, where `ps` and the journal would show it. One mount, read-only,
# and no cache volume: the engine starts clean every run.
exec docker run --rm \
  --name "$KUBELAB_RENOVATE_NAME" \
  --network "$KUBELAB_RENOVATE_NETWORK" \
  --memory "$KUBELAB_RENOVATE_MEMORY" \
  --pull never \
  --env-file "$KUBELAB_RENOVATE_ENV_FILE" \
  -v "$KUBELAB_RENOVATE_CONFIG:$KUBELAB_RENOVATE_CONFIG_MOUNT:ro" \
  "$RENOVATE_IMAGE"
