---
id: lesson-213-headscale-node-cleanup-required-before-tailsc
type: lesson
status: active
created: "2026-03-26"
owner: manu
tags: [kubelab, lesson]
---

# Headscale node cleanup required before Tailscale re-registration

**Context**: Destroying and recreating aws1 Spot instance.

**Problem**: Old Headscale node entry (offline) blocks clean registration. New instance registers as `aws1-<random>` with a new IP instead of reusing the `aws1` identity and IP.

**Solution**: Cloud-init calls Headscale API to delete stale node by hostname before `tailscale up`. Requires Headscale management API key (stored in SOPS `aws.headscale_api_key`, passed via Terraform variable to cloud-init).

**Rule**: Cloud-init for cattle instances must include a Headscale node cleanup step before Tailscale registration. Pattern: `curl DELETE /api/v1/node/{id}` for offline nodes matching the hostname, then `tailscale up`.
