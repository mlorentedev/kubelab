---
id: lesson-670-dockerd-resumes-a-layer-only-within-its-own-attempts-and-a-failed-pull-drops-every-layer
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, ansible, docker, lab-edge]
---

# dockerd resumes a layer only within its own attempts, and a failed pull drops every layer

**Context**: ace2's agent_stack images (3.2 GB) were refilled overnight through the lab edge's shaped uplink (#2703), with the play's pull bounded by its estimate and retried by Ansible (`image_pull_retries`). lesson-655 left open whether a retried pull reuses the layers an interrupted attempt fetched.

**Problem**: It does not. Behind the edge, a pull's connections ended in `unexpected EOF` 18 times in 111 minutes, 2 to 12 minutes apart, sometimes on every open layer in the same second. dockerd retries a failed layer download itself, up to `max-download-attempts` (default 5), and does not reset the count when an attempt made progress. Each of those retries resumes from the layer's partial file in `/var/lib/docker/tmp` with a Range request. After the last attempt, though, dockerd fails the pull and the overlay2 store drops every layer the pull had registered (`Download failed after 5 attempts`, then `Cleaned up layer` in the journal). The play's retry then pulls from nothing. Open WebUI's 1.6 GB image needed more than five EOFs' worth of time, so three Ansible attempts of about 30 minutes each ended at the same point and kept nothing.

**Solution**: `"max-download-attempts": 40` in the docker role's `daemon.json`. dockerd's pause after attempt k is 5k seconds, linear and uncapped (moby `daemon/internal/distribution/xfer/download.go`), so 40 attempts sleep at most 65 minutes in all, which is also how long a blob that never downloads takes to fail. `tests/test_image_pull_budget.py` holds the value between "survives the edge's EOFs" (at least 37, as many as Open WebUI's largest layer can meet) and "fails a dead blob within two hours". Applied to ace2 with `make provision NODE=ace2 ENV=prod TAGS=docker` (`changed=2`, rerun `changed=0`). On the next EOF (2026-10-30T06:50:56Z, `retrying (1/40)` on three layers), the same three `GetImageBlob*` files went from 26.6 MB to 38.3 MB at the next sample instead of starting over.

**Rule**: Behind an uplink that drops connections, progress is kept only by the retry closest to the bytes. A retry wrapped around the whole operation (Ansible's `retries`, a CI re-run) restarts from zero whenever the inner layer cleans up on failure. Find the innermost retry, check whether it resumes, and size its count for the drop interval, before raising any outer one. The play's `image_pull_retries` still covers what dockerd does not retry, such as a manifest the registry refuses before any layer is fetched.

**Tags**: `#docker` `#lab-edge` `#issue-2703` `#issue-2834`
