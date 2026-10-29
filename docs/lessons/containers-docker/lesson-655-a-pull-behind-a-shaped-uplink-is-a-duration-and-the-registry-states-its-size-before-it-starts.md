---
id: lesson-655-a-pull-behind-a-shaped-uplink-is-a-duration-and-the-registry-states-its-size-before-it-starts
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, ansible, lab-edge]
---

# A pull behind a shaped uplink is a duration, and the registry states its size before it starts

**Context**: On 2026-10-27 `make provision NODE=ace2 ENV=prod` failed at "Pull the
Open WebUI image" with an EOF after 52 minutes. ace2 is behind the lab edge, which
shapes the uplink to `networking.edge.uplink.bandwidth.down_kbit` (2970 kbit/s) on
purpose (ADR-075). Nothing in the play said how long the pull would take, so it
held the run until the connection broke.

**Problem**: A pull was treated as a step, when behind a shaped link it is a
duration that can be known in advance. `docker manifest inspect -v <image>` reads
the manifest list from the registry without pulling, and each platform entry
carries its layers' compressed sizes (`SchemaV2Manifest.layers[].size`, or
`OCIManifest` for an OCI image). For `ghcr.io/open-webui/open-webui:v0.12.0` the
amd64 entry is 1,618,157,731 bytes: 4359 s at 2970 kbit/s, about 73 minutes. Two
details matter. A multi-platform list also holds attestation entries (platform
`unknown/unknown`), which must not be summed. A single-platform image returns one
object rather than a list.

**Solution**: `_includes/image-pull.yml` runs `files/image-pull-estimate.py` on the
node first. An image the node holds counts 0; any other counts its platform's
layers. The include refuses past `image_pull_budget_seconds` (30 minutes) unless
`image_pull_allow_slow`, then pulls with `async` bounded by twice the estimate,
`poll: 15` and `until`/`retries`. Each poll is its own SSH round trip, so the pull
no longer depends on one session staying up for an hour. A retry runs the pull
again: whether it reuses the layers an interrupted attempt fetched depends on the
node's image store (classic or containerd), and was not measured. Ansible's
`until` loop wraps the async poll, and
`async_wrapper` kills a job that outlives its bound. Only a play whose node is
behind the edge sets `image_pull_down_kbit`, from the SSOT key (#2742).

**Rule**: Where a link is shaped on purpose, size a transfer before starting it,
from what the remote already publishes, and make "too long" a refusal with an
override rather than a timeout an hour in.

**Tags**: `#ansible` `#docker` `#lab-edge` `#issue-2742`
