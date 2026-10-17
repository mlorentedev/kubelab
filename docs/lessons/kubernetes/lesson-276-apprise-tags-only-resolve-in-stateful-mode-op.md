---
id: lesson-276-apprise-tags-only-resolve-in-stateful-mode-op
type: lesson
status: active
created: "2026-06-14"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# Apprise tags only resolve in stateful mode — Option B needs `simple` mode + a mounted config, not stateless

**Context:** NOTIFY-001 / ADR-044 chose Option B for the notification fabric: Apprise (`caronc/apprise`) owns the `tag → URL` routing table and n8n only sends a tag. Criterion #1 had proven delivery with the **stateless** endpoint (`POST /notify/` with `urls=tgram://…` in the request body, `APPRISE_STATEFUL_MODE=disabled`).
**Problem:** The stateless `/notify/` endpoint does **not** accept tags — tags are meaningless without a stored config to filter against. So Option B is impossible while Apprise stays stateless; the manifest had to change. Easy to miss because the stateless path "works" for a single hard-coded URL, masking that the whole point of Option B (one POST, tag selects the channel) is unavailable until the config is persisted.
**Solution:** Set `APPRISE_STATEFUL_MODE=simple`. In `simple` mode the API maps a `{KEY}` straight to a file `/config/{KEY}.yml`, so `POST /notify/{KEY}` with `{"tag":"page","title":…,"body":…,"type":…}` resolves the tag against that file. The file (a YAML `urls:` list, each entry a quoted `tgram://bot/chat` URL → `tag:`) holds secrets, so it is rendered from SOPS by the toolkit (`_build_apprise_config`, mirroring `_build_users_database`) into the `apprise-secrets` Secret as the single key `kubelab.yml`, mounted **read-only** at `/config`. Quote each URL key — Telegram bot tokens contain a colon that otherwise breaks the YAML mapping. Generalizes: for tag-based fan-out, the router must be stateful; pick the delivery topology (who holds the URLs) before proving delivery, or criterion #1 proves the wrong path.
**Tags:** `#apprise` `#notifications` `#notify-001` `#adr-044` `#k8s` `#sops` `#gotcha`
