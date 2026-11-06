---
tags: [spec, tasks, templates]
created: "2026-11-01"
---

# Tasks - IDP-036-renovate-gitea

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [ ] Branch created from main: `feat/IDP-036-renovate-gitea`
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

Spec ACs, not #1384's: `[AC<n>]` below names this proposal's criteria, which are numbered independently of the ticket's.

- [x] [P] [AC4] Interim, closed by the deletion task below: `.github/workflows/renovate.yml` carries no literal `renovate-version`, and the step that sets it reads the `common.yaml` image key (`tests/test_renovate_engine_version.py`) ✓ 2026-11-04
- [x] [AC4] Interim, closed by the deletion task below: declare `ghcr.io/renovatebot/renovate:<version>` in `common.yaml` (`ci.renovate.image`) and make the workflow read the tag from it (a `.github/**` change, so the owner merges it) ✓ 2026-11-04
- [ ] [AC4] Interim only: the `ci-workflows` session's kubelab PR deletes `renovate.yml`, `ci.renovate.image` and `tests/test_renovate_engine_version.py`, since the weekly `ci-workflows` run autodiscovers kubelab (mlorentedev/ci-workflows#35). It lands only after a central run has succeeded against kubelab and is linked in that PR. Autodiscovery alone proves nothing: the central run fails without `RENOVATE_TOKEN` or the repository's config, and deleting the local workflow first would stop kubelab's updates.
- [ ] [P] [AC4] Failing test: the `beelink_services` role carries no literal engine version and reads it from `ci-workflows` at the pinned tag
- [ ] [P] [AC1] Failing test: the rendered repository list equals the repositories in `apps.services.core.gitea.organizations`
- [ ] [AC1] [AC3] Template the global config (`extends` the `ci-workflows` preset at a pinned tag, `onboarding: false`, `requireConfig: optional`) and the repository list in `beelink_services`, once the `ci-workflows` session publishes the preset's path and tag
- [ ] [AC3] [AC6] Record a read-only `GITHUB_COM_TOKEN` in SOPS and `SECRET_CATALOG`, then dry-run against one Gitea repository: `renovate/default` resolves at the pinned tag and the engine comes from `renovate/engine.json`
- [ ] [AC6] Declare the bot identity and its organization membership; mint and record its token with the role's existing mint-then-record pair, the mint gated on the SOPS entry being absent; register it in `SECRET_CATALOG`
- [ ] [AC2] Timer and oneshot service (`OnCalendar=hourly`, `Persistent=true`, after the forge's compose unit and a Gitea readiness wait, a container memory limit)
- [ ] [AC2] Provision Beelink twice: first run applies, second reports `changed=0`
- [ ] [AC5] First run: a dashboard issue on each repository; record PR volume over two cycles on #1384
- [ ] [AC7] Remove the dead `dependabot.yml` files (#2140)

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/IDP-036-renovate-gitea/features.json`):

```json
[
  {
    "id": "IDP-036-renovate-gitea-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
