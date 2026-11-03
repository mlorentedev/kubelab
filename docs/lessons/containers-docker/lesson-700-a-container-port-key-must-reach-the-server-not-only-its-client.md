---
id: lesson-700-a-container-port-key-must-reach-the-server-not-only-its-client
type: lesson
status: active
created: "2026-11-02"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, searxng, open-webui, ai-026]
---

# A container port key must reach the server, not only its client

**Context**: AI-025 put SearXNG beside Open WebUI on ace2 with no published
port, and declared its port once in `common.yaml` as `searxng.container_port`.
The independent review (#2970) changed that value from 8080 to 9999 and the
suite stayed green.

**Problem**: The key reached only the client side, Open WebUI's
`SEARXNG_QUERY_URL`. Nothing told SearXNG to listen there, so it kept the
image's 8080 and every search would have failed. The rendered config looked
consistent because both sides happened to agree with the image default. The
pinned image (`2026.10.30-ffa88e3ba`) runs granian, which reads `GRANIAN_PORT`.
Its entrypoint copies `SEARXNG_PORT` into it (`container/entrypoint.sh`).

**Solution**: The compose service sets `GRANIAN_PORT` from the same key, and a
test asserts the key appears on both sides. A post-provision probe runs inside
Open WebUI's container and searches through the URL Open WebUI was given, so a
dead or misbound engine now fails the play. The same change reads Open WebUI's
effective config from `/api/v1/configs/export`. With
`ENABLE_PERSISTENT_CONFIG=false` that export returns every env default,
secrets included, so it is read under `no_log` and only the checked keys are kept.

**Rule**: A port key is wired only when the server's own listen setting reads
it. Find that setting in the pinned image's entrypoint, not in its docs. For a
service with no published port, probe it from where its one client stands.

**Tags**: `#searxng` `#open-webui` `#ai-026`
