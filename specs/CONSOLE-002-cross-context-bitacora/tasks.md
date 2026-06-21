---
tags: [spec, tasks]
created: "2026-06-20"
---

# Tasks - CONSOLE-002-cross-context-bitacora

> TDD order. One task = one focused commit. Module 1 does NOT fit one atomic PR — it is a
> sequence of ~9 PRs (each ≤ ~300 LOC prod diff per AGENTS.md). This file holds the full PR
> roadmap plus the detailed TDD checklist for the PR currently in flight. Freeze a PR's
> checklist once its branch starts; reorder freely while still `draft`.

## Locked decisions (2026-06-20)

- **Store wiring = DI in `board/` only.** Introduce a `Store` interface + constructor injection
  in the new `internal/board/` package. The existing newsletter code (module-level `conf`
  singleton, free-function handlers) is NOT touched. TDD needs an injectable fake.
- **Ordering = DB-first.** After the test harness (PR-0), Postgres infra + schema land first;
  git event-store and projector follow. (Trade-off accepted: infra precedes the first green AC.)
- **Migration tool = atlas** (schema-as-Go / declarative). One-paragraph **ADR-051** captures the
  Postgres-as-data-service + atlas lock-in before PR-1 freezes it (Regla del 3).

## Grounding prerequisites (from codebase audit, not assumptions)

- **No tests exist** in `apps/api/src` and CI runs only `go vet` + `go build` — a failing test is
  invisible today. PR-0 retrofits the harness from zero. (blocks every TDD criterion)
- **Postgres is 100% greenfield** — no `infra.postgres`, no K8s manifest, no migration tool. The
  only Postgres in the repo is Gitea's embedded one. D7 is new infra, not wiring.
- **Authelia identity is NOT in the Go API** (enforced upstream at Traefik ForwardAuth);
  `middleware.go` is CORS-only. In M1 `owner`/`context_id` is passed **explicitly** (header/param),
  not read from a session. C6 ("reuse Authelia identity") has no in-process hook yet.
- **go.mod skew**: declares `go 1.23.1`; CI/Docker build on `1.25`. Align the directive when the
  first dependency lands.

## Setup

- [x] Branch created from master: `feat/CONSOLE-002-cross-context-bitacora` ✓ 2026-06-20
- [x] `proposal.md` complete; acceptance criteria testable ✓ 2026-06-20 (ratified)
- [x] No blocking open questions in `proposal.md` (2 resolved + 3 locked; remainder are
      implementation-time, not gates) ✓ 2026-06-20

## PR roadmap (DB-first)

| PR | Title | ~LOC (prod+test) | Acceptance |
|----|-------|------------------|------------|
| 0 | `ci: go test step + first Go test harness` | 40 + 60 | enables all (TDD prereq) |
| 1 | `feat(infra): Postgres on K3s + infra.postgres SSOT + atlas + initial schema` | ~190 | AC1 (PG provisioning) |
| 2 | `feat(api): Context + work-item append-only domain model + Store interface (DI)` | 180 + 150 | AC2 |
| 3 | `feat(api): Postgres projection Store (idempotent upsert + read model)` | 210 + 160 | AC1 (PG persistence) |
| 4 | `feat(api): git-canonical event store (go-git append + replay)` | 220 + 180 | AC1 (git half) · AC2 |
| 5 | `feat(api): synchronous in-process projector git→Postgres + round-trip test` | 150 + 140 | AC1 (headline) |
| 6 | `feat(api): bitacora query+write HTTP endpoints under /v1/board` | 180 + 170 | What #4 |
| 7 | `feat(api): resolveContextPolicy default-deny isolation gate` | 110 + 130 | AC4 |
| 8 | `feat(api): GitHub forge adapter (issue ingest + verified status write)` | 230 + 180 | AC3 |

Notes:
- ADR-051 (Postgres + atlas) is authored alongside PR-1.
- PR-7 (policy gate) needs only the domain model (PR-2); it may be pulled earlier if convenient.
- The projector (PR-5) stays **synchronous + in-process** (write-path + startup replay). No separate
  deployment / watcher goroutine / webhook / CronJob — scope guard against ADR-050 MVP discipline.
- Idempotency keyed on event UUID (`ON CONFLICT (event_id) DO NOTHING`) is non-negotiable from PR-3 on
  (git-write-succeeds / PG-write-fails is the designed-for failure mode; git wins).

---

## PR-0 — `go test` CI step + first Go test harness  ← IN FLIGHT

> Trigger: first step of a multi-PR sequence + touches deployed CI config (Discipline Gate).
> The "feature" IS the test harness. No domain code.

### Red — make a test exist and run

- [x] Baseline: `go test ./...` from `apps/api/src` reports `no test files` (proves zero tests today). ✓ 2026-06-20
- [x] **Course correction (init() panic):** `services.init()` calls `config.GetConfig()` which `panic`s
      when `validateConfig` fails (SITE_TITLE required). Any `_test.go` in `package services` panics on
      load — so the planned `IsValidEmailFormat` test is unusable. Chose `pkg/config` instead (no
      `init()`): `apps/api/src/pkg/config/env_test.go`, table-driven test of the **pure** `validateConfig`
      (dev/staging/prod valid + invalid env + empty env + missing title/domain/smtp branches). ✓ 2026-06-20
- [ ] Local verify: test passes and exercises real failure branches (run with a wrong expectation once
      to confirm assertions execute, not just compile).

### Green — wire the harness into CI

- [x] `.github/workflows/ci-pipeline.yml`: added `Test API code` step (`go test -race ./...`,
      `working-directory: ./apps/api/src`) gated on `should_build` + `inputs.app == 'api'`, placed
      AFTER `Lint API code` and BEFORE `Build API binary` so a red test blocks the build. ✓ 2026-06-20
- [x] Reuses the existing `actions/setup-go@v6` (`go-version: '1.25'`) — no second Go setup. ✓ 2026-06-20

### Refactor / verify

- [x] Locally from `apps/api/src`: `go vet ./...` (OK) + `go test ./...` (`ok pkg/config 1.876s`,
      rest `no test files`) + `go build` (OK). `-race` deferred to CI (Linux); Windows lacks gcc. ✓ 2026-06-20
- [ ] PR body notes the `go.mod` 1.23.1 vs CI/Docker 1.25 skew; defer aligning the directive to the
      first PR that adds a dependency (PR-1/atlas or PR-4/go-git).
- [x] Production `.go` files unchanged — diff is CI yaml + one `_test.go` (plus the ratified spec docs,
      bundled into this PR per the "todo junto en esta rama" routing choice). ✓ 2026-06-20
- [ ] `verification.md`: paste the CI run URL showing `Test API code` executing + passing.

---

## PR-1 — Postgres + atlas + schema (next)

> Stand up the persistence foundation. Author **ADR-051** (Postgres data-service + atlas) in the same PR.

- [ ] ADR-051 drafted: why Postgres now (D7), why atlas, connection-detail SSOT, init-container migration flow.
- [ ] `infra/k8s/base/services/postgres.yaml` — StatefulSet + PVC + Service, house style mirroring
      `redis.yaml` but PVC-backed (`postgres:16-alpine`).
- [ ] `infra.postgres.{host,port,database,version,image}` in `common.yaml` + SOPS
      `infra.postgres.{username,password}`; register in `toolkit/features/secrets_manager.py`
      `SECRET_CATALOG` + `k8s_secrets.py` mapping so `INFRA_DATABASE_URL` / `INFRA_POSTGRES_*` reach the
      api ConfigMap+Secret (ADR-036).
- [ ] `INFRA_DATABASE_URL` in `pkg/config/env.go` — optional (required only in prod via `validateConfig`),
      so the API still boots when unset (mirrors SMTP-optional pattern).
- [ ] atlas schema + first migration: `contexts`, `work_items`, `events` (`context_id` NOT NULL
      everywhere; `events` PK = UUID for idempotency).
- [ ] Real DB ping in `checkDatabaseConnection` (`healthchecks.go`) replacing the mock.
- [ ] Tests: migration applies cleanly; ping succeeds against an integration DB (skipped when
      `DATABASE_URL` unset so unit CI stays green).
- [ ] LOC guard: if SSOT + SOPS + manifest crosses ~300, split the K8s manifest from the SSOT/secrets wiring.

## Closing (whole module)

- [ ] Every acceptance criterion covered by ≥1 test
- [ ] Every acceptance criterion has a `features.json` entry with a non-vacuous verification command
- [ ] `go vet` + `go test -race` + lint pass
- [ ] No unrelated changes / scope creep in any PR
- [ ] `verification.md` filled per PR
- [ ] Each PR references this spec folder

## Machine-readable features

Sibling `features.json` (one entry per acceptance criterion). The agent CANNOT write
`"state": "passing"` — only the harness, after running `verification` with exit 0, sets that terminal
state. Reviewers reject PRs where `features.json` has `passing` entries with empty `evidence`.
