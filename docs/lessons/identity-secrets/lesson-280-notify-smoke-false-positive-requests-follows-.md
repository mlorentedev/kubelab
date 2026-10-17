---
id: lesson-280-notify-smoke-false-positive-requests-follows-
type: lesson
status: active
created: "2026-06-17"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# `notify-smoke` false-positive: `requests` follows the Authelia 303 to a 200 login page

**Context:** Validating the notify fabric end-to-end in prod (`make notify-smoke ENV=prod`). The smoke POSTs to `/webhook/notify` with a Bearer and expects 200 for authenticated probes, 403 for the unauthenticated one. It reported `page/log: 200 (ok)` and only `unauthenticated: 200 (expected 403) FAIL`.
**Problem:** The `200 ok` on the authenticated probes was a **false positive**. The prod webhook was behind Authelia ForwardAuth, which 303-redirects every request (Bearer or not — a Bearer is not an Authelia session cookie) to `auth.kubelab.live`. `requests.post` follows redirects by default, lands on the Authelia login page (HTTP 200), and the smoke reads 200 → "ok". The two TLS warnings per probe (`n8n.kubelab.live` AND `auth.kubelab.live`) were the tell. **No message ever reached n8n or Telegram**; the smoke looked half-green while the fabric was fully broken. Confirmed with `curl --max-redirs 0` → `303, location: auth.kubelab.live/?rd=...`.
**Solution:** Diagnose status codes with redirects DISABLED when an auth proxy may sit in front (`curl --max-redirs 0`, or `requests(..., allow_redirects=False)`). Hardening candidate for `notify_smoke.py`: disable redirect-following and treat any 3xx to the auth host as a FAIL, not a pass. General rule: a probe that follows redirects cannot distinguish "backend accepted" from "auth proxy bounced me to a 200 login page"; for auth-gated endpoints assert on the FIRST response, not the final one.
**Tags:** `#notify-001` `#testing` `#smoke` `#authelia` `#http` `#false-positive` `#gotcha`
