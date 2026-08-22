---
id: "adr-063-hub-cloud-provider-migration"
type: adr
status: proposed
created: "2026-08-20"
tags: [architecture, cost, gitops, multi-cloud, topology, argocd]
related:
  - adr-023-hub-spoke-multicloud-gitops
  - adr-025-magicdns-internal-naming
  - adr-028-operational-topology
  - adr-020-iac-lifecycle-strategy
issue: mlorentedev/kubelab#1181
owner: manu
---

# ADR-063: Hub Cloud Provider — GCP over AWS

## Status

Proposed — 2026-08-20. Tracks [#1181](https://github.com/mlorentedev/kubelab/issues/1181) (GCP-001).

**Supersedes [ADR-023](adr-023-hub-spoke-multicloud-gitops.md) §3.1 only.** The
hub-and-spoke topology, the Autonomous Spoke pattern, the stateless-hub property
and every other decision in ADR-023 stand unchanged. What is replaced is the
choice of *which* cloud hosts the hub, and — more importantly — the way that
choice recorded its own cost.

## Date

2026-08-20

## Context

### The number in ADR-023 was wrong by 3.5x, and the reason matters more than the number

ADR-023 §3.1 justified AWS on two grounds: *"Multi-cloud on CV (3 providers: AWS
+ Hetzner + on-prem). Cost is ~$3.60/mo (no Elastic IP — VPN-only access)."*

Measured against the AWS API on 2026-08-20, the hub costs **~$12.75/mo**:

| Line | Rate | $/mo (730 h) | Source |
|---|---|---|---|
| `t4g.small` Spot, `eu-central-1a` | $0.0109/hr | 7.96 | `ec2 describe-spot-price-history`, 7-day window |
| Public IPv4 `18.185.148.191` | $0.005/hr | 3.65 | AWS public IPv4 charge, effective 2024-02-01 |
| EBS 12 GB gp3, eu-central-1 | ~$0.0952/GB-mo | 1.14 | published Frankfurt rate |
| **Total** | | **~12.75** | |

Three inputs moved after the ADR was accepted, and none of them updated it:

1. **AWS began charging for every public IPv4 address on 2024-02-01.** The ADR's
   parenthetical — *"no Elastic IP"* — was a correct cost argument at the time and
   became a wrong one without anybody editing a word. It is now 29% of the bill.
2. The instance was upsized `t4g.micro` → `t4g.small` (2026-03-28, RELIAB-009,
   after 1 GB OOM-killed every Helm upgrade).
3. The root volume grew 8 GB → 12 GB (2026-05-11).

**The root cause is a documentation pattern, not an arithmetic slip.** ADR-023
recorded cost as a *fact* — a single scalar — rather than as a *derivation*: rate
× hours, plus named line items. A scalar goes stale silently. A derivation shows
which input moved. This ADR treats that as the primary defect to fix, because it
will otherwise recur on GCP within a year.

A second measured finding, incidental but real: the instance sits in
`eu-central-1a`, the **most expensive of the three AZs** ($0.0109/hr against
$0.0091 in `1b`/`1c`). Nothing pins it there — `subnet_id` takes
`data.aws_subnets.default.ids[0]`, so the placement is an accident of list order
worth ~$1.24/mo.

### The CV argument is provider-agnostic

ADR-023's first ground was three providers on the CV. Swapping AWS for GCP
**preserves the property** — three providers remain (GCP + Hetzner + on-prem) —
while trading which specific vendor appears. That is a genuine trade-off and it
is recorded in Consequences rather than waved away, but it does not favour AWS.

### The cloud-agnosticism claim has never been executed

Three places in this repo already promise that the hub is portable:

- `infra/ansible/playbooks/provision-aws1.yml:46` — *"a future GCP/Azure hub
  creates its own `provision-<node>.yml` but reuses `hub.yaml` and every Ansible
  role unchanged"*
- `infra/config/values/hub.yaml:4` — *"Same overrides apply to any future hub
  (GCP, Azure) — cloud-agnostic"*
- `docs/runbooks/aws1-ebs-resize.md:123` — *"cloud-agnostic in spirit"*

None has ever been tested. A claim that has never been executed is a hypothesis,
and this migration is its first experiment. That is a decision input, not a
side benefit: it is the reason to do this now rather than to keep paying $12.75
and defer.

### A monthly platform credit exists but does not carry the decision

The maintainer's Google AI Pro subscription includes a $10/mo GCP credit,
**confirmed available as of 2026-08-20**. It is deliberately **not** load-bearing
here. If the credit were to lapse or stop applying to Compute Engine Spot, the
raw-price case still favours GCP ($9.57 vs $12.75). The credit changes the
outcome from *cheaper* to *free*; it does not change the direction — and D6 is
designed on that assumption, capping exposure rather than depending on the
credit's continued existence.

## Decision

### D1 — The hub runs on GCP Compute Engine Spot

`e2-small` (2 vCPU / 2 GB) in `europe-west4`, Spot provisioning model, 12 GB
`pd-balanced` boot disk.

The selection bar was **equal-or-better than `t4g.small` on every axis**, not
"cheapest that works":

| Axis | AWS `t4g.small` | GCP `e2-small` | Verdict |
|---|---|---|---|
| Sustained CPU | 0.4 vCPU (T4g 20% baseline) | 0.5 vCPU | better |
| Burst model | CPU credits, *unlimited* by default (surcharged) | best-effort, no surcharge | different, see Consequences |
| RAM | 2 GB | 2 GB | equal |
| Disk IOPS @ 12 GB | 3,000 (gp3 flat baseline) | 3,072 (`pd-balanced` 3,000 floor + 6/GB) | equal |
| External IPv4 | $0.005/hr | $0.0025/hr (Spot rate) | better |
| Cost | $12.75/mo | $9.57/mo + egress | better |

Egress is listed rather than folded into the total because it is the one line
that is not yet measured — see D8. The $9.57 covers compute ($6.42), external
IPv4 at the Spot rate ($1.83) and the boot disk ($1.32). Every other GCP service
the design consumes — Secret Manager, Pub/Sub, the kill-switch function — sits
inside an Always Free allowance and is recorded at $0 with its allowance named,
per D8's second rule.

Rejected alternatives are recorded below. The two that matter: `e2-medium`
(4 GB) was rejected as scope creep, not as a bad option — it is the natural
follow-up if RELIAB-009 concludes 2 GB is the binding constraint. `t2a-standard-1`
was rejected because Arm parity costs 2.6× and delivers **half** the vCPUs.

### D2 — Preemption recovery is a managed instance group of size 1

GCP Spot VMs do not auto-restart. A preempted VM stops and stays `TERMINATED`
until something recreates it — unlike AWS's persistent Spot request, which is
what silently relaunched `aws1` on 2026-08-19 at 22:45 UTC.

**The parity being restored is narrower than it first appears, and the difference
drives D7.** An AWS Spot *stop/restart* preserves the EBS volume: Argo CD, its
spoke cluster secrets and its OIDC config all survive an interruption untouched,
and only a deliberate `aws1-replace` re-runs `deploy-argocd`. A MIG does not
restart; Compute Engine's documentation is explicit that the group *"repeatedly
tries to **recreate** that instance using the specified instance template"*. Every
preemption therefore becomes a full replacement with a fresh boot disk and a
cloud-init run from zero. A MIG alone restores the *VM* and not the *hub*.

A **regional MIG with target size 1** restores that property and improves on it:
a MIG repeatedly attempts to reach its target size, and being *regional* it can
place or recreate the VM in whichever `europe-west4` zone currently has Spot
capacity — the exact failure that produced
[#1066](https://github.com/mlorentedev/kubelab/issues/1066), where
`eu-central-1a` had no capacity and the instance simply stayed stopped.

> **Corrected 2026-08-22, on the first real apply.** This paragraph originally
> specified `instance_termination_action = DELETE`, reasoning that the `STOP`
> default leaves a `TERMINATED` shell behind. **GCP refuses it:** *"Spot virtual
> machines with termination action set to DELETE cannot be used with Managed
> Instance Groups."* The decision was written here, encoded in the module, and
> asserted by a test — all green, because nothing had run. Kept visible rather
> than rewritten: the reasoning still reads well, and that is exactly why
> someone will try to restore it. See
> `docs/lessons/process-method/lesson-366-*.md`.

The instance template leaves `instance_termination_action` unset, because a MIG
permits only the `STOP` default. A preempted VM is stopped rather than deleted,
and the MIG recreates it.

Autohealing is **omitted in v1**, and the reason is *not* the one first given
here. The original argument — that DELETE termination restores target size
without a health check — died with DELETE. The conclusion survives on the
documented behaviour of the STOP path
([Spot VMs](https://docs.cloud.google.com/compute/docs/instances/spot)):

> MIGs always attempt to maintain their target size [...] If Compute Engine
> stops one or more Spot VMs in a MIG, the group repeatedly tries to recreate
> those VMs using the specified instance template.

Recreation therefore happens without autohealing, which addresses
application-level failure rather than preemption. A health probe firing before
cloud-init's multi-minute bootstrap completes would instead produce a recreate
loop on a Spot hub. Adding autohealing later requires an `initial_delay_sec` no
shorter than the measured bootstrap time.

**AC4 still has to observe this.** A documented behaviour and an observed one are
different claims, and believing the first without the second is what put DELETE
in this ADR.

**A singleton regional MIG constrains `maxUnavailable` to one legal value.**
Measured, not documented in the general MIG guide: a regional group rejects a
fixed value that is neither 0 nor at least the zone count, and rejects the
percent form entirely below size 10. Zero would forbid replacing the only
instance. So the zone count is the sole option, and the module derives it from
`data.google_compute_zones` rather than writing `3` — which is a fact about
`europe-west4`, not about this design, and would fail closed on any region with
a different zone count.

**Regional, not zonal, and explicitly not hand-picked.** On AWS, Spot pricing is
set *per availability zone* — which is why this hub pays $0.0109/hr in
`eu-central-1a` while `1b`/`1c` sit at $0.0091 — so choosing a cheap AZ is a real
optimisation there. **On GCP, Compute Engine pricing including Spot is set per
region and is uniform across the zones within it**; every published price table,
Google's own included, is keyed by region and never by zone. Zone choice on GCP
therefore buys nothing on price. What it does affect is *capacity*, and a regional
MIG answers that better than any static choice could: it follows capacity instead
of guessing at it.

This also closes a documented-but-never-applied contract. `provision-aws1.yml`'s
header has specified *"`instance_interruption_behavior = "terminate"` + ASG(1,1)
— cattle, not pets"* since March; `git log -S` shows `terminate` was never
applied, which is what
[#1106](https://github.com/mlorentedev/kubelab/issues/1106) (ANSIBLE-043) owns.
A MIG(1) **is** that contract. #1106 is resolved by construction rather than
separately implemented.

### D3 — The node is `gcp1` under `networking.gcp`; the role stays abstract

The node keeps a **provider-specific** name, mirroring `aws1`/`networking.aws`.
The role is already abstract where it should be — `clusters.hub`, `argocd.spokes`,
and the Ansible group `hub` — so provider-specificity is confined to the node
identity, exactly as today.

A provider-neutral `hub1`/`networking.hub` was considered and deferred. It is the
better end state, but folding a rename into a migration destroys this change's
main instrument: the size and shape of the diff is the measurement, and a rename
would contaminate it with self-inflicted churn indistinguishable from genuine
coupling.

### D4 — Cost is recorded as a derivation, never as a scalar

This is the decision that outlives the provider. Any ADR, ticket or doc stating
an infrastructure cost states it as **rate × quantity, with every line item
named** — as in the table in Context and the one in D1 — never as a bare
`~$N/mo`.

Rationale: a scalar cannot go stale *visibly*. It has no inputs to re-check, so
nothing prompts a reader to notice that one moved. The 2024 IPv4 charge changed
the correct answer while the sentence stating it remained grammatically fine for
two and a half years. A derivation makes the same drift self-announcing.

### D5 — The migration scores the portability claim

The spec's `verification.md` records a three-column inventory of every file the
migration touches:

| column | meaning | interpretation |
|---|---|---|
| **reused unchanged** | the abstraction held | the claim's evidence |
| **net-new** | genuinely provider-specific (Terraform module, cloud-init, tfvars command) | expected, not a finding |
| **touched only due to naming** | leaked provider coupling | **a finding** — fix or ticket each |

Column three is the result. A migration that lands with an empty column three has
proven the claim in `provision-aws1.yml:46`; one with a long column three has
falsified it, which is equally valuable and must not be quietly reframed as
"expected churn".

### D7 — The hub bootstraps itself; secrets reach it through Google Secret Manager

D2 restores the VM. **D7 restores the hub**, and it exists because F1 above makes
a MIG's recreate a from-scratch build rather than a resume.

Cloud-init must therefore complete the whole bring-up unattended: join the
Headscale mesh, install K3s, and install Argo CD with the spoke cluster
credentials. All three need secrets, at an arbitrary future moment that no
operator is present for.

**SOPS remains the SSOT. Google Secret Manager is a delivery path, never a
second source.** `make tf-gcp-apply` syncs the required values one way, SOPS →
Secret Manager; nothing is ever authored there, and a drift is resolved by
re-syncing rather than by reading. This extends ADR-038's secret-delivery paths
with a fourth; it does not compete with SOPS.

The VM's service account is granted `secretmanager.secretAccessor` on **named
secrets only**, never at project scope.

**Consequence for the preauth key, which is the part that stops being a
liability.** `aws1` stores a long-lived Headscale preauth key in SOPS and bakes
it into user_data; every other node in the fleet mints one just-in-time with
`--expiration 1h` (`provision-ace1.yml:105`). On AWS the stored key is only ever
consumed during a deliberate replacement, with freshly rendered tfvars — so its
expiry never bites. A MIG fires cloud-init weeks or months after the template was
written, and an expired key means the recreated VM never joins the mesh and the
hub dies **silently**.

Headscale exposes `POST /api/v1/preauthkey`, and cloud-init already holds the
Headscale **API key** for stale-node cleanup. So cloud-init mints its own
single-use, short-expiry preauth key at boot, and the stored preauth key is
deleted outright: **one long-lived credential instead of two**, and the fleet's
just-in-time pattern finally reaches the hub.

Note the exposure this does not remove: instance-template metadata is readable by
any principal with `compute.instances.get`, the same class of exposure as AWS
user_data. Secret Manager is what keeps the credentials *out* of that metadata.

### D6 — Spend is alerted at $10 and hard-capped at $15

Two thresholds, two mechanisms, because GCP conflates them and the difference
matters:

| Threshold | Meaning | Mechanism |
|---|---|---|
| **$10** | the credit is exhausted; real money starts | Budget alert (email) at 50% / 90% / 100% of a $10 budget |
| **$15** | something is wrong that alerting did not stop | Budget → Pub/Sub → Cloud Function calling `projects.updateBillingInfo` with an empty billing account |

**Both thresholds measure gross usage, not net spend.** A budget's
`credit_types_treatment` defaults to `INCLUDE_ALL_CREDITS`, which subtracts
credits — so a $10 budget on the default would fire at $10 of *real money*, i.e.
$20 of usage, which is not "the credit is exhausted". Both budgets set
`EXCLUDE_ALL_CREDITS`, so $10 and $15 mean usage and keep their meaning if the
credit ever lapses.

**GCP budgets notify; they do not cap.** A $10 budget does not prevent a $50
bill. The only hard stop Google offers is detaching the billing account from the
project, which must be built rather than configured.

The threat model this defends against is *not* the hub overrunning its own cost.
At `e2-small` Spot + one IP + 12 GB disk, the theoretical monthly ceiling is
~$9.57 — it **cannot** reach $15 by running as designed. $15 can only be reached
by a resource nobody intended to create. That is precisely what a kill switch
should catch, and it is why $15 is the right number: high enough that normal
operation never trips it, low enough that a mistake is caught within days.

The likeliest such mistake is identified and designed out rather than merely
alerted on: a **reserved-but-unattached** external IP costs $0.010/hr — **4x** the
$0.0025/hr Spot-attached rate, and $7.30/mo for nothing. A MIG that recreates VMs
is exactly the machine for orphaning reserved addresses. The hub therefore uses an
**ephemeral** external IP only; it needs no stable public address, because every
path in and out is Tailscale.

Accepted consequence, stated plainly: **detaching billing takes the hub down**,
and recovery is manual (re-attach billing, let the MIG recreate). For a
management plane whose spokes keep running without it — the Autonomous Spoke
property from ADR-023 — that is the correct trade. It would not be correct for a
data-plane project.

Budget data is not real-time; Pub/Sub budget notifications arrive on the order of
tens of minutes, and cost data itself lags. The cap is a backstop measured in
hours, not a rate limiter.

### D8 — Every GCP line, including the free ones, is named — and egress was not

**Correction to this ADR, recorded rather than silently patched.** D4 requires
cost to be stated as a derivation with every line item named, so that an input
which moves is visible instead of silent. This ADR's own derivation named three
lines — compute, external IPv4, boot disk — and **omitted network egress
entirely**. That is precisely the failure mode D4 exists to prevent, committed by
the document stating it.

The omission is not cosmetic. The hub's traffic *is* egress: Argo CD polls and
syncs two spokes — the Hetzner VPS and the homelab — continuously, and that
leaves GCP. The two Network Service Tiers differ by roughly **two orders of
magnitude** in free allowance (Premium: ~1 GiB per destination, then ~$0.12/GiB
to Europe; Standard: a 200 GiB monthly allowance across all regions), against
**$0.43/mo of headroom**.

Two rules follow, and the second is the general one:

1. **The network tier is chosen, never inherited.** The module sets
   `network_tier` explicitly, with a test asserting it is set rather than left to
   the `PREMIUM` API default. The point holds whichever tier wins: a
   cost-relevant value taken from a vendor default is invisible until the bill
   arrives. The allowance figures are flagged UNVERIFIED at the variable itself
   and must be confirmed in the console at plan review — Google's network pricing
   page renders per-region values via XHR and truncates for a plain fetch.

2. **A line item at $0 is still a line item.** When a service is free, its row
   says `$0` **and names the allowance it sits inside**, so that exhausting the
   allowance shows up as a row that stopped matching reality. An absent row is
   how egress went missing here.

The full map of which GCP services are free, which are traps, and under what
conditions, is
[`docs/architecture/infra/gcp-cost-envelope.md`](../architecture/infra/gcp-cost-envelope.md).
Its short form: **the Always Free tier is generous in the control plane and
hostile in the data plane**, which matches this architecture — data lives on
Hetzner and R2 (ADR-049), and GCP hosts only the hub, which is control plane in
its entirety. A GCP proposal that moves data is fighting the grain and must say
so.

## Consequences

### Positive

- **Hub cost falls from ~$12.75/mo to ~$9.57/mo**, and to **$0 net** while the
  monthly platform credit applies. Annualised: $153/yr saved at list price.
- **Preemption recovery becomes declarative.** MIG(1) reconciles toward target
  size; a regional MIG survives single-zone Spot exhaustion, which AWS's
  single-AZ persistent request did not.
- **#1106 is resolved by construction** rather than as separate work.
- **#1102's chain gets its deferred evidence.** ANSIBLE-041 built
  `wait-node-ready` → `provision` → `deploy-argocd` but could only verify it
  against a *restarted* instance; its AC5 (full-cycle, against a genuinely
  replaced node) was deferred to "when a replacement is warranted on its own
  merits". This migration is that occasion.
- **The portability claim stops being untested.**
- **Three latent defects in the AWS setup are surfaced and fixed**, none of which
  the migration created: the stored preauth key's expiry (D7), the Tailscale IP
  rotation that three consumers ignore despite `common.yaml:90` telling them not
  to, and the absence of any budget or alert at all on the AWS side. Each was
  invisible because the triggering event was rare and supervised; the MIG makes
  them frequent and unattended, which is what turned them up.
- **The hub gains just-in-time credentials**, matching the pattern every other
  node in the fleet already uses and the hub alone did not.
- **Spend becomes bounded rather than merely observed.** The AWS side had no
  budget, no alert and no cap; the drift from $3.60 to $12.75 was found by an
  audit, not by a notification. D6 means the next such drift announces itself.

### Negative / accepted trade-offs

- **AWS leaves the CV.** ADR-023 explicitly valued AWS as one of three providers.
  Three providers remain (GCP + Hetzner + on-prem) and GCP is not a weaker line
  item, but the specific AWS experience narrated by this repo's history ends
  here. The git history and the archived ADRs remain as evidence that it happened.
- **Region moves Frankfurt → Eemshaven** (~400 km). Hub→spoke latency to the
  Hetzner VPS goes from ~5 ms to ~12 ms. Immaterial against a 3-minute Argo CD
  reconcile interval, and the hub carries no user traffic. `europe-west3`
  (Frankfurt) is available at +$2.85/mo if exact geographic parity is later
  judged worth paying for.
- **Architecture moves arm64 → amd64.** The hub runs only K3s and Argo CD, both
  multi-arch; nothing from `apps/` or `edge/` is ever scheduled on it. The repo's
  "VPS is ARM, multi-arch builds required" rule is about the Hetzner VPS and is
  unaffected.
- **The CPU burst model changes and is strictly less predictable.** `t4g.small`
  accrues credits and runs in *unlimited* mode, so it can sustain 100% CPU by
  paying a surcharge. `e2-small` bursts on a best-effort basis with no credits and
  no surcharge. The higher baseline (0.5 vs 0.4 vCPU) more than covers steady
  state, but there is no credit balance to spend during a `helm upgrade` spike if
  the host is contended. `make deploy-argocd` already scales workloads to zero
  before upgrades, which is the existing mitigation.
- **Google does not publish per-VM disk performance limits below 4 vCPU.** The
  3,072 IOPS figure is the *disk's* capability; the shared-core VM's ceiling is
  undocumented. To be measured at cutover, not assumed.
- **Preemption frequency on GCP Spot is unknown a priori** and cannot be
  established by reading. AWS reclaimed `aws1` at least twice. D2 exists so the
  answer stops being load-bearing.
- **D7 adds a secret-delivery path, and that is real complexity.** A fourth path
  alongside ADR-038's existing three is more surface to reason about and to keep
  synced. Accepted because the alternative is a hub that self-heals its VM and not
  itself — which reproduces #1102's exact shape (a recovery path that completes
  the visible half and silently omits the half nobody checks).
- **Cloud-init becomes load-bearing rather than merely convenient.** On AWS it
  ran at deliberate replacement under supervision. Under a MIG it runs unattended,
  possibly months later, and every failure in it is a silent hub outage. It needs
  the same testing discipline as application code.

### Neutral

- **RELIAB-009 / [#368](https://github.com/mlorentedev/kubelab/issues/368) is
  unaffected.** `e2-small` keeps 2 GB, so `hub.yaml`'s low-RAM mitigations
  (`etcd_snapshot_retention: 2`, `terminated_pod_gc_threshold: 100`) remain
  necessary. Recorded explicitly so no one reads this ADR as having relieved the
  memory pressure.
- **The monthly credit is confirmed but not perpetual.** It is tied to a
  subscription that could lapse. D6's $10 alert is the mechanism that surfaces
  that the day it happens, rather than on the next bill.

## Alternatives considered

| Option | Specs | $/mo | Why not |
|---|---|---|---|
| **Stay on AWS, move AZ to `1b`/`1c`** | unchanged | 11.51 | Saves $1.24/mo for near-zero effort and is worth doing *if this ADR is rejected*. Leaves the IPv4 charge, the untested portability claim and #1106 all in place. |
| **`e2-medium`, `europe-west4`** | 2 vCPU / 4 GB | 16.00 | Genuinely better — 4 GB would retire `hub.yaml`'s low-RAM mitigations and the scale-to-zero dance in `deploy-argocd`. Rejected as scope creep: it couples a capacity decision (RELIAB-009's) to a provider decision. Natural follow-up, not a competitor. |
| **`e2-small`, `europe-west3`** | 2 vCPU / 2 GB | 12.42 | Exact geographic parity with Frankfurt, +$2.85/mo, and exceeds the monthly credit. Parity has no measured value here — the hub serves no user traffic. |
| **`t2a-standard-1`, `europe-west4`** | **1** vCPU / 4 GB, Arm | 20.74 | Preserves Graviton parity at 2.6× the cost and **half** the vCPUs. Arm parity buys nothing: the hub runs only multi-arch third-party images. |
| **`e2-micro` (free tier)** | 2 vCPU / **1 GB** | ~0 | Ruled out by this repo's own evidence: `t4g.micro` (1 GB) OOM-killed every Helm upgrade (RELIAB-009, 2026-03-28), and `provision-aws1.yml` asserts `memtotal_mb >= 1700`. |
| **Single VM, no MIG** | — | −0 | Simplest Terraform, near 1:1 with `aws_instance`. Rejected: a preempted hub stays down until noticed, an Argo CD outage is *silent* (no new deploys produces no alert), and a zone with no Spot capacity reproduces #1066 exactly. |
| **Stateful MIG (preserved boot disk)** | — | +0 | Would make Argo CD survive preemption as EBS does on AWS, removing the need for D7. Rejected on three counts: Google recommends against stateful boot disks (they cannot be re-imaged or repaired), the Spot combination is undocumented, and **a stateful *regional* MIG requires disabling proactive redistribution and does not orchestrate cross-zone failover** — cancelling the single property regional MIG was chosen for. |
| **MIG + a one-command completion step** | — | −0 | MIG restores the VM; `make gcp1-complete` finishes Argo CD. Honest and much smaller than D7. Rejected because it leaves the hub half-recovered until a human acts, and the half that silently stays missing is the half that does the work — #1102's shape again, one level up. |
| **Retire the hub; push-based deploys** | — | 0 | Cheapest of all, and reverses ADR-023 wholesale rather than its §3.1. Out of scope: GitOps reconciliation and drift detection are the reason the hub exists. |

## References

- Bitácora: [#1181](https://github.com/mlorentedev/kubelab/issues/1181) (GCP-001)
- Spec: `specs/GCP-001-hub-cloud-provider-migration/`
- Runbook: `docs/runbooks/gcp-hub-bootstrap.md`
- Superseded section: [ADR-023](adr-023-hub-spoke-multicloud-gitops.md) §3.1
- Coupled tickets: [#1066](https://github.com/mlorentedev/kubelab/issues/1066) (mooted),
  [#1106](https://github.com/mlorentedev/kubelab/issues/1106) (resolved by D2),
  [#1102](https://github.com/mlorentedev/kubelab/issues/1102) (chain reused; AC5 satisfiable),
  [#368](https://github.com/mlorentedev/kubelab/issues/368) (unaffected)
- Untested claims this ADR puts to the test: `provision-aws1.yml:46`,
  `hub.yaml:4`, `docs/runbooks/aws1-ebs-resize.md:123`
