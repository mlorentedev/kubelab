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
| AC8 | staging: apply, bootstrap, key label count, cert fingerprint, probe digest, rerun unchanged (deployed) | Partial. After `make apply-secrets ENV=staging`, `sealed-secrets-key` in `kube-system` carries `sealedsecrets.bitnami.com/sealed-secrets-key=active`, and its certificate's SHA-256 fingerprint equals the SOPS copy's (`4D:81:CF:CD…0B:22:8C:B7`). Bootstrap, the probe digest and the rerun are pending. | #3644 | 2026-11-18 |
| AC9 | resume pod `Ready` on `/healthz` (deployed) | Pass. After the owner ran `make apply-secrets ENV=staging`, `kubectl -n kubelab rollout status deploy/resume` reported rolled out; the pod was `1/1 Running` with 0 restarts and its readiness probe on `/healthz`. The unauthenticated URL answers 302 to Authelia, and `pytest tests/e2e -m e2e --env staging -k resume` passed 5/5. Checked read-only by the agent. | #3609, #3644 | 2026-11-18 |
| AC10 | `operator` 403, `superadmin` 200 on `resume.staging.kubelab.live` (deployed) | Pass. The owner signed in from a private window: an `operator` user got 403, and the owner's `superadmin` user got the board. | #3609 | 2026-11-18 |
| AC11 | egress: public 443 ok; private 443 refused; public 80 refused; notify-router ok (deployed) | Pass. The agent ran TCP connects from the resume pod (`kubectl exec`), with the owner's leave: `boards.greenhouse.io:443` connected; `172.16.1.2:443` refused; `example.com:80` blocked; `n8n:5678` connected. The commands were `kubectl -n kubelab exec deploy/resume -- python3` with `socket.create_connection(..., timeout=5)` per target. Control, run minutes later on the same day: the same `172.16.1.2:443` (traefik's LoadBalancer VIP) connects from the n8n pod, which has no egress policy (`kubectl -n kubelab exec deploy/n8n -- node -e` with `net.connect`). So the refusal is kube-router enforcing the `except` block, not a closed port. | #3609 | 2026-11-18 |
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
| Q1 | (A), accepted by the owner | 2026-11-14 | none, D7 stands |
| Q2 | (A) ruled, `100.64.0.0/10` in except | 2026-11-14 | threat model and upgrade path recorded; step E6 |
| Q3 | (A) ruled | 2026-11-14 | D11: per-store copies, restore drill checks the set |
| Q4 | (A), accepted by the owner | 2026-11-14 | none |
| Q5 | (A) ruled, https://gitea.kubelab.live/personal/resume/issues/810 | 2026-11-14 | slice I depends on it |
| Q6 | (B) ruled; staging runs the contract's schedule | 2026-11-14 | shared-budget risk recorded as accepted |
| Q7 | ruled 2026-11-14 | one prod node (`vps`); DNS derived by kubelab tooling (#3489) | owner |
| Q8 | (A), accepted by the owner | 2026-11-14 | none |

## Independent review

Reviewer (not the implementer), verdict and findings, before archive.
