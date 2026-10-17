---
id: lesson-579-replacement-token-probe-every-route
type: lesson
status: active
created: "2026-10-16"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, vikunja, n8n, tokens]
---

# A replacement token that passes the new probe can have lost every old route

**Context**: n8n's staging Vikunja token was replaced (#2327) so the workflow could read Kanban buckets. The old token answered 401 on buckets; the new one read them. That was the only thing checked before the merge.

**Problem**: Vikunja API tokens are scoped by route group and the scopes cannot be edited after creation, so a new token is a new, independent grant, not the old one plus a permission. The new token was minted with the project, view and bucket groups only. From inside the n8n pod: `/projects/4/views/16/buckets` 200, but `/tasks?s=`, `/tasks/{id}`, `PUT /projects/4/tasks`, `/labels` and `/user` all 401. Forge sync and Slack capture, which live on the task group, were dead on staging from the merge until #2344 found it, with `make n8n-probe` red the whole time (#2344).

**Solution**: Verify a replacement credential against every route its consumers use, not against the one that motivated the change. For n8n and Vikunja the consumers' contract is the probe: `make n8n-probe ENV=<env>` before the merge, not a bucket read. List the routes with a loop of `fetch` calls inside the pod and compare them to the old token's list.

**Rule**: A replacement credential is judged by the union of what the old one did and what the new one must do. When scopes cannot be edited, minting is a rebuild of the grant: write down the route groups to select, and run the consumers' own acceptance test after the swap, before declaring it landed.

**Tags**: `#tokens` `#vikunja` `#n8n` `#issue-2344`
