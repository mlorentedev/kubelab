---
tags: [spec, verification]
created: "2026-11-01"
---

# Verification - OBS-042-alert-notice-contract

## Evidence

- [ ] AC1 (title): PR 1. Delivered from a local `grafana/grafana-oss:13.0.2` on 2026-11-02, with the repo's `templates.yaml` and `contact-points.yaml` provisioned and real rules firing from the TestData datasource (receiver pointed at a local sink). What the receiver got:

  ```
  TAG log  | [staging] FIRING: Proof fault
  TAG log  | [staging] FIRING (no data): Proof no data
  TAG log  | [staging] FIRING (query error): Proof query error
  TAG page | [prod] FIRING: Proof fault
  TAG page | [prod] FIRING (no data): Proof no data
  TAG page | [prod] FIRING (query error): Proof query error
  TYPE success | [prod] RESOLVED: Proof pulse
  ```

  A no-data body, as delivered:

  ```
  Cause: no data. The rule's source stopped reporting; the condition itself was not evaluated.
  summary of nodata
  Runbook: https://example.invalid/runbook#nodata
  Started: 2026-11-02 07:19:40 +0000 UTC

  Source: https://grafana.staging.kubelab.live/
  ```

  Pending: one real prod delivery after merge.
- [ ] AC2 (runbook): `tests/test_alert_notice_contract.py::test_the_body_carries_the_runbook`, `test_every_rule_declares_a_runbook_and_a_summary`, and the delivered bodies above.
- [ ] AC3: PR 2.
- [ ] AC4: PR 3.
- [ ] AC5: PR 4.

## Test status

- `tests/test_alert_notice_contract.py`: 10 failed before the template change, 12 passed after; `tests/test_grafana_alerting_render.py` still green.

## Decisions made during implementation

- **The contact-point test endpoint cannot prove a custom payload.** `POST /api/alertmanager/grafana/config/api/v1/receivers/test` answers 410 on 13.0.2, and its replacement (`/apis/notifications.alerting.grafana.app/v1beta1/.../receivers/{uid}/test`) fails every payload that calls `tmpl.Exec` with `template "apprise.type" not defined`, including the template already on master, which delivers in both clusters. So the proof fires real rules instead.
- **Environment from `.ExternalURL`** via `match "\\.staging\\."`, not a per-overlay literal: the overlays already render different root URLs (OBS-007 AC4), so there is no second value to keep in sync.
- **The no-data marker comes from Grafana, not from the rules.** Grafana 13 sets `grafana_state_reason` to `NoData`/`Error` when `noDataState`/`execErrState` maps to Alerting (`pkg/services/ngalert/state/state.go`, `compat.go`), so no rule had to change for the title to tell a silent emitter from a fault.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/observability/lesson-693-grafana-contact-point-test-cannot-prove-a-payload-template.md
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/OBS-042-alert-notice-contract/` -> `specs/archive/OBS-042-alert-notice-contract/`
