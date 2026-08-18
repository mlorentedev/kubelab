---
id: lesson-024-generated-then-committed-configs-drift-silent
type: lesson
status: active
created: "2026-05-23"
owner: manu
tags: [kubelab, lesson]
---

# Generated-then-committed configs drift silently — regen-and-diff periodically

**Context**: SEC-AUDIT-003 (closed 2026-03-28) ensured prod IngressRoutes use the `secure-headers` middleware. Two months later (2026-05-23), AI-002 E2E verification surfaced 3 failures — `test_security_headers_present[api|web]` + `test_hsts_header[web]`. Root cause: `infra/k8s/overlays/prod/generated/ingress.yaml` had only `[error-pages]` on api+web routes; the toolkit generator always emits `[secure-headers, error-pages]`. The committed prod file was stale relative to the generator code.

**Problem**: Two failure modes for "generator-emitted, committed-to-repo" files: (a) generator code evolves but stale committed files were never regenerated, (b) someone hand-edits a generated file. Either way, `kubectl apply -k` uses the stale file, the live cluster diverges from generator-implied invariants, and tests that assert on those invariants fail months after the original closure. The discrepancy is invisible unless someone reruns the generator.

**Solution**: `make config-generate ENV=prod` produced a clean 2-line diff (PR #204) — secure-headers added to api+web. Only `ingress.yaml` had drifted; deployments, services, configmaps, terraform, traefik, ansible, authelia configs all matched current generator output.

**Rule**: For any generator-emitted file committed to repo, schedule periodic regen-and-diff. Either: (a) manual review monthly (low cost, high friction, susceptible to skipping), or (b) **CI gate that runs `config-generate` in dry-run and fails if `git diff` is non-empty** (eliminates human-discipline tax, makes committed-generated files trustworthy by construction). Backlog: CI-GATE-002 in `11-tasks.md`. The trigger for prioritizing the CI gate is "this pattern surfaced once" — drift-detection-by-accident does not scale.
