---
id: lesson-266-ci-gates-surface-stack-debt-layer-by-layer-bu
type: lesson
status: active
created: "2026-05-23"
owner: manu
tags: [kubelab, lesson, ci, process, patterns]
---

# CI gates surface stack debt layer-by-layer — budget for cascading failures

**Context:** CI-GATE-002 (PR #207) hit 5 consecutive CI failures across one session. Each failure was diagnosed and fixed before the next was visible. The pattern was not "flaky" — each was a genuine, distinct issue surfacing only after the prior one was resolved.
**Problem:** The 5 layers, in order: (1) `pipx: command not found` — self-hosted runner had no pipx; assumed it was preinstalled. (2) `PackageNotFoundError: toolkit` — used `poetry install --no-root` to be "minimal", which doesn't install the project itself; `toolkit/__init__.py` calls `importlib.metadata.version("toolkit")` which then fails. (3) `Failed to get GitHub repository information` — `toolkit.features.github_secrets` instantiated a manager at module import time and shelled out to `gh repo view`; CI had no GH_TOKEN. (4) `Template variable error: BASIC_AUTH_CREDENTIALS` — Traefik middleware template reads SOPS-sourced value; CI without age key produces empty output → drift. (5) `Drift detected in configmaps.yaml` — `EMAIL_USER/EMAIL_FROM/BEEHIIV_PUB_ID` are non-secret values living in SOPS that leak into ConfigMaps via the merge order. Each was a distinct architectural assumption that broke in the new context (CI without SOPS, no auth, no Poetry root). Estimated time consumed: ~45 min of iteration.
**Solution:** Two rules to internalize: (1) **When installing a NEW CI workflow, budget for cascading failures**. Each failure exposes one layer of "this worked locally because [X] was implicit". Don't promise "this PR is ~50 LOC" — promise "this PR plus the stack debt it surfaces". The lazy-init refactor in `github_secrets.py` was a latent bug for months; the gate found it. (2) **Treat each cascade layer as informative, not flake**. Resist the urge to add `continue-on-error: true` or to scope-narrow until the gate is useless. The gate's value is precisely in catching what was hidden. The honest end state of CI-GATE-002 Phase 1 — narrow scope with explicit follow-up tickets (SSOT-012, CI-GATE-003) — is better than a wider gate that papers over the underlying SOPS pollution. Related pattern: regen-and-diff drift detection (2026-05-23 lesson) catches the same family of "committed file evolved past its generator" debt that the gate then enforces.
**Tags:** `#ci` `#process` `#patterns`
