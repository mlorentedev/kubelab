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

- [x] [P] [AC1] Add a test asserting Grafana's provisioning API returns a non-empty contact-point list. **Fails now** — measured `[]` in both environments. ✓ 2026-08-10 — landed in a new `tests/infra/test_grafana_alerting.py` rather than `test_k3s.py`, whose docstring scopes it to "node status, pods, PVCs". Observed failing against staging before the manifest existed. A second test was added alongside it: Grafana's default root policy has receiver `empty`, so a contact point can provision cleanly while every alert is still discarded.
- [x] [AC1] Add `infra/k8s/base/services/grafana-alerting/` with the contact points and a notification policy, wired via `configMapGenerator` with `files:`. Add the `provisioning/alerting` volume and mount to the Grafana Deployment — the deployed-config-schema change that put this through the Discipline Gate. ✓ 2026-08-10. **Diverges from the `grafana-dashboards` sibling on purpose:** that generator sets `disableNameSuffixHash: true` because dashboards are re-read on a timer. Alerting provisioning is read once at startup, so the hash suffix is what rolls the pod on a rule change. Same rationale as `authelia-config`.
- [x] [AC6] Route prod to the `page` tier in the overlay, then assert `kubectl kustomize` renders the right tier per environment. **Read the rendered output, not the patch.** ✓ 2026-08-10 — `tests/test_grafana_alerting_render.py`. See the AC6 amendment in `proposal.md`: the overridden field is the root policy's `receiver`, not the tag, which shrinks the per-environment surface from ~25 lines to 5 and makes drift structurally impossible. Negative control: rendering `infra/k8s/base` alone emits the staging value, so a no-op merge in prod is visible.
- [x] [AC1] [AC2] Deploy to staging and prove delivery with a throwaway always-firing rule: confirm a Telegram message actually arrives. Then remove the rule. Until a message lands, nothing downstream is trustworthy. ✓ 2026-08-10 — operator confirmed both messages in the archive channel.
  - Deployed to staging 2026-08-10; contact points provisioned and both AC1 tests went red -> green.
  - **The ordering earned its keep immediately.** The first delivery attempt failed with `template: :1: unexpected ":=" in command` — Grafana's custom-payload parser rejects variable assignment. It failed at *delivery*, not at provisioning: the contact point was present and healthy in the API the whole time. Had the LogQL rule been written first, this would have looked like a query that matches nothing. Fixed by moving the conditional into a `templates.yaml` define, where full template syntax is accepted.

> **Both branches exercised — corrected 2026-08-10.** This note first recorded the
> resolved path as unexercised, because the probe rule was deleted without checking
> for a resolved delivery. It was wrong: deleting the rule DID fire the resolve, and
> the operator received both messages five minutes apart —
> `firing: OBS-007 delivery probe` then `resolved: OBS-007 delivery probe`. So the
> `apprise.type` else-branch and `disableResolveMessage: false` are both confirmed
> working, and AC5's *mechanism* is proven for the delivery path. AC5 itself still
> belongs to phase 3, which must show the real ACME rule recovers rather than latches.
>
> The delivered body also settles AC4 ahead of schedule: it carried
> `Domain: probe.staging.kubelab.live` from the rule's label and
> `Source: https://grafana.staging.kubelab.live/` from `.ExternalURL`, so the
> recipient can identify both the domain and the environment without opening Grafana
> — and without any per-environment value in the config.

### Phase 2 — the query, on a delivery path already known to work

- [x] [AC3] Write the LogQL match against the two known lines: it must catch `Unable to obtain ACME certificate` and must **not** catch the `Testing certificate renew…` heartbeat. ✓ 2026-08-10 — validated against seven days of real logs, not reasoned about.

  Final shape: match ACME lines that ALSO carry an error indicator, rather than matching ACME lines and excluding the heartbeat by name. **The data decided this**: staging logs `Starting provider *acme.Provider` on every Traefik boot (8 in seven days), so the denylist variant would have alerted on a startup message, and would have kept doing so for every future benign ACME line. Measured: prod returns exactly the 1 real failure and none of its 7 heartbeats; staging returns 0, which is correct because its DNS-01 flow works.

  **New finding — the ANSI codes break field extraction too, not only `detected_level`.** The raw line is `\x1b[36mdomains=\x1b[0m["host"]`, so the obvious `domains=\["` matches nothing. The rule's regexp tolerates an ANSI reset between the key and the value. Verified that a line *without* a `domains=` field is still counted with an empty domain label, so a failure whose wording we have never seen still alerts rather than being silently dropped — which was the whole worry about extracting at all.

  Original text follows. Prefer a pattern robust to wording over an exact phrase — the issue's proposed string appears nowhere in seven days of logs, and no renewal failure exists inside retention to confirm its wording. Do not filter on `detected_level`: Traefik's ANSI codes make Loki read these lines as `unknown`.
- [x] [AC1] [AC3] Add the real alert rule to the ConfigMap, deploy to staging, and confirm the provisioning API returns it. ✓ 2026-08-10 — `infra/k8s/base/services/grafana-alerting/rules.yaml`. Two tests added, both observed failing first. `noDataState: OK` is load-bearing and has its own test: a LogQL query matching nothing returns **no series rather than zero**, so healthy IS NoData, and at Grafana's default the rule would fire continuously while certificates renewed perfectly.
- [x] [AC1] `rollout restart` Grafana and confirm the rule and contact point survive — the check that they are provisioned from the ConfigMap rather than living in Grafana's database. ✓ 2026-08-10 — restarted, 5/5 green afterwards. Rule reports `state=inactive health=ok` in staging, which is the correct resting state there.

### Phase 3 — exercise the failure rather than wait for it

- [x] [AC2] [AC4] Induce a real ACME failure in staging: apply a throwaway IngressRoute requesting an unissuable domain, and confirm the rule transitions to `Alerting` and a Telegram message arrives naming the affected domain and the environment. ✓ 2026-08-10

  Chose a `.local` host deliberately: Let's Encrypt rejects it at the **new-order** step with `rejectedIdentifier`, *before* any DNS-01 challenge — so nothing is written to Cloudflare and no failed-validation rate limit is consumed. It also reproduces the exact shape of the real prod failure (#927) rather than a different one that happens to be convenient.

  Timeline, all measured: IngressRoute applied 04:55; Traefik's `ERR Unable to obtain ACME certificate` at 04:55:44; rule `pending` 04:58; **`firing` 05:03:00**; Apprise `POST /notify/kubelab 200`, `Tags: log` at **05:03:34**. The firing instance carried `domain=obs007-induced-failure.kubelab.local` as a label extracted from the log line, which is AC4's domain half arriving from real data rather than from a static label as in the phase 1 probe. This is the only honest test — #927 removes the one live signal that existed, and staging's DNS-01 flow produces no failures on its own.
- [ ] [AC5] Delete the throwaway IngressRoute, confirm the rule returns to `Normal` and a resolved notification is delivered. A rule that fires but never clears is a rule people learn to ignore.
- [x] [AC3] Leave the rule enabled across at least one `Testing certificate renew…` heartbeat with no failure present, and confirm it stays `Normal`. The false-positive half of the query, which the firing test cannot show. ✓ 2026-08-10 — **proved directly instead of by waiting.**

  Waiting ~24h for the next heartbeat would have been the weaker test: it demonstrates the rule stayed quiet, without establishing that a heartbeat was ever in the evaluated window. Instead the alert expression was evaluated at an instant one minute *after* a known heartbeat, so the heartbeat is provably inside the `[10m]` range. Result: heartbeats in window = 1, alert query = **empty**. The heartbeat is isolated as the only ACME line present, which is the property the criterion is actually about.

### Phase 4 — prod

- [x] [AC6] Merge and let Argo CD sync prod. Confirm prod's rendered tag is `page`, and that the rule and contact point are present in prod's provisioning API. ✓ 2026-08-10 — verified against the live prod cluster after #958 merged.

  `grafana-alerting-d9b2569g6f` carries all four keys, and prod's rendered `policies.yaml` selects **`apprise-page`** — the per-environment tier confirmed in the cluster, not only in the render. Prod's scheduler evaluates `rule_uid=obs007-acme-failure` every 5m.

  **This is where `noDataState: OK` proved itself in production.** Every prod evaluation returns `framesLength=0`, because prod has no ACME failures. At Grafana's default that is `NoData` → alerting, so prod would have been paging continuously from the moment this merged. Zero deliveries to Apprise since the sync.

  Note the provisioning-API half is still read indirectly (via the scheduler's own logs) rather than through `/api/v1/provisioning`, because that endpoint remains blocked by **#951** — prod's Grafana refuses the admin username its Secret declares. The infra test skips there naming that ticket rather than reporting a false pass.

## Closing

- [x] Record in `docs/runbooks/` what a firing alert looks like and what to do about it. An alert whose recipient does not know the next step is a notification, not an alert. ✓ 2026-08-10 — `docs/runbooks/acme-alerting.md`. Written because the rule's `runbook_url` annotation already promised the page existed. Carries the four known causes with their fixes, the recovery check (wait for the resolved message; do not assume), and the induced-failure procedure so the alert can be re-tested by anyone. States that an empty `Domain` field is expected rather than a bug.
- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command — **still owed; not started.** The file does not exist yet.
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
