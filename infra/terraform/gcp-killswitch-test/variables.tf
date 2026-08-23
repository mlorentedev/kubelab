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
    Scratch project id, UNIQUE PER RUN. Rendered by
    `toolkit infra terraform killswitch-test-tfvars` as
    `kubelab-killswitch-<UTC timestamp>`.

    The default used to be the fixed `kubelab-killswitch-proof`, on the reasoning
    that a name collision is what makes an orphaned project noticeable. Measured
    2026-08-23: the collision happens even when the destroy is CLEAN. GCP holds a
    deleted project in DELETE_REQUESTED for ~30 days and reserves its id the whole
    time, so a second run inside that window fails with
    `Error 409: Requested entity already exists` -- which is not a signal about
    orphans at all, it is the normal case.

    A proof of the billing kill switch that can only run once a month does not
    verify the kill switch; it records that the switch worked on one day. There is
    deliberately NO default now: a fixed id is the defect, so the value must come
    from the generator.
  EOT
  type        = string

  # GCP caps a project id at 30 characters and rejects a violation at APPLY time,
  # after the run has already started doing work. Asserting it here moves the
  # failure to plan, where it costs nothing. Found by generating a 31-char id.
  validation {
    condition     = length(var.project_id) >= 6 && length(var.project_id) <= 30
    error_message = "project_id must be 6-30 characters; GCP rejects longer ids at apply time, not at plan."
  }

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.project_id))
    error_message = "project_id must start with a letter, contain only lowercase letters, digits and hyphens, and not end with a hyphen."
  }
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
