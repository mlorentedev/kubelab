---
tags: [spec, verification, infra]
created: "2026-08-20"
---

# Verification - GCP-001-hub-cloud-provider-migration

## Evidence

- [x] AC1 billing account recorded -> `gcp.billing_account_id` in SOPS (ends
      `…-CED2F4`, display name `GCP-Kubelab`). Confirmed by API, not console:
      `gcloud billing projects describe kubelab-hub` reports
      `billingAccountName: billingAccounts/0118CE-…` and `billingEnabled: true`.
      The value is in SOPS rather than here because this repository is public;
      it is an identifier, not a credential, but git history is permanent.
- [ ] AC2 budget + kill switch -> `gcloud billing budgets list` output
- [x] AC2b kill switch fired -> `make gcp-killswitch-prove`, 2026-08-22:
      billing detached from `kubelab-killswitch-proof` in 10.7s, target restored
      to `kubelab-hub` and the restore verified. Fired through the REAL topic
      against the REAL deployed function, so the trigger and IAM were exercised
      rather than a copy of the code.
- [x] AC3 hub reconciles from GCP -> both Applications Synced/Healthy **with a
      real write behind each**, 2026-08-22:

      | Application | Sync | Health | operationState | history |
      |---|---|---|---|---|
      | `kubelab-prod` | Synced | Healthy | `Succeeded` | `[0]` — **93 resources** |
      | `kubelab-staging` | Synced | Healthy | `Succeeded` | `[0]` |

      `check-spokes` from the hub's own credential: **both** `ok — HTTP 200`.
      `syncPolicy` survived the recreate intact and per-env (ADR-037):
      prod `{"prune":true,"selfHeal":true}`, staging `selfHeal:false`.

      **THE TENTH FALSE GREEN, and it is the one this AC exists to catch.**
      Immediately after the recreate, before any sync was forced:

          kubelab-prod   Synced   Healthy   history: EMPTY

      Synced/Healthy with an empty history means the hub *compared* the spoke
      against git and found them equal — because aws1 had already reconciled it
      before being paused — and never exercised its own write path at all. The
      state is indistinguishable from a working hub until you ask for the
      history. It is the same shape that hid a broken staging hub last session,
      reproduced here on prod, and the reason the acceptance is a forced sync
      rather than a status read.

      Corollary worth stating because it inverts the obvious test: **history is
      per-hub, not per-Application-name.** aws1's `kubelab-prod` history ended at
      id 51; gcp1's own starts at id 0. A check written as "history > 51" would
      report failure on a hub that is working perfectly.
- [x] AC4 preemption self-heals -> **a real recreate, unattended, end to end**,
      2026-08-22 (the prod handover triggered it: changing `managed_spokes`
      changes the instance template, so the MIG recreates the hub and the cutover
      re-exercises this path instead of bypassing it).

      | Property | Before | After |
      |---|---|---|
      | Tailscale address | `100.64.0.24` | `100.64.0.12` |
      | SSH host key | — | **new** (a genuinely new machine) |
      | MagicDNS | resolves | **follows the new node**, still `gcp1` (F2) |
      | cloud-init | — | `status: done` |
      | Argo CD | — | **installed unattended**, both spokes registered (F1) |
      | prod cluster secret | absent | **installed from Secret Manager at boot** |
      | Human steps between apply and Synced | — | **zero** |

      **CORRECTION to the previous session's lesson, measured today.** That
      lesson said to judge recreate completion by the instance **`id`** rather
      than the name, because `RECREATE` preserves the name. The `id` reported by
      `list-instances` is the **managed instance's** id, not the VM's, and it is
      preserved too — it stayed `7978086404576288333` across a recreate that
      demonstrably happened. A 10-minute poll waiting for it to change would
      have run forever. **Neither name nor id changes.** The reliable signals are
      the ones observable from outside the group: the Tailscale address and the
      SSH host key, both of which rotated.

      **The host key rotation is HANDLED, and I proved that by getting it wrong.**
      Hitting the `REMOTE HOST IDENTIFICATION HAS CHANGED` warning, I filed it as
      an unhandled gap (#1295) — then found `wait-node-ready.yml:110` already
      purges the stale key, scoped to exactly the nodes whose instance rotates
      (`tailscale_dns` with no `tailscale_ip`), tested, and annotated as the TOFU
      mitigation it is, with the real fix tracked as **#1261** (SSH host
      certificates) and an instruction that landing #1261 must delete the purge.
      #1295 closed as redundant.

      What actually happened is a sequencing error of mine: I ran `ssh gcp1`
      directly instead of `make wait-node-ready NODE=gcp1 ENV=hub`, which the
      module's own `next_steps` output lists as step 1 precisely so this is
      handled. Recorded because the failure mode generalises — **a capability
      that lives on one path looks absent from every other path**, and the
      instinct on meeting the symptom is to file rather than to look.

      **PARTIAL, and deliberately not ticked.** A template update triggered a MIG
      replacement on 2026-08-22 and the recreate path worked end to end:

      | Property | Before | After |
      |---|---|---|
      | instance | `gcp1-hx0q` | `gcp1-bxjh` |
      | Tailscale address | `100.64.0.20` | `100.64.0.21` |
      | MagicDNS | resolves | **follows the new node** |
      | Headscale registration | `gcp1` | **`gcp1`, not `gcp1-<random>`** (F2) |
      | cloud-init | `error` | **`done`** |
      | Argo CD | 0 pods | **6 pods, installed unattended** (F1) |

      What this is NOT: a preemption. AC4 asks for
      `simulate-maintenance-event` or a direct delete, and a rolling template
      update is a different trigger. Nor does it show "returns to Synced" — the
      hub manages no spoke yet.

      What it DOES settle: the IP rotates and MagicDNS is the stable identity
      (the aws1 lesson, reproduced on GCP); stale-node cleanup works, so F2
      holds; and F1 works **only after** the `KUBECONFIG` fix — it was broken on
      the first boot, having been recorded as "closed in code" in #1217.
- [ ] AC5 portability scored -> the table below, with real counts
- [x] AC6 AWS decommissioned -> three AWS API outputs, pasted, 2026-08-23

      **Reconciliation is handed over; the inbound route and the teardown are
      not.** Deliberately stopped here, 2026-08-22, at the last point where the
      rollback is one command.

      State right now, and it is a confusing one to walk into cold:

      | | gcp1 | aws1 |
      |---|---|---|
      | reconciles prod | **yes**, verified by a forced sync | no — controller at 0 |
      | reconciles staging | yes | no — was detached earlier |
      | holds `kubelab-prod` + `cluster-prod` | yes | **yes, untouched** |
      | serves `argo.kubelab.live` | no | **yes** (HTTP 200) |

      **The route is repointed as of 2026-08-23** and the table above is now
      history: `argo.kubelab.live` serves from gcp1.

      **HTTP 200 does not prove it, and that is the trap.** Both hubs answer 200
      on the same NodePort, so the obvious check cannot tell them apart — the
      eleventh signal in this migration that looks like evidence and is not.
      Three things were compared instead, and the third is the conclusive one:

      | Check | Result |
      |---|---|
      | EndpointSlice address | `100.64.0.12` = gcp1 (aws1 is `100.64.0.7`) |
      | Applications each hub knows | gcp1 **2**, aws1 **1** — they are distinguishable |
      | **SHA-256 of the served body** | public `53a01d03…` **= gcp1**, aws1 `652d7690…` |

      Two weaker probes were tried first and are recorded because they failed
      silently rather than loudly: a marked `User-Agent` and a marked URL path
      both returned zero hits on *both* hubs, because `argocd-server` logs events
      and not HTTP requests. An absent log line is not a negative result.

      Autonomous reconciliation was demonstrated by the merge of #1299 itself:
      gcp1 picked up `eb41ee2` (a parallel session's merge, with nobody watching)
      and then `ea1a7c2`, reaching `history: [0 1]` on both Applications. That is
      stronger than the forced sync, which ran against the revision the spoke was
      already at.

      **Rollback, if anything looks wrong before the repoint:**
      `make hub-resume HUB=~/.kube/kubelab-hub-aws-config`. It is complete and
      instant because nothing was deleted from aws1 — that is the entire reason
      the handover pauses rather than unregisters, and why `unregister-spoke`
      comes after the soak instead of here.

      **DONE 2026-08-23. The rollback above no longer exists** — that sentence is
      kept as the record of why the order was what it was, not as an option.

      Unregistered first, with the hub still up, because the step needs it alive:

      ```
      1. did: strip the cascade finalizer from kubelab-prod (MUST precede the delete)
      2. did: delete Application kubelab-prod — now inert, the spoke's workloads stay
      3. did: delete this hub's cluster-prod credential
      [SUCCESS] prod detached. The spoke's workloads were not touched.
      ```

      Run WITHOUT `--remove-shared-rbac`, and the dry-run confirmed why that
      matters: all three actions are hub-side. The spoke's shared ClusterRoles —
      the ones gcp1 also uses — were never touched.

      Then `make aws1-destroy`, from `~/Projects/kubelab`. **The working directory
      is load-bearing**: the AWS state is local-backend and exists only in that
      checkout, so the same command from a worktree reports `0 to destroy`, exits
      0, and leaves you paying.

      The three AWS API outputs, `--region eu-central-1` given explicitly — the
      default `us-east-1` returns empty for everything and reads exactly like a
      completed teardown:

      | Query | Result |
      |---|---|
      | `describe-instances` | `i-0be7ecf199975bf1a  terminated  t4g.small` |
      | `describe-volumes` | *(empty — the 12 GB gp3 is gone)* |
      | `describe-spot-instance-requests` | `sir-xng7dfkh  cancelled` |

      **What proves the decommission rather than merely reporting it**: prod never
      noticed. All 12 deployments stayed 1/1 (`authelia`, `grafana`, `loki`,
      `minio`, `n8n`, `postgres`, `redis`, `web`, …) and `argo.kubelab.live` kept
      answering 200 with gcp1's body hash. AWS spend goes from ~$8.9/mo to $0 —
      and note the itemisation D4 demands: of $6.64 billed 1-23 August, **$1.86
      was the public IPv4 address**, the line ADR-023 §3.1 never had.

      **The code stays.** `infra/terraform/aws/`, its runbooks and
      `networking.aws` are not dead weight to clear: they are what makes the
      portability claim AC5 measures true, they cost nothing with no resources
      alive, and `toolkit/cli/infra.py` renders the module's tfvars straight from
      that config block. Deleting them would destroy the evidence rather than the
      infrastructure. The `common.yaml` comment promising to remove `networking.aws`
      predates that decision and is corrected in the same change.
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
