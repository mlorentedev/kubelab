---
id: "adr-037-environment-promotion-strategy"
type: adr
status: accepted
created: "2026-05-23"
tags: [architecture, gitops, argocd, environment-promotion, stream-c]
related:
  - adr-023-hub-spoke-multicloud-gitops
  - adr-030-self-hosted-runner
  - adr-036-shared-infra-namespace
---

# ADR-037: Environment Promotion Strategy

## Status

Accepted — 2026-05-23

## Context

The 2026-05-22 AI-001 session captured a lesson worded as "GitOps test-before-merge with Argo CD selfHeal = impossible vía kubectl directo (revierte en segundos); use merge-then-smoke". That was a tactical observation, not a principle. Treating staging as a write-only mirror of prod (because Argo CD selfHeal reverts any direct kubectl apply) defeats the entire purpose of having staging.

The platform needs a clear, codified answer to: **"how do I validate a change against a non-prod environment before it touches prod?"**

Without this, every refactor lands in prod un-validated. Every PR that touches shared infrastructure (e.g., SSOT-012 PR #3 with its SMTP namespace migration) becomes a high-anxiety merge-and-pray operation. The team-of-one is paying enterprise-grade attention to design rigor (ADR-035 stage-gated rollout, ADR-036 namespace boundaries) but using a workflow that erases the validation step.

GitOps does NOT mandate "everything deploys together". The industry has converged on several patterns that achieve environment isolation under GitOps. We need to pick one, document why, and implement it.

## Decision

Adopt a **three-pattern combination**:

### Pattern B — Kustomize Overlay Path Separation (already in place)

`infra/k8s/overlays/{staging,prod}/` are independent Kustomize bases. Each Argo CD Application watches its own path:

- `kubelab-staging`: `path: infra/k8s/overlays/staging`
- `kubelab-prod`:    `path: infra/k8s/overlays/prod`

A PR that touches ONLY `infra/k8s/overlays/staging/` deploys ONLY to staging on merge. No code change required for this — the architecture is free.

For PRs that touch BOTH overlays (e.g., refactors that affect shared base), the additional safety comes from Pattern (selfHeal-off-staging) below.

### Pattern D — Image Tag Promotion (depends on ARGO-014)

For code changes (application images), `argocd-image-updater` (currently backlog as ARGO-014) reads OCI registry tags and updates per-overlay image references on a schedule:

- staging overlay references `kubelab-api:rolling-staging` (mutable tag bumped automatically per merge)
- prod overlay references `kubelab-api:rolling-prod` (mutable tag bumped via explicit PR)

Promotion of an image from staging to prod becomes an explicit commit ("promote api to v1.2.3 in prod"). The toolkit's existing per-app SemVer versioning (already established 2026-02-28) provides the stable tag scheme; image-updater wires it into Argo CD.

Pattern D is **blocked on ARGO-014** and lands as a follow-up to this ADR — not in the same PR as ARGO-015.

### Conditional SelfHeal — Staging Mutable, Prod Strict

Argo CD `syncPolicy.automated.selfHeal` flag determines whether Argo CD reverts manual drift back to git state. The flag's correct value differs by environment:

- **staging** (`kubelab-staging` Application): `selfHeal: false`. Staging is a *test bed*. A developer doing `make deploy-k8s ENV=staging` from a feature-branch worktree wants their changes to PERSIST long enough to run e2e against them. Argo CD still auto-syncs from master on master commits (`automated: true` remains), so drift from intentional manual deploys eventually corrects naturally on the next master change. No background revert race.
- **prod** (`kubelab-prod` Application): `selfHeal: true`. Prod is the *system of record*. Any drift from master HEAD is a bug or an intrusion; Argo CD must correct it immediately and automatically. The merge-then-smoke pattern continues to apply for prod.
- **hub** (Argo CD itself on aws1): `selfHeal: true`. Same rationale as prod — the hub is critical infrastructure.

This is **ARGO-015**, the immediate change landing alongside this ADR.

## Consequences

**Positive**:

- **Staging recovers its purpose**: developers can deploy a feature branch's K8s manifests to staging via `make deploy-k8s ENV=staging`, run e2e against the live staging cluster, and trust that Argo CD will not revert their work mid-test. Validation before promotion becomes possible again.
- **Prod stays protected**: selfHeal-on-prod means any out-of-band manual edit (well-intentioned hot fix, mistaken kubectl apply, or hostile drift) self-corrects within seconds. Operational guarantee unchanged.
- **Code vs config separation**: future ARGO-014 (Pattern D) layers cleanly on top — code promotion becomes an explicit "bump rolling-prod tag" PR, config changes flow through the overlays.
- **Trunk-based preserved**: no `develop`/`staging` branch, no GitFlow ceremony. Master remains the only permanent branch (per CLAUDE.md).
- **Stream C ready**: when individual apps extract to their own repos (Stream C), each repo follows the same pattern — its `infra/k8s/overlays/{staging,prod}` + its own Argo CD App with the same selfHeal policy. The convention scales by repetition, not by refactoring.

**Negative / accepted tradeoffs**:

- **Staging can develop semantic drift from master**: a developer who manually deploys, validates, then forgets to merge leaves staging running un-committed config. Mitigation: any Argo CD sync triggered by a master commit (which happens on every other PR merge) corrects the drift. The window of inconsistency is ≤ 1 PR cycle. Acceptable for a single-developer platform.
- **Staging "test bed" must NOT host production data**: implied but worth stating. Mutable test bed → assume any data can be wiped at any time. This already aligns with the existing staging design (staging is on-demand per ADR-028, not always-on).
- **Manual restart of pods on ConfigMap/Secret changes**: this was already true before this ADR (per CLAUDE.md gotchas). Not introduced by this change.

## Alternatives Considered

**Pattern A — Branch-per-environment (GitFlow + GitOps)**: rejected. CLAUDE.md explicitly mandates trunk-based development with `master` as the only permanent branch. Adding a `staging` or `develop` branch creates dual-branch ceremony (merge to staging, test, then PR to master) and recreates exactly the friction trunk-based was chosen to avoid. The cost is paid every PR forever to gain a property (`selfHeal: false` already gives us).

**Pattern C — Per-PR ephemeral preview environments (Argo CD ApplicationSet + PullRequest generator)**: rejected for now. Gold-standard for teams with multiple reviewers and parallel PRs — the preview env protects each PR's iteration from others. For a solo-developer platform with sequential PRs, the value collapses (there's only ever one PR-in-flight to validate). Setup cost (~100 LOC of ApplicationSet YAML + DNS plumbing for preview hosts + cleanup CronJob) exceeds the marginal benefit. Worth revisiting if Stream C drives the platform toward multiple contributors per app.

**Pattern E — Sync windows / time-based gates**: rejected as primary mechanism. Gates by clock are fragile (a critical hotfix at 2 AM is blocked), and they don't actually validate the change — they just delay it. Useful as a *backup* safeguard for ultra-critical prod changes (e.g., `syncWindow: business hours only` on the most fragile apps), but not as the foundation.

**Status quo (selfHeal everywhere + merge-then-smoke)**: rejected. The AI-001 lesson that codified merge-then-smoke described it as a workaround, not a norm. Continuing it makes "test in staging" a fiction. The cost of changing one line in one Argo CD Application manifest (this PR) is trivially smaller than the cost of every future PR pretending staging exists when it functionally does not.

## Implementation

Three landing pieces, sequenced:

1. **ARGO-015 (this PR / immediate)** — `infra/k8s/argocd/applications/staging.yaml`: `selfHeal: true` → `false`. Adds a comment block citing this ADR. Lands with this ADR document.
2. **ARGO-014 (next session / future)** — already in backlog. Adds `argocd-image-updater` configuration for image promotion (Pattern D). Estimated +2GB disk + ~150MB RAM on aws1 hub per backlog entry; budget already verified per ARGO-014 ticket text.
3. **Pattern B (Kustomize overlays)** — no implementation needed. Already in place.

## Validation post-implementation

The first concrete proof of the new flow is **SSOT-012 PR #3** (`feat/ssot-012-shared-smtp-c1`), which lands SMTP migration. Once ARGO-015 merges:

1. From the SSOT-012 worktree: `make deploy-k8s ENV=staging`
2. `make apply-secrets ENV=staging`
3. `kubectl rollout restart deploy/api deploy/authelia -n kubelab` (against staging spoke)
4. `make test-e2e ENV=staging` → expect green
5. Merge SSOT-012 #3 → Argo CD prod auto-syncs → prod-side smoke

If staging validation fails, the PR stays open until fixed. Prod remains untouched.

This sequence becomes the **canonical PR workflow for every change that touches K8s state going forward**.

## References

- [adr-023-hub-spoke-multicloud-gitops](adr-023-hub-spoke-multicloud-gitops.md) — Argo CD hub-spoke architecture this builds on.
- [adr-036-shared-infra-namespace](adr-036-shared-infra-namespace.md) — surfaced the need for staging-first validation (SMTP cross-namespace refactor was hard to validate without staging-as-test-bed).
- AI-001 session lesson (`90-lessons.md` 2026-05-22): "GitOps test-before-merge with Argo CD selfHeal = impossible vía kubectl directo" — the symptom this ADR addresses.
- ARGO-014 backlog ticket — argocd-image-updater follow-up that completes Pattern D.
- ARGO-015 PR — the implementing PR for the staging selfHeal flip.
- OpenGitOps principles (https://opengitops.dev/) — confirm GitOps does NOT mandate uniform reconciliation policy across environments.
