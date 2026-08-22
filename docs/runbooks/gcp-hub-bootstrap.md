---
id: gcp-hub-bootstrap
type: runbook
status: active
created: "2026-08-20"
---

# GCP hub bootstrap — from no account to a reconciling Argo CD hub

> Zero-to-running procedure for the Argo CD hub on Google Cloud: billing account,
> project, spend guardrails, then the IaC. Decision and rationale live in
> [ADR-063](../adr/adr-063-hub-cloud-provider-migration.md); the implementation
> plan is `specs/GCP-001-hub-cloud-provider-migration/`.
>
> **§1–§4 are one-time account setup and are driven by a human at a browser.**
> §5 onward is IaC and runs from the repo. Do not create any resource before §4
> is done — the guardrails exist to bound the mistakes made while learning the
> console, which is precisely when they happen.

## When to run

- First-time creation of the GCP hub (GCP-001 / [#1181](https://github.com/mlorentedev/kubelab/issues/1181)).
- Rebuilding the project from scratch after a billing detach (see §4.3).
- As the reference for any future cloud hub — §1–§4 are provider-account
  hygiene and only §5 onward is GCP-specific.

## Prerequisites

- A Google account with the platform credit attached (confirmed 2026-08-20).
- `terraform` ≥ 1.5 and `sops` on the workstation.
- The repo cloned, with `make worktree-init` already run in the worktree.
- **`gcloud` is not installed by default on this workstation.** §2 installs it.
- Headscale reachable at `vpn.kubelab.live` (public IP — never the Tailscale
  address; bootstrap must not depend on the VPN being up).

---

## §1 — Billing account (browser, ~5 min)

1. Open <https://console.cloud.google.com/billing>.
2. Identify the billing account that **holds the monthly credit**. If more than
   one exists, open each and check *Credits*. Creating a *new* billing account
   does **not** carry the credit over — this is the single most expensive
   mistake available in this runbook, because it is silent: everything works and
   you simply pay.
3. Record the billing account ID (`XXXXXX-XXXXXX-XXXXXX`) into the spec's
   `verification.md` under AC1. It is recorded so a future reader re-checks
   rather than re-discovers.

> **Why this is step 1 and not an afterthought.** The whole cost case is
> "$9.57/mo, $0 net". The `$0` half depends entirely on *which* account the
> project is attached to, and attachment is invisible in every later step.

## §2 — Install and authenticate `gcloud` (~5 min)

Run these yourself — the login is interactive and opens a browser. In a Claude
Code session, prefix with `!` so the output lands in the transcript.

```bash
# Debian/Ubuntu
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] \
  https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
sudo apt-get update && sudo apt-get install -y google-cloud-cli

gcloud auth login                 # user credentials, browser
gcloud auth application-default login   # ADC — what Terraform uses
```

Both logins are needed and they are **not** the same thing: `auth login` sets the
CLI's identity, `application-default login` writes the credentials the Terraform
provider reads. Skipping the second produces a `could not find default
credentials` failure at `terraform plan`, which reads like a provider bug.

## §3 — Record the billing account, then apply the bootstrap (~5 min)

§3 and §4 used to be a list of `gcloud` commands. They are one Terraform root
now — `infra/terraform/gcp-bootstrap/` — which creates the project, enables its
APIs and lands both budgets. Two commands total.

First, put the ID from §1 into SOPS. `--stdin` keeps it out of `argv`, which is
readable by other users on the machine via `ps`:

```bash
toolkit secrets set gcp.billing_account_id --stdin --env common
```

It is not a credential — nothing can be spent with it absent IAM — but this
repository is public and git history is permanent, so it does not go in a
committed file. Everything else the root needs is already in `common.yaml`.

Then:

```bash
make tf-gcp-bootstrap-plan     # read it: 13 resources, 0 to change, 0 to destroy
make tf-gcp-bootstrap-apply
```

**Verify the link afterwards. Do not trust the apply's exit code:**

```bash
gcloud billing projects describe kubelab-hub
# Expect billingEnabled: true AND billingAccountName matching §1.
# `billingEnabled: true` alone does not say WHICH account, and the wrong one is
# silent — everything works and the bill simply arrives.
```

Then, once per workstation:

```bash
gcloud config set project kubelab-hub
gcloud auth application-default set-quota-project kubelab-hub
```

> **The second command is what clears the warning §2 left behind** — *"Cannot
> find a quota project to add to ADC"*. It cannot be run any earlier: it needs
> the project that §3 creates. Without it, `gcloud billing budgets list` fails
> with a permission error naming a project number that is not yours. Terraform
> itself is unaffected: the root sets `user_project_override`, which is the
> programmatic equivalent.

> **`cloudbudgets.googleapis.com` does not exist.** An earlier revision of this
> runbook told you to enable it. The real API is `billingbudgets.googleapis.com`,
> and because `gcloud services enable` takes the whole list in a single call, the
> invented name did not merely skip a line — it failed the entire enablement
> step. Recorded because it is the shape of error a runbook cannot catch by being
> re-read: only by being run.

## §4 — Spend guardrails — applied by §3, described here

Two thresholds, two different mechanisms, because GCP does not offer one that
does both. Both land with `make tf-gcp-bootstrap-apply`; there is nothing extra
to run. The code is `infra/terraform/gcp-bootstrap/budget.tf` — read it there
rather than from a snippet here, so the two cannot drift.

### 4.1 Alert at $10 — the credit is exhausted

Thresholds at 50 / 90 / 100%. The first two exist so the third is never the
first thing anyone hears: a cost problem found at 100% has already been running
for most of a month.

**`credit_types_treatment = EXCLUDE_ALL_CREDITS` is the setting that matters.**
The default, `INCLUDE_ALL_CREDITS`, subtracts credits before comparing — so a
$10 budget on the default fires at $10 of *real money*, i.e. **$20 of usage**.
The number on the budget and the number it enforces are different, and nothing
surfaces the gap. With credits excluded, $10 means $10 of usage, and keeps that
meaning if the credit ever lapses.

> **This is worth checking on your own account, not just in this code.** On the
> account used here, a pre-existing `$10 Monthly Budget Alert` was found with
> `INCLUDE_ALL_CREDITS` — a budget whose displayed figure is double what it
> enforces. List them and read the column:
>
> ```bash
> gcloud billing budgets list --billing-account=<ID> \
>   --format="table(displayName, amount.specifiedAmount.units, budgetFilter.creditTypesTreatment)"
> ```

**Two API constraints, both found by applying rather than by reading:**

- **The budget's currency must equal the billing account's.** Check with
  `gcloud billing accounts describe <ID>` and read `currencyCode`. Do not infer
  it from where you live — this account is `USD` while the operator is in Europe.
- **`disable_default_iam_recipients` is rejected** with a bare
  `Error 400: Request contains an invalid argument` when `all_updates_rule`
  carries only a `pubsub_topic`. It is valid only alongside
  `monitoring_notification_channels`. Leaving the default e-mail on costs
  nothing: Pub/Sub is what caps, and the human notice is a second channel rather
  than a competing one.

### 4.2 Hard cap at $15 — the kill switch

> **GCP budgets notify. They do not cap.** A $10 budget does not prevent a $50
> bill. The only hard stop Google offers is **detaching the billing account from
> the project**, which has to be built.

Second budget at $15 (same credit treatment) → Pub/Sub topic → Cloud Function
calling `projects.updateBillingInfo` with an empty `billingAccountName`.

Two properties to keep in mind:

- **It takes the hub down.** Detaching billing stops the VM. That is the correct
  trade *here* because the spokes keep running without the hub (ADR-023's
  Autonomous Spoke property). It would be the wrong trade for a data plane.
- **It is a backstop measured in hours, not a rate limiter.** Budget data lags
  and Pub/Sub notifications arrive on the order of tens of minutes.

**Why $15 is the right number.** The hub's theoretical ceiling is ~$9.57/mo — it
*cannot* reach $15 by running as designed. $15 is only reachable by a resource
nobody intended to create, which is exactly what a kill switch should catch. The
likeliest such mistake, and it is designed out rather than merely alerted on: a
**reserved-but-unattached external IP costs $0.010/hr — 4x** the $0.0025/hr
Spot-attached rate. The hub therefore uses an **ephemeral** external IP only; it
needs no stable public address because every path in and out is Tailscale.

### 4.3 Test the kill switch without spending anything

Never test it against the hub project — it would work, and prove it by taking the
hub down.

```bash
# 1. Scratch project on the SAME billing account (an empty project bills nothing)
gcloud projects create kubelab-killswitch-test
gcloud billing projects link kubelab-killswitch-test --billing-account=<ID>

# 2. Point the function at the scratch project (target is an ENV VAR, not payload)
gcloud functions deploy billing-killswitch \
  --update-env-vars TARGET_PROJECT=kubelab-killswitch-test

# 3. Invoke with a message matching the REAL budget schema — no real spend needed
gcloud functions call billing-killswitch \
  --data '{"budgetDisplayName":"kubelab-hub cap","costAmount":16,"budgetAmount":15,
           "currencyCode":"USD"}'

# 4. Prove it detached
gcloud billing projects describe kubelab-killswitch-test
# Expect: billingEnabled: false

# 5. Restore the real target, then clean up
gcloud functions deploy billing-killswitch --update-env-vars TARGET_PROJECT=kubelab-hub
gcloud projects delete kubelab-killswitch-test
```

**The payload must carry no target field.** A real budget notification contains
`budgetDisplayName`, `costAmount`, `budgetAmount` and `currencyCode` — and
nothing identifying a project to act on. A synthetic message carrying a
`targetProject` would exercise a parsing branch that never runs in production,
so the test would prove a test-only path. The target belongs in an environment
variable, which is also what makes this scratch-project test possible.

Step 5 is not optional. A function left pointing at the scratch project is a
kill switch that will never fire on the hub — and its failure mode is silence.

A `DRY_RUN` mode was considered and rejected: it leaves untested exactly the one
API call that matters.

---

## §5 — Secrets (IaC)

SOPS stays the SSOT. Secret Manager is a **delivery path**, never a second
source: values are synced one way and never authored there (ADR-063 D7).

```bash
make secrets-audit                    # clean before adding
make sync-secret-manager              # SOPS -> Secret Manager, one way
make sync-secret-manager-dry          # same, compare and report without writing
```

The VM's service account gets `secretmanager.secretAccessor` on **named secrets
only**, never at project scope.

**The stored Headscale preauth key does not exist here, deliberately.** `aws1`
baked a long-lived key into user_data; every other node in the fleet mints one
just-in-time with `--expiration 1h`. Cloud-init already holds the Headscale API
key, so it mints its own single-use key at boot via `POST /api/v1/preauthkey`.
One long-lived credential instead of two — and no key that can quietly expire
between the template being written and a preemption firing it months later.

## §6 — Bring-up (IaC)

**Confirm the rates while reviewing the plan.** The cost case was built from
published rates on 2026-08-20, and the external-IP figure ($0.0025/hr for a Spot
VM) came from sources that disagreed with each other — one reporting a 2024
increase. The console shows the real per-resource rate at creation time, and this
is the only moment it is free to check. If a rate differs materially, update the
derivation in ADR-063 and `verification.md` rather than leaving two numbers in
circulation.

```bash
make tf-gcp-plan                      # review; expect MIG + template, no static IP
make tf-gcp-apply
make wait-node-ready NODE=gcp1 ENV=hub   # sshd AND cloud-init, not just sshd
dig +short gcp1.kubelab.internal      # assert the MagicDNS given-name resolved
make provision NODE=gcp1 ENV=hub
make provision NODE=gcp1 ENV=hub      # second pass MUST report changed=0
make maintain-notify-test NODE=gcp1 ENV=hub   # expect Result=success
make deploy-argocd
```

The second `provision` is not redundant. Idempotence is the acceptance bar;
completion is not.

### What the first real apply refused — 2026-08-22

Three API rejections, in this order, none of them visible to `terraform
validate` or to any test. They are recorded because a reader hitting one of them
should recognise it rather than re-derive it, and because all three were
*decisions this repository had already made and encoded*:

1. **`instance_termination_action = "DELETE"`** —
   *"Spot virtual machines with termination action set to DELETE cannot be used
   with Managed Instance Groups."* ADR-063 chose it; the module set it; a test
   asserted it. Removed. STOP is the only behaviour available inside a MIG, and
   the live instance now reports `instanceTerminationAction: STOP`.

2. **`max_unavailable_fixed = 1`** —
   *"has to be either 0 or at least equal to the number of zones."* A regional
   MIG spans every zone in its region.

3. **`max_unavailable_percent = 100`** —
   *"only allowed for regional managed instance groups with size at least 10."*

Taken together, (2) and (3) leave the **zone count as the only legal non-zero
value** for a singleton regional MIG. It is derived, never typed:
`length(data.google_compute_zones.available.names)`. Writing `3` would be a fact
about `europe-west4` sitting beside a `region` that is a variable.

**The knock-on worth checking.** ADR-063 omitted autohealing *because of* DELETE
— "the MIG already restores target size on preemption without a health check".
That reasoning died with DELETE. The conclusion survives for a different reason,
[per the Spot docs](https://docs.cloud.google.com/compute/docs/instances/spot):
*"If Compute Engine stops one or more Spot VMs in a MIG, the group repeatedly
tries to recreate those VMs using the specified instance template."* §7 is what
observes it; a documented behaviour and an observed one are different claims.

See `docs/lessons/process-method/lesson-366-*.md`.

## §7 — Verify preemption self-healing

The property the whole design turns on, and it must be observed rather than
inferred from the MIG's configuration.

```bash
gcloud compute instances delete <instance> --zone <zone>   # simulate preemption
# Watch: MIG recreates -> cloud-init -> stale Headscale node cleaned ->
#        fresh preauth minted -> mesh joined -> K3s -> Argo CD installed
dig +short gcp1.kubelab.internal      # MUST return the same given-name
```

**The `dig` is the load-bearing check.** Headscale names nodes by *given-name*,
and a re-registration without stale-node cleanup lands as `gcp1-<random>` — which
breaks the Ansible inventory, the kubeconfig server URL and the prod
EndpointSlice at once, silently, because the old records keep resolving until
they do not.

## §8 — Day-2 lifecycle

| Command | Effect |
|---|---|
| `make gcp1-status` | MIG state + instance state + `dig` of the MagicDNS name |
| `make gcp1-start` | `target_size = 1` — MIG places the VM in a zone with capacity |
| `make gcp1-stop` | `target_size = 0` — deliberate shutdown |
| `make gcp1-replace` | Recreate, then the ANSIBLE-041 chain completes it |

`aws1` had no `start` target: after the 2026-05 Spot reclaim, bringing it back
was manual. This is an improvement over the AWS setup, not parity with it.

---

## Troubleshooting

**`terraform plan` fails with "could not find default credentials"** — §2's
second login was skipped. `gcloud auth login` is not enough; Terraform reads ADC.

**VM comes up but never joins the mesh** — check the Headscale API key in Secret
Manager first, not the network. Cloud-init mints its preauth key through that API
key; if it is invalid the node cannot register and the failure presents as
"unreachable", which points at the wrong layer.

**`dig gcp1.kubelab.internal` returns nothing after a recreate** — stale-node
cleanup failed and the node registered under a random suffix. Verify with
`headscale nodes list` on the VPS; the fix is to delete the stale entry and let
the MIG recreate. See §7.

**Hub reachable, Argo CD absent** — cloud-init's Argo CD stage failed. Read
`/var/log/kubelab-bootstrap.log` on the node, not the MIG's status: the MIG's job
ends at a running VM, and it reports success for a hub that never finished
bootstrapping.

**Everything works but the bill is not $0** — the project is on the wrong billing
account. Re-check §1.3, and note that nothing in §3–§7 would have told you.

## References

- Decision: [ADR-063](../adr/adr-063-hub-cloud-provider-migration.md)
- Spec: `specs/GCP-001-hub-cloud-provider-migration/`
- Bitácora: [#1181](https://github.com/mlorentedev/kubelab/issues/1181)
- Lessons: [354](../lessons/process-method/lesson-354-a-cost-recorded-as-a-scalar-goes-stale-silen.md) (cost as a derivation),
  [355](../lessons/process-method/lesson-355-rare-and-supervised-hides-what-frequent-and-.md) (rare-and-supervised paths)
- Superseded by this: `aws1-destroy-replace.md`, `aws1-ebs-resize.md` (both retire with AWS)
