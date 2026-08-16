---
tags: [spec, tasks, templates]
created: "2026-08-16"
---

# Tasks - ANSIBLE-041-aws1-replacement-provisioning

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Design decision this breakdown resolves

`proposal.md` left one question open: whether readiness means "sshd answers" or "cloud-init finished". **It means both, in that order, and they are separate waits.** `wait_for_connection` cannot run before sshd exists, and `cloud-init status --wait` cannot run before a connection exists — but sshd comes up well before cloud-init installs K3s and registers Tailscale, so an SSH-only gate would start provisioning against a half-built node. The failure would be confusing rather than dangerous, which is the worst kind to leave in a path that runs unattended.

The wait therefore lives in its own playbook rather than in `provision-aws1.yml`: bare-metal nodes have no cloud-init, and the same target is wanted for any future cloud node. It is a playbook and not Makefile shell because the Makefile must carry no inline scripts.

## Setup

- [ ] Branch created from master: `feat/ANSIBLE-041-aws1-replacement-provisioning`
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] Open question on the readiness signal is resolved — see "Design decision" above

## Implementation

- [ ] [P] [AC2] Failing test `tests/test_aws1_replace_chain.py`: parse the `aws1-replace` recipe from the `Makefile` and assert it invokes the readiness wait, `provision-aws1` and `deploy-argocd` in that order; that it contains no "then run" prose instructing a human; and that no stage is suffixed `|| true`. Static parse — no AWS, runs in `make test-fast`.
- [ ] [AC1] [AC2] Add `infra/ansible/playbooks/wait-node-ready.yml`: `gather_facts: false`, `wait_for_connection` with an explicit timeout, then `cloud-init status --wait` guarded by a `stat` on the cloud-init binary so bare-metal nodes skip it rather than fail. Add the `make wait-node-ready NODE=x ENV=y` wrapper.
- [ ] [AC2] Failing test then fix for the **unresolvable-name** path: when the MagicDNS name does not resolve, the play must fail with a message naming the given-name cause (`common.yaml:585`, stale Headscale record → `aws1-<random>`), not a bare "host unreachable". This is the diagnostic the proposal's OPEN risk demands.
- [ ] [AC2] Verify the timeout path empirically: point `wait-node-ready` at an unreachable host and capture the non-zero exit and its diagnostic. A wait that cannot be shown to time out is a sleep with extra steps.
- [ ] [AC1] Rewrite the `aws1-replace` recipe to chain terraform → `wait-node-ready` → `provision NODE=aws1 ENV=hub` → `deploy-argocd`, deleting the `Wait ~5 min, then run:` echo. Each stage's failure must abort the chain.
- [ ] [AC1] Re-run the AC2 test suite green against the rewritten target.
- [ ] [AC3] Against the **restarted** aws1 once Spot capacity returns: `make provision NODE=aws1 ENV=hub TAGS=maintenance` twice (expect `changed>0` then `changed=0`), then `make maintain-notify-test NODE=aws1 ENV=hub` (expect `Result=success, ExecMainStatus=0`). Capture both recaps verbatim.
- [ ] [AC3] Assert the resolved MagicDNS name after that restart — `dig +short aws1.kubelab.internal` — and record it, so the given-name property is measured rather than assumed.
- [ ] [AC4] Write `verification.md` naming exactly which segment has direct evidence and which does not: the terraform→wait handoff is exercised against a restarted, not replaced, instance.
- [ ] [AC5] Record the deferred full-cycle evidence as a comment on #1102 after archive, with the trigger condition from #1106.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff — in particular **no Terraform spot-option edits** (that is #1106) and **no edits to `provision-aws1.yml`'s stale header** (also #1106)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder
- [ ] Independent adversarial review obtained before archive — the identity gate is on repo-wide, so this needs a non-Anthropic reviewer via `dotf spec review`. Check that `dotf secrets` is unlocked *before* reaching the archive step, not at it.

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

**AC5 carries no feature entry by design.** Its evidence depends on a replacement that is deliberately not scheduled; a feature with an unrunnable `verification` would sit `pending` forever and read as an incomplete spec rather than a declared deferral. The deferral lives in `verification.md` and on #1102.

Minimal `features.json` skeleton (drop into `<repo>/specs/ANSIBLE-041-aws1-replacement-provisioning/features.json`):

```json
[
  {
    "id": "ANSIBLE-041-aws1-replacement-provisioning-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
