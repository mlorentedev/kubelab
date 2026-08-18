---
id: aws1-destroy-replace
type: runbook
status: active
created: "2026-05-11"
---

# aws1 destroy + cattle replace — operational runbook

> Procedures to safely tear down or re-roll the aws1 Argo CD hub. The
> underlying Spot Persistent Request is orphaned from Terraform state
> since the AWS-003 refactor (state rm aws_spot_instance_request +
> import aws_instance), so a raw `terraform destroy` would leave AWS
> retrying to relaunch a replacement instance. Always go through the
> Makefile wrappers below.

## When to run

- **destroy**: decommissioning aws1 (cost cleanup, replatform decision, etc.).
- **replace**: deliberate cattle re-roll on a fresh AMI / new kernel /
  damaged instance / k3s major version bump. The `lifecycle { ignore_changes = [ami, user_data] }`
  on `aws_instance.argo_hub` prevents accidental replacement on routine
  plans; this is the explicit, blessed path to re-roll.

### Do NOT run replace to recover an interrupted Spot instance

**This is the trap, and it is easy to walk into**: aws1 goes offline, `argo.kubelab.live`
stops reconciling, and `make aws1-replace` looks like the recovery command. It is not.

`main.tf` sets `instance_interruption_behavior = "stop"` with a **persistent** Spot
request, so an interruption does not destroy anything: the instance is *stopped* with
its root volume intact, and the open request restarts it automatically when capacity
returns. Running `aws1-replace` in that state cancels the queued restart, deletes the
root volume (`delete_on_termination = true`), and then tries to create a new instance
needing the very capacity that is currently unavailable — leaving you with no stopped
instance, no queued request, and no replacement.

**Triage first, and read EC2 — not Tailscale:**

```bash
aws ec2 describe-instances --profile kubelab --region eu-central-1 \
  --filters "Name=tag:Project,Values=kubelab" \
  --query 'Reservations[].Instances[].{Id:InstanceId,State:State.Name}' --output table

aws ec2 describe-spot-instance-requests --profile kubelab --region eu-central-1 \
  --query 'SpotInstanceRequests[].{State:State,Status:Status.Code}' --output table
```

| EC2 state | Spot request | Action |
|---|---|---|
| `stopped` | `open` / `capacity-not-available` | **Wait.** AWS restarts it. Replacing destroys a recoverable node. |
| `stopped` | cancelled or absent | Replace — nothing will bring it back on its own. |
| `running` but unreachable | any | Wedged instance; replace is appropriate. |

**`tailscale status` is not evidence about the machine.** It reports the state of *your*
connection attempt, not the host. An interrupted aws1 shows as
`active; relay "fra"; offline, tx 103116 rx 0` — the `active` token means a session is
being attempted, and `rx 0` is the part that matters: nothing is answering. Observed
2026-08-16, when EC2 said `stopped` throughout.

**When it does come back, do not assume it is clean.** The 2026-03-26 lesson recorded in
`provision-aws1.yml`'s header states that `stop` corrupts WireGuard and SSH state — which
is why the header documents `terminate` as the contract. That contract was never applied
to Terraform (`git log -S` shows one commit, the original). Tracked as **#1106**.

## Prerequisites

- AWS CLI configured against the `kubelab` profile.
- Local clone with `terraform` ≥1.5.
- `aws.tfvars` will be regenerated transparently from SOPS by the toolkit.

## Procedure A — destroy (`make aws1-destroy`)

```bash
make aws1-destroy
```

What it does:

1. Reads `spot_request_id` from terraform output.
2. `aws ec2 cancel-spot-instance-requests --spot-instance-request-ids <sir-id>`
   — cancels the Spot Persistent Request so AWS won't relaunch.
3. Runs `tf-aws-destroy` (terraform destroy with SOPS-injected tfvars).

The cancellation step is idempotent: if `spot_request_id` is empty or
the request is already cancelled, the target prints
`No spot_request_id in terraform state — skipping cancellation` and
proceeds.

## Procedure B — cattle replace (`make aws1-replace`)

```bash
make aws1-replace       # one command — provisioning and Argo CD are part of it
```

What it does (ANSIBLE-041 / #1102 — the chain used to stop after step 4 and
print a manual instruction, which also never mentioned provisioning):

1. Cancels the existing Spot Persistent Request (same as above).
2. Regenerates `aws.tfvars` from SOPS.
3. `terraform apply -auto-approve -replace=aws_instance.argo_hub`
   — forces destroy+recreate even though the `lifecycle` block ignores
   `ami` and `user_data`. The `-replace` flag is the explicit override.
4. Cleans `aws.tfvars`.
5. `make wait-node-ready NODE=aws1 ENV=hub` — waits for sshd **and** for
   `cloud-init status --wait`. Two conditions: sshd answers long before
   cloud-init has installed K3s and registered Tailscale.
6. `make provision NODE=aws1 ENV=hub` — day-2 provisioning, including the
   `node_maintenance` role. **Skipping this was the bug**: a replaced hub came
   up with no maintenance timer and no failure-notify path, and neither
   absence announced itself.
7. `make deploy-argocd`.

Any stage failing aborts the chain — nothing is suffixed `|| true`.

The new instance comes up with:

- Fresh Canonical AMI (whatever `data.aws_ami.ubuntu` resolves to).
- Fresh `user_data` (re-rendered cloud-init with current SOPS secrets).
- A new EC2 instance ID and a new Spot Persistent Request ID.
- Same K3s + Argo CD config (re-bootstrapped via cloud-init + `deploy-argocd`).
- The same name, `aws1.kubelab.internal` — **but not for the reason this
  runbook used to give.** It credited the Headscale `extra_records` in
  common.yaml; those render into the *apex* zone as `<name>.kubelab.live` and
  have never resolved at all (#964). The name comes from MagicDNS
  `base_domain: kubelab.internal` (`headscale/templates/config.yaml.j2:39`),
  and MagicDNS resolves a node's **given-name**, which is not guaranteed to
  equal its hostname (`common.yaml:585`). Stability therefore depends on
  cloud-init's stale-node cleanup succeeding; without it a re-registration
  lands as `aws1-<random>` and the name breaks. `wait-node-ready` fails with
  that diagnosis rather than a bare connection timeout.

Verify the name after any replacement rather than assuming it:

```bash
dig +short aws1.kubelab.internal      # expect the new Tailscale IP
```

Argo CD state is rebuilt from declarative manifests on next sync — no
manual intervention. Downtime: roughly 5–7 minutes from `make
aws1-replace` start to a healthy `argo.kubelab.live` again.

## Rollback

- After `aws1-destroy`: there is no rollback — re-provision with
  `make tf-aws-apply` + `make provision NODE=aws1 ENV=hub` + `make
  deploy-argocd`. See `40-runbooks/runbook-disaster-recovery.md`.
- After `aws1-replace`: same as destroy. The previous instance is
  gone; the new one is the source of truth.

## Why these wrappers exist (history)

AWS-003 (2026-05-11) migrated `aws_spot_instance_request` →
`aws_instance` + `instance_market_options` so that EBS resizes work
in-place (the legacy resource silently dropped root_block_device
updates — see lesson 2026-05-11). Migration used `terraform state rm`
+ `terraform import`, which preserved the running instance but
orphaned the underlying Spot Persistent Request from Terraform state.

`aws_instance` exposes the Spot Request ID as a computed read-only
output (`spot_instance_request_id`) but does NOT manage its lifecycle.
A bare `terraform destroy aws_instance.argo_hub` would:

- Terminate the EC2 instance.
- Leave the Spot Persistent Request `active`, which AWS would honour
  by relaunching another EC2 within minutes — a zombie outside
  Terraform state, costing money and confusing operators.

These Makefile wrappers close that gap by cancelling the Spot Request
first. Codex flagged this regression on PR #168 (review of the AWS-003
refactor); AWS-004 codifies the fix.

## References

- ADR-023 (Hub-and-Spoke Multi-Cloud GitOps)
- AWS-003 refactor: PR #167, PR #168 (2026-05-11)
- `40-runbooks/aws1-ebs-resize.md` (in-place EBS expansion procedure)
- Lesson 2026-05-11 in `90-lessons.md` (aws_spot_instance_request
  silently drops root_block_device updates)
