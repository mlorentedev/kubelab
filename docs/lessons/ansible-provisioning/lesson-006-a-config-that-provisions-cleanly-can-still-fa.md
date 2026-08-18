---
id: lesson-006-a-config-that-provisions-cleanly-can-still-fa
type: lesson
status: active
created: "2026-08-10"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# A config that provisions cleanly can still fail at delivery

**Context**: OBS-007 phase 1 — building the Grafana -> Apprise -> Telegram path before writing any alert query. The spec ordered it that way deliberately: "the substrate is the work; the rule is the easy part."

**Problem**: The contact point provisioned without a single warning. `GET /api/v1/provisioning/contact-points` returned it, Grafana logged `finished to provision alerting`, and the test asserting a non-empty contact-point list went green. Everything that could be checked *before sending anything* said the configuration was correct.

It was not. The first alert produced `notify retry canceled due to unrecoverable error: template: :1: unexpected ":=" in command`. Grafana's custom webhook **payload** parser rejects variable assignment (`{{ $type := "success" }}`), which ordinary Go templates accept and which is accepted inside a `templates.yaml` `define`. The restriction applies only to the payload template, and only at send time.

Two further traps sat behind it. Grafana applies a newly provisioned alerting config roughly **60 seconds after the pod starts**, not at startup — so for the first minute after a rollout the *old* config is still notifying, and a fix looks like it did not work. And Grafana's stock webhook body (`title`/`message`/`alerts[]`) has neither the `body` nor the `tag` field Apprise requires, so the default payload would have been rejected regardless.

**Solution**: Move any conditional logic out of the payload template into a named `define` in the provisioned templates file, and call it with `tmpl.Exec`. Build the JSON with `coll.Dict | data.ToJSON` rather than by hand, so quotes inside an alert annotation are escaped instead of producing a malformed body — Traefik's ACME errors do contain quotes. Then read the *Apprise* access log for `POST /notify/kubelab 200` and `Delivered Notification(s) - Tags: <tier>`, and compare timestamps against the `Applying new configuration to Alertmanager` line to be sure you are looking at the config you just deployed.

**Rule**: For anything that *sends*, provisioning success is not delivery success — the only check that counts is an artifact observed at the far end. Order the work so the transport is proven by a trivial always-firing rule before any query exists; otherwise a silent alert has two candidate causes and no way to separate them. This one paid immediately: written in the other order, a payload-template parse error would have presented as "my LogQL matches nothing."
