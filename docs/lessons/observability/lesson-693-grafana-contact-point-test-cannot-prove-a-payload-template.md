---
id: lesson-693-grafana-contact-point-test-cannot-prove-a-payload-template
type: lesson
status: active
created: "2026-11-02"
owner: manu
category: observability
tags: [kubelab, observability, grafana, alerting]
---

# Grafana 13's contact-point test cannot prove a custom webhook payload; fire a real rule instead

**Context**: OBS-042 changed the notification title and body that both Apprise contact points render. A template error in a custom payload fails at delivery, not at provisioning, so the change needed a delivery before merge.

**Problem**: On grafana-oss 13.0.2 the old test endpoint, `POST /api/alertmanager/grafana/config/api/v1/receivers/test`, answers 410. Its replacement, `POST /apis/notifications.alerting.grafana.app/v1beta1/namespaces/default/receivers/{uid}/test`, failed every payload that calls `tmpl.Exec` with `template "apprise.type" not defined`. That included the template already on master, which delivers in both clusters, and it happened with the templates provisioned and listed by `/api/v1/provisioning/templates`. A test that fails the known-good template proves nothing about the new one. Separately, a bind mount from macOS `/private/tmp` reached the container empty, so Grafana provisioned nothing and reported no error.

**Solution**: Run `grafana/grafana-oss:13.0.2` locally with the repo's `templates.yaml` and `contact-points.yaml` copied in with `docker cp` (not mounted). Point the webhook at a local sink. Provision a TestData datasource and real rules: a fault, a `no_data_points` rule with `noDataState: Alerting`, a rule on a missing datasource with `execErrState: Alerting`, and a `predictable_pulse` rule that fires and resolves. The sink received the rendered title and body for every case, `[prod] FIRING (no data): ...` included.

**Rule**: Prove a Grafana payload template by firing a real rule, never with the contact-point test endpoint. Calibrate any proof harness against the version already in production first: if it fails the known-good template, it is measuring itself. Copy provisioning files into a local container rather than mounting them, and confirm Grafana loaded them before reading any result.

**Tags**: `#grafana` `#alerting` `#obs-042`
