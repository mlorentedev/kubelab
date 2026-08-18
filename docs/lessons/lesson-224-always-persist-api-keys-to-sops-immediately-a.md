---
id: lesson-224-always-persist-api-keys-to-sops-immediately-a
type: lesson
status: active
created: "2026-03-27"
owner: manu
tags: [kubelab, lesson, sops, credentials, ssot, operational]
---

# Always persist API keys to SOPS immediately after generation

**Context:** Uptime Kuma API key was generated in the UI but never stored in SOPS. The plaintext was lost — only bcrypt hash remains in the DB.
**Problem:** API keys generated in service UIs are shown once. If not immediately persisted to SOPS, the plaintext is lost forever. The hash in the DB is irreversible. This breaks the SSOT principle — a credential exists in the system but not in the managed secret store.
**Solution:** Rule: any credential generated in a service UI MUST be immediately stored via `toolkit secrets set` before closing the dialog. Add to CLAUDE.md as a gotcha. For Uptime Kuma specifically, regenerate the API key and store it in SOPS under `apps.services.observability.uptime_kuma.api_key`.
**Tags:** `#sops` `#credentials` `#ssot` `#operational`
