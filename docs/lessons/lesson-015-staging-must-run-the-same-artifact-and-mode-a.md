---
id: lesson-015-staging-must-run-the-same-artifact-and-mode-a
type: lesson
status: active
created: "2026-06-15"
owner: manu
tags: [kubelab, lesson]
---

# Staging must run the same artifact AND mode as prod, or it is not a gate

**Context**: The `api:1.1.0` CrashLoop above reached prod despite staging existing. Staging ran the mutable `:dev` tag, not the `1.1.0` artifact promoted to prod; and staging runs `ENVIRONMENT=staging`, while the guard that fired was `required in production`.

**Problem**: Two independent axes of divergence each defeat the gate. (1) **Artifact**: staging on `:dev` never executes the image being shipped, so image-level regressions pass straight through. (2) **Mode**: even if staging ran `1.1.0`, the `production`-gated guard would not fire under `ENVIRONMENT=staging`, so production-only code paths stay dark. The ADR-027 drift gate verifies overlay *consistency*, not that the *container boots* — a different guarantee. A pre-prod environment that differs from prod in artifact or correctness-affecting behavior validates nothing about what actually ships.

**Solution**: Immediate cause fixed in #666. The parity gaps are tracked: knowledge#105 (staging runs the candidate immutable build, not `:dev`) and knowledge#106 (staging exercises production-mode guards — run prod-equivalent strictness, or de-gate *required-infra* guards in the app source `mlorente-backend` `internal/services/beehiiv.go`).

**Rule**: A staging/pre-prod environment may differ from prod ONLY in environment-specific values (domains, scale, `selfHeal`) — never in the artifact (run the same immutable tag you will promote) nor in correctness-affecting mode. If a guard is `if production`, staging won't catch it: make *required-infra* guards unconditional and keep only side-effectful behavior (live email, real charges) environment-gated.

**Tags**: `#staging` `#parity` `#promotion` `#gates` `#adr-046` `#adr-037` `#issue-105` `#issue-106`
