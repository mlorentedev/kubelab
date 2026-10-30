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

**Solution**: agent_stack renders the agent user's `daemon.json` with the one key, from the same play var as the system daemon (`networking.edge.uplink.max_download_attempts`). The file holds that one key on purpose. Any option that `dockerd-rootless.sh` also passes as a flag makes dockerd refuse to start on the conflict.

#2855 also reloaded the user unit and read the daemon's `reload` event back, and the event read 40. rootlesskit v3.3.0 does forward the HUP to dockerd (`pkg/parent/parent.go:246`, `pkg/child/child.go:548`). But the event proves less than the PR claimed, for two reasons, both found by the spec's independent review.

- At docker-v29.8.2, `reloadMaxDownloadAttempts` (`daemon/reload.go:200`) writes the value into the config store and the event's attributes, and nothing else. The graphdriver's layer download manager takes its attempts once, when the daemon starts (`daemon/images/service.go:60`). So a reload changes the event and not the retry gate (`xfer/download.go:289`).
- The agent's daemon runs the containerd image store (`docker info` reads `driver-type io.containerd.snapshotter.v1`), and nothing under `daemon/containerd/` reads the attempts at all. On this daemon the key has no effect, restart included.

The follow-up to #2855 removed the reload and its read-back, and kept the file. What the containerd store does on an EOF is #2868.

**Rule**: A host with a rootless daemon has two Docker configurations, and a fix to one does not reach the other. Prove a setting by its consumer, not by the config. Before configuring a pull setting, read which image store the daemon runs (`docker info --format '{{json .DriverStatus}}'`) and check that the store reads the key. Then prove the effect where the key is used, for attempts the daemon's own `Download failed, retrying (n/M)` line, or a daemon started after the file. A reload event proves that the config store changed, and no more.

**Tags**: `#rootless` `#dockerd` `#pr-2855`
