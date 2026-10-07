---
tags: [spec, tasks, templates]
created: "2026-10-07"
---

# Tasks - APP-CONFIG-018-sale-digest-import

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `feat/sale-metrics-digest`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

- [x] [AC4] Failing test: the `smtp` credential's field names, and `secure` derived from the port (587 with `infra.smtp.secure: true` reads `false`). Then `render_smtp_credential`.
- [x] [AC1][AC5] Failing test: a prod run imports `kubelab-smtp` and the Cloudflare credential before the digest, once each; staging neither. Then `N8N_SHARED_CREDENTIALS` and `_import_shared_credentials`.
- [x] [AC5] Failing test: removing the sale entry leaves `kubelab-smtp` imported; two workflows import it once.
- [x] [AC3] Failing test: a reference nothing imports, a wrong shared id and divergent Header Auth ids are refused. Then `_unimported_references` and the check in `read_workflow_ids`.
- [x] [AC2] Failing test: each absent SOPS value fails closed naming its path, with no sentinel in the output; every absent placeholder path named at once. Then the resolver stops logging values and collects every absent path.
- [x] [AC6] Digest JSON with fixed ids and `RESOLVE_*` placeholders, three `SECRET_CATALOG` entries, a `PROVIDER_CHECKS` line, `PLACEHOLDER_SSOT` mappings.
- [x] [AC7] README: shared credential, sending email, the digest, removal steps.
- [x] Mutation-check the new tests (14 mutants, all killed).

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [x] Type checks pass (`mypy toolkit/`)
- [x] Lint passes (`make lint`)
- [x] No unrelated changes in the diff (no scope creep)
- [x] `verification.md` filled in
- [x] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/APP-CONFIG-018-sale-digest-import/features.json`):

```json
[
  {
    "id": "APP-CONFIG-018-sale-digest-import-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
