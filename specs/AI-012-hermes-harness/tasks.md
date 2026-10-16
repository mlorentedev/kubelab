---
tags: [spec, tasks, templates]
created: "2026-10-10"
---

# Tasks - AI-012-hermes-harness

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `feat/ai009-hermes-harness` (it carries AI-009's AC3 record too) ✓ 2026-10-10
- [x] `proposal.md` complete. Operator decisions 2026-10-10: a new spec; research jobs included; the fallback is Anthropic Haiku with a 20 USD cap; triage hourly.
- [x] R1 (Anthropic key) answered: workspace `hermes-kubelab`, 20 USD monthly limit read in the Console (`verification.md`). ✓ 2026-10-15
- [ ] R2 (BrightData token, operator directory name) and R3 (alert channels) answered before the PR that needs each. R4 to R6 are measured in their PRs.

## Implementation

One PR per block, in this order. Each block starts with the failing test.

### PR 1: config parity (AC1)

- [x] [P] [AC1] `tests/test_hermes_config.py`: assert each applicable `config-desired.yaml` key renders with its declared value. Read the declarations from `common.yaml`, not literals. Expected: FAIL. ✓ 2026-10-10
- [x] [AC1] Declare the values under `apps.services.ai.hermes_kubelab.agent_config` (name to be confirmed with the operator) and render them in `hermes-config.yaml.j2`. Check tirith's presence in the image before rendering `security.tirith_*`. ✓ 2026-10-10
- [x] [AC1] Live: provision `changed=1`, then `0`. `hermes config show` inside the gateway reads every key back. ✓ 2026-10-10

### PR 2: fallback (AC2, needs R1)

Unblocked by Hermes v0.22 (draft #2204, lesson-557). The pin moved to v0.22.1 in the same PR, which retires the tirith scanner (verification.md, 2026-10-15).

- [x] [AC2] Test (written in draft #2204): the env renders `ANTHROPIC_API_KEY` only when the key exists, and `fallback_providers` names the pinned Haiku. `SECRET_CATALOG` gains the entry. ✓ 2026-10-10
- [x] [AC2] Runbook: create the workspace, its 20 USD monthly limit and its key, step by step (`## Models`, "Create the workspace and key"). ✓ 2026-10-15
- [x] [AC2] Live (R5): with NaN refused for the agent's uid, a turn completes on Haiku. ✓ 2026-10-15

### PR 3: identity (AC3)

- [ ] [AC3] Test: `SOUL.md` renders from the role and is mounted `:ro` over `<data>/SOUL.md`. The private profile is joined on the node with `ansible.builtin.assemble` (`remote_src: true`): the public template is rendered to a fragment beside the mirror's profile, so the profile's content never passes through the controller. No `slurp`, and no diff output.
- [ ] [AC3] Adapt the persona from `hermes-nan/SOUL.md` and `AGENTS.md`, without NaN, Telegram or pod references.
- [ ] [AC3] Live: an edit to `SOUL.md` from inside the gateway fails, and the next turn's context lists the role's file.

### PR 4a: job reconciler and the session record (AC4, AC5 in part)

- [x] [AC4] Measure R6: does the gateway pick up `hermes cron create` without a restart? No restart needed (`verification.md`). ✓ 2026-10-15
- [x] [AC4] Test: declared jobs render into the reconcile task's input. A job is identified by name. Undeclared jobs that the role did not create are untouched, by the `kubelab:` name prefix. ✓ 2026-10-15
- [x] [AC4] Reconcile task: list, diff, create, replace, remove. `changed_when` comes from the diff, and it is `CHECK=1`-safe. `edit` replaces `remove` + `create`, which would lose the job's history. ✓ 2026-10-15
- [x] [AC5] Job: daily session record, fed by a read-only context script and gated by `wakeAgent`. ✓ 2026-10-15
- [x] [AC5] Live: the session record's commit lands under the zone. ✓ 2026-10-15

### PR 4b: memory capture and the digest (AC5 in part)

PR 4 was split: with both halves it was about 650 non-test lines against the 300 cap.

- [x] [AC5] Job: memory capture. The zone's `memories/` directory is mounted over the gateway's `memories/`, so the existing sync commits what the agent remembers. ✓ 2026-10-15
- [x] [AC5] Job: daily health and consumption digest, a no-agent script (gateway, sandbox and sidecar through `docker.sock`, data-directory disk, month-to-date tokens per model and provider). Delivery goes to `slack:<home_channel>`. ✓ 2026-10-15
- [x] [AC5] Live: the digest reaches `#agent-fleet`, and a memory commit lands under the zone. ✓ 2026-10-15

### PR 5: skills and the repository mirror (AC9, AC10)

- [ ] [AC9] Test: the manifest in `common.yaml` installs each `SKILL.md` from the vault mirror. A missing file fails. Managed skills are read-only to the gateway.
- [ ] [AC10] A root-owned read-only mirror of the repository's `docs/`, mounted in the sandbox and served by the MCP bridge.

### PR 6: curator (AC6)

- [ ] [AC6] Port `curator-analyze.py` and `emit-proposals.py` as host units of the agent's user, which can see the clone, plus the judge as an agent job that reads the analyzer's output.
- [ ] [AC6] `dispose-proposals` (dotfiles skill) reads `hermes-kubelab/proposals/`, landed in a sibling worktree of that repository.

### PR 7: research (AC7, needs R2, R4)

- [ ] [AC7] BrightData MCP (R4 decides where it runs). The token goes in `SECRET_CATALOG`.
- [ ] [AC7] The three research jobs, with prompts read from the operator directory.

### PR 8: triage (AC8, needs R3; closes #2080)

- [ ] [AC8] Alert channels in `common.yaml` (done, 8a). A Grafana read-only service account token goes in `SECRET_CATALOG` (done, 8a), plus the `tag:hermes` grant to Grafana (#2339, open).
- [ ] [AC8] Hourly triage job, plus catch-up at power-on. Loki output passes through the SEC-021 redactor.
- [ ] [AC8] Live: #2080's four criteria.

### Retirement (AC11)

- [ ] [AC11] `80_agents/hermes-nan/_index.md` points here, with the disposition table from `verification.md`. AI-009 AC6 is marked superseded.

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

Minimal `features.json` skeleton (drop into `<repo>/specs/AI-012-hermes-harness/features.json`):

```json
[
  {
    "id": "AI-012-hermes-harness-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
