---
id: "ADR028-004-classify-stateful-service-placement"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-11"
issue: "mlorentedev/kubelab#988"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# ADR028-004-classify-stateful-service-placement

> **Naming**: file lives at `<repo>/specs/ADR028-004-classify-stateful-service-placement/proposal.md`. `ADR028-004-classify-stateful-service-placement` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #988: ADR028-004: Classify stateful platform services by state promotion and availability -->

Nine stateful PVCs run in both staging and prod for no decided reason: they sit in `infra/k8s/base/`, and both overlays inherit base, so a topology decision was made as a side effect of a packaging choice and no ADR records it. Three of them — `gitea`, `n8n`, `minio` — are verified empty and unused (the operator tests directly in prod, and staging `minio` has no consumer at all since `overlays/prod/backup.yaml` is prod-only), so their second instance is not a test bed but latent divergence. Real data is about to land in Gitea and MinIO, which makes this the last moment the placement is a free decision rather than a stateful migration with a downtime window and metadata that git clones do not replicate.

## What

- A two-axis classification, recorded as an ADR amending [ADR-028](../../docs/adr/adr-028-operational-topology.md) and [ADR-037](../../docs/adr/adr-037-environment-promotion-strategy.md), applied to all nine stateful services: axis 1 asks whether the state has a promotion path in git (dual vs singleton), axis 2 applies ADR-028's 3 AM test (always-on vs on-demand). The axes are independent — "prod" is an environment, not a location.
- The staging twins of `gitea`, `n8n` and `minio` no longer exist: they leave `base/` and the platform tier becomes singleton. Its intended test path is an ephemeral restore from a prod backup rather than a permanently-live second instance — **declared as doctrine here, not operational**: #487 (verified restore) is open, so that path does not exist yet. It must NOT appear in this spec's acceptance criteria or the spec can never archive.
- The ADR's table emits a value on **both** axes for **every** service, not only for Gitea. A singleton's location is a separate decision per service: n8n's row is currently blank, and whether its singleton stays in prod K3s or follows Gitea to the platform plane depends on R2's answer.
- A CI gate fails when a stateful service in `base/` carries no classification, or when state with no git promotion path is duplicated across overlays — turning the rule from prose into something enforced.

## Out of scope

This spec spans more than one PR (the Discipline Gate names a multi-PR sequence as its own trigger), but a single PR still carries a single concern under the ~300-line cap. The list below is out of the **spec**, not merely out of its first PR.

- **MinIO's migration.** MinIO is classified here; it is not moved. Its destination follows from R3 and from the backup path chosen in the wider backup/DR work — moving it before that is deciding the offsite tier by accident.
- **A promotion path for n8n workflows.** They live in the database with no export/import route, which is why n8n's second instance can only drift. This spec only classifies n8n as a singleton. The gap is **already tracked, twice under one id**: [#501](https://github.com/mlorentedev/kubelab/issues/501) and [#688](https://github.com/mlorentedev/kubelab/issues/688) are both open as `APP-CONFIG-003` (a collision the 2026-07-02 platform audit already named), with [#691](https://github.com/mlorentedev/kubelab/issues/691) closed as `TOOL-009` on the import half. Reconciling those three belongs to the backlog triage ([#823](https://github.com/mlorentedev/kubelab/issues/823)), not here — filing a fourth ticket for the same concern is the pathology, not the fix.
- **[#264](https://github.com/mlorentedev/kubelab/issues/264) (official Helm charts) and [#503](https://github.com/mlorentedev/kubelab/issues/503) (Gitea mirror, org/team, webhooks).** Both touch the same three services and both already have tickets with their own gates. Absorbing ticketed work here would orphan or duplicate those gates — the ID-collision pathology the 2026-07-02 platform audit documented (ANSIBLE-026 across two issues, TOOL-009 across three places). Packaging is also orthogonal to placement: doing both at once means a break cannot be attributed.
- **Restructuring `base/` into a `platform/` tier.** Removing three services invites reorganising the rest along the management/workload split the reference audit found. That is a layout refactor and it depends on this classification being settled first.
- **[#479](https://github.com/mlorentedev/kubelab/issues/479) and [#487](https://github.com/mlorentedev/kubelab/issues/487) (offsite age key, verified restore).** They gate *using* these services with real data. They do not gate *deciding* their placement, and this spec closes without them.

## Risks / open questions

**All six below are MUST-RESOLVE, so `tasks.md` stays unfrozen — each needs an answer backed by measurement, not by inference.** R1, R2 and R3 are resolved as of 2026-08-12 (evidence in `verification.md`); R4, R5 and R6 remain open.

- **R1 — RESOLVED (measured, `verification.md`).** Which node Gitea lands on. Its role is settled (private repos and private experiments only; Argo CD keeps reconciling from GitHub), so it no longer inherits prod's always-on requirement and the operator only pushes with the homelab powered on. Beelink — ADR-028's own "Platform Node" — was measured live: 7.18 GB RAM free of 8.09 GB, 57.2 GB disk free, idle load. Summed against the *declared* limits of everything already there (glances + minio + github-runner, worst case 6.75 GB) plus Gitea's own K8s-declared limit (256Mi), the worst case still leaves ~1.1 GB headroom — and that worst case is mitigated by ADR-030 making self-hosted CI idle-by-default. Not a blocker.
- **R2 — RESOLVED (decided, `verification.md`).** Beelink is Docker Compose, not K3s, so Gitea leaves Kustomize and Argo CD's reconciliation. Decided deliberately, not a regression: this is the same shape already in the repo twice — Headscale outside K3s (ADR-015) and the Argo CD hub outside both clusters — for the same reason, a platform component can't be reconciled by the GitOps system that depends on reaching it. Gitea hosting the repos Argo CD would otherwise fetch from is exactly that trap; the proposal already avoids it by keeping Argo CD on GitHub.
- **R3 — RESOLVED, and inverted from the original framing (`verification.md`).** The original text said the prod backup CronJob loses its *destination* if MinIO moves. MinIO's migration is out of scope for this spec (see above), so `http://minio:9000` keeps resolving throughout — that framing was wrong. What actually breaks, inside this spec's own scope, is the *source*: `overlays/prod/backup.yaml` mounts the `gitea-data` PVC (and `n8n-data`, pending R2's node for n8n) that R1's move task deletes. Kustomize renders a CronJob with a dangling PVC claim without error, `kubectl apply` accepts it, and `backup.yaml` is prod-only so staging e2e never exercises it — AC3's render-and-e2e safety net has a hole here. **The move task for Gitea (and n8n) must edit `backup.yaml` in the same change**, dropping its PVC mount and backup step, keeping `authelia-data` (Authelia stays in-cluster). This is now a named MUST for R6's sweep, not an implicit item on its consumer list. Separately, and not something this spec resolves: the in-cluster MinIO destination was never a real offsite copy (same-cluster storage doesn't survive a cluster/node loss) — ADR-049 D3 already routes the real offsite tiers to Hetzner Storage Box (Borg) and R2 (restic, tracked as BACKUP-043 #596, open, neither pipeline built yet). This spec's job is only to stop the CronJob from silently mounting a deleted claim, not to build that pipeline.
- **R4 — Where the classification is asserted from.** The repo's own doctrine narrows this close to an answer rather than leaving it open: `common.yaml` already carries a service taxonomy at `apps.services.{core,automation,data,observability,security,network}`, and the SSOT rule forbids a second home for configuration. A manifest annotation would therefore BE a second SSOT. The discriminating question is only whether anything prevents the classification from being fields under `common.yaml`, read by a static test in the style of `tests/test_spoke_rbac_covers_manifests.py` — which runs with the homelab powered off. A gate that parses the ADR prose is the weakest option and is the exact pattern this spec exists to stop.

  The gate's acceptance criterion must assert the **negative** control, not just the positive: "the test FAILS when a stateful service is left unclassified". Two vacuous controls shipped on a single day during OBS-007 — a negative control that broke unreferenced code, and a guard whose bad import was swallowed by a broad `except`, silently skipping 13 tests while reporting green. A gate that cannot be shown to fail is not a gate.

- **R6 — Retiring from `base/` has a blast radius, and one part of it breaks on the first `kubectl kustomize`.** `overlays/prod/patches.yaml` patches **seven** targets that live in `base/`: `gitea-config`, `gitea`, `n8n-config`, `n8n`, `minio-config`, `minio-api`, `minio-console`. Kustomize fails when a patch has no target, so removing these from base without moving the resources into the prod overlay in the same change breaks the prod render immediately. **This fixes the task order; it is not optional sequencing.**

  Cross-cutting consumers that also carry a staging-shaped assumption, all verified present:
  - `tests/e2e/expectations.py` — entries for all three (lines 111, 114, 122). Without `skip_in_envs=("staging",)` the staging e2e breaks. The precedent is the stale `uptime_kuma` entry that CLAUDE.md documents as not belonging in that list.
  - `SECRET_CATALOG` in `toolkit/features/secrets_manager.py` — gitea and minio secrets registered `envs=("dev","staging","prod")`. Leaving them makes `secrets-audit` report a staging requirement whose consumer no longer exists (the ANSIBLE-033 class: `envs` is the audit dimension, not the storage location).
  - Homepage `services.yaml`, Authelia's staging access rules and OIDC clients, and the `apps.services.*` tree in `common.yaml`.

  Rather than enumerate every file in `tasks.md` and miss one, force the sweep with an outcome: both overlays must render and `make test-e2e ENV=staging` must be green after the retirement.
- **R5 — "Empty" must be proven per instance before any PVC is deleted, not assumed.** The operator reports staging `gitea`, `n8n` and `minio` unused, and staging `minio` provably has no consumer. Deleting a PVC is irreversible and #479 (offsite age key) and #487 (verified restore) are both still open, so there is no recovery path if the report is wrong for one of the three. Require a per-instance emptiness check — repo count, workflow count, bucket listing — captured as output in `verification.md` before the deletion task runs.

## Acceptance criteria

Observable outcomes. Each must be testable.

Deliberately absent: anything asserting the ephemeral restore-from-prod-backup test path. That is declared doctrine, not present capability (#487 is open), and an acceptance criterion depending on it would make this spec unarchivable.

- [ ] **AC1** — The ADR is merged and emits a value on **both** axes for all nine stateful services, with a location cell filled per singleton (not only for Gitea).
- [ ] **AC2** — The classification is readable from a single SSOT, and a static test fails when a stateful service in `infra/k8s/base/` carries no classification. Verified by **demonstrating the failure**: remove one service's classification, show the test red, restore it, show it green. A passing test alone does not satisfy this criterion.
- [ ] **AC3** — After the retirement, `kubectl kustomize` renders **both** overlays without error and `make test-e2e ENV=staging` is green. This is the criterion that forces the consumer sweep in R6 rather than an enumeration that can miss a file.
- [ ] **AC4** — Per-instance emptiness evidence for staging `gitea`, `n8n` and `minio`, **and for any prod instance being moved (e.g. prod `gitea-data`, per R1)** — repo count, workflow count, bucket listing — is captured as command output in `verification.md` **before** any PVC deletion task runs. Found while resolving R3: R1's move deletes the prod PVC too, and the original AC4 only required proof for staging.

## References

- Bitácora: [kubelab#988](https://github.com/mlorentedev/kubelab/issues/988) — carries the full reference audit and the disposition on #507.
- Amends: `docs/adr/adr-028-operational-topology.md` (node classification, the 3 AM test), `docs/adr/adr-037-environment-promotion-strategy.md` (what staging is for).
- Constrains: `docs/adr/adr-049-edge-object-storage-placement-doctrine.md` D3 — MinIO is `tier-object-store`; the offsite tiers are Hetzner Storage Box + R2, so the in-cluster backup hop is not the offsite copy.
- Precedent for the rejected Argo-CD-from-Gitea option: `docs/adr/adr-015-*` (Headscale outside K3s) and the VPS-uses-public-IP rule in `CLAUDE.md` — the same circular-dependency doctrine, third instance.
- Related tickets: #507 (headline already done, remainder redistributed), #264 (Helm charts), #503 (mirror/org/webhook config), #479 + #487 (gate *using* these services with real data, not deciding their placement).
- Vault: `10_projects/kubelab/research/2026-08-10-fronts-inventory-and-lane-split.md` — how this front was scoped, and the stale-`context.md` correction it rests on.
