---
tags: [spec, tasks]
created: "2026-08-09"
---

# Tasks - OBS-007-cert-expiry-alerting

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers:**
> - `[P]` — no dependency on another unchecked task, safe to run in parallel.
> - `[AC<n>]` — helps satisfy acceptance criterion #`<n>` from `proposal.md`.

> **The substrate is the work; the rule is the easy part.** Grafana has zero alert rules and zero contact points today, so Phase 1 builds and proves the delivery path with a trivial always-firing rule *before* any LogQL is written. That ordering means a failure in Phase 2 can only be the query, never the plumbing — otherwise a silent alert has two candidate causes and no way to separate them.

## Setup

- [x] Branch created from main: `feat/OBS-007-cert-expiry-alerting` ✓ 2026-08-09
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-08-09
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-08-09 — both MUST-RESOLVE items decided: broad ACME framing, and prod `page` / staging `log`

## Implementation

### Phase 1 — the delivery path, proven end to end before any query exists

- [ ] [P] [AC1] Add a test to `tests/infra/test_k3s.py` asserting Grafana's provisioning API returns a non-empty contact-point list. **Fails now** — measured `[]` in both environments.
- [ ] [AC1] Add `infra/k8s/base/services/grafana-alerting/` with the contact point (`http://apprise:8000/notify/kubelab`, tag `log`) and a notification policy, wired via `configMapGenerator` with `files:` following the `grafana-dashboards` sibling. Add the `provisioning/alerting` volume and mount to the Grafana Deployment — the deployed-config-schema change that put this through the Discipline Gate.
- [ ] [AC6] Patch the tag to `page` in the prod overlay, then assert `kubectl kustomize` renders `log` for staging and `page` for prod. **Read the rendered output, not the patch** — #927 is the precedent for why that distinction is the whole point.
- [ ] [AC1] [AC2] Deploy to staging and prove delivery with a throwaway always-firing rule: confirm a Telegram message actually arrives. Then remove the rule. Until a message lands, nothing downstream is trustworthy.

### Phase 2 — the query, on a delivery path already known to work

- [ ] [AC3] Write the LogQL match against the two known lines: it must catch `Unable to obtain ACME certificate` and must **not** catch the `Testing certificate renew…` heartbeat. Prefer a pattern robust to wording over an exact phrase — the issue's proposed string appears nowhere in seven days of logs, and no renewal failure exists inside retention to confirm its wording. Do not filter on `detected_level`: Traefik's ANSI codes make Loki read these lines as `unknown`.
- [ ] [AC1] [AC3] Add the real alert rule to the ConfigMap, deploy to staging, and confirm the provisioning API returns it.
- [ ] [AC1] `rollout restart` Grafana and confirm the rule and contact point survive — the check that they are provisioned from the ConfigMap rather than living in Grafana's database.

### Phase 3 — exercise the failure rather than wait for it

- [ ] [AC2] [AC4] Induce a real ACME failure in staging: apply a throwaway IngressRoute requesting an unissuable domain, and confirm the rule transitions to `Alerting` and a Telegram message arrives naming the affected domain and the environment. This is the only honest test — #927 removes the one live signal that existed, and staging's DNS-01 flow produces no failures on its own.
- [ ] [AC5] Delete the throwaway IngressRoute, confirm the rule returns to `Normal` and a resolved notification is delivered. A rule that fires but never clears is a rule people learn to ignore.
- [ ] [AC3] Leave the rule enabled across at least one `Testing certificate renew…` heartbeat with no failure present, and confirm it stays `Normal`. The false-positive half of the query, which the firing test cannot show.

### Phase 4 — prod

- [ ] [AC6] Merge and let Argo CD sync prod. Confirm prod's rendered tag is `page`, and that the rule and contact point are present in prod's provisioning API.

## Closing

- [ ] Record in `docs/runbooks/` what a firing alert looks like and what to do about it. An alert whose recipient does not know the next step is a notification, not an alert. (Housekeeping, not tied to a criterion — it documents the change rather than producing an observable behaviour.)
- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] `make test-infra ENV=staging` and `ENV=prod` green
- [ ] Type checks pass (`make type`)
- [ ] Lint passes (`make lint`)
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/<feature-id>/features.json`):

```json
[
  {
    "id": "OBS-007-cert-expiry-alerting-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
