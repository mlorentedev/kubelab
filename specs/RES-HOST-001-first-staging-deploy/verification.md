---
id: RES-HOST-001-first-staging-deploy
type: verification
status: draft
created: "2026-11-13"
issue: "mlorentedev/kubelab#2366"
owner: manu
---

# RES-HOST-001 verification

Filled as slices land. Each row records the command run, its result, the PR or
commit, and the date. Deployed rows name who ran them. No secret value, and no
digest of a real credential, is recorded here. The probe's plaintext is not a
credential; its digest check reports only match or mismatch.

## Acceptance criteria

| AC | Command or check | Result | PR / commit | Date |
|---|---|---|---|---|
| AC1 | `uv run pytest tests/test_product_contract.py tests/test_product_contract_guards.py` | | | |
| AC2 | `uv run pytest tests/test_product_contract_schema.py` | | | |
| AC3 | `make validate-sync` | | | |
| AC4 | renderer tests on the resume fixture snapshot | | | |
| AC5 | `uv run pytest tests/test_stateful_service_classification.py` | | | |
| AC6 | `uv run pytest tests/test_product_staging_hostname.py` | | | |
| AC7 | `uv run pytest tests/test_networkpolicy_coverage.py tests/test_authelia_access_rules.py` | | | |
| AC8 | staging: apply, bootstrap, key label count, cert fingerprint, probe digest, rerun unchanged (deployed) | | | |
| AC9 | resume pod `Ready` on `/healthz` (deployed) | | | |
| AC10 | `operator` 403, `superadmin` 200 on `resume.staging.kubelab.live` (deployed) | | | |
| AC11 | egress: public 443 ok; private 443 refused; public 80 refused; notify-router ok (deployed) | | | |
| AC12 | one Job from the CronJob completes; success marker in Loki; rule normal (deployed) | | | |

## Mutation checks

| Module | Test | Survivors | Disposition |
|---|---|---|---|
| `toolkit/features/product_contract.py` | `tests/test_product_contract.py` | | |
| `toolkit/features/product_guards.py` | `tests/test_product_staging_hostname.py` | | |
| renderer claim functions | renderer tests | | |

## Open questions resolved

| Q | Owner answer | Date | Spec change |
|---|---|---|---|
| Q1 | (A), pending owner objection | 2026-11-14 | none, D7 stands |
| Q2 | (A) ruled, `100.64.0.0/10` in except | 2026-11-14 | threat model and upgrade path recorded; step E6 |
| Q3 | (A) ruled | 2026-11-14 | D11: per-store copies, restore drill checks the set |
| Q4 | (A), pending owner objection | 2026-11-14 | none |
| Q5 | (A) ruled, https://gitea.kubelab.live/personal/resume/issues/810 | 2026-11-14 | slice I depends on it |
| Q6 | (B) ruled; staging runs the contract's schedule | 2026-11-14 | shared-budget risk recorded as accepted |
| Q7 | open | | |
| Q8 | (A), pending owner objection | 2026-11-14 | none |

## Independent review

Reviewer (not the implementer), verdict and findings, before archive.
