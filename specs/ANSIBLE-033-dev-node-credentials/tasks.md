---
tags: [spec, tasks, templates]
created: "2026-08-07"
---

# Tasks - ANSIBLE-033-dev-node-credentials

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created: `spec/ANSIBLE-033-dev-node-credentials` (implementation continues on `feat/ANSIBLE-033-dev-node-credentials`) ✓ 2026-08-07
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-08-07
- [x] No open questions left in `proposal.md` "Risks / open questions" — expiry resolved to 90d; the GitHub App is deferred to its own ADR, which is a decision, not an open question ✓ 2026-08-07
- [x] Token minted and stored (**pre-move step, kept for the audit trail**): first written to `staging.enc.yaml`, then relocated by the task below. It no longer lives there — `common.enc.yaml` is the only copy. Verified structurally, never decrypted ✓ 2026-08-07
- [x] Repository scope decided: **All repositories**, deliberately and against the agent's recommendation; rationale and compensating controls recorded in `proposal.md`. Token moved to `common.enc.yaml`; `staging` no longer carries it (both verified structurally) ✓ 2026-08-07

## Implementation

> Ansible role work, so "tests" are the `features.json` verification commands run against a provisioned ace2 — same shape as ANSIBLE-028. Static tasks come first so a failure costs nothing; anything touching the live node comes after.

- [ ] [P] [AC3] Verify the minted token matches the contract **before** wiring anything: fine-grained, 90d expiry, **All repositories** (the recorded decision — assert what was chosen, not the enumerated list that was originally recommended and declined), `contents`+`pull-requests` write and `checks`+`statuses` read only. A token that does not match makes every task below verify the wrong thing. The expiry and repo scope come from the token's settings page; the fine-grained prefix and the `workflows: write` refusal are executable (`probes/f3-workflow-refusal.sh`).
- [ ] [AC4] Register the secret in `SECRET_CATALOG` (env `common`) (`toolkit/features/secrets_manager.py`) so `make secrets-audit` knows it exists — today it is in SOPS but invisible to the audit, which is exactly the drift SSOT discipline exists to prevent.
- [ ] [P] [AC6] Add `dev_node_github_token` to the role's defaults as an empty-by-default var, so a run without the secret degrades to "not configured" rather than rendering an empty credential.
- [ ] [AC1] [AC6] Role task: deliver the token to `gh` via `gh auth login --with-token` reading from **stdin**, never a command argument (SEC-SECRETS-001). Guard with a `no_log: true` and a `changed_when` tied to the auth state, not to the task running.
- [ ] [AC1] Role task: `gh auth setup-git` so the same PAT serves git over HTTPS — this is what makes it one credential instead of two.
- [ ] [AC4] Confirm idempotence the way ANSIBLE-028 learned to: two consecutive passes, second reports `changed=0`, and read the **task list**, not just the aggregate count.
- [ ] [AC2] End-to-end from a tmux session on ace2: clone a private repo, commit, push a branch, `gh pr create`. No agent forwarding, no human at the keyboard. Delete the test PR and branch afterwards. Fixture is `mlorentedev/go-dsa-sample` (private, 15KB, dormant since 2024-11 so an acceptance branch cannot collide with real work); the probe asserts the fixture is private and that `origin` is HTTPS, so a configured git protocol cannot route the push over SSH and test a key instead of the PAT.
- [ ] [AC5] Assert the negative: no prod SOPS key, no prod kubeconfig context, no prod-scoped token reachable from ace2. Paths pinned against the real artefact names: `~/.config/sops/age/keys.txt`, `~/.age/key.txt`, `/etc/sops/age.key`, the `sops` binary, and the **contents** of `~/.kube/` (kubeconfigs follow `kubelab-<env>-config`, so a prod context can sit inside `~/.kube/config` with no `*prod*` file present — grep the contents, never the filenames). Deliberately does not assert `~/.kube` is absent: the claim is "no *prod* credential", and D2's dev loop may add a staging kubeconfig later.
- [ ] [AC7] Write the rotation runbook in `docs/runbooks/`: what breaks on expiry day (agent pushes start failing 401), how it surfaces, and the exact mint + re-provision + revoke sequence. Due 2026-11-05. Include a **"narrow repository access?"** step — with the repo axis open, rotation is the natural moment to reconsider it — and, immediately after it, a **"does the acceptance fixture still resolve?"** step: narrowing scope can silently drop `go-dsa-sample`, and f2 would then fail at the clone with a generic auth error that reads like a broken credential rather than a moved goalpost.
- [ ] [AC6] Confirm the token never reaches a log, a process argument, or a world-readable file — `no_log` on the auth task, and `gh`'s own store holding the credential rather than a hand-rolled dotfile.

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

Minimal `features.json` skeleton (drop into `<repo>/specs/ANSIBLE-033-dev-node-credentials/features.json`):

```json
[
  {
    "id": "ANSIBLE-033-dev-node-credentials-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
