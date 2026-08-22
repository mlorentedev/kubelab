# Inputs for the bootstrap root.
#
# Rendered by `toolkit infra terraform gcp-bootstrap-tfvars` and deleted after
# every use. Unlike the hub module -- which carries NO secret, because cloud-init
# reads its credentials from Secret Manager -- this root has one: the billing
# account id. It is not a credential (nothing can be spent with it absent IAM),
# but this repository is public and git history is permanent, so it lives in
# SOPS rather than in a committed default.

variable "billing_account_id" {
  description = <<-EOT
    The billing account the project is linked to. Mirrors `gcp.billing_account_id`
    in SOPS.

    THIS IS THE VALUE THE WHOLE COST CASE RESTS ON. The migration is "$9.57/mo,
    $0 net" only if the project is attached to the account holding the monthly
    credit. Attaching a different one is silent: every resource works and the
    bill simply arrives. Verify with `gcloud billing projects describe` after
    apply -- `billingEnabled: true` alone does not tell you WHICH account.
  EOT
  type        = string
  sensitive   = true

  validation {
    # Catches a project id, an account name, or a truncated paste -- each of
    # which fails deep inside the provider with a message about permissions
    # rather than about the value being the wrong shape.
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account_id))
    error_message = "billing_account_id must look like XXXXXX-XXXXXX-XXXXXX (uppercase hex)."
  }
}

variable "project_id" {
  description = <<-EOT
    Globally unique project id. Mirrors `networking.gcp.project_id`.

    Global across all of GCP, not just this account, so it can be taken by a
    stranger. The runbook assumed it was free.
  EOT
  type        = string
  default     = "kubelab-hub"
}

variable "project_name" {
  description = "Human-readable project name shown in the console."
  type        = string
  default     = "KubeLab Hub"
}

variable "region" {
  description = "Default region for the provider. Mirrors `networking.gcp.region`."
  type        = string
  default     = "europe-west4"
}

variable "budget_alert_amount" {
  description = <<-EOT
    Soft threshold, in whole currency units. Alerts only -- GCP budgets notify,
    they do not cap.
  EOT
  type        = number
  default     = 10
}

variable "budget_cap_amount" {
  description = <<-EOT
    Hard threshold. Crossing it detaches the billing account, which takes the hub
    down and requires manual recovery. Accepted deliberately: the spokes keep
    running without a hub (ADR-023's Autonomous Spoke property), so the blast
    radius of the cap is the management plane, not the workloads.
  EOT
  type        = number
  default     = 15
}

variable "currency" {
  description = <<-EOT
    Currency of the billing account. A budget whose currency differs from the
    account's is rejected, so this is not cosmetic.

    MEASURED, not assumed: `gcloud billing accounts describe 0118CE-...` reports
    `currencyCode: USD`. The first draft of this file defaulted to EUR on the
    strength of the operator being in Europe, which would have failed at apply.
    Matches the cost derivation in ADR-063, which is denominated in dollars.
  EOT
  type        = string
  default     = "USD"
}
