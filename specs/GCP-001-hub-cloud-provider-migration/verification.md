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

**Every line is named, including the free ones** (ADR-063 D8). A line item at
$0 still appears, with the allowance it sits inside — an absent row is how egress
went missing from the original derivation.

| Line | Rate | Qty | $/mo | Allowance it sits inside |
|---|---|---|---|---|
| `e2-small` Spot, europe-west4 | $0.0088/hr | 730 h | 6.42 | — |
| External IPv4 (Spot rate) | $0.0025/hr | 730 h | 1.83 | — |
| `pd-balanced` boot disk | $0.11/GB-mo | 12 GB | 1.32 | — |
| **Network egress** | tier-dependent | **TO MEASURE** | **?** | Standard: 200 GiB/mo · Premium: ~1 GiB per destination |
| Secret Manager | $0.06/version-location | 1 version | 0.00 | 6 active versions, 10,000 access ops/mo |
| Pub/Sub (budget → kill switch) | $40/TiB | ~KB | 0.00 | 10 GiB/mo |
| Cloud Run function (kill switch) | per-request | a few/mo | 0.00 | 2M invocations/mo |
| Artifact Registry (`gcf-artifacts`) | $0.10/GiB-mo | small | 0.00 | 0.5 GB (needs a cleanup policy) |
| Budgets | — | 2 | 0.00 | no charge |
| **Total** | | | **9.57 + egress** | |
| Monthly credit applied | | | −10.00 | |
| **Net** | | | **0.43 − egress** | |

**The egress row is the open one.** ADR-063's original derivation omitted it
entirely, which is the failure D4 of that same ADR exists to prevent. It is
measured in Phase 3 (AC8) and the tier allowance confirmed in the console at plan
review — the two Network Service Tiers differ by roughly two orders of magnitude
in free allowance against **$0.43/mo of headroom**. Full constraint map:
`docs/architecture/infra/gcp-cost-envelope.md`.

Replaces: AWS at **$12.75/mo** (`t4g.small` Spot `eu-central-1a` $7.96 + public
IPv4 $3.65 + 12 GB gp3 $1.14), measured 2026-08-20.

## Test status

- Test suite: `<command> -> <output>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing suite: yes / no

## Decisions made during implementation

<!-- Non-obvious trade-offs and course corrections. Routine choices go in commits. -->
