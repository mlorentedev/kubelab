variable "billing_account_id" {
  description = <<-EOT
    The SAME billing account the hub uses. Mirrors `gcp.billing_account_id` in
    SOPS.

    Not an arbitrary choice: the detach path depends on the project being
    attached to this account, so proving it against a different one proves
    something else.
  EOT
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account_id))
    error_message = "billing_account_id must look like XXXXXX-XXXXXX-XXXXXX (uppercase hex)."
  }
}

variable "kill_switch_service_account" {
  description = <<-EOT
    Email of the kill switch's service account, from the bootstrap root's
    `kill_switch_service_account` output. Read from there rather than retyped:
    a stale copy grants the wrong identity and the proof fails as a 403 that
    looks like a broken kill switch.
  EOT
  type        = string
}

variable "project_id" {
  description = <<-EOT
    Scratch project id. Globally unique across all of GCP, and the previous
    run's project must be gone before the next can use the name -- which is the
    mechanism that makes leaving one behind noticeable.
  EOT
  type        = string
  default     = "kubelab-killswitch-proof"
}

variable "quota_project" {
  description = <<-EOT
    Project billed for the provider's own API calls. The HUB, not the scratch
    project: the test's whole purpose is to disable billing on the scratch
    project, and a provider attributing its quota there would start failing at
    the exact moment the test succeeds.
  EOT
  type        = string
  default     = "kubelab-hub"
}

variable "region" {
  description = "Provider default region. Mirrors `networking.gcp.region`."
  type        = string
  default     = "europe-west4"
}
