# A scratch project, existing only to be killed (AC2b).
#
# The kill switch must be proven to fire, and it must never be proven against
# the hub: that would work, and prove it by taking the hub down. So the proof
# needs a project that is expendable, attached to the SAME billing account (a
# different one would exercise a different permission path), and empty -- an
# empty project bills nothing, so this costs $0 to stand up.
#
# Its own root with its own state, so `terraform destroy` here can be routine
# and can never reach the hub. The bootstrap root sets `prevent_destroy` on its
# project precisely so the two cannot be confused; this one is the opposite kind
# of object and says so.

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "google" {
  region = var.region
  # Same reason as the bootstrap root: billing APIs refuse to bill a request to
  # nothing under user ADC. Attributed to the HUB project, which exists and is
  # not the one being detached -- attributing quota to the scratch project would
  # make the API calls fail the moment the test succeeds in disabling it.
  user_project_override = true
  billing_project       = var.quota_project
}

resource "google_project" "scratch" {
  project_id      = var.project_id
  name            = "KubeLab kill-switch proof"
  billing_account = var.billing_account_id

  # The provider defaults `deletion_policy` to PREVENT, which made the first run
  # fail with `Cannot destroy project as deletion_policy is set to PREVENT` --
  # leaving behind exactly the orphan this root exists to avoid. Measured.
  deletion_policy = "DELETE"

  # NO prevent_destroy, deliberately, and this is the one place in the repo
  # where that is the point: this project is meant to be destroyed, every time.
  # Leaving one behind is not free of consequence -- a project detached from
  # billing lingers until deleted, and the next run's `project_id` collides.
}

# The detach permission is per-project (see gcp-bootstrap/killswitch.tf). Without
# this grant the function returns a 403 and the proof would read as "the kill
# switch does not work" when what failed was the test's own setup.
resource "google_project_iam_member" "kill_switch" {
  project = google_project.scratch.project_id
  role    = "roles/billing.projectManager"
  member  = "serviceAccount:${var.kill_switch_service_account}"
}
