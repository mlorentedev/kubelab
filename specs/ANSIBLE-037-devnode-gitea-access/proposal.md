---
id: "ANSIBLE-037-devnode-gitea-access"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-23"
issue: "kubelab#1075"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# ANSIBLE-037: Devnode Gitea Access

> **Naming**: file lives at `<repo>/specs/ANSIBLE-037-devnode-gitea-access/proposal.md`. `ANSIBLE-037-devnode-gitea-access` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #1075: ANSIBLE-037: dev_node has no provisioned git access to Gitea -->

Single paragraph. The user or business problem this feature solves. Link to the vault roadmap or the bitácora board issue if applicable. If you cannot write this in 3 sentences, you do not understand the problem yet.

## What

Concrete behavior change. What does the system do after this PR that it did not do before? Observable, not implementation-focused.

## Out of scope

Things this PR explicitly does NOT include. Forces a sharp boundary and prevents scope creep.

-
-

## Risks / open questions

Failure modes, dependencies, and unknowns to clarify before implementation. If any item here is unresolved, do not move to `tasks.md` yet.

- **BLOCKED — the identity SSOT this depends on does not exist.** #1075's AC2 requires the
  credential to resolve from the identity SSOT rather than be hardcoded. That SSOT is
  `apps.auth.identities` ([ADR-062](../../docs/adr/adr-062-platform-identity-model.md) D3).
  Measured 2026-08-23: `common.yaml` declares only `apps.auth.admin_username: operator`, and
  `grep -rn identities` over `infra/config/values/`, `toolkit/features/` and the `dev_node`
  role returns nothing. The map is decided and unbuilt.
  **AUTH-004 (#1013) builds it, and it is OPEN** — its spec sits at 6/32 tasks with R1-R6
  unmeasured, several of which its own text says must be settled against a live instance
  rather than from documentation. #1077's ordering puts AUTH-004 at step [1] and this spec
  at [2a], downstream of it.
- **Do not route around it.** The obvious shortcut is to provision the agent half now using
  `dev_node_github_token` as precedent. #1075 forbids exactly that — "this must not invent a
  third credential path" — and the overlap cuts the other way: this spec's agent half is
  approximately AUTH-004's AC5, so doing it properly means doing a piece of AUTH-004, which
  needs D3's map first. There is no honest partial.
- **Decided already, so it does not need re-litigating:** the operator chose (2026-08-23)
  **both identities, separate keys** — the human key resolving from `apps.auth.identities`
  per ADR-062, the agent using AUTH-004's machine-token pattern (dedicated account, scoped
  token, login prohibited). #1272 (ANSIBLE-047) stays separate: it is LLM-provider
  credentials, not git access.
- **AC1's `changed: 0` cannot be read fleet-wide until #1300 lands** — the dev_node role
  reports `changed=1` on a settled pass because `npm install -g` prints `changed 2 packages`
  for a no-op. The new tasks' own idempotence is measurable on their own lines; the
  full-role reading is not.

## Acceptance criteria

Observable outcomes. Each must be testable.

- [ ] Outcome 1
- [ ] Outcome 2
- [ ] Outcome 3

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
