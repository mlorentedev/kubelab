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

- [x] [P] [AC3] Verify the minted token matches the contract **before** wiring anything: fine-grained, 90d expiry, **All repositories** (the recorded decision — assert what was chosen, not the enumerated list that was originally recommended and declined), `contents`+`pull-requests` write and `checks`+`statuses` read only. A token that does not match makes every task below verify the wrong thing. The expiry and repo scope come from the token's settings page; the fine-grained prefix and the `workflows: write` refusal are executable (`probes/f3-workflow-refusal.sh`). **Executable half done ✓ 2026-08-08** — `F3_OK`, exit 0, GitHub's rejection naming the workflow scope verbatim. **Manual half operator-attested ✓ 2026-08-08**: expiry `2026-11-05`, repository access `All repositories`, permissions as specified with no workflows/issues/actions. Recorded as attested rather than observed — the warrant is the owner's confirmation, since the settings page is not reachable from a session. The consequential entry is independently corroborated: f3 observed GitHub refusing a workflow push for the missing scope.
- [x] [AC4] Register the secret in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`) so `make secrets-audit` knows it exists — it was in SOPS but invisible to the audit, which is exactly the drift SSOT discipline exists to prevent. Registered `envs=("staging",)`, **not** "env `common`" as this task originally read: `envs` is the *audit* dimension and the catalog has no `common` pseudo-env. The value lives in `common.enc.yaml`; `audit()` merges common into each env, so staging — the env ace2 provisions with — is where its absence must be reported. Same construction as the Argo CD hub keys under `prod`. Verified: `make secrets-audit` → staging 38/38, token tracked present ✓ 2026-08-08
- [x] [P] [AC6] Add `dev_node_github_token` to the role's defaults as an empty-by-default var, so a run without the secret degrades to "not configured" rather than rendering an empty credential. ✓ 2026-08-08
- [x] [AC1] [AC6] Role task: deliver the token to `gh` via `gh auth login --with-token` reading from **stdin**, never a command argument (SEC-SECRETS-001). Guard with a `no_log: true` and a `changed_when` tied to the auth state, not to the task running. ✓ 2026-08-08
- [x] [AC1] Ensure the same PAT serves git over HTTPS — what makes it one credential instead of two. **Built as an assert, not a `gh auth setup-git` call**, and the change is load-bearing: that command writes `~/.gitconfig`, which the dotfiles bootstrap — run earlier in this same role — redeploys wholesale every pass. Measured on ace2 2026-08-08: the helper was deleted by hand and the bootstrap had restored it before the role's own check ran, so a write here is erased next pass and the task would report `changed` forever (the "one writer per file" failure ANSIBLE-028 already paid for). The wiring is dotfiles' to own; this role owns the token and verifies the contract, failing loudly if the helper is absent. AC1's observable outcome is unchanged — f2 proves it by pushing over HTTPS under the PAT, and it does not care which file declares the helper ✓ 2026-08-08 ✓ 2026-08-08
- [x] [AC4] Confirm idempotence the way ANSIBLE-028 learned to: two consecutive passes, second reports `changed=0`, and read the **task list**, not just the aggregate count. Pass 1 `ok=35 changed=1 failed=0`, pass 2 `ok=35 changed=0 failed=0` with no task reporting changed ✓ 2026-08-08
- [x] [AC2] End-to-end from a tmux session on ace2: clone a private repo, commit, push a branch, `gh pr create`. No agent forwarding, no human at the keyboard. Delete the test PR and branch afterwards. Fixture is `mlorentedev/kubelab-devnode-fixture` — private, README-only, and purpose-built, after the first choice (`go-dsa-sample`, picked for being dormant) turned out to be **archived** and therefore read-only. The probe asserts the fixture is private, that it is **not archived**, and that `origin` is HTTPS, so a configured git protocol cannot route the push over SSH and test a key instead of the PAT. `F2_OK`, exit 0; fixture left with only `main` and zero open PRs ✓ 2026-08-08
- [x] [AC5] Assert the negative: no prod SOPS key, no prod kubeconfig context, no prod-scoped token reachable from ace2. Paths pinned against the real artefact names: `~/.config/sops/age/keys.txt`, `~/.age/key.txt`, `/etc/sops/age.key`, the `sops` binary, and the **contents** of `~/.kube/` (kubeconfigs follow `kubelab-<env>-config`, so a prod context can sit inside `~/.kube/config` with no `*prod*` file present — grep the contents, never the filenames). Deliberately does not assert `~/.kube` is absent: the claim is "no *prod* credential", and D2's dev loop may add a staging kubeconfig later. Re-run **last**, after both node mutations, exit 0 ✓ 2026-08-08
- [x] [AC7] Write the rotation runbook in `docs/runbooks/`: what breaks on expiry day (agent pushes start failing 401), how it surfaces, and the exact mint + re-provision + revoke sequence. Due 2026-11-05. Include a **"narrow repository access?"** step — with the repo axis open, rotation is the natural moment to reconsider it — and, immediately after it, a **"does the acceptance fixture still resolve?"** step: narrowing scope can silently drop the fixture, and f2 would then fail at the clone with a generic auth error that reads like a broken credential rather than a moved goalpost. ✓ 2026-08-08 — revised 2026-08-08 when the fixture moved to `kubelab-devnode-fixture`; the runbook's verify step now runs f2 itself, since `gh auth status` proves storage, not capability.
- [x] [AC6] Confirm the token never reaches a log, a process argument, or a world-readable file — `no_log` on the auth task, and `gh`'s own store holding the credential rather than a hand-rolled dotfile. Both halves verbatim, exit 0; `stat -c %a ~/.config/gh/hosts.yml` = `600` ✓ 2026-08-08

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test ✓ 2026-08-08
- [x] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command — f4 was strengthened after it passed while proving nothing, and f2 after a fixture and a `gh` defect were found to sit inside it ✓ 2026-08-08
- [x] Type checks pass — `make test` runs mypy via pre-commit; 389 passed, 0 failed ✓ 2026-08-08
- [x] Lint passes — pre-commit clean on every commit; `shellcheck` + `bash -n` clean on both probes ✓ 2026-08-08
- [x] No unrelated changes in the diff (no scope creep) — the only production code is the role, the playbook wiring and the `SECRET_CATALOG` entry; everything else is spec, tests and docs ✓ 2026-08-08
- [x] `verification.md` filled in — 7 of 7 executable criteria evidenced with dated output; AC3's manual halves recorded as outstanding rather than assumed ✓ 2026-08-08
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
