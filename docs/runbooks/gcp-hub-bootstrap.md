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

## §3 — Project (~3 min)

```bash
gcloud projects create kubelab-hub --name="KubeLab Hub"
gcloud billing projects link kubelab-hub --billing-account=<ID from §1>

# Verify the link — do not trust the create command's exit code
gcloud billing projects describe kubelab-hub
# Expect: billingEnabled: true, and billingAccountName matching §1

gcloud config set project kubelab-hub
gcloud services enable compute.googleapis.com secretmanager.googleapis.com \
  cloudbilling.googleapis.com cloudbudgets.googleapis.com \
  pubsub.googleapis.com cloudfunctions.googleapis.com
```

## §4 — Spend guardrails (~15 min) — before any resource exists

Two thresholds, two different mechanisms, because GCP does not offer one that
does both.

### 4.1 Alert at $10 — the credit is exhausted

A budget with alert thresholds at 50 / 90 / 100% of $10.

**Set `credit_types_treatment = EXCLUDE_ALL_CREDITS`.** The default,
`INCLUDE_ALL_CREDITS`, subtracts credits before comparing — so a $10 budget on
the default fires at $10 of *real money*, i.e. $20 of usage, which is not what
"the credit is exhausted" means. With credits excluded, $10 means $10 of usage
and keeps that meaning if the credit ever lapses.

Terraform (`infra/terraform/gcp/budget.tf`), not the console — it is
infrastructure:

```hcl
resource "google_billing_budget" "alert" {
  billing_account = var.billing_account
  display_name    = "kubelab-hub alert"
  budget_filter {
    projects               = ["projects/${var.project_number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }
  amount { specified_amount { currency_code = "USD"; units = "10" } }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules { threshold_percent = 1.0 }
  all_updates_rule { monitoring_notification_channels = [...] }
}
```

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
