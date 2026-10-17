---
id: lesson-014-a-generated-artifact-s-content-must-not-depen
type: lesson
status: active
created: "2026-06-15"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, generator, determinism, sops, drift-gate, secrets, adr-046, adr-027, pr-666]
---

# A generated artifact's content must not depend on whether secrets are decrypted

**Context**: First gated prod promotion (`api` → `1.1.0`, #664) put the new pod in `CrashLoopBackOff` — `panic: SMTP credentials required in production`. The api Deployment's `envFrom` referenced only `configMapRef: api-config`, never `secretRef: api-secrets`, so `INFRA_SMTP_PASS` (present in the cluster Secret for 86 days) was never injected. `:dev` had no such guard; `1.1.0` added one. No outage — the rolling update held the old `:dev` pod Ready while the new one never became Ready.

**Problem**: The K8s generator's `_has_secret_vars` scanned `APPS_PLATFORM_<APP>_*` env vars for secret-name patterns to decide whether to mount `<app>-secrets`. Those keys come from SOPS, so the decision depended on whether SOPS was decrypted at generation time. The prod overlay had been committed from a SOPS-less `generate` → the keys were absent → `has_secrets=False` → no `secretRef`. Staging had been generated with SOPS → it had the mount all along. Same source, two outputs. The ADR-027 drift check runs in CI **without** SOPS, so it regenerated the same secret-less output and went green — the gate shared the generator's blind spot (false green). The heuristic was also blind to *shared* `INFRA_*` secrets (`INFRA_SMTP_PASS` lives under the `INFRA_` prefix, not `APPS_PLATFORM_API_`).

**Solution**: #666 — tie the mount to the secrets SSOT: `_has_secret_vars(component)` returns true iff a `<component>-secrets` mapping exists in `SECRET_DEFINITIONS`. No `env_vars` input → deterministic and SOPS-independent. CI and local now emit identical overlays, so the drift gate means something again. Regression test asserts the mount decision equals registry presence for every platform app, and that `web` (no secret) never mounts. Validated on staging: `api:1.1.0` boots Ready with `INFRA_SMTP_PASS` injected.

**Rule**: A generator's output must be a pure function of *committed* inputs — never of ambient state like "are secrets decrypted right now". To decide "does this thing exist", read the static SSOT (the definition/registry list), not a side effect of the environment. Corollary: an equality/drift gate is only as strong as the conditions it runs under — if generation can vary with SOPS, either run the gate with SOPS or (better) make generation SOPS-independent. And: *provisioning* a secret (it exists in the cluster) and *consuming* it (the workload references it) are two facts that can silently diverge — bind them at one source.

**Tags**: `#generator` `#determinism` `#sops` `#drift-gate` `#secrets` `#adr-046` `#adr-027` `#pr-666`
