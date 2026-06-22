---
tags: [spec, verification, templates]
created: "2026-06-21"
---

# Verification - TOOL-014-k8s-connect

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [!] **AC1** (`make connect ENV=staging` + `kubectl get ns`) -> **PENDING live validation** against staging (needs homelab on + ts-bridge joining the mesh). Code path implemented + unit-tested (`resolve_transport`, `ts_bridge_argv`, healthcheck loop).
- [x] **AC2** (idempotent no-op) -> `_port_listening` short-circuit in `connect()`; manual: `make connect-status ENV=staging` reports down cleanly, re-runs are no-ops.
- [x] **AC3** (`access status` + `disconnect`) -> tests `TestTransportState`; manual: `make connect-status ENV=staging` (ts-bridge target, down), `make disconnect ENV=prod` (public no-op).
- [x] **AC4** (no hardcoded IPs; pure helpers unit-tested) -> `tests/test_k8s_connect.py::TestResolveTransport::test_no_hardcoded_ips_target_comes_from_the_ssot` + `TestCommittedSSOT` (18 tests, no network).
- [x] **AC5** (onboarding runbook) -> `docs/runbooks/operate-from-new-workstation.md`.

## Test status

- Unit (feature): `poetry run pytest tests/test_k8s_connect.py -q` -> **18 passed**.
- Unit (full, excl. e2e): `poetry run pytest tests/ --ignore=tests/e2e -q` -> **295 passed, 21 deselected** (no regressions; sibling `test_k8s_kubeconfig` green).
- Lint: `make lint` -> **All checks passed** (ruff check + format).
- Type: `make type` -> my files clean; 2 pre-existing errors in `generator_authelia.py` (`os.geteuid` on Windows), unrelated.
- Manual smoke: `make connect-status ENV=staging` (resolves ts-bridge -> 100.64.0.11:6443, reports down), `make disconnect ENV=prod` (public no-op), unknown-env -> exit 2 listing `hub, prod, staging`.
- **Not yet exercised:** live `make connect ENV=staging` end-to-end (the only network-dependent AC).

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **Sub-noun `infra k8s access *` instead of flat verbs** — `infra k8s status` already exists (namespace workloads); nesting the transport trio avoids the collision and leaves the legacy command untouched.
- **prod is a no-op, not a tunnel** — ts-bridge dials targets *through* the mesh, so it cannot reach a public IP outside the mesh. "prod public, no tunnel" means prod's cert SAN covers the public IP and `connect prod` only verifies reachability (the prod kubeconfig targets the public apiserver directly). Full prod end-to-end is deferred (acceptance is staging-focused).
- **Derive, don't extend the SSOT** — the transport target is computed from the existing `clusters.<env>.node` against `networking.*` (position-aware, mirrors SSOT-014a). No edit to the `clusters:` block; apiserver port defaults to 6443 in code. Stronger SSOT-purity than adding a field.
- **ASCII-only CLI/log strings** — `→`/`—` (U+2192/U+2014) crash Typer/Rich `--help` rendering on the Windows cp1252 console (`UnicodeEncodeError`). Same class as the SOPS-basename portability trap. Replaced with `->`/`-`.
- **Idempotency keyed on the local port, not pid liveness** — `_port_listening(127.0.0.1:<local_port>)` is the cross-platform "is it up" check; the statefile carries the pid only for `disconnect`.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons.md`? **yes** — non-ASCII (`→`/`—`) in Typer/Rich CLI help/log strings crashes `--help` on the Windows cp1252 console; keep CLI strings ASCII (same class as the SOPS-basename portability trap).
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? **no** — ADR-052 already covers the transport design; this is its implementation.
- [ ] New pattern candidate for `00_meta/patterns/`? **no** — repo-local, not cross-project.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
