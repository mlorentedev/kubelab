---
id: gcp-cost-envelope
type: architecture
status: active
created: "2026-08-20"
owner: manu
tags: [gcp, cost, free-tier, infra]
---

# GCP cost envelope — what is free, what is a trap, and the rule that separates them

> Reference for anything proposed on GCP. The hub's own decision is
> [ADR-063](../../adr/adr-063-hub-cloud-provider-migration.md); the bring-up
> procedure is [`gcp-hub-bootstrap.md`](../../runbooks/gcp-hub-bootstrap.md).
> This document is the **constraint map** both of those assume.
>
> All figures verified against Google's own pricing pages on **2026-08-20**.
> Where a figure could not be confirmed first-hand it says so inline — that
> distinction is load-bearing and must survive editing.

## The budget this exists to protect

| | |
|---|---|
| Monthly credit | **$10** (Google AI Pro subscription; confirmed 2026-08-20) |
| Hub target spend | **$9.57/mo** — compute $6.42 + external IPv4 $1.83 + disk $1.32 |
| Headroom before real money | **$0.43/mo** |
| Hard cap | **$15/mo**, enforced by a Cloud Run function detaching the billing account |

**$0.43 is the whole margin.** Every figure below should be read against it, not
against intuition about what "a few cents" means. A service that costs $1/mo is
not cheap here; it is 230% of the headroom.

## The rule

**GCP's Always Free tier is generous in the control plane and hostile in the
data plane.**

- *Control plane* — secrets, events, functions, schedules, uptime checks,
  billing analysis: allowances are large relative to a single-hub platform, and
  most carry **no region restriction**.
- *Data plane* — object storage, network egress, metric volume: allowances are
  small, region-locked, or absent, and the per-unit rates past them are steep.

This happens to match the existing architecture: data lives on Hetzner and
Cloudflare R2 (ADR-049), and GCP hosts only the Argo CD hub, which is control
plane in its entirety. **A GCP proposal that moves data is fighting the grain.**

## Three framings that correct common misreadings

1. **$300 is not Always Free.** It is the 90-day Free Trial welcome credit —
   one-off, expires 90 days after signup, a different mechanism entirely. Never
   build a recurring cost case on it.

2. **"The GCP free tier is US-only" is true of exactly two products.** Only
   **Cloud Storage** and **Compute Engine** carry an explicit region restriction.
   Every other product's free tier states no region limit. Unfortunately those
   two are the ones that matter most for backups and VMs, which is where the
   folklore comes from.

3. **Per-billing-account vs per-project is the hidden axis.** Cloud Logging
   (50 GiB) and uptime checks (1M executions) are **per project** — cheap to
   scale by adding projects. Secret Manager, Pub/Sub, BigQuery, Cloud Run,
   Artifact Registry, Cloud Build, Cloud Scheduler and Cloud Monitoring metrics
   are **per billing account** — one pool, shared with everything else that ever
   runs under it.

Google's own escape clause, quoted because it bounds how much any of this can be
relied on: *"The Free Tier has no end date, but Google reserves the right to
change the offering, including changing or eliminating usage limits, with 30
days' advance notice."* **Nothing here should be load-bearing for production
availability.**

## In use, and free

These are consumed by the design in ADR-063. Each stays free only under the
conditions named.

### Secret Manager — free, with four rules

Allowance: **6 active secret versions**, **10,000 access operations/month**,
3 rotation notifications. Per billing account, aggregated across projects. No
region restriction. Past free: $0.06 per active version **per location** per
month; $0.03/10,000 access operations.

Four rules, each of which is the difference between $0.00 and eating the headroom:

1. **Automatic replication.** Billing is per replication *location* — a
   user-managed policy across 3 locations bills 3x.
2. **At most 6 active versions.**
3. **Destroy superseded versions; do not disable them.** "Active" means Enabled
   **or Disabled** — a disabled old version still bills. 12 versions means 6
   billable, $0.36/mo, which is 84% of the headroom for nothing.
4. **Boot-time reads only, never a polling client.** An External Secrets
   Operator refreshing 6 secrets every minute is ~263,000 operations/month =
   $0.76/mo — over budget on access operations alone.

The hub reads one secret once per boot, so it sits far inside the allowance.

### The billing guardrail chain — free end to end

`budget alert → Pub/Sub → Cloud Run function → detach billing`

| Component | Allowance | Hub usage |
|---|---|---|
| Pub/Sub | 10 GiB/month throughput | a handful of small messages |
| Cloud Run function | 2M invocations (2nd gen bills as Cloud Run: 2M requests, 180,000 vCPU-s, 360,000 GiB-s) | a few per month |

Free by roughly six orders of magnitude. **One caveat:** the function's build
image lands in Artifact Registry as `gcf-artifacts` and quietly consumes its
0.5 GB allowance, so that repository needs a cleanup policy.

### Cloud Run — free tier is full value in Europe

Worth recording because it is unusual: *"The free tier is applied as a spending
based discount using Tier 1 pricing"*, and europe-west4 is a Tier 1 region. So
unlike Cloud Storage, Cloud Run's allowance is **not** degraded outside the US.

Traps if it is ever used for more than the kill switch: `min-instances` idle time
bills regardless of requests, and the egress allowance is *"1 GiB free data
transfer within North America"* only.

## Worth adopting, not yet adopted

### Uptime checks — a second opinion on the monitoring of record

**1,000,000 executions per project per month**, $0.30/1,000 after. No region
restriction on the allowance.

The value here is specific: the RPi3 running Uptime Kuma is currently a **single
point of failure for external production monitoring**. Multi-region GCP checks
watch the watcher.

**The frequency cliff is the trap**, because 1M sounds inexhaustible and is not.
*"A check that executes in three regions counts as three executions."* Minimum 3
checkers; "Global" means 6.

| Configuration | Executions/check/month | Free checks | Cost per extra check |
|---|---|---|---|
| 1-min x Global (6) | 263,000 | **3.8** | ~$79/mo |
| 1-min x 3 checkers | 131,500 | 7.6 | ~$39/mo |
| 5-min x 3 checkers | 26,300 | 38 | ~$7.89/mo |
| 15-min x 3 checkers | 8,767 | 114 (config cap is 100) | ~$2.63/mo |

Two constraints on scope: **public endpoints only** — *"Private uptime checks
issue requests to internal IP addresses of Google Cloud resources"*, so VPN-only
staging is unreachable by design — and this is a **complement**. Making it the
monitoring of record would mean reopening ADR-032 and ADR-028.

Note a dated cliff worth diarising: alerting policies begin costing
$0.35/month per metric reference **effective 2027-09-01**. Policies on Billing,
Quota or **Uptime** metrics are never charged, so uptime alerting stays free past
that date.

### BigQuery — billing export

1 TiB queries + 10 GiB storage per month, per billing account, no region
restriction. Enough for the Cloud Billing detailed export, which gives direct
visibility into what is creeping toward the $15 cap rather than inferring it
from a budget alert after the fact.

### Cloud Logging, Artifact Registry, Cloud Scheduler

- **Cloud Logging**: 50 GiB per *project* per month. Trigger to adopt: hub logs
  need to survive a Spot preemption independently of Loki. Anything broader means
  reopening ADR-032. **Trap:** vended network logs (VPC Flow Logs, Firewall Rules
  Logging, Cloud NAT) have **no free allotment** at all — $0.25/GiB. Enabling
  flow logs on the hub VPC is silent spend.
- **Artifact Registry**: 0.5 GB total across attached projects. Today GHCR and
  Gitea cover the need; the only current consumer is `gcf-artifacts`.
- **Cloud Scheduler**: 3 jobs free per billing account (paused jobs count).
  Not listed on the Always Free page — only on its own pricing page.

## Traps

Ordered by how likely they are to be proposed here.

| Trap | Why it fails |
|---|---|
| **Cloud Storage 5 GB** | US-only, verbatim: *"Always Free quotas apply to usage in US-WEST1, US-CENTRAL1, and US-EAST1"*. And **egress is $0.12/GiB to worldwide from byte 0** — strictly worse than R2 on the single axis ADR-049 chose R2 for. Reopening that ADR would argue against itself. |
| **Custom metrics / Managed Prometheus** | Past a 150 MiB floor the rate is **$0.2580/MiB ≈ $264/GiB**, and Managed Prometheus has **no free allotment** ($0.06/million samples; 1,000 series at 30s ≈ $5.18/mo). Piping the existing Prometheus/Grafana metrics here crosses $15 within days. The fastest route to the kill switch on this list. |
| **Uptime checks at 1-min x Global** | 1M executions = **3.8 checks**. The fifth costs ~$79/mo. |
| **Synthetic monitors** | **100 executions per billing account per month.** One monitor at 5-minute intervals is 8,767 executions = $10.40/mo on its own. |
| **e2-micro + 30 GB PD** | US-only; cannot subsidise a europe-west4 hub in any way. The free 30 GB is **pd-standard only** — a pd-balanced boot disk bills from the first GiB even in the US. |
| **Cloud DNS** | Verbatim: *"There is no free tier for Cloud DNS."* $0.20/zone/month regardless of use. ADR-017 conflict **and** recurring cost for no benefit. |
| **Cloud Build** | 2,500 minutes/month, e2-standard-2, default pool only, and Google's own footnote calls it *"promotional ... subject to change"*. Beaten outright by free, parallel, unlimited GitHub-hosted minutes on a public repo (ADR-030). |
| **GKE "free cluster"** | Waives the **management fee only**: *"This credit doesn't apply to compute, networking, or other resources."* Nodes bill at full price. |
| **Cloud KMS free tier** | *"The monthly free usage only applies to key versions created using Cloud KMS Autokey."* Hand-created keys bill at $0.06/version/month — so it would not cover moving SOPS from age to KMS. |
| **The $300 credit** | 90-day trial, one-off. Not a recurring subsidy. |

## Network egress — the line ADR-063 originally omitted

Egress is the one data-plane cost the hub genuinely incurs, because Argo CD polls
and syncs two spokes continuously and that traffic leaves GCP.

| Tier | Free allowance | Rate after |
|---|---|---|
| **Premium** (API default) | 1 GiB per destination SKU | **$0.12/GiB to Europe** (0–1,024 GiB) |
| **Standard** | *"First 200 GiB per month free (per account, across all regions)"* | $0.085/GiB |

Standard is regional-only (no global load balancing — unused here) and rides the
public internet rather than Google's backbone (irrelevant: Tailscale encrypts the
traffic either way, and a 3-minute reconcile does not notice the latency). Note
also: *"Always Free usage limits do not apply to Standard Tier"* — the two do
**not** stack.

**External IPv4**, for completeness, since it is a named line in the hub's cost:

| Attachment | Rate | $/mo |
|---|---|---|
| Spot / preemptible VM | $0.0025/hr | **1.83** |
| Standard VM | $0.005/hr | 3.65 |
| **Reserved, unattached** | $0.010/hr | **7.30** |

The third row is why the hub uses an **ephemeral** address and the module
declares no `google_compute_address`: a MIG that recreates VMs is exactly the
machine for orphaning reserved addresses, at **4x** the attached rate. IPv6
assigned to a VM is free, but IPv4-only reachability requirements (Headscale at a
public IPv4, GitHub, Google APIs) must be checked before treating that as a lever.

> **UNVERIFIED, and it must stay flagged until confirmed.** The Standard Tier
> allowance and the per-GiB rates above come from a research pass that could not
> be confirmed first-hand: Google's network pricing page renders per-region
> figures via XHR and truncates for a plain fetch. `gcp-hub-bootstrap.md` §6
> requires confirming rates in the console at plan review; this is the one that
> matters most, because the two tiers differ by roughly two orders of magnitude
> in free allowance and the hub has $0.43/mo of headroom.

## How to use this document

Before proposing any GCP service, answer three questions in order:

1. **Is it control plane or data plane?** Data plane is fighting the grain — say
   so explicitly and justify it against Hetzner/R2.
2. **Is the allowance per project or per billing account?** Per-account
   allowances are shared with everything else and shrink over time.
3. **Does it conflict with a settled ADR?** ADR-017 (DNS), ADR-030 (CI),
   ADR-032/028 (observability), ADR-049 (object storage). If yes, the proposal is
   "reopen ADR-0NN", not "adopt service X".

Then add its line to the cost derivation — **including when the answer is $0**,
naming the allowance it sits inside. A line item at zero is still a line item;
an absent one is how the egress row went missing from ADR-063 in the first place.

## Sources

All fetched 2026-08-20:
[Free tier features](https://docs.cloud.google.com/free/docs/free-cloud-features) ·
[Cloud Storage](https://cloud.google.com/storage/pricing) ·
[Secret Manager](https://cloud.google.com/secret-manager/pricing) ·
[Operations suite](https://cloud.google.com/stackdriver/pricing) ·
[Cloud Run](https://cloud.google.com/run/pricing) ·
[Functions](https://cloud.google.com/functions/pricing) ·
[Pub/Sub](https://cloud.google.com/pubsub/pricing) ·
[Scheduler](https://cloud.google.com/scheduler/pricing) ·
[Artifact Registry](https://cloud.google.com/artifact-registry/pricing) ·
[BigQuery](https://cloud.google.com/bigquery/pricing) ·
[Cloud Build](https://cloud.google.com/build/pricing) ·
[Cloud DNS](https://cloud.google.com/dns/pricing) ·
[Network pricing](https://cloud.google.com/vpc/network-pricing) ·
[Disk pricing](https://cloud.google.com/compute/disks-image-pricing) ·
[Uptime checks](https://docs.cloud.google.com/monitoring/uptime-checks/introduction)
