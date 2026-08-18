---
id: lesson-058-headscale-v0-28-cli-route-commands
type: lesson
status: active
created: "2026-02-21"
owner: manu
tags: [kubelab, lesson]
---

# Headscale v0.28 CLI Route Commands

**Context**: Trying to approve subnet routes in Headscale v0.28.

**Problem**: Online documentation and project memory referenced `headscale routes list` and `headscale routes enable -r <ID>` — neither exists in v0.28. The `routes` command was moved under `nodes`.

**Solution**: Correct CLI: `headscale nodes list-routes`, `headscale nodes approve-routes -i <NODE_ID> --routes <CIDR>`. The `--routes` flag is a SET operation (replaces all approved routes, not additive).

**Rule**: Always check `--help` before running Headscale CLI. The API changes between minor versions. Running without `--routes` can clear existing approved routes.
