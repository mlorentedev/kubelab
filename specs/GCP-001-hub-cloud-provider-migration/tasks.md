---
tags: [spec, tasks, infra]
created: "2026-08-20"
---

# Tasks - GCP-001-hub-cloud-provider-migration

> TDD order. One task = one focused commit. `[P]` = no dependency on another
> unchecked task. `[AC<n>]` = satisfies acceptance criterion `<n>` in `proposal.md`.
>
> **Read "State as of" first.** Three PRs already exist and two findings changed
> the plan after it was first written; starting from the phase list without that
> context will re-derive work that is done.

## State as of 2026-08-20

| PR | Contents | State |
|---|---|---|
| **#1185** | ADR-063, this spec, `gcp-hub-bootstrap.md`, lessons 354/355 | **merged** |
| **#1187** | `_ssh_target` addresses cloud nodes by MagicDNS name | **open** — tests green, attestation gate red (see below) |
| **#1191** | `networking.gcp` SSOT + Terraform module + static test | **open** |

**Nothing is applied. No GCP resource exists. AWS is untouched and running**
(`sir-xng7dfkh` active/fulfilled since 2026-08-19 22:45 UTC, which mooted #1066).

Two blockers that are **not** technical:

- **Phase 0 needs a human at a browser.** `gcloud` is not installed on the
  workstation, and §1 of the runbook records *which* billing account holds the
  credit — the one mistake in this whole plan that fails silently, because
  everything works and you simply pay.
- **#1187's red gate is not its code.** Filed as **#1189**: CodeRabbit reviewed
  it cleanly and the classifier read that as "not reviewed", plus a second
  symptom where PR-Agent published its declared marker and the gate still
  refused. Neither is a defect in #1187.

## Design decisions this breakdown resolves

**1. Additive-then-subtractive, never a swap.** `gcp1` is built and proven while
`aws1` still runs. `Makefile:504` renders prod's Argo CD EndpointSlice from
`aws1.kubelab.internal`, so a simultaneous swap points prod's IngressRoute at a
host about to stop existing. Two hubs coexist briefly; one is referenced.

**2. Terraform state is per-module and local.** `infra/terraform/gcp/` has its own
`backend "local"`, as `infra/terraform/aws/` does. No `state mv` — the AWS module
is destroyed intact at the end. One module holding both providers would couple
the destroy to the create.

**3. Billing lives in its own Terraform root.** Phase 0 needs guardrails as code
*before* the compute module exists, which reads circular and is not: **budgets
attach to the billing account, not to project compute**. They go in
`infra/terraform/gcp-billing/` with its own local state and no dependency on
`infra/terraform/gcp/`.

**4. Cloud-init is load-bearing code, not a convenience.** A MIG recreate is a
from-scratch build that runs unattended, possibly months after the template was
written, and every failure inside it is a silent hub outage. Static assertions
landed in #1191; live verification is Phase 4.

**5. F3's ACL scope was retracted after checking the policy template.** An earlier
draft put "route the Headscale ACL render through `resolve_magicdns`" in PR 1,
justified as load-bearing for AC4. **The template falsified it**: no ACL rule
references the `aws1` alias, and hub→spoke rides rule 1, which is user-based and
IP-independent. PR 1 shrank to the one consumer that genuinely breaks — the
reachability probe — plus a dated warning on **#586 (VPN-ACL-004)**, the change
that would *make* the alias load-bearing. `deploy-vps.yml:63` and
`render_headscale_policy.py:38` keep writing the SSOT literal, which is correct.

**6. Every GCP service gets a cost line, including the free ones** (ADR-063 D8).
The constraint map is
[`docs/architecture/infra/gcp-cost-envelope.md`](../../docs/architecture/infra/gcp-cost-envelope.md);
its short form is that the Always Free tier is generous in the control plane and
hostile in the data plane. Egress was omitted from the original derivation and is
the one line still unmeasured.

---

# Phase 0 — account, billing, guardrails · **NEXT, needs the operator**

Nothing else can start against a real project until this is done. Everything in
Phases 1–2 can proceed in parallel because it creates no resource.

- [ ] **[AC1]** Runbook §1–§3: project created and linked to the billing account
      that **holds the credit**. Paste `gcloud billing projects describe` output
      into `verification.md` — the create command's exit code proves nothing
      about *which* account it landed on.
      *A new billing account does not carry the credit. This is the silent one.*
- [ ] **[AC2]** `infra/terraform/gcp-billing/`: **$10 budget**, alerts at
      50/90/100%, **`credit_types_treatment = "EXCLUDE_ALL_CREDITS"`**.
      *The default `INCLUDE_ALL_CREDITS` subtracts credits, so a $10 budget would
      fire at $10 of real money — $20 of usage — which is not "credit exhausted".*
- [ ] **[AC2]** Same root: **$15 budget** → Pub/Sub topic → Cloud Run function
      calling `projects.updateBillingInfo` with an empty billing account. Target
      project as an **env var**, never a constant — that is what makes the test
      below possible.
- [ ] **[AC2b]** Runbook §4.3: prove the kill switch on a **scratch project on the
      same billing account** (an empty project bills nothing), with a **synthetic
      message matching the real budget schema** — `budgetDisplayName`,
      `costAmount`, `budgetAmount`, `currencyCode`, and **no target field**, since
      a real notification carries none. Restore `TARGET_PROJECT` afterwards.
      *A kill switch left pointing at the scratch project fails silently.*
- [ ] **[P]** Put an **Artifact Registry cleanup policy** on `gcf-artifacts`. The
      kill-switch function's own build images land there and erode the 0.5 GB
      Always Free allowance.
- [ ] **[P]** Confirm the **Network Service Tier** allowances in the console while
      reviewing the plan (see Phase 3). This is the figure flagged UNVERIFIED in
      `variables.tf`, and the two tiers differ by ~2 orders of magnitude against
      $0.43/mo of headroom.

**Cost lines this phase adds, all $0** — record them with their allowances
(ADR-063 D8): Pub/Sub `$0` (10 GiB/mo), Cloud Run function `$0` (2M invocations),
Artifact Registry `$0` (0.5 GB), budgets `$0` (no charge).

# Phase 1 — Terraform module · **substantially done in #1191**

- [x] Static test `tests/test_gcp_hub_module.py` — SPOT, `DELETE` termination,
      **regional** MIG at `target_size = 1`, **no `google_compute_address`**,
      `pd-balanced`, disk size mirroring the SSOT, no credential literal,
      `network_tier` set explicitly.
- [x] `infra/terraform/gcp/{main,variables,outputs}.tf` — firewall, service
      account with `secretAccessor` on **named secrets only**, instance template,
      regional MIG. **No autohealing in v1** (the test permits it only with an
      explicit `initial_delay_sec`).
- [x] `cloud-init.yml` — Secret Manager fetch → stale-node cleanup → **mints its
      own single-use pre-auth key** via `POST /api/v1/preauthkey` → `tailscale up`
      → K3s. Closes **F2**.
- [ ] **[AC5]** `toolkit infra terraform gcp-tfvars`, mirroring `aws-tfvars`; the
      Makefile deletes the rendered file after every use.
- [ ] **[AC5]** `make tf-gcp-{plan,apply,destroy}` and
      `make gcp1-{status,start,stop,replace,destroy}`.
      *Until these exist, runbook §6 and §8 are not executable — they document the
      end state. `gcp1-start`/`stop` set the MIG's `target_size`; note `aws1` never
      had a `start` target at all, so this is an improvement, not parity.*
- [ ] **[P]** Register `gcp.headscale_api_key` in `SECRET_CATALOG` with
      **`envs=("prod",)`** — **not `("common",)`**, which matches no real env and
      makes the secret vanish from every audit silently (ANSIBLE-033).
- [ ] `make secrets-audit` clean.

# Phase 2 — the SOPS → Secret Manager sync, and F1

**This is the largest remaining piece and the one that closes F1.**

- [ ] **[AC4]** A one-way sync pushing named SOPS values into Secret Manager.
      **SOPS stays the SSOT**; nothing is ever authored in Secret Manager, and
      drift is resolved by re-syncing rather than by reading (ADR-063 D7).
- [ ] **[AC4]** Extend `cloud-init.yml` to install **Argo CD** and the spoke
      cluster secrets from Secret Manager. Until this lands, a recreated hub has
      K3s and no Argo CD — the same place the AWS hub reaches, and **F1 is not
      closed**.
- [ ] **Secret Manager discipline, asserted not assumed** — the four rules that
      keep it free, from the cost envelope:
      automatic replication (per-location billing); **≤6 active versions**;
      **destroy** superseded versions rather than disabling them (a *disabled*
      version still bills); **boot-time reads only, never a polling client**
      (an operator refreshing 6 secrets a minute is ~263k ops/mo = $0.76, over
      budget on access operations alone). A test should assert the version count.

# Phase 3 — SSOT blast radius and bring-up

Requires Phase 0 (a real project) and Phase 1's Makefile targets.

- [x] `networking.gcp` in `common.yaml`; completeness guards extended to cover it.
- [ ] **[AC5]** Point `clusters.hub.{node,ssh_alias}` at `gcp1`, then walk the
      remaining column-3 rows from `proposal.md` **one row per commit**, so the
      diff shows exactly what a provider change costs. Do **not** refactor them
      into a generic lookup — that is **#1182**, and doing it here destroys the
      measurement this spec exists to produce.
- [ ] `infra/ansible/playbooks/provision-gcp1.yml`, from `provision-aws1.yml` with
      the hardware assertions retargeted. **Do not copy its header's stale
      claims** (it documents a `terminate`+ASG contract never applied, and 8 GB
      where the volume is 12).
- [ ] Regenerate the Ansible inventory; confirm `gcp1` lands in group `hub` with
      `ansible_user: deployer`. SSOT-014a infers the SSH-user category from **YAML
      position**, so verify it did not fall through to the homelab user.
- [ ] **[AC3]** `make tf-gcp-plan` → **confirm rates in the console here**
      (network tier, external IP, disk) → `make tf-gcp-apply`.
- [ ] **[AC3]** `make wait-node-ready NODE=gcp1 ENV=hub` — sshd **and** cloud-init.
- [ ] **[AC3]** `dig +short gcp1.kubelab.internal` on **first** registration.
- [ ] **[AC3]** `make provision NODE=gcp1 ENV=hub` **twice** — second pass must
      report `changed=0`. Idempotence is the bar; completion is not.
- [ ] **[AC3]** `make maintain-notify-test NODE=gcp1 ENV=hub` → `Result=success`.
      *This is the check ANSIBLE-035/041 exist to protect and the one a rebuild
      has historically dropped.*
- [ ] **[AC3]** `make deploy-argocd`; both Applications Synced/Healthy.
- [ ] **[AC8]** Measure the undocumented ceilings on the live node: disk IOPS
      (`fio`) and wall time of one full `make deploy-argocd` under the
      best-effort burst model. **A regression against the AWS baseline is a
      finding to report, not a number to file away.**
- [ ] **[AC8]** **Measure egress** over a representative window and add the row to
      the derivation in ADR-063 and `verification.md` — `$0` with its allowance
      named if it is inside the tier's free band (ADR-063 D8).

# Phase 4 — preemption evidence · the design's load-bearing claim

- [ ] **[AC4]** Delete the MIG's instance. Observe end to end: MIG recreates →
      cloud-init → stale node cleaned → **fresh pre-auth minted** → mesh joined →
      K3s → **Argo CD installed** → Synced.
- [ ] **[AC4]** `dig +short gcp1.kubelab.internal` post-recreate. **The
      load-bearing assertion**: a re-registration without cleanup lands as
      `gcp1-<random>` and breaks the inventory, the kubeconfig and the prod
      EndpointSlice at once — silently, because the old records keep resolving
      until they do not.
- [ ] **[AC4]** Confirm **zero** human steps between delete and Synced. If any
      were needed, the MIG has not replaced the AWS persistent Spot request.
- [ ] **[AC4]** Repeat once. IP rotation may only appear on a second
      re-registration. **Record whether the address actually changed** — that
      observation tells **#586** how urgent its own fix is.

# Phase 5 — cutover and decommission · strictly ordered

- [ ] **[AC3]** Re-render the prod EndpointSlice against `gcp1` **before** any AWS
      teardown. Until this runs, prod's Argo CD route points at `aws1`.
- [ ] **[AC3]** Verify `https://argo.kubelab.live` serves from the GCP hub.
- [ ] **[AC6]** `make aws1-destroy`.
- [ ] **[AC6]** Verify by API, output pasted: `describe-instances` empty,
      `describe-spot-instance-requests` cancelled, `describe-volumes` empty.
- [ ] **[AC6]** **Credential rotation — the full exposure set.** Four secrets were
      printed in plaintext during the 2026-08-20 study session. The operator
      reports them rotated; this task is the audit that confirms it:

      | Secret | Retired by migration? | When |
      |---|---|---|
      | `aws.access_key_id` / `secret_access_key` | yes | at cutover |
      | `aws.headscale_preauth_key` | yes — D7 deletes it | **now** |
      | `aws.headscale_api_key` | **no** — survives as `gcp.headscale_api_key` | **now** |
      | `argocd.admin_password` (+ hash) | **no** — hub credential | **now** |

      *`make credentials-generate` also rotates OIDC client secrets and the HMAC,
      so re-run `make deploy-argocd` after.*
- [ ] Remove `infra/terraform/aws/`, `provision-aws1.yml`, `aws1-*` targets and
      `networking.aws`. **Separate commit from the destroy**, so the teardown is
      revertable independently of the code removal.
- [ ] Retire `docs/runbooks/aws1-{destroy-replace,ebs-resize}.md`.

# Phase 6 — optional, free, and worth doing once the hub is stable

Neither blocks the migration. Both are `$0` under Always Free and both need their
allowance named in the derivation (ADR-063 D8).

- [ ] **Uptime checks as a second opinion.** The RPi3 running Uptime Kuma is
      currently a single point of failure for external prod monitoring;
      multi-region GCP checks watch the watcher. **5–15 minute intervals with 3
      checkers** — at 1-minute × Global the 1M allowance is **3.8 checks** and the
      fifth costs ~$79/mo. **Public endpoints only**: private checks target
      internal GCP IPs, so VPN-only staging is unreachable by design. Framed as a
      complement — making it the monitoring of record means reopening ADR-032/028.
- [ ] **BigQuery billing export.** 10 GiB storage / 1 TiB queries free, enough for
      the Cloud Billing detailed export — direct visibility into what creeps
      toward $15 instead of inferring it from an alert after the fact.

## Closing

- [ ] **[AC5]** `verification.md` carries the **final** three-column inventory with
      real counts. **Report whichever result occurred** — a long column 3
      falsifies `provision-aws1.yml:46`'s portability claim, which is a finding of
      equal value and must not be reframed as expected churn.
- [ ] **[AC7]** ADR-063 `proposed` → `accepted`; ADR-023 §3.1 annotated superseded.
- [ ] Close **#1066** (mooted). Comment on **#1106** (resolved by ADR-063 D2) and
      **#1102** (its deferred AC5 is now satisfied).
- [ ] `CLAUDE.md` topology + gotchas: `aws1` → `gcp1`, `t4g.small` → `e2-small`,
      and the GCP-specific gotchas — per-region Spot pricing, unattached IP at 4x,
      budgets notify but do not cap, `# yamllint disable-file` inert in
      cloud-config.
- [ ] `make test` green; lint and type checks pass.
- [ ] Lessons 354 and 355 are written. Add a third only if implementation produces
      something neither covers.

## Open threads not owned by this spec

- **#1189** — the attestation gate misreads a clean CodeRabbit review as "not
  reviewed", plus a second unexplained symptom. Blocks #1187's gate, not its code.
- **#1182 (SSOT-015)** — `networking`'s cloud/homelab asymmetry. This spec
  *produces the evidence*; fixing it here would make the measurement unreadable.
- **#586 (VPN-ACL-004)** — warned, dated: when rule 1 is tightened to host-based,
  the hub must be named by tag or resolved address, never the `common.yaml`
  literal. Note that tagging drops it out of rule 1 and loses its `*:*` grant.
