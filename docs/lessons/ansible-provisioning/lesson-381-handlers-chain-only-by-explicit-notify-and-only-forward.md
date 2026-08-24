---
id: lesson-381-handlers-chain-only-by-explicit-notify-and-only-forward
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, handlers, gitea, idempotence, silent-failure]
---

# Ansible handlers chain only by explicit `notify`, and only forward — a handler nothing notifies is dead code shaped like a safeguard

**Context**: Repairing prod Gitea SSO (#1352). The `beelink_services` role needed two things after `gitea admin auth update-oauth` wrote the new OIDC client secret to SQLite: restart the container so the running web process re-parses its auth source, then wait until Gitea can actually serve OIDC again before anything downstream reads a transient failure as the real answer.

**Problem**: Two distinct traps, and the second is the one worth writing down.

1. **Handlers do not chain implicitly.** Defining `Wait for gitea to answer after restart` immediately after `Restart gitea` does not make it run when the restart fires. Nothing infers the dependency from adjacency. Without an explicit `notify:` on the restart handler, the wait is *defined, syntactically valid, present in the diff, reads like a safeguard, and never executes*. That is strictly worse than omitting it: reviewers see the code and conclude the hazard is handled.
2. **The chain is order-dependent.** A handler may notify another handler **only if the target is defined after it**. Handlers run in definition order within a play, so a backward `notify` targets something that has already had its turn and is silently dropped — the same invisible failure, with the added trap that moving a handler for tidiness can break it.

The compressed folklore version — "Ansible handlers don't chain" — is wrong in a way that matters: it would have argued *against* the fix that was correct here.

**Solution**: `infra/ansible/roles/beelink_services/handlers/main.yml` carries an explicit `notify: Wait for gitea to answer after restart` on the `Restart gitea` handler (line 29), with the wait defined below it (line 34) so the forward-ordering requirement holds. The comment at lines 24-28 states the constraint at the point of use. `Restart gitea` is deliberately a `docker restart gitea`, not the role's existing `Restart beelink services` handler, which does `compose up -d --force-recreate` across the whole stack — blast radius should match the change, so an auth-source change does not bounce MinIO and the GitHub runner.

**Rule**: Every handler needs a traceable notifier. Before merging one, grep for its exact name and confirm something notifies it; a handler with zero inbound references is dead code, and it fails in the direction that produces false confidence. When one handler must notify another, define the target *below* the notifier and say so in a comment, because the ordering is invisible to every linter and to code review. Generalizes past Ansible: any declaratively-registered callback whose registration is separate from its definition can be defined-but-unreachable, and the reviewer's eye reads presence as wiring.

**Tags**: `#ansible` `#handlers` `#silent-failure` `#gitea` `#blast-radius` `#pr-1352`
