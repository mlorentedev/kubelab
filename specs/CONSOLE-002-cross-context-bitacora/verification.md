---
tags: [spec, verification, templates]
created: "2026-06-20"
---

# Verification - CONSOLE-002-cross-context-bitacora

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] AC1 (Context round-trips git + Postgres projection) -> commit `<hash>` / test `TestContextRoundTrip`
- [ ] AC2 (append-only event history, prior events immutable) -> commit `<hash>` / test `TestAppendOnlyHistory`
- [ ] AC3 (GitHub adapter ingest + write verified by re-read) -> commit `<hash>` / test `TestGitHubAdapterVerifiedWrite`
- [ ] AC4 (default-deny per-context routing) -> commit `<hash>` / test `TestResolveContextPolicyDefaultDeny`

## Test status

### PR-1a (Postgres infra foundation) — 2026-06-20

- Unit suite (`poetry run pytest tests/ --ignore=tests/e2e --ignore=tests/infra`): **249 passed, 11 failed**.
  The 11 failures (`test_k8s_secrets_users_db.py`, `test_k8s_secrets_apprise.py`) are **pre-existing and
  SOPS-dependent** — confirmed by re-running them on the clean state with my changes stashed (same 11 fail).
  They need decrypted SOPS hashes/tokens, absent locally (no `sops` binary); they pass in CI (age key present).
- New tests: `tests/test_k8s_generator_configmap_env.py` — 3 passing, guard the ADR-051 D4 behavior.
- Generators (`toolkit config generate --env {staging,prod} --force`): `configmaps.yaml` regenerated; diff is
  exactly `INFRA_POSTGRES_{HOST,PORT,DATABASE,USERNAME}` added to api-config + web-config, **no
  `INFRA_POSTGRES_IMAGE`** (guard works). `ingress.yaml` / `hosts.yml` unchanged → drift gate green for those.
- `toolkit/scripts/sync_k8s_images.py`: `postgres:16-alpine` synced into `base/kustomization.yaml` images.
- No regressions introduced (the only failures are the pre-existing SOPS-local ones above).

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **PR-1 split into PR-1a (infra) + PR-1b (data layer)** per the ~300-LOC guard. PR-1a = ADR-051 + manifest +
  `infra.postgres` SSOT/SOPS + ConfigMap guard. PR-1b = atlas schema + `env.go` DSN + real `pg_isready`.
- **Deployment + PVC, not StatefulSet** (tasks.md said StatefulSet): the repo has zero StatefulSets; every
  stateful service (gitea/loki/minio/n8n) is `Deployment(Recreate)` + PVC. A single Postgres needs no clustered
  identity → matched the convention rather than introduce the first StatefulSet. (ADR-051 D1.)
- **`username` in common.yaml, only `password` in SOPS** (tasks.md said both in SOPS): mirrors the SMTP precedent
  (`user` non-secret, `pass` secret). Password is `RANDOM_TOKEN` (our own DB password, not an external credential).
- **Dropped the separate `version` field** — redundant with the tag in `image`; no other service splits them.
- **ConfigMap deploy-concern guard (ADR-051 D4)**: `_extract_app_env_vars` now skips `*_IMAGE`/`*_VERSION`, so the
  shared `infra.postgres.image` (needed by `sync_k8s_images`) does not leak into every component's ConfigMap.
- **Env note (not a code decision):** Poetry on the dev box was tied to a deleted interpreter; reinstalled on
  Python 3.12.8 (CI parity). `sops` is not installed locally → secret-bearing generators/tests are skipped, which
  is why generating `infra.postgres.password` and the 11 SOPS tests are deferred to a SOPS-enabled context.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/CONSOLE-002-cross-context-bitacora/` -> `specs/archive/CONSOLE-002-cross-context-bitacora/`
- [ ] Backlog entry in vault `11-tasks.md` ticked with PR link
- [ ] Promotions above executed (if any)
