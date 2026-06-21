---
id: "adr-051"
type: adr
status: accepted
owner: manu
date: "2026-06-20"
issue: "kubelab#711"
tags: [architecture, decision, postgres, data-service, atlas, migrations, shared-infra, lock-in, console]
depends_on: [adr-036-shared-infra-namespace, adr-050-cross-context-command-center, adr-014-secrets-management-strategy, adr-027-generated-code-drift-detection, adr-024-pvc-backup-strategy, adr-049-edge-object-storage-placement-doctrine, adr-042-reference-architecture]
created: "2026-06-20"
---

# ADR-051: Postgres as a shared K3s data-service (atlas for schema migrations)

## Status

Accepted — 2026-06-20. **Implements [[adr-050-cross-context-command-center|ADR-050]] D7** (canonical state = git + Postgres projection + object-store backup) and **extends [[adr-036-shared-infra-namespace|ADR-036]]** with a new shared-infra service, `infra.postgres`. First infrastructure step of CONSOLE-002 (#711); freezes the persistence + migration substrate before the board schema lands.

## Context

ADR-050 D7 fixed the *high-level* state model (git canonical + Postgres projection + offsite backup) but deferred two implementation questions that a schema cannot be written without:

1. **How Postgres runs** in the cluster.
2. **How its schema is migrated** — a lock-in choice, because a migration-history format is expensive to swap once it holds production history.

State verified at decision time: the repo has **zero Postgres** (only Gitea's embedded SQLite). This is greenfield infra — no data to migrate, no sunk cost. The constraint is therefore "pick the convention-matching, portable option," not "minimise migration pain."

## Reference audit (Regla del 3, ADR-015)

The data-service tier is part of the ADR-042 blueprint ("state off compute nodes via an object-store *role* + Postgres", C3), so the cross-instance-reuse gate fires.

| Dimension | R1 · repo precedent (stateful services) | R2 · migration tooling | R3 · ADR-042/050 blueprint |
|---|---|---|---|
| Run model | gitea/loki/minio/n8n = `Deployment(replicas:1, Recreate)` + separate PVC, secrets via `SECRET_DEFINITIONS`, image via `sync_k8s_images` SSOT. **Zero StatefulSets exist.** | n/a | `tier-data-service` is a *role*; substrate picks the vendor (Postgres-on-K3s here) |
| Schema model | Gitea/n8n self-migrate (opaque); no reviewable migration artifact in-repo | **atlas** = declarative schema-as-code + versioned migrations + `migrate diff`/`lint`; golang-migrate/goose = imperative SQL files, no diffing; ORM auto-migrate = implicit, no artifact | "generate + drift-gate" doctrine (ADR-027): the source is the SSOT, derived files are checked |
| Portability | in-cluster, S3/pg_dump-portable | atlas runs against *any* Postgres (not a vendor primitive) | blueprint names roles, never vendors (ADR-049 D1) |

### Divergence log

- **Intersection (load-bearing, safe):** Postgres reached over the standard SQL/`pg_dump` contract = portable commodity (same class as S3 in ADR-049 D2). Admissible inside the blueprint as `tier-data-service`.
- **Lock-in (substrate only):** atlas's migration-history format (`atlas.sum` + versioned dir) is the sticky part — switching tools later means re-baselining. Accepted as a **deliberate substrate lock-in** with low blast radius (one DB, greenfield, the *data* stays portable). atlas is never a blueprint dependency.
- **Strategic finding:** atlas's declarative model mirrors the repo's own SSOT/drift doctrine (ADR-027) — schema-as-SSOT, migrations derived-and-linted — so it is the *consistent* choice, not just a popular one.

## Constraints

| # | Constraint | Origin |
|---|---|---|
| C1 | Postgres is **shared infra** (`infra.postgres`), placed under `infra.*` even though M1 has one consumer (the board); pgvector/memory is the planned second consumer | ADR-036; ADR-027/043 |
| C2 | Connection **secrets via SOPS + `SECRET_DEFINITIONS`**, never in ConfigMaps | ADR-014/038, ADR-036 |
| C3 | Image **pinned via common.yaml SSOT + `sync_k8s_images`**; deploy-concern keys stay out of ConfigMaps | ADR-027 |
| C4 | **Single replica, PVC-backed, `Recreate`** — no HA in M1 (matches gitea/minio at single-operator scale) | ADR-029 |

## Options Considered

**Run model:**

| Option | Verdict |
|---|---|
| In-cluster `Deployment(Recreate)` + PVC | **Chosen** — matches every stateful service in the repo |
| StatefulSet + `volumeClaimTemplates` | Rejected — would be the repo's first; ordered identity / stable network ID / per-replica volumes solve multi-replica problems a single Postgres does not have |
| Managed cloud Postgres (RDS/Neon) | Rejected — contradicts the ADR-031 anti-lock-in pitch, adds cost + VPN-reachability complexity |
| Reuse Gitea's embedded DB | Rejected — not a general-purpose data-service |

**Migration tool:**

| Option | Verdict |
|---|---|
| **atlas** (declarative schema-as-code) | **Chosen** — diff/lint in CI fits the generate-and-drift-gate doctrine; schema is the SSOT |
| golang-migrate / goose | Rejected — imperative SQL files, no schema diffing/linting, no SSOT |
| ORM auto-migrate (GORM) | Rejected — implicit, no reviewable migration artifact, fights the drift discipline |

## Decision

- **D1 — In-cluster Deployment.** Postgres runs as `Deployment(replicas:1, strategy:Recreate)` + `PersistentVolumeClaim(ReadWriteOnce)` + `ClusterIP Service`, in `infra/k8s/base/services/postgres.yaml` (deploys to staging + prod), house style mirroring `gitea.yaml`. Image `postgres:16-alpine`, `PGDATA` in a sub-directory of the mount.
- **D2 — SSOT at `infra.postgres` (ADR-036).** Non-secrets (`host`, `port`, `database`, `username`, `image`) in `common.yaml`; **`password` in SOPS** (`RANDOM_TOKEN`, machine-generated — this is our own DB password, not an external credential). The server reads `POSTGRES_PASSWORD` from the `postgres-secrets` K8s Secret; `POSTGRES_USER`/`POSTGRES_DB` are literals in the manifest annotated with the `common.yaml` SSOT key they mirror. Consumers (PR-1b+) read `INFRA_POSTGRES_*` from their ConfigMap + `INFRA_POSTGRES_PASSWORD` from their Secret and compose the DSN themselves (no `DATABASE_URL` literal on disk).
- **D3 — atlas is the migration tool.** The schema is the SSOT; migrations are generated + linted and committed (`atlas.sum` + versioned dir). They are applied by a migration step (init-container / Job) that runs before the app reads the DB — wired in PR-1b/PR-3, not this PR.
- **D4 — Deploy-concern keys excluded from ConfigMaps.** Keys whose trailing segment is `IMAGE`/`VERSION` (e.g. `INFRA_POSTGRES_IMAGE`) are skipped by the ConfigMap generator so a shared image pin does not leak into every component's ConfigMap.

## Consequences

**Positive:** ADR-050 D7's state model gets a concrete, convention-matching substrate; atlas aligns with the existing SSOT/drift-gate discipline; the same Postgres is reusable by pgvector/memory (ADR-027/043) without re-deciding placement.

**Negative:** introduces the repo's first Postgres → a new backup surface (covered by the ADR-024 PVC-backup CronJob pattern + ADR-049 offsite); atlas migration-history lock-in (accepted, low blast radius).

**Neutral:** single-replica (no HA) is fine at single-operator scale (ADR-029); HA is a later increment. The committed `secrets.yaml` placeholders are documentation only — Secrets are applied imperatively via `toolkit secrets apply`.

## Implementation / backlog

- **This PR (PR-1a):** this ADR + `postgres.yaml` + `infra.postgres` SSOT/SOPS wiring (`SECRET_CATALOG`, `postgres-secrets` mapping, `sync_k8s_images`) + the ConfigMap deploy-concern guard.
- **Next (PR-1b):** atlas schema (`contexts`, `work_items`, `events` — `context_id NOT NULL`, `events` PK = UUID for idempotency), `INFRA_DATABASE_URL`/DSN composition in `pkg/config/env.go`, real `pg_isready`/ping in `healthchecks.go`.
- **Later:** migration init-container/Job (PR-3); PVC backup for the Postgres volume (ADR-024 pattern); offsite per ADR-049.

## References

- [[adr-050-cross-context-command-center]] (D7 canonical state), [[adr-036-shared-infra-namespace]] (`infra.*`), [[adr-014-secrets-management-strategy]] / ADR-038 (secret delivery), [[adr-027-generated-code-drift-detection]] (generate + drift gate), [[adr-024-pvc-backup-strategy]] (PVC backup), [[adr-049-edge-object-storage-placement-doctrine]] (offsite), [[adr-042-reference-architecture]] (blueprint vs substrate)
- Tickets: CONSOLE-002 (#711)
- atlas: atlasgo.io (declarative schema migrations)
