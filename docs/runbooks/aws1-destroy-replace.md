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
make aws1-replace
# Wait ~5 min for cloud-init to bring K3s + Tailscale up.
make deploy-argocd      # redeploy Argo CD hub onto the fresh instance
```

What it does:

1. Cancels the existing Spot Persistent Request (same as above).
2. Regenerates `aws.tfvars` from SOPS.
3. `terraform apply -auto-approve -replace=aws_instance.argo_hub`
   — forces destroy+recreate even though the `lifecycle` block ignores
   `ami` and `user_data`. The `-replace` flag is the explicit override.
4. Cleans `aws.tfvars`.

The new instance comes up with:

- Fresh Canonical AMI (whatever `data.aws_ami.ubuntu` resolves to).
- Fresh `user_data` (re-rendered cloud-init with current SOPS secrets).
- A new EC2 instance ID and a new Spot Persistent Request ID.
- Same hostname (`aws1`), same Tailscale registration (the Headscale
  `extra_records` in common.yaml keep `aws1.kubelab.internal` stable),
  same K3s + Argo CD config (re-bootstrapped via cloud-init + `make
  deploy-argocd`).

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
