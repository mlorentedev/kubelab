---
id: lesson-278-apprise-status-417-crashloop-stateful-mode-wr
type: lesson
status: active
created: "2026-06-16"
owner: manu
tags: [kubelab, lesson, apprise, notifications, notify-001, k8s, healthcheck, initcontainer, gotcha]
---

# Apprise `/status` 417 → CrashLoop: stateful mode write-tests `/config`, so the SOPS config can't be a read-only mount

**Context:** Finishing NOTIFY-001 Option B — `APPRISE_STATEFUL_MODE=simple` with the SOPS-rendered routing table `kubelab.yml` mounted read-only at `/config` (the 2026-06-14 lesson above). The pod then CrashLooped: `/status` returned HTTP 417 on every probe, the liveness probe killed it (14 restarts), apprise never reached Ready, so Telegram delivery silently failed even though `POST /webhook/notify` returned 200.
**Problem:** apprise-api 1.5.0's `/status` healthcheck (`healthcheck()` in `api/utils.py`) **write-tests all three storage dirs** — `APPRISE_CONFIG_DIR` (`/config`), `APPRISE_ATTACH_DIR`, and `APPRISE_STORAGE_DIR` (defaults to `/config/store`) — via `os.makedirs`/touch. Any non-writable dir adds a `*_PERMISSION_ISSUE` and drops `"OK"` from the response `details`; `/status` returns 200 **only if** `"OK" in details`, else 417. Mounting the Secret read-only at `/config` (the whole point of Option B) makes `CONFIG_PERMISSION_ISSUE` permanent. A first fix gave the store its own writable emptyDir at `/config/store` (STORE_OK) — necessary but **not sufficient**: `/config` itself was still read-only → still 417. Confirmed against the live pod (`Expectation Failed: /status/` looping) and the upstream source, not guessed.
**Solution:** Make `/config` a writable `emptyDir` and seed it with `kubelab.yml` via an **initContainer** that copies the file out of the (still read-only) `apprise-secrets` Secret mounted at `/seed`. Reuse the app image (`caronc/apprise:1.5.0`) for the initContainer so no extra image enters the SSOT. Result: CONFIG_OK + STORE_OK + ATTACH_OK → `/status` 200, pod 1/1. Chose the initContainer over a `subPath` Secret mount (which would also keep the parent dir writable) because subPath freezes content and doesn't propagate Secret updates (2026-05-25 subPath lesson) — and we re-render from SOPS + rollout-restart anyway. Generalizes: a healthcheck that write-tests its config dir is incompatible with a read-only config mount — seed a writable dir from the secret instead of mounting the secret AS the config dir. Codified as `make notify-smoke` so this regression (and the n8n 403 auth gate) is caught reproducibly.
**Tags:** `#apprise` `#notifications` `#notify-001` `#k8s` `#healthcheck` `#initcontainer` `#gotcha`
