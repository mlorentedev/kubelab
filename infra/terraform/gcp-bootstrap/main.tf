# GCP bootstrap — the project and the guardrails that must outlive the hub
# (ADR-063, GCP-001 Phase 0)
#
# WHY THIS IS A SEPARATE ROOT, and not part of infra/terraform/gcp/:
#
#   1. ORDER. Spend guardrails have to exist BEFORE the first billable resource,
#      which is the whole point of a $15 hard cap. A budget that lands with the
#      VM is a budget that was absent for the only boot nobody was watching.
#   2. LIFECYCLE. `make tf-gcp-destroy` destroys the hub deliberately and often --
#      preemption drills, machine-type changes, the AWS cutover. If the project
#      lived in that root, every one of those would delete the project, the
#      budgets and the secrets with it.
#   3. STATE. Separate local state, so a corrupt or lost hub state file cannot
#      take the account-level objects with it.
#
# The spec named this root `gcp-billing/`. It is `gcp-bootstrap/` because it
# carries the project and the API enablement too, and those are not billing.
#
# Two things here are deliberately NOT automated, because they cannot be:
#
#   - `gcloud auth application-default login` is interactive OAuth. The only
#     alternative is a service-account key file, which is worse: a long-lived
#     credential for a repository that is public.
#   - WHICH billing account holds the monthly credit. No API exposes credits;
#     it is a console-only fact. Recorded once in SOPS as
#     `gcp.billing_account_id` (AC1) so the next reader re-checks rather than
#     re-discovers.
#
# Everything else is here.

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    # Zips the kill switch's source. Declared rather than left implicit so the
    # lock file pins it like everything else.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

# No `project` on the provider, deliberately. This root CREATES the project, so
# a provider pinned to it would need the thing it is about to make. Resources
# that need a project name it explicitly.
#
# `user_project_override` + `billing_project` exist because of a failure MEASURED
# on the first real apply, not anticipated:
#
#   Error 403: ... The billingbudgets.googleapis.com API requires a quota
#   project, which is not set by default.  reason: SERVICE_DISABLED
#   consumer: projects/764086051850          <- Google's own shared project
#
# Under user Application Default Credentials, some APIs refuse to bill a request
# to anything and fail with a message about the API being disabled -- pointing at
# a project number that is not yours. `billingbudgets` is one of them.
#
# The documented human fix is `gcloud auth application-default set-quota-project`,
# which cannot help inside a single apply: it needs the project to exist, and the
# budgets are created in the same run that creates it. That circularity is why
# the runbook's ordering was wrong rather than merely incomplete.
#
# These two settings are the Terraform answer: attribute quota to THIS project
# for calls that demand one. `var.project_id` rather than a reference to
# `google_project.hub` on purpose -- a reference would make the provider depend
# on a resource it configures, which Terraform refuses.
provider "google" {
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

# ---------------------------------------------------------------------------
# The project
# ---------------------------------------------------------------------------

# `billing_account` here is what links the project, so creation and linking are
# one operation rather than the two-step the runbook used to describe. The
# ordering hazard that removes is real: a project created but not linked accepts
# no billable resource, and the failure surfaces later as an unrelated-looking
# quota error.
resource "google_project" "hub" {
  project_id = var.project_id
  name       = var.project_name

  billing_account = var.billing_account_id

  # An org would place this under a folder. A personal account has none, and
  # setting either would fail rather than be ignored.
  auto_create_network = true

  lifecycle {
    # Destroying this destroys EVERYTHING in it -- the hub, the secrets, the
    # budgets that exist to stop a runaway bill. There is no operational reason
    # to ever `terraform destroy` this root: the hub has its own root and its
    # own destroy target. Removing the project is a deliberate, manual act.
    prevent_destroy = true
  }
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

# MEASURED against the live service catalogue on 2026-08-22, not copied from the
# runbook: it listed `cloudbudgets.googleapis.com`, WHICH DOES NOT EXIST. Every
# other candidate resolved; that one is absent from
# `gcloud services list --available`. The budget API is `billingbudgets`.
#
# `gcloud services enable` takes the whole list in one call, so the invented name
# did not merely skip a line -- it failed the entire enablement step. That error
# was undetectable by reading and only appeared on the first real run.
locals {
  services = [
    "cloudresourcemanager.googleapis.com", # google_project itself
    "serviceusage.googleapis.com",         # google_project_service itself
    "compute.googleapis.com",              # the MIG, the VM, the firewall rules
    "secretmanager.googleapis.com",        # cloud-init's boot credentials
    "cloudbilling.googleapis.com",         # reading/detaching the billing link
    "billingbudgets.googleapis.com",       # the budgets below
    "pubsub.googleapis.com",               # budget -> kill switch transport
    "cloudfunctions.googleapis.com",       # the kill switch itself
    "run.googleapis.com",                  # 2nd-gen functions run on Cloud Run
    # A 2nd-gen function is not one service. Deploying it BUILDS a container
    # (cloudbuild), PUSHES it (artifactregistry), is TRIGGERED through eventarc,
    # its source is uploaded to a bucket (storage), it runs as a service account
    # (iam) and it writes logs (logging).
    #
    # This list was assembled by hitting the errors, one apply at a time, which
    # is exactly what listing it here spares the next person. Each missing API
    # fails with `SERVICE_DISABLED` naming THAT service -- not the resource you
    # were creating -- so the message sends you looking at the wrong thing.
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "eventarc.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    # The notification channel in budget.tf. Added late and the same way as the
    # rest -- by hitting the error, not by reading: the channel arrived in a
    # change that merged and was never applied, so nothing ever asked GCP for it
    # and `Cloud Monitoring API has not been used in project kubelab-hub` sat
    # undiscovered behind a green build. Enablement is what a merged-but-
    # unapplied root cannot tell you.
    "monitoring.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project = google_project.hub.project_id
  service = each.value

  # Leaving an API enabled costs nothing. Disabling one on destroy can break
  # anything else that grew to depend on it, and turns a routine teardown into
  # an outage with a confusing cause.
  disable_on_destroy = false
}
