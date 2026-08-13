---
id: "adr-061-stateful-service-placement"
type: adr
status: accepted
created: "2026-08-12"
tags: [architecture, kubernetes, state, topology, environment-promotion]
related:
  - adr-028-operational-topology
  - adr-037-environment-promotion-strategy
  - adr-049-edge-object-storage-placement-doctrine
  - adr-050-cross-context-command-center
  - adr-051-postgres-data-service
issue: mlorentedev/kubelab#988
owner: manu
---

# ADR-061: Stateful Service Placement

## Status

Accepted — 2026-08-12. Tracks [#988](https://github.com/mlorentedev/kubelab/issues/988) (ADR028-004).

Amends [ADR-028](adr-028-operational-topology.md) (operational topology) and [ADR-037](adr-037-environment-promotion-strategy.md) (environment promotion). Neither is superseded: this ADR adds a second axis that those two were silently conflating.

## Date

2026-08-12

## Context

Nine stateful `PersistentVolumeClaim`s run in **both** staging and prod. Not one of them was placed there by a decision.

They sit in `infra/k8s/base/services/`, both overlays consume `../../base`, and so every stateful service is duplicated across environments as a **side effect of a packaging choice**. No ADR records it, and the two ADRs that should have covered it each answer half the question:

- **ADR-028** decides *where compute lives* — the always-on / on-demand split, and its "would I need this at 3 AM?" test. It says nothing about state.
- **ADR-037** decides *what staging is for* — a mutable test bed validated before prod. It assumes a second instance is always meaningful.

The gap between them is the question neither asks: **does a second live instance of this service's state make sense at all?** For Grafana it does — its dashboards are ConfigMaps, so the second instance is reconstructable from git. For Gitea it does not — a second live instance is a second set of repositories that no promotion path can ever merge back.

This became urgent rather than theoretical because real data is about to land in Gitea and MinIO. That makes now the last moment their placement is a free decision rather than a stateful migration with a downtime window and metadata that git clones do not replicate.

A verification pass (`specs/ADR028-004-.../verification.md`) also corrected the premise the work started from. The operator's report was that `gitea`, `n8n` and `minio` were all empty and unused. Gitea and MinIO checked out. **n8n did not** — its staging instance hosts an active workflow (`notify-router`, the notification fabric), and its prod instance is the live alerting path. That single finding flipped n8n's classification and is why the table below is not "retire all three".

## Decision

### D1 — Two independent axes, not one

Every stateful service is classified on **both**:

| axis | question | values |
|---|---|---|
| `state_promotion` | Does this state have a promotion path in git? | `dual` \| `singleton` |
| `location` | ADR-028's 3 AM test | `always-on` \| `on-demand` \| `undecided` |

`dual` means a second instance is *reconstructable* — the state is a projection of something git-canonical, so staging and prod may both run live. `singleton` means a second live instance would **fork** state that nothing can merge back.

The axes do not imply each other. **"Prod" is an environment, not a location** — the conflation of those two is the root of the drift this ADR corrects.

### D2 — The classification

| service | state_promotion | location |
|---|---|---|
| `authelia` | dual | always-on |
| `crowdsec` | dual | always-on |
| `gitea` | singleton | on-demand |
| `grafana` | dual | always-on |
| `loki` | dual | always-on |
| `minio` | singleton | undecided |
| `n8n` | dual | always-on |
| `postgres` | dual | always-on |

Eight services, nine PVCs — `crowdsec` owns two (`crowdsec-db`, `crowdsec-config`).

**The `dual` rows.** `authelia`, `crowdsec`, `grafana` and `loki` promote their configuration as ConfigMaps; their PVCs hold derived or disposable content (sessions, decision caches, log data), never canonical state. `postgres` is `dual` by citation, not re-derivation: [ADR-051](adr-051-postgres-data-service.md) D1 already deploys it to staging and prod, and [ADR-050](adr-050-cross-context-command-center.md) D7 already establishes its content as a projection of git-canonical state plus an object-store backup — the same shape as the ConfigMap-promoted services.

**`gitea` is a singleton and moves to the Beelink platform node.** Its role is settled: private repos and private experiments only, with Argo CD continuing to reconcile from GitHub. It therefore does not inherit prod's always-on requirement — the operator pushes to it only with the homelab powered on. The node is an implementation detail of the `on-demand` value, not a third axis.

**`n8n` carries a binding condition — see D3.**

**`minio` is deferred, and the deferral is bounded — see D4.**

### D3 — n8n stays dual, on a condition that is binding

n8n is `dual` **only while git plus `toolkit infra n8n import` remains the sole write path into either instance.**

This is a constraint, not background colour. n8n's one workflow is git-projected through a mechanism that is special-cased to that workflow — it is not a general import/export route. A workflow authored by hand in either instance's UI would fork state immediately and with no way back, at which point n8n is a `singleton` that has been mislabelled `dual`, and the classification silently becomes false.

The general gap (a real promotion path for n8n workflows) is tracked separately and deliberately out of scope here.

Its `location` needed no decision: n8n's prod instance is the live alerting path, so ADR-028's own 3 AM test forces `always-on`, and it never left K3s prod.

### D4 — MinIO's location is deferred, with a stated condition for deciding it

`location: undecided` is a **recorded decision, not an omission**, and the declaration must name the ticket that owns it ([#972](https://github.com/mlorentedev/kubelab/issues/972)).

The reason it cannot be decided today is concrete rather than procedural. `infra/k8s/overlays/prod/backup.yaml` targets `http://minio:9000`, which makes the in-cluster MinIO **the only backup destination that currently exists**. So MinIO's location is not free — it is *coerced* to always-on by a dependency that [ADR-049](adr-049-edge-object-storage-placement-doctrine.md) D3 has already superseded **by decision but not by implementation**: the real offsite tiers are Hetzner Storage Box (Borg) and R2 (restic), and neither pipeline is built. Same-cluster storage was never an offsite copy.

Recording that coerced state as `always-on` would encode an accident as a decision — precisely the failure this ADR exists to correct.

**Condition for deciding it:** once the real offsite path exists, MinIO loses its only load-bearing role, and the question stops being "where does it live" and becomes "does anything still consume it?" — at which point the answer may well be retirement rather than relocation. Deciding sooner would set the offsite tier by accident.

### D5 — The classification is enforced, not merely documented

The table above is prose and prose rots. The enforceable copy lives in `common.yaml`, beside each service's existing configuration, and a static test fails when a stateful service discovered in the manifests carries no classification.

Three properties make it a gate rather than decoration:

- **Ground truth is the manifests**, not a hand-kept list. A service that gains a PVC is classified or CI fails.
- **Values are checked for membership**, not just presence. A typo like `singelton` passing a presence check is a gate that cannot fail.
- **`undecided` must name its ticket**, so the sentinel cannot quietly become the dodge for every future service.

`postgres` lives at `infra.postgres` rather than `apps.services.*` (ADR-051 D2), so the check resolves each service's block from wherever it actually lives instead of walking a single tree. That same split required extending the ConfigMap generator's exclusion set — the classification keys are read by a static gate and never by a running pod, so they are excluded exactly as ADR-051 D4 excludes `IMAGE`/`VERSION` pins. Without that, being under `infra.*` would have emitted them into every component's ConfigMap, changing every `configMapGenerator` hash and rolling every pod.

## Consequences

- The staging twins of `gitea` and `minio` leave `base/`. The platform tier becomes singleton for those two services.
- **Their intended test path is an ephemeral restore from a prod backup, declared here as doctrine and not as present capability.** Verified restore is open work; until it lands, the honest statement is that these services have no staging validation path, not that they have a restore-based one.
- Gitea leaves Kustomize and Argo CD's reconciliation when it moves to Docker Compose on Beelink. This is deliberate and has two precedents in this repo — Headscale outside K3s (ADR-015) and the Argo CD hub outside both clusters — for the same reason: a platform component cannot be reconciled by the GitOps system that depends on reaching it. Gitea hosting the repos Argo CD would otherwise fetch from is exactly that trap, avoided by keeping Argo CD on GitHub.
- Retiring Gitea's PVC requires editing `overlays/prod/backup.yaml` in the **same change**, or the backup CronJob renders and applies cleanly while mounting a claim that no longer exists. That file is prod-only, so staging e2e never exercises it.
- The `dual` rows are unchanged in deployment. This ADR records why they are duplicated; it does not move them.

## Alternatives considered

**One axis ("is this prod-only?").** Rejected — it is the conflation that produced the drift. It cannot express "singleton state that lives on an on-demand node", which is exactly Gitea.

**Classify but do not enforce.** Rejected. The premise this work started from ("gitea, n8n and minio are all empty") was wrong about one of three, and was only caught by verifying rather than re-asserting. A classification with no gate would decay the same way the original placement did.

**Decide MinIO's destination now, for completeness.** Rejected — see D4. A complete-looking table is not worth deciding the offsite tier by accident.

**Restructure `base/` into a `platform/` tier while touching these files.** Rejected as scope. It is a layout refactor, and it depends on this classification being settled first.

## References

- Spec: `specs/ADR028-004-classify-stateful-service-placement/` — proposal, task list, and the verification evidence for all six risks.
- Amends: [ADR-028](adr-028-operational-topology.md), [ADR-037](adr-037-environment-promotion-strategy.md).
- Cited: [ADR-049](adr-049-edge-object-storage-placement-doctrine.md) D3 (offsite tiers), [ADR-050](adr-050-cross-context-command-center.md) D7 (git + Postgres projection + object-store backup), [ADR-051](adr-051-postgres-data-service.md) D1/D2/D4 (Postgres placement, its `infra.*` SSOT, and the ConfigMap exclusion precedent).
- Precedent for keeping a platform component outside the GitOps system that depends on it: [ADR-015](adr-015-vps-k3s-migration-strategy.md) (Headscale stays in Docker Compose on the VPS).
