---
id: lesson-251-terraform-data-aws-ami-filter-drift-triggers-
type: lesson
status: active
created: "2026-05-10"
owner: manu
tags: [kubelab, lesson, terraform, aws, spot, cattle, ami, lifecycle, drift, iac-pattern]
---

# Terraform data.aws_ami filter drift triggers Spot replacement on every plan

**Context:** Post-merge of feat/aws-002-ebs-resize-12gb (PR #165): ran `terraform plan` in `infra/terraform/aws/` to validate the EBS resize would be an in-place `ec2:ModifyVolume` action. Expected diff: 1 in-place change on root_block_device.volume_size 8 → 12. Reality: Terraform output `aws_spot_instance_request.argo_hub must be replaced` with the AMI attribute marked `# forces replacement` (`ami-023c2be60b92b00a3 → ami-050a364ece0d45bcd`).
**Problem:** `data "aws_ami" "ubuntu" { name_regex = "...ubuntu-noble-24.04-arm64-server-*" most_recent = true }` resolves to the LATEST matching AMI each time `terraform plan` runs. Canonical publishes new Ubuntu 24.04 ARM64 AMIs periodically (security updates). On a Spot/cattle infra design (ADR-026) where replacement IS the model, this means EVERY `terraform plan` for ANY unrelated attribute (EBS resize, tag change, security group rule, …) triggers a destroy+create of the instance — losing kine state, Headscale registration, etc. Replacement should be DELIBERATE, not a side effect of unrelated plans.
**Solution:** Add `lifecycle { ignore_changes = [ami, user_data] }` to the `aws_spot_instance_request` (or `aws_instance`) resource. AMI updates then require explicit `terraform apply -replace=<resource>` — codified as a Makefile target (e.g. `make aws1-replace`) that orchestrates the full cattle cycle: snapshot Headscale node entry → terraform apply -replace → wait cloud-init → re-run deploy-argocd. Also ignore `user_data` because Spot user_data embeds the tailscale_authkey (1h-lifetime) — its rotation should not trigger replacement; instead re-render and reboot if needed. Future automation: a scheduled `terraform plan -refresh-only` GH Action can detect AMI drift weekly and open an advisory PR. Generalisable rule: on any "cattle" cloud resource where the data source resolves to a moving target (latest AMI, latest VPC, etc.), ALWAYS pair with `lifecycle.ignore_changes` on the attributes driven by that data source.
**Tags:** `#terraform` `#aws` `#spot` `#cattle` `#ami` `#lifecycle` `#drift` `#iac-pattern`
