---
id: "OBS-042-alert-notice-contract"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-11-01"
issue: "mlorentedev/kubelab#2929"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "absorbs six open alert tickets: #2924, #2923, #1320, #1668, #1583, #1710 (13 active, limit 10, 2026-11-01)"
---

# OBS-042-alert-notice-contract

## Why

<!-- from issue #2929: OBS-042: one notice contract for every alert and node notice -->

An audit of #ops-log and the prod page tier for 2026-10-18..11-01 (245 staging messages, 26 prod pages) found that most of the noise, and every page nobody could explain, comes from what a notice says rather than from any one rule. A notice does not say whether it reports a fault or a silent emitter (118 staging messages, none a real fault), names no first move although every rule declares a `runbook_url`, and a prod page leaves no record of the rule that sent it (8 pages unattributable, #2924). A reader who cannot tell these apart learns to discount every notice, including the real ones.

## What

One notice contract, declared once in `grafana-alerting/templates.yaml` and checked by tests against the rendered ConfigMap:

1. **Title** names the environment, the state and, when it applies, why: `[prod] FIRING (no data): <rule>`. The environment is derived from `.ExternalURL`, which each overlay already renders differently.
2. **Body**, per alert: a cause line when Grafana fired on no data or on a query error (read from the `grafana_state_reason` annotation, which Grafana 13 sets to `NoData` or `Error` when `noDataState`/`execErrState` maps to Alerting, `pkg/services/ngalert/state/compat.go`); the rule's summary; the domain when present; the runbook link; the start time.
3. **A durable record of every notification**: Grafana's alert state history goes to Loki in both environments, so a page can be tied to its rule and state after the fact (#2924).
4. **Rules that answer two questions are split** so each has one cause and the right `noDataState` (#1668), and every `noDataState: Alerting` rule's emitter is checked against its window fleet-wide (#1320).
5. **Node notices** (systemd notifiers rendered by Ansible) follow the same title and runbook contract, and collapse "recovered after N failed runs" into one notice per incident.

Delivered as separate PRs by deploy path: K8s base changes reach both clusters on merge, node templates only on `make provision`.

## Out of scope

- Root-cause fixes owned by other tickets: #2920 (restic check timeout), #2921 (vault mirror fail-fast), #2922 (R2 listing timeout, merged).
- #2923 (R2 rule reachability) is offered to the backup lane; it joins this spec only if that lane does not take it.
- Changing a rule's threshold or window: the contract is about what a notice says, not when it fires.

## Risks / open questions

- **A template error fails at delivery, not at provisioning** (measured 2026-08-10, see `contact-points.yaml`). A broken template lands green and silences every prod page. Mitigation: each template change is proven by a real delivery from Grafana 13.0.2 before merge, and after each prod-bound merge one real prod delivery is observed before the next prod-bound merge.
- **Severity routing (#1710, ADR-044 §2)** changes who is woken up. It stays planned here and is decided with the operator, not landed unattended.
- **#1320's sample floor**: the existing guard uses 3 samples, and applying 3 fleet-wide turns disk and quota rules red. The fleet-wide guard starts at the measured floor of 2 so nothing existing goes red; raising it to 3 is the operator's call.
- **#1668's live measurements** (a ~90 minute resolve trace and a suspended staging CronJob) need a quiet staging slot. The split and its tests can land first; the measurements follow in a daytime window.
- **State history to Loki restarts Grafana.** If prod Grafana's database were ephemeral, the restart would erase the annotation-backed history needed to attribute #2924's eight pages, so attribution is read first.

## Acceptance criteria

- [ ] AC1: every notification title rendered by both contact points names its environment (`staging`/`prod`) and its state, and marks a no-data or query-error firing as such; proven by a delivery from Grafana 13.0.2 for each case, not by reading the template.
- [ ] AC2: every notification body carries the rule's `runbook_url`, and a test fails when a rule lacks one or the template stops rendering it.
- [ ] AC3: Grafana's alert state history is written to Loki in both environments, read back from Loki for a real transition.
- [ ] AC4: the rule split of #1668 lands with single-cause summaries, and every `noDataState: Alerting` rule is enumerated by a guard that checks its emitter against its window (#1320).
- [ ] AC5: node notices carry the same title contract and one recovery notice per incident.

## References

- Issue #2929 and the absorbed #2924, #1668, #1320, #1583, #1710
- ADR-044 (notification tiers)
- `infra/k8s/base/services/grafana-alerting/`
