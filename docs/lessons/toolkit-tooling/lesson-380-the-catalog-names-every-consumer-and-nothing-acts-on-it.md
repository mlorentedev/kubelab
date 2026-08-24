---
id: lesson-380-the-catalog-names-every-consumer-and-nothing-acts-on-it
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, secrets, catalog, rotation, tool-043]
---

# The secret catalog already names every consumer — both readers turn that into prose for a human, and neither acts on it

**Context**: Diagnosing why the 2026-08-23 prod rotation reported success while prod SSO was down. `credentials-generate` wrote 25 prod secrets and exited 0; nothing in the toolkit knew, or checked, whether any consuming service had received them. Filed as #1356 (TOOL-043).

**Problem**: `SecretSpec` carries a `services: tuple[str, ...]` field — "which services consume this" (`toolkit/features/secrets_manager.py:58`) — and it is populated for essentially the whole catalog. The model *has* the delivery graph. Grepping for every read of it finds exactly two, and neither one executes anything:

- `toolkit/cli/secrets.py:554` — `", ".join(spec.services)` becomes a column in a printed table.
- `toolkit/features/secrets_manager.py:1417` — `restart_services=spec.services` on a `RotationPlan`, which at `secrets_manager.py:933-936` is rendered into a human-readable next-step string.

So the tooling can *tell you* that rotating this key requires restarting Gitea, and has no code path that restarts Gitea, verifies Gitea restarted, or fails when it did not. The knowledge is complete and inert. This is why a rotation can be simultaneously correct at the vault and undelivered at the cluster, and report exit 0.

**Solution**: None applied in this session — the finding is recorded as the root-cause statement for #1356. The fix shape is to make `services` executable rather than decorative: either drive post-rotation restarts from it, or drive a *verification* from it so the command's exit status reflects delivery rather than only the write. Pairs with [lesson-377](../gitops-delivery/lesson-377-rotating-is-not-landing-under-selfheal.md), which is the same gap one layer down: the write landed in SOPS and Argo CD reverted it.

**Rule**: When a registry declares a relationship, grep for its readers before trusting that the relationship is enforced. A field that is populated everywhere and read only by formatters is documentation wearing a data structure's clothes — it will be cited in review as evidence the system handles a case it does not handle. The tell is a `join`/f-string at every call site. Treat "the model knows X" and "the system does X" as separate claims requiring separate evidence.

**Tags**: `#secrets` `#catalog` `#rotation` `#dead-data` `#tool-043` `#issue-1356`
