---
id: lesson-676-a-rootless-dockerd-reads-its-own-daemon-json-and-only-its-reload-event-proves-a-reload
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, rootless, dockerd]
---
# A rootless dockerd reads its own daemon.json, and only its reload event proves a reload

**Context**: #2835 gave the system dockerd `max-download-attempts: 40` in `/etc/docker/daemon.json`, so that a pull behind the lab edge survives the EOFs that cut its connections about every 10 minutes (lesson-670). ace2 also runs the agent's rootless dockerd, which holds the hermes-kubelab images (4.5 GB and 1.6 GB).

**Problem**: A rootless daemon does not read `/etc/docker/daemon.json`. It reads `$XDG_CONFIG_HOME/docker/daemon.json`, `~/.config/docker/daemon.json` for the agent user, and nothing rendered one, so the daemon most exposed to a large pull kept Docker's 5 attempts. Reloading it has a second trap. The unit that `dockerd-rootless-setuptool.sh` installs reloads with `kill -s HUP $MAINPID`, and its main process is rootlesskit, not dockerd. A HUP that stopped there would change nothing and report success: the unit's reload succeeds, and `docker info` does not show the attempts.

**Solution**: agent_stack renders the agent user's `daemon.json` with the one key, from the same play var as the system daemon (`networking.edge.uplink.max_download_attempts`), and reloads the user unit when the file changes. rootlesskit v3.3.0 forwards every signal from parent to child and from child to dockerd (`pkg/parent/parent.go:246`, `pkg/child/child.go:548`). The role does not rely on that. It reads the daemon's `reload` event back, which carries the value dockerd now uses (`attributes["max-download-attempts"]`, moby `daemon/reload.go:207` at docker-v29.8.2):

```
docker events --since <play start> --until "$(date +%s)" --filter type=daemon \
  --filter event=reload --format '{{index .Actor.Attributes "max-download-attempts"}}'
```

The file holds that one key on purpose. Any option that `dockerd-rootless.sh` also passes as a flag makes dockerd refuse to start on the conflict.

**Rule**: A host with a rootless daemon has two Docker configurations, and a fix to one does not reach the other. Prove a reload by what the process itself reports, here its `reload` event, never by the exit status of the signal that should have caused it.

**Tags**: `#rootless` `#dockerd` `#pr-2855`
