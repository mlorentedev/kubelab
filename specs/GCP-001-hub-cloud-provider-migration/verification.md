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
- [x] AC2 budget + kill switch -> live, queried 2026-08-24 against billing
      account `0118CE-…`:

      | Display name | Units | Credit treatment | Thresholds |
      |---|---|---|---|
      | `kubelab-hub alerting (10 USD)` | 10 | `EXCLUDE_ALL_CREDITS` | 0.5 / 0.9 / 1.0 |
      | `kubelab-hub HARD CAP (15 USD)` | 15 | `EXCLUDE_ALL_CREDITS` | 1.0 |

      `EXCLUDE_ALL_CREDITS` on both is the setting F4 exists for: on the API
      default the $10 budget would fire at $10 of *real money* against a $10
      credit — $20 of usage — and nothing would surface the gap.

      The mechanism behind the cap is in `terraform state list` for
      `gcp-bootstrap`, not only in the budget: `google_pubsub_topic.budget_alerts`
      -> `google_cloudfunctions2_function.kill_switch` (+
      `google_service_account.kill_switch`, `google_project_iam_member.kill_switch`).
      A budget alone notifies; these are what detach billing, and AC2b is the
      proof they fire.
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

      > **A REAL PREEMPTION ON 2026-08-24 CONFIRMED HALF OF THIS AND FALSIFIED
      > THE OTHER HALF ([#1369](https://github.com/mlorentedev/kubelab/issues/1369)).**
      > The `[x]` stands for the criterion as written — the MIG recreated the VM
      > after a genuine preemption and the hub came back with **no human
      > involved**, in **18 seconds**: `preempted 17:13:39` → `repair.recreateInstance
      > 17:13:47` → `insert 17:13:57`. That is stronger evidence than the
      > template-change recreate below, and it also settles the question
      > `main.tf:184` left open, since recreation on the STOP path is now
      > *observed* rather than quoted from the documentation.
      >
      > **The MagicDNS row is the falsified one.** It reads "follows the new node,
      > still `gcp1`", and on 2026-08-24 the replacement registered as
      > `gcp1-mj5bsge9` while the dead record kept the name — so
      > `gcp1.kubelab.internal` resolved to a corpse and `argo.kubelab.live` went
      > down. The stale-node cleanup in `cloud-init.yml` had never worked: its
      > predicate tests `.online == false`, an offline node omits that field
      > entirely, and `null == false` matches nothing.
      >
      > **The demonstration below passed because it was gentler than reality.**
      > Both recreates that produced this evidence were *graceful* — a template
      > change and a `gcloud compute instances delete` — where the node logs out on
      > the way down. The branch that runs on an abrupt preemption was never
      > exercised. Recorded here rather than only in the fix, because the lesson
      > belongs to the acceptance criterion: **"a real simulated preemption, not a
      > MIG config screenshot" was satisfied and still measured the wrong path.**
      >
      > **CLOSED 2026-08-24 by a drill with matching stimulus.** The adversarial
      > review graded the earlier demonstration on fidelity and was right to. This
      > one reproduces the production path at the layer that decides the outcome,
      > and GCP's own operation log shows the two are indistinguishable there:
      >
      > | | Reason string logged by the MIG |
      > |---|---|
      > | Real preemption, 17:13:47 | `Instance eligible for repair: instance should be RUNNING, but is STOPPING.` |
      > | Drill, 18:54:46 | `Instance eligible for repair: instance should be RUNNING, but is STOPPING.` |
      >
      > A preemption on this instance manifests as the VM entering STOPPING
      > (`instance_termination_action = STOP`), so `gcloud compute instances stop`
      > presents the MIG with the same condition. `simulate-maintenance-event` was
      > tried first and **did nothing** — DONE returned, instance still RUNNING,
      > `creationTimestamp` unchanged. Recorded rather than retried: a drill
      > command that reports success without acting is the same false green this
      > spec keeps finding.
      >
      > ```
      > 18:54:40  stop
      > 18:54:46  repair.recreateInstance      <- unprompted
      > 18:55:16  insert                        <- creationTimestamp moves
      >
      > headscale  41:gcp1=100.64.0.15  ->  deleted
      >            42:gcp1=100.64.0.16  <-  registered under the CANONICAL name
      > cloud-init  "deleted stale Headscale node 41 (gcp1)"
      > dig +short gcp1.kubelab.internal -> 100.64.0.16
      > ```
      >
      > Zero human steps between the stop and the reclaim. The line the old
      > predicate could never print is the whole difference: on 2026-08-24 under
      > the same precondition it printed `no stale Headscale node to recycle`.
      >
      > Two facts the drill settled as a side effect. The MIG **recreates** rather
      > than restarts — `creationTimestamp` moves, the boot disk is fresh, which is
      > why cloud-init re-runs and why the recycle path is reached on every repair.
      > And recovery is still **not** hands-free: `argocd-repoint`, a re-trusted
      > SSH host key (#1380) and a fresh cluster CA were all needed afterwards.

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
- [x] AC5 portability scored -> the table below, with real counts. Column 1
      confirmed (10/10 paths untouched across the 39 migration commits); column 3
      undercounted by two, both in observability and both now #1249.
- [x] AC6 AWS decommissioned -> three AWS API outputs, pasted, 2026-08-23.
      **Teardown only.** The credential-rotation half of AC6 is open and audited
      NOT DONE — see the audit at the end of this entry. Do not read this `[x]`
      as the whole criterion.

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

      **The teardown is done; the credential half of AC6 is not.** Audited
      2026-08-23, and the audit contradicts the record. `tasks.md` carried "the
      operator reports them rotated; this task is the audit that confirms it" —
      the audit ran and confirms the opposite.

      > **CLOSED LATER THE SAME DAY — 2026-08-23, after this audit was written.**
      > The audit below is what made it happen and is kept verbatim; read it as
      > history, not as current state. All four exposed credentials were
      > neutralised **at the source**, which is the only place that counts: the
      > three Headscale keys were expired at the issuer, the IAM access key ending
      > `…IQYC` was deleted, and `kubelab-terraform` was left holding **zero**
      > keys (#1335, #1349, #1353).
      >
      > Re-checked 2026-08-24 by consequence, decrypting nothing: SOPS key *names*
      > are plaintext, so the key tree answers what changed. `aws.headscale_preauth_key`
      > — the one D7 said to delete and the audit found still present — is **gone**
      > from `common.enc.yaml`, retired by #1353.
      >
      > **What remains is dead ciphertext, not a live credential.** `aws.access_key_id`
      > and `aws.secret_access_key` are still in SOPS and now authenticate nothing,
      > because the key they hold was deleted at AWS. That residue is
      > [#1351](https://github.com/mlorentedev/kubelab/issues/1351) (SSOT-025).
      > It cannot be re-verified by an AWS API call *precisely because the keys are
      > gone* — the disclosure belongs in the record rather than being presented as
      > an unanswered question.

      Method, which decrypts nothing and therefore prints nothing: SOPS preserves
      the ciphertext of values it does not edit, so `git diff --numstat` over the
      encrypted file answers "did this key change" without exposing it. Verify a
      credential by consequence, never by printing it.

      | Fact | Measurement |
      |---|---|
      | `common.enc.yaml`, 2026-08-15 → `a8750ed` | **10 added, 2 removed** |
      | the additions | `gcp.{billing_account_id,headscale_api_key}`, four `push_tokens.*` |
      | the removals | `lastmodified`, `mac` |
      | **existing keys rewritten** | **zero** |
      | `argocd.admin_password` ciphertext | byte-identical across the window |
      | `prod`/`staging.enc.yaml` | 9 added / 3 removed — Slack webhooks; the third removal is `version: 3.7.3 → 3.13.1`, a SOPS upgrade, not a key |
      | working tree | clean — no uncommitted rotation hiding |

      The additions are the positive control: they prove the method can see a
      change at all, which is what separates this negative result from an
      unanswered question. All four exposed secrets are still in SOPS unchanged,
      including `aws.headscale_preauth_key`, which D7 said to delete.

      **The consequence checks, with the vault unlocked.** One is answered, two
      are not — and both non-answers arrived disguised as answers.

      **Headscale: answered.** `toolkit secrets check-expiry` asks the issuer over
      SSH and decrypts nothing. Two distinct API keys exist:
      `hskey-api-j4_9sZt5zTPr-***` expiring 2027-03-27 — the date the catalog
      measured for `aws.headscale_api_key` — and `hskey-api-zcJQKhYGg5SW-***`
      expiring 2029-05-17. The GCP hub's key was minted fresh, corroborated by
      `gcp.headscale_api_key` first appearing in SOPS on 2026-08-21, after the
      exposure. **The exposure does not reach the GCP hub.** The exposed AWS key,
      however, is live for another 215 days with nothing consuming it.

      **The pre-auth key: still unanswered.** `check-expiry` asks about apikeys
      only, so `aws.headscale_preauth_key` was never in scope. Its absence from
      that table is not revocation — the same shape as the User-Agent probe above.

      **IAM: re-run, and the exit code flipped without answering.** `dotf secrets
      run -- aws sts get-caller-identity` now exits **0**, but `AWS_ACCESS_KEY_ID`
      is UNSET in the child process: `dotf` never injects the SOPS AWS keys, so
      the call authenticated with a credential in `~/.aws/` (ending `ODHC`,
      region `us-east-1`). Exit 1 proved nothing last time because the vault was
      locked; exit 0 proves nothing this time because the keys under test were
      never in the process. Same question, twice, still open.

      **Drift, in whichever direction it resolves.** If the Argo password was
      rotated out-of-band on the hub, SOPS still holds the exposed value and the
      next `make deploy-argocd` reinstalls it silently.
- [x] AC7 cost recorded as derivation -> the table below, every line item named
      including the $0 ones (ADR-063 D4/D8), **and the source closed**: ADR-023
      §3.1 now carries a supersession marker at the section itself, not only in
      its Status block, because the stale `~$3.60/mo` is what a grep or a deep
      link lands on. The egress row is measured (2026-08-24) rather than deferred.
- [~] AC8 ceilings measured -> **two of three done, the third deferred as a
      stated decision.** Egress and disk IOPS are measured (2026-08-24, tables
      below). The `make deploy-argocd` wall time is **not**: obtaining it means
      running a real deploy against the live hub, and the last one died between
      its two phases (#1348). Running production to collect a diagnostic number
      inverts the risk, so it is recorded on the next legitimate deploy — #1209
      (the hub's chart is two majors behind) forces one.

      The IOPS number is measured through `make benchmark-disk` (#1371) rather
      than an ad-hoc `fio` over SSH, because ANSIBLE-035's adversarial review
      already failed a spec for an unreproducible number in a file exactly like
      this one.

## The portability scorecard (AC5)

> Filled at closing. The prediction is in `proposal.md`; this records what
> actually happened. **Report the result that occurred** — a long column 3
> falsifies the claim in `provision-aws1.yml:46`, which is a finding of equal
> value to confirming it, and must not be reframed as expected churn.

Scored 2026-08-24 over the 39 commits from `cf5f98f^` (the ADR + plan, #1185) to
master whose subject names the migration — 117 distinct files. Scoring the whole
range would have counted the unrelated work the arc ran alongside.

| Column | Predicted | Actual | Delta |
|---|---|---|---|
| 1 — reused unchanged | 7 groups | **7 groups, 10/10 paths untouched** | none |
| 2 — net-new (expected) | 6 items | 6 items, all present | none |
| 3 — touched due to naming (**findings**) | 10 rows, 1 legitimate | **11 sites**, 1 legitimate; 8 of the 9 predicted files touched | +2 found, −1 not touched |

**Column 1 — confirmed, and it is the result.** None of `hub.yaml`, the roles
`base_system` / `ssh_hardening` / `tailscale` / `k3s_server` / `node_maintenance`,
`wait-node-ready.yml`, `maintain.yml`, `infra/k8s/argocd/**` or
`toolkit/features/argo_manager.py` appears in the touched set. The provider under
them changed and they did not.

**Column 3 — two corrections to the prediction, in opposite directions.**

- Row 9 (`infra/ansible/inventories/homelab.yml`) was **not** touched. Not a
  point for portability: the committed inventory is generated and stale, which is
  its own open bug ([#1228](https://github.com/mlorentedev/kubelab/issues/1228)).
  A file that would have needed the edit and did not receive one is a gap in the
  inventory, not an abstraction holding.
- **Two sites the inventory missed entirely**, raised by the operator rather than
  by the plan and now [#1249](https://github.com/mlorentedev/kubelab/issues/1249):
  `infra/config/uptime-kuma/monitors.json` and
  `toolkit/scripts/sync_homepage_config.py`, both hardcoding `aws1`. So column 3
  was *undercounted*, and the way it was undercounted is the more interesting
  half — the omission was in the observability layer, which no acceptance
  criterion covered.

**A residue that is neither column 3 nor nothing.** Five Column-1 files still say
`aws1` — in comments and `make` usage examples only, never in executable content:
`hub.yaml:3,14` (*"Currently single hub on AWS"*), `wait-node-ready.yml:17,20,54`,
`maintain.yml:8,11,14`, `node_maintenance/defaults/main.yml:10`, and
`dns/main.tf:43` (legitimate — it records why the IP map exists). They were reused
unchanged, which is what the column claims, and their prose is now wrong, which
the column does not measure. `hub.yaml` is corrected in this change; the rest are
usage examples that GCP-002 covers.

**Verdict on `provision-aws1.yml:46`** — *"reuses `hub.yaml` and every Ansible role
unchanged"*: **confirmed, by measurement rather than by assertion.** The claim was
about executable reuse and it held exactly. It says nothing about documentation,
and documentation is where the migration leaked.

## Measured baselines (AC8)

| Metric | AWS `t4g.small` baseline | GCP `e2-small` measured | Regression? |
|---|---|---|---|
| Disk IOPS, random 4K read | 3,000 (gp3 **spec sheet**) | **3,209** (12.5 MiB/s) | no, +7% |
| Disk IOPS, random 4K write | 3,000 (gp3 **spec sheet**) | **3,233** (12.6 MiB/s) | no, +8% |
| `make deploy-argocd` wall time | — | deferred, see AC8 above | — |
| Preemption events observed | ≥2 (2026-05-06, #1066) | **1** (2026-08-24, #1369) | see below |

`make benchmark-disk NODE=gcp1 ENV=hub`, 2026-08-24, `--direct=1 --bs=4k
--iodepth=64 --runtime=30 --time_based`. `--direct=1` is what makes the number
mean anything: the hub has 2 GB of RAM and the test file is 512 MB, so without it
the kernel serves the whole run from the page cache and reports memory bandwidth.

**Read the comparison honestly.** The AWS column is a **datasheet**, not a
measurement, and the disk it describes no longer exists to measure. So this shows
the GCP ceiling clears the figure the decision was made against — the module
predicted 3,072 from `pd-balanced`'s per-instance floor and the live number is
above it — and it does **not** show a like-for-like comparison. "No regression"
is the correct verdict for the decision at hand and the weaker claim of the two.

**The preemption row is the important one and it is not a performance number.**
The single observed event (2026-08-24, 17:13:39 UTC-7) had the MIG rebuild the
hub in **18 seconds** unattended — better than the AWS path, which was a manual
`make aws1-replace` and, in #1066, no replacement at all for want of capacity.
The same event also broke `argo.kubelab.live`, for a reason that has nothing to
do with the MIG: #1369.

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
| **Network egress** | $0.085/GiB after the allowance | **4.5 GiB/mo measured** | **0.00** | Standard Tier: 200 GB/mo per region, across all projects — usage is **2.2%** of it |
| Secret Manager | $0.06/version-location | 1 version | 0.00 | 6 active versions, 10,000 access ops/mo |
| Pub/Sub (budget → kill switch) | $40/TiB | ~KB | 0.00 | 10 GiB/mo |
| Cloud Run function (kill switch) | per-request | a few/mo | 0.00 | 2M invocations/mo |
| Artifact Registry (`gcf-artifacts`) | $0.10/GiB-mo | small | 0.00 | 0.5 GB (needs a cleanup policy) |
| Budgets | — | 2 | 0.00 | no charge |
| **Total** | | | **9.57** | |
| Monthly credit applied | | | −10.00 | |
| **Net** | | | **0.43** | |

**The egress row was the open one, and it is now closed by measurement.** ADR-063's
original derivation omitted it entirely — the failure D4 of that same ADR exists to
prevent. Two facts settle it, both from a primary source rather than from the
console at plan review:

- The VM is on **Standard Tier** (`gcloud compute instances list` →
  `NETWORK_TIER: STANDARD`), whose allowance is *"200 GB of free Standard Tier
  usage per month in each region that you use across all of your projects, on a
  per SKU basis"* — not the Compute Engine Always Free 1 GB, which is a different
  allowance, applies to North American origins, and does not stack. Getting those
  two confused is what the "two orders of magnitude" warning was about, and the
  hub is on the generous side of it.
- Measured send volume is **~4.5 GiB/mo** (Cloud Monitoring
  `instance/network/sent_bytes_count`, the two complete days since the MIG
  recreated the VM on 2026-08-23: 187.6 MB and 131.7 MB). That is **2.2%** of the
  allowance, and it is a ceiling — the metric counts everything leaving the NIC,
  including traffic that is not billable internet egress.

So the row is $0.00 with ~44x headroom, and the **$0.43/mo net stands as written**.
Full constraint map: `docs/architecture/infra/gcp-cost-envelope.md`, where the
`UNVERIFIED` flag on the tier allowance is now cleared with the source quoted.

Replaces: AWS at **$12.75/mo** (`t4g.small` Spot `eu-central-1a` $7.96 + public
IPv4 $3.65 + 12 GB gp3 $1.14), measured 2026-08-20.

## Test status

- Test suite: `<command> -> <output>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing suite: yes / no

## Decisions made during implementation

<!-- Non-obvious trade-offs and course corrections. Routine choices go in commits. -->
