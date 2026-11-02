---
tags: [spec, tasks]
created: "2026-11-01"
---

# Tasks - OBS-042-alert-notice-contract

> One PR per deploy path. K8s base reaches both clusters on merge; Ansible templates reach a node on `make provision`.
> After every prod-bound merge, observe one real prod delivery before the next prod-bound merge: a template error fails at delivery, not at provisioning.

## PR 1: notice title and body (AC1, AC2)

- [x] [AC1] [AC2] Failing tests read the rendered ConfigMap: title define, environment from `.ExternalURL`, cause line for `NoData`/`Error`, runbook link, every rule declares runbook and summary (`tests/test_alert_notice_contract.py`)
- [x] [AC1] [AC2] `apprise.title` and the cause and runbook lines in `templates.yaml`; both apprise contact points take the title from the define
- [x] [AC1] Delivery proven from a local grafana-oss:13.0.2 firing real rules (fault, no data, query error, resolved), both tiers and both root URLs; recorded in verification.md
- [ ] After merge: one real prod delivery observed with the new title before the next prod-bound merge

## PR 2: state history in Loki (AC3, #2924)

- [ ] Read whether prod Grafana's database survives a restart, and attribute #2924's eight pages from its history first
- [ ] Failing test on the rendered Grafana env: state history enabled with the Loki backend, both envs
- [ ] Enable it; confirm Grafana may reach Loki under its NetworkPolicy
- [ ] Read a real transition back from Loki in staging, then in prod after merge

## PR 3: one question per rule (AC4, #1668, #1320)

- [ ] Split the PVC rule into PVC health (`noDataState: OK`) and watcher liveness; single-cause summaries
- [ ] Guard enumerating every `noDataState: Alerting` rule against its emitter period, floor 2 samples
- [ ] Daytime: #1668's resolve trace and silence drill in staging

## PR 4: node notices (AC5)

- [ ] Inventory the node notifier templates and their recovery notices
- [ ] Same title contract and one recovery notice per incident; provision and prove `changed=0`

## Planned with the operator, not landed unattended

- [ ] #1710 severity routing (ADR-044 §2)
- [ ] Raise the #1320 floor from 2 to 3 samples

## Closing

- [ ] Every AC covered by a test and an entry in `features.json`
- [ ] `verification.md` filled in
- [ ] Independent adversarial review before archive
