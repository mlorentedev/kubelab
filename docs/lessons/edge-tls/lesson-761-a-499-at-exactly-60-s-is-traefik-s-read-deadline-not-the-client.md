---
id: lesson-761-a-499-at-exactly-60-s-is-traefik-s-read-deadline-not-the-client
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, traefik, gitea, ci]
---

# A 499 at exactly 60 s is Traefik's read deadline, not the client

**Context**: imagesensortool's multi-arch push to the Gitea registry on the Beelink failed on master (#3550). The job resolved `gitea.kubelab.live` publicly, so every blob left the home uplink for the VPS edge and came back over the tailnet to the same node.

**Problem**: Prod Traefik logged the failed uploads as 499, which reads as "the client gave up". The per-line access log for the gitea router showed something else:

- every 499 was a `PUT` whose `total` was 60.000 s from the request start;
- the paired 504s had `total` ≈ 60 s and an origin time of a few µs.

That is the `websecure` entrypoint's `respondingTimeouts.readTimeout`. Traefik v3 defaults it to 60 s, it covers the whole request body, and nothing in the repo declared it. A 26 MB layer over an uplink under about 2.3 Mbit/s needs longer than that. Traefik has no per-router read bound, so raising it would apply to every route on the entrypoint.

**Solution**: Remove the edge from the path instead of widening the bound. The runner hands every job `KUBELAB_FORGE_REGISTRY` (`gitea:3000`) and `KUBELAB_FORGE_NETWORK` (`kubelab`), declared in `gitea_runner.forge_endpoint` and `.job_network`. The workflow attaches its BuildKit container to that network and marks the endpoint `http = true`. Measured: a 50 MB layer took 3.3 s, a rate the uplink cannot carry, and the prod access log shows no gitea `PUT` for those runs. The recipe is in `docs/runbooks/cicd.md`.

**Rule**: Before reading a 499 as a client abort, look at its `Duration`. A cluster of 499s at one round number is a server-side deadline, and the fix is to find the bound, not to retry. Traffic between two services on the same node should never hairpin through the public edge.

**Tags**: `#traefik` `#gitea` `#issue-3550`
