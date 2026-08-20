---
tags: [spec, verification, infra]
created: "2026-08-20"
---

# Verification - GCP-001-hub-cloud-provider-migration

## Evidence

- [ ] AC1 billing account recorded -> `<account id>` / `verification.md` below
- [ ] AC2 budget + kill switch -> `gcloud billing budgets list` output
- [ ] AC2b kill switch fired -> function invocation log
- [ ] AC3 hub reconciles from GCP -> `argocd app list` both Synced/Healthy
- [ ] AC4 preemption self-heals -> delete → recreate → Synced transcript
- [ ] AC5 portability scored -> the table below, with real counts
- [ ] AC6 AWS decommissioned -> three AWS API outputs, pasted
- [ ] AC7 cost recorded as derivation -> ADR-063 D4
- [ ] AC8 ceilings measured -> `fio` output + `deploy-argocd` wall time

## The portability scorecard (AC5)

> Filled at closing. The prediction is in `proposal.md`; this records what
> actually happened. **Report the result that occurred** — a long column 3
> falsifies the claim in `provision-aws1.yml:46`, which is a finding of equal
> value to confirming it, and must not be reframed as expected churn.

| Column | Predicted | Actual | Delta |
|---|---|---|---|
| 1 — reused unchanged | 7 groups | | |
| 2 — net-new (expected) | 6 items | | |
| 3 — touched due to naming (**findings**) | 10 rows, 1 legitimate | | |

Verdict on `provision-aws1.yml:46` — *"reuses `hub.yaml` and every Ansible role
unchanged"*: `<confirmed / falsified / partially held>`, with the reason.

## Measured baselines (AC8)

| Metric | AWS `t4g.small` baseline | GCP `e2-small` measured | Regression? |
|---|---|---|---|
| Disk IOPS (live, `fio`) | 3,000 (gp3 spec) | | |
| `make deploy-argocd` wall time | | | |
| Preemption events observed | ≥2 (2026-05-06, #1066) | | |

## Cost, as a derivation (AC7)

> Never a scalar. See ADR-063 D4 for why.

| Line | Rate | Qty | $/mo |
|---|---|---|---|
| `e2-small` Spot, europe-west4 | $0.0088/hr | 730 h | 6.42 |
| External IPv4 (Spot rate) | $0.0025/hr | 730 h | 1.83 |
| `pd-balanced` boot disk | $0.11/GB-mo | 12 GB | 1.32 |
| **Total** | | | **9.57** |
| Monthly credit applied | | | −10.00 |
| **Net** | | | **0.00** |

Replaces: AWS at **$12.75/mo** (`t4g.small` Spot `eu-central-1a` $7.96 + public
IPv4 $3.65 + 12 GB gp3 $1.14), measured 2026-08-20.

## Test status

- Test suite: `<command> -> <output>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing suite: yes / no

## Decisions made during implementation

<!-- Non-obvious trade-offs and course corrections. Routine choices go in commits. -->
