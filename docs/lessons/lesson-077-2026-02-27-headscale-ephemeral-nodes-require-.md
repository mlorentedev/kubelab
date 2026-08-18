---
id: lesson-077-2026-02-27-headscale-ephemeral-nodes-require-
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-02-27 — Headscale Ephemeral Nodes Require `--ephemeral` on the Pre-Auth Key

**Context:** ts-bridge sets `tsnet.Server{Ephemeral: true}`, but after Ctrl+C the node persisted as `Ephemeral: false` / offline in `headscale nodes list`.

**Problem:** Headscale controls ephemeral behavior via the **pre-auth key**, not the client-side setting. `tsnet.Server.Ephemeral=true` is a Tailscale SaaS feature; Headscale ignores it. If the key was created without `--ephemeral`, the node is permanent regardless of what the client requests.

**Fix:** Create the key with `--ephemeral`:
```bash
headscale preauthkeys create --user <ID> --reusable --expiration 8760h --ephemeral
```

**Rule:** For any headless/tsnet service that should auto-cleanup on disconnect, the Headscale pre-auth key MUST include `--ephemeral`. Don't rely on client-side `Ephemeral: true` — it's Headscale's key, not the client, that controls this behavior.

---
