---
tags: [spec, tasks]
created: "2026-08-11"
---

# Tasks - ADR028-004-classify-stateful-service-placement

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> All six risks (R1-R6) are resolved with evidence in `verification.md` as of 2026-08-12 — that is what unfroze this file. Task order below follows R6's own finding: R3's `backup.yaml` edit and R6's consumer sweep have to land in the **same commit** as the retirement, or `kubectl kustomize` breaks the prod render immediately (a patch with no target fails). PRs are grouped so each stays under the ~300-line cap and carries one concern.

## Setup

- [x] This spec ships as **four PRs, not one branch** — each PR block below gets its own branch off `master`, opened and merged independently. PR 3 must land before PR 4 starts (PR 4's task list assumes the retirement mechanics are already proven once); PR 1 and PR 2 have no ordering dependency on each other or on PR 3/4.

**Deviation, decided by the operator 2026-08-14 — PR 4 runs before PR 3, and splits in two.** Recorded here rather than rewritten above, because this file froze when the spec went `implementing`.

*Why the order flipped.* The operator needs Gitea for real work, urgently. PR 4's whole design depends on Gitea being empty — its flow is "verify empty → delete", which is why AC4 exists at all. The moment real repos land in the prod instance, that retirement stops being a retirement and becomes a data migration, and the AC4 evidence goes stale. So urgency argues for moving *before* first use, not after. The original ordering's stated reason was de-risking ("prove the mechanics on the lower-risk service"), not a technical dependency, so nothing else breaks by flipping it.

*Consequence, which must not be dropped.* The duplication-clause gate extension is the **last** task of PR 4 above, and its placement was reasoned, not arbitrary: it can only go green once no `singleton` service still renders in both overlays. With the order flipped, Gitea retires first and MinIO still renders in both, so that clause **moves to PR 3**. Leaving it in PR 4 would put `master` red the day PR 4 merges; dropping it silently would archive this spec over-claiming what its gate enforces.

*Why PR 4 splits into 4a and 4b.* Same shape as ADR-015's Pattern C: stand the target up side by side, then cut over. **4a** deploys Gitea to the Beelink and touches no K8s and no traffic — additive and reversible on its own. **4b** performs the cutover and the retirement. The seam is real rather than cosmetic: 4a is verifiable in isolation against a live instance, and it unblocks the operator immediately over the tailnet (`beelink.kubelab.internal:3000`, SSH on 2222) without waiting for the cutover to be reviewed. Data created in 4a survives 4b, because 4b only removes the K8s instance and re-points the domain.

*One task moved from 4b into 4a on purpose:* Gitea's environment identity. The instance must carry prod's `oidc_client_secret`, `secret_key` and domain from its very first start, so that anything created between 4a and 4b stays valid across the cutover.
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions" — all six resolved

## PR 1 — The ADR itself [AC1]

- [x] [AC1] Confirm the next free ADR number before writing the file — the repo has hit this collision twice this month (adr-059 twice, fixed as adr-060 via #998). Check `docs/adr/` directly, do not infer from the last-known number.
- [x] [AC1] Write `docs/adr/adr-0XX-stateful-service-placement.md`, amending [ADR-028](../../docs/adr/adr-028-operational-topology.md) and [ADR-037](../../docs/adr/adr-037-environment-promotion-strategy.md). Table emits both axes for all nine PVCs / eight services:

  | service | promotion (axis 1) | location (axis 2) |
  |---|---|---|
  | gitea | singleton | on-demand (Beelink) |
  | minio | singleton | *undecided — out of scope, see proposal.md* |
  | n8n | dual (git-projected) | always-on (K3s prod, unchanged) |
  | grafana | dual (ConfigMaps promote) | always-on |
  | loki | dual (ConfigMaps promote) | always-on |
  | authelia | dual (ConfigMaps promote) | always-on |
  | crowdsec | dual (ConfigMaps promote) | always-on |
  | postgres | dual (git-projected, per ADR-050 D7: "canonical state = git + Postgres projection + object-store backup") | always-on |

  n8n's binding condition (git+`n8n import` is the only legal write path) is enforcement detail, not the axis value — write it into the ADR as prose under the table, not crammed into the cell; the table must stay scannable as a plain lookup. Postgres's row is not a judgment call for this task: ADR-051 D1 already deploys it to staging+prod, and ADR-050 D7 already establishes its content as a projection of git-canonical state, same shape as Grafana/Loki's ConfigMaps — cite both ADRs in the row, don't re-derive.
- [x] [AC1] Write the ADR's own "condition" clause for n8n's dual status verbatim from `verification.md`'s R5 section — this is a binding constraint (git+import only), not background color, and a future reader must be able to find it without archaeology.
- [x] [AC1] Cross-link: add an amendment note to `adr-028-operational-topology.md` and `adr-037-environment-promotion-strategy.md` pointing at this ADR, matching how other amendments in this repo are recorded (see ADR-028's own 2026-08-09 amendment note as the pattern).

## PR 2 — Classification SSOT + enforced gate [AC2] [P]

Independent of PR 1's prose — the gate reads config, not the ADR file. Can run in parallel.

- [x] [P] [AC2] Add `state_promotion` and `location` fields to each of the eight services' config blocks in `common.yaml`: seven under `apps.services.<category>.<name>`, `postgres` under `infra.postgres` (see R4 in `verification.md` for why the second namespace exists and must not be skipped). **Include gitea and minio here too**, even though PR 3/4 retire their staging twins later — the gate in this PR checks every stateful service currently in `base/`, and gitea/minio are still there until PR 3/4 land. A classified-then-later-removed service is fine; an unclassified-but-present one fails the gate the moment this PR merges.
- [x] [AC2] Write `tests/test_stateful_service_classification.py`, mirroring `tests/test_spoke_rbac_covers_manifests.py`'s shape (already proven, already reviewed, TOOL-029):
  - `_stateful_services()` — walk `infra/k8s/base/*.yaml` for `kind: PersistentVolumeClaim`, return the owning service name per PVC.
  - `_declared_classification()` — load `common.yaml`, resolve each service's block from wherever it lives (`apps.services.*` or `infra.*`), return `(state_promotion, location)` or `None`.
  - Main test: fail, listing every stateful service missing either field by name — not a bare assertion count. This must **pass red-to-green against the real repo** once PR 2's `common.yaml` edit lands, proving AC2's "single SSOT" claim for real, not hypothetically.
- [x] [AC2] Write the negative-control test: construct a synthetic fixture (a small in-memory dict, not live repo state) missing one classification field, assert the checking function fails on it. This is the test that satisfies AC2's explicit "demonstrate the failure" requirement — a passing main test alone does not satisfy AC2. Reference the OBS-007 precedent in `proposal.md`'s R4 text for why this control is non-negotiable.
- [x] [AC2] Run both tests, capture the pass/fail transcript (main test green against real repo, negative control demonstrably red-then-green) as command output in `verification.md`.

## PR 3 — Retire MinIO's staging twin only [AC3] [AC4]

MinIO's own destination stays out of scope (see `proposal.md` Out of scope, and the new evidence on **#972**) — this PR only removes the staging duplicate now that it's classified as a singleton. Smaller and more isolated than Gitea's PR, so it goes first to prove the retirement mechanics on the lower-risk service.

- [ ] [AC4] Re-verify staging MinIO emptiness (authenticated check, same method as R5) immediately before the deletion sub-task runs, unconditionally — do not rely on the 2026-08-12 evidence in `verification.md` from memory, however recent it looks. Capture the fresh output there, **prefixed with the literal marker line `AC4-EVIDENCE staging/minio pre-deletion`** — `features.json` f5 greps for that exact string, because a bare mention of "minio" somewhere in the file proves neither which instance was checked nor that the check preceded the deletion.
- [ ] [AC3] Move `minio-config`, `minio-api`, `minio-console` out of `base/kustomization.yaml` into `overlays/prod/` as first-class resources; remove their three entries from `overlays/prod/patches.yaml` (they're no longer patching a base resource — they *are* the resource now).
- [ ] [AC3] `tests/e2e/expectations.py` — add `skip_in_envs=("staging",)` to the `minio` entry.
- [ ] [AC3] `SECRET_CATALOG` — MinIO's `envs` stays `("dev","staging","prod")` only if something *else* still needs it in staging (check before narrowing; ANSIBLE-033's failure mode is narrowing an `envs` tuple to no longer match any real consumer, which makes the secret vanish from every future audit silently).
- [ ] [AC3] `toolkit/scripts/sync_homepage_config.py` — remove the MinIO tile construction (lines ~288-299 as of this spec's writing; confirm current line numbers before editing).
- [ ] [AC3] `apps.services.security.authelia.oidc_clients` — remove the `minio-oidc` entry.
- [ ] [AC3] `staging.yaml` — remove MinIO's `domain`/`console_domain` overrides.
- [ ] [AC3] `kubectl kustomize` both overlays, confirm clean render. `make test-e2e ENV=staging` green.

## PR 4 — Retire Gitea's staging twin, move prod to Beelink [AC3] [AC4]

The larger of the two retirements — moves both instances, not just staging's. Do this after PR 3 proves the mechanics once already.

- [x] **(4a)** [AC4] Capture prod Gitea emptiness evidence (authenticated repo search against `gitea.kubelab.live`, same method as the staging check in `verification.md`'s R5) as committed output in `verification.md`, **before** the deletion sub-task below runs. This is the AC4 gap this spec's own R3 work surfaced — do not skip it because staging was already checked. Prefix it with the literal marker `AC4-EVIDENCE prod/gitea pre-deletion`, and add `AC4-EVIDENCE staging/gitea pre-deletion` above R5's existing staging-Gitea evidence in the same commit. `features.json` f5 greps for all three markers by exact string.
- [x] **(4a)** [AC3] Deploy Gitea to Beelink via an Ansible role in the `beelink_services`-style pattern (Docker Compose, reading from the same `apps.services.core.gitea.*` config Gitea already uses) — R1/R2 already resolved that this is the intended shape, not a decision this task re-opens.
- [x] **(4b)** [AC3] Expose Gitea at its existing domain using the repo's already-established **external service pattern** (`infra/k8s/base/external/`, Service + EndpointSlice → K3s Traefik → the backend's Tailscale IP — the exact shape already proven for Pi-hole and Uptime Kuma). No new exposure mechanism needs inventing.
- [x] **(4b)** [AC3] ~~Whether Gitea keeps its Authelia OIDC SSO login option post-move is an auth-surface change — **surface it to the operator, don't resolve it inline.**~~ **DECIDED by the operator 2026-08-12: Gitea KEEPS its Authelia OIDC login.** R6's original assumption of removal rested on Gitea losing a stable domain, which the external-service pattern above contradicts — the domain survives the move, so the OIDC flow stays valid and only the backend changes. Remaining work is therefore a *check*, not a removal: verify the registered redirect URI still resolves post-move, and leave `gitea-oidc` in `apps.services.security.authelia.oidc_clients`.
- [x] **(4b)** [AC3] Move `gitea-config`, `gitea` out of `base/kustomization.yaml` into `overlays/prod/`; remove their two entries from `overlays/prod/patches.yaml`.
- [x] **(4b)** [AC3] `overlays/prod/backup.yaml` — drop the `gitea-data` mount and its backup step; keep `authelia-data` and `n8n-data` (R5 kept n8n dual, unmoved — its mount stays).
- [x] **(4b)** [AC3] `tests/e2e/expectations.py` — add `skip_in_envs=("staging",)` to the `gitea` entry.
- [x] **(4b)** [AC3] `SECRET_CATALOG` — **do not blindly narrow gitea's `envs` to `("prod",)`.** `infra/ansible/playbooks/provision-bee.yml` hardcodes `deploy_env: staging` for the whole Beelink provisioning play, so post-move, Gitea's secrets get decrypted under the **staging** env variable during Ansible runs, regardless of Gitea being conceptually a prod singleton now. Verify what `provision-bee.yml` actually needs before setting `envs` — this is "prod is an environment, not a machine" biting in the secrets dimension specifically, and narrowing incorrectly here passes every render and fails silently in an audit weeks later (the exact ANSIBLE-033 shape).
- [x] **(4b)** [AC3] `toolkit/scripts/sync_homepage_config.py` — remove the Gitea tile construction (or re-point it at the new external-service domain if Gitea's homepage entry should still resolve — confirm which during this task).
- [x] **(4b)** [AC3] `apps.services.security.authelia.oidc_clients` — resolve per the OIDC decision above. *(No edit needed: the list never contained `gitea-oidc` — that client is registered directly in the hand-maintained K8s Authelia configs. The list/config split is recorded on #1013.)*
- [x] **(4b)** [AC3] `staging.yaml` — remove Gitea's `domain` override.
- [x] **(4b)** [AC3] `kubectl kustomize` both overlays, confirm clean render. `make test-e2e ENV=staging` green.
- [ ] **MOVED TO PR 3** (see the 2026-08-14 deviation note in Setup — with Gitea retiring first, MinIO is the service still rendering in both overlays, so this clause can only go green once PR 3 lands) [AC2] **Extend the gate with the duplication clause.** `proposal.md`'s What promises the gate fails not only on a missing classification but also "when state with no git promotion path is duplicated across overlays" — and no task in PR 1-3 implements that half, so the spec would archive over-claiming. It belongs here and not earlier: while gitea and minio still render in both overlays, the check would be red on `master` from the moment it merged. Add to `tests/test_stateful_service_classification.py`: a service classified `state_promotion: singleton` must not resolve in both `overlays/staging` and `overlays/prod`. Same negative-control bar as the rest of the file — demonstrate it red before it goes green. *(Gap found 2026-08-12 while implementing PR 2, recorded here before `tasks.md` froze.)*

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test or captured verification output
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep) — MinIO's own migration, n8n workflow promotion generally, Helm packaging (#264/#503), and `base/` → `platform/` restructuring all stay out per `proposal.md`'s Out of scope
- [ ] `verification.md` filled in for PRs 3 and 4's AC4 evidence
- [ ] PR opened referencing this spec folder, for each of PR 1-4 above

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

```json
[
  {
    "id": "ADR028-004-f1",
    "behavior": "ADR emits both axes for all eight classified stateful services (nine PVCs)",
    "verification": "grep -c '| .* | .* | .* |' docs/adr/adr-0XX-stateful-service-placement.md | awk '{exit !($1 >= 9)}'",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "ADR028-004-f2",
    "behavior": "Static classification gate fails on an unclassified stateful service, demonstrated red then green",
    "verification": "poetry run pytest tests/test_stateful_service_classification.py -v",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "ADR028-004-f3",
    "behavior": "Both overlays render and staging e2e passes after MinIO's staging twin retires",
    "verification": "kubectl kustomize infra/k8s/overlays/staging && kubectl kustomize infra/k8s/overlays/prod && make test-e2e ENV=staging",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "ADR028-004-f4",
    "behavior": "Both overlays render and staging e2e passes after Gitea's staging twin retires and prod moves to Beelink",
    "verification": "kubectl kustomize infra/k8s/overlays/staging && kubectl kustomize infra/k8s/overlays/prod && make test-e2e ENV=staging",
    "state": "pending",
    "evidence": ""
  }
]
```
