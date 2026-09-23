---
tags: [spec, verification, templates]
created: "2026-09-22"
---

# Verification - SSOT-017-oidc-client-ssot

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Scoping, 2026-09-22, decided with the operator:

- **Generated client file, not a full `configuration.yml` template, and not a guard only.** Authelia 4.39 merges multiple config files, but lists are not combined across files, so the whole `clients` list lives in `oidc-clients.yml`. That is the smallest change that leaves a single writer.
- **`kubelab-oidc` leaves the SSOT.** No K8s registration and no consumer. Its secret pair is handed to #1777.
- **Per-environment shape: `envs` plus a domain reference.** The redirect host is derived from the service's declared domain, never written per environment. The alternative, one list carrying both environments' URIs as `vikunja-oidc` does today, was rejected because it lets each environment accept the other's callbacks.
- **`argocd` is prod-only.** The hub's issuer is prod Authelia (`infra/helm/argocd/values.yaml:208`), so the staging registration was unreachable.
- **Stored digests, not recomputed ones.** This deviates from ADR-040 §1's wording; see proposal R7.
- **#1332's body was stale on the auth method.** gitea is `basic`, measured 2026-08-23, and argocd is the `post` client. Corrected on the issue: <https://github.com/mlorentedev/kubelab/issues/1332#issuecomment-5786621926>.

**R5 re-grep (2026-09-22).** No K8s consumer references a removed or renamed id:
- `kubelab-oidc` appears only as the name of a Gitea bootstrap marker file;
- `grafana-oidc` appears in `docs/runbooks/sops-and-secrets.md:334`, already listed by audit D14;
- `minio-oidc` appears in the Compose `compose.base.yml`, which dev blanks. It was added to #1782.
The staging `argocd` registration has no consumer, because the hub's issuer is prod.

**R8 measurement (2026-09-22).** The only dev OIDC consumer is Grafana: the Compose stack enables generic OAuth. MinIO's `compose.dev.yml` blanks its OpenID config. `dev.yaml` carried a third copy of the client list, in the old schema; it was deleted, and `grafana` declares `dev`.

**R1 verified.** After the schema migration, the resolver's output for prod equals the five running prod clients field for field, auth methods included. The generated digests equal the previously committed ones for every client in both envs, so nothing was rotated.

**Mutation proof (2026-09-22, after commit `b488caf7`).** Each mutant turned its guard red:
- a hand edit to the generated file (argocd `post` changed to `basic`) turned the AC1 guard red;
- dropping the second file from `X_AUTHELIA_CONFIG` turned AC2 red;
- a generator hardcoding the auth method turned AC1 red.

`/spec check` on 2026-09-22 (agent judgment, deterministic path): **PASS**. AC1 through AC6 are each covered by `[AC<n>]`-tagged Implementation tasks, and there are no orphan tasks.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/SSOT-017-oidc-client-ssot/` -> `specs/archive/SSOT-017-oidc-client-ssot/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
