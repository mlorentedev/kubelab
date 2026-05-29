---
id: aws1-ebs-resize
type: runbook
status: active
created: "2026-05-10"
---

# aws1 EBS online resize — operational runbook

> Procedure to expand the root EBS volume on the aws1 Argo CD hub without
> instance replacement. Pure declarative IaC: Terraform owns the cloud size,
> cloud-init owns the host-side partition + filesystem growth.

## When to run

- Disk utilization on aws1 trending above 75% (Uptime Kuma alert, future MON-XX).
- After a planned Argo CD scope expansion (new controllers, more spokes).
- Following the 2026-05-10 RELIAB-009 incident: every Helm upgrade on the
  8GB original sizing triggered disk-pressure → 12GB is the new baseline.

## Prerequisites

- AWS CLI configured against the `kubelab` profile.
- Local clone of the repo on the workstation with `terraform` ≥1.5.
- SSH access to aws1 via Tailscale MagicDNS (`aws1.kubelab.internal`).
- **`main.tf` MUST contain `lifecycle { ignore_changes = [ami, user_data] }`
  on `aws_instance.argo_hub`** (shipped by `refactor/aws-003-aws-instance`,
  2026-05-11; superseded the legacy `aws_spot_instance_request` resource
  whose root_block_device updates were silently dropped — see lesson
  2026-05-11 in 90-lessons.md). Without `ignore_changes`, `data.aws_ami.ubuntu`
  with `most_recent = true` resolves to a newer Canonical AMI each plan and
  forces destroy+create of the instance — turning a safe in-place EBS resize
  into a full replacement. Sanity check before running anything:
  ```bash
  grep -B1 -A3 "ignore_changes" infra/terraform/aws/main.tf
  # Expected: resource "aws_instance" "argo_hub" { ... ignore_changes = [ami, user_data] }
  ```

## Procedure (≈3 min, zero downtime)

1. **Update the SSOT — already done in PR feat/aws-002-ebs-resize-12gb**
   - `infra/config/values/common.yaml` → `networking.aws.ebs_size_gb: 12`
   - `infra/terraform/aws/variables.tf` → `default = 12`
   - `infra/terraform/aws/aws.tfvars.example` → comment mirror

2. **Apply the Terraform change** (always via Makefile — wraps SOPS-injected tfvars)
   ```bash
   make tf-aws-plan
   # Expected plan: 0 to add, 1 to change, 0 to destroy
   #   ~ aws_instance.argo_hub will be updated in-place
   #     ~ root_block_device { ~ volume_size = 8 -> 12 }
   # Output-only diffs (ami_id, public_ip) are cosmetic and ignored
   # by the lifecycle block — they do NOT trigger replacement.
   # If you see "must be replaced" or "1 to destroy", STOP — the
   # lifecycle block is missing or `aws.tfvars` is wrong.
   make tf-aws-apply
   ```
   AWS issues `ec2:ModifyVolume`. Apply takes ~35s ("Still modifying..."
   every 10s in the terraform output — a real call, not the 1s no-op that
   the legacy `aws_spot_instance_request` would have reported). Confirm
   from AWS:
   ```bash
   aws ec2 describe-volumes-modifications --volume-ids <vol-id> \
     --profile kubelab --region eu-central-1 \
     --query 'VolumesModifications[*].[ModificationState,OriginalSize,TargetSize]' \
     --output table
   # Expected: optimizing | 8 | 12  (optimizing continues in background;
   # the filesystem can be grown before it finishes).
   ```

3. **Grow partition + filesystem online (no reboot needed)**
   ```bash
   ssh aws1 'sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/root'
   # growpart prints: CHANGED: partition=1 ... new: size=...
   # resize2fs prints: on-line resizing required ... now N blocks long.
   ```
   ext4 supports online resize, and the NVMe kernel driver detects the
   new EBS size automatically on modern Ubuntu (no manual rescan needed
   in practice; if `lsblk` still shows old size, force a rescan with
   `echo 1 | sudo tee /sys/block/nvme0n1/device/rescan`).

   **Reboot is NOT required** with this procedure — Tailscale, K3s, and
   Argo CD stay up throughout. Reboot remains an option only if a kernel
   pin or other host-level change is also pending.

4. **Verify**
   ```bash
   ssh aws1 "df -h /; lsblk | head -3"
   # Expect / on /dev/root showing ~11G usable (12G - reserved blocks).
   KUBECONFIG=~/.kube/kubelab-hub-config kubectl get nodes
   # aws1 Ready.
   KUBECONFIG=~/.kube/kubelab-hub-config kubectl describe node aws1 | grep -A2 Taints
   # Taints: <none>  (no disk-pressure).
   curl -sS -o /dev/null -w "HTTP %{http_code}\n" https://argo.kubelab.live/
   # HTTP 200.
   ```

## Rollback

EBS gp3 volumes can be **expanded** online but **cannot be shrunk**. If 12GB
later proves problematic, the rollback path is a cattle replace:

```bash
make aws1-replace          # see 40-runbooks/aws1-destroy-replace.md
make deploy-argocd
```

The new instance is created from scratch with whatever `ebs_size_gb` is
configured in common.yaml at that moment, and cloud-init re-bootstraps
K3s + Tailscale. Argo CD re-syncs from declarative manifests.

## Cost impact

eu-central-1 gp3: `$0.0952/GB-month`. Delta 8→12 GB = **+$0.38/mo** = **$4.57/year**.

## Notes

- The reboot interrupts argo.kubelab.live for ~90s. Acceptable because the
  hub doesn't serve user traffic (Argo CD UI is fronted by VPS Traefik
  tunnel) and Spot replacements interrupt longer anyway.
- Cloud-init's `cc_growpart` ran on aws1 last on 2026-05-08 (verified during
  RELIAB-009 pre-flight) — module list and resizefs success confirmed.
- This procedure is cloud-agnostic in spirit: a future GCP/Azure hub would
  use the equivalent in-place disk resize + cloud-init reboot pattern.

## References

- ADR-023 (Hub-and-Spoke Multi-Cloud GitOps)
- ADR-026 (Spot replacement = cattle, not pets)
- Lesson 2026-05-10 "Helm upgrade on disk-constrained node creates
  pull-evict-prune-pull death loop" (`90-lessons.md`)
- PR feat/aws-002-ebs-resize-12gb (this procedure)
