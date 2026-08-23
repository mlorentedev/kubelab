# The kill switch: the half of the $15 cap that actually caps.
#
# `budget.tf` publishes to a Pub/Sub topic when the hard cap is crossed. Nothing
# subscribing to that topic means the cap alerts and does not stop anything --
# which is a worse position than having no cap, because everyone believes they
# are protected. This file is the subscriber.

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
# Its own service account, not the default compute one. The default is attached
# to everything in the project and would carry the power to disable billing into
# every workload that ever runs here.
resource "google_service_account" "kill_switch" {
  project      = google_project.hub.project_id
  account_id   = "billing-kill-switch"
  display_name = "Billing kill switch"
  description  = "Detaches billing when the hard-cap budget fires. Nothing else."
}

# THE GRANT IS ON THE PROJECT, NOT THE BILLING ACCOUNT -- and that was measured,
# not chosen. Granting `roles/billing.projectManager` on the billing account is
# rejected outright:
#
#   Error 400: Role roles/billing.projectManager is not supported for this
#   resource., badRequest
#
# It is a PROJECT-level role. Disabling billing needs
# `resourcemanager.projects.deleteBillingAssignment` on the project being
# detached, which is what that role carries.
#
# The failed attempt produced the better design. A billing-account grant would
# have let this function detach billing from ANY project under the account; this
# one reaches exactly the project it is deployed beside. The blast radius is the
# hub, which is the blast radius the cap is supposed to have.
#
# Consequence for the AC2b test: the scratch project needs its own grant for the
# same service account. That is a feature -- the permission is visible and
# temporary rather than ambient.
resource "google_project_iam_member" "kill_switch" {
  project = google_project.hub.project_id
  role    = "roles/billing.projectManager"
  member  = "serviceAccount:${google_service_account.kill_switch.email}"
}

# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------
# Zipped from the directory rather than committed as a blob, so the code stays
# reviewable as code. `archive_file` hashes the contents, and the object name
# carries that hash -- which is what makes a source change redeploy the function
# instead of silently leaving the old one running.
#
# EXCLUDES ARE LOAD-BEARING, not tidiness. `archive_file` zips the DIRECTORY as
# it exists on disk, and it does not consult .gitignore -- so `__pycache__/`,
# which IS gitignored and therefore invisible in review, was being packaged and
# shipped to the function. A `.pyc` embeds the source file's mtime and size in
# its header, so anything that touches main.py (a checkout, a fresh clone, a
# local test run) changed the zip's bytes without changing a line of code.
#
# The consequence was not cosmetic: `terraform plan` reported
# `detect_md5hash -> "different hash"` on EVERY run, so this root never
# converged. A plan that always shows a change cannot detect drift, which is the
# one thing a plan is for -- and worse, it MASKS it: had someone edited the
# deployed function by hand, the plan would have looked exactly like this.
# The compute root converges to "No changes"; this one never had.
#
# Measured 2026-08-23: the packaged zip contained
# `__pycache__/main.cpython-312.pyc` (4,713 bytes) alongside main.py (3,537).
# Timestamps were NOT the cause -- archive_file already pins them to 2049-01-01,
# and checking that first is what ruled out the obvious hypothesis.
data "archive_file" "kill_switch" {
  type        = "zip"
  source_dir  = "${path.module}/function"
  output_path = "${path.module}/.terraform/kill-switch.zip"

  excludes = [
    "__pycache__",
    "__pycache__/**",
    "*.pyc",
  ]
}

resource "google_storage_bucket" "function_source" {
  project  = google_project.hub.project_id
  name     = "${google_project.hub.project_id}-function-source"
  location = var.region

  uniform_bucket_level_access = true
  force_destroy               = true

  # The bucket holds build inputs, not history. Without this, every redeploy
  # leaves another zip behind for the life of the project.
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket_object" "kill_switch" {
  name   = "kill-switch-${data.archive_file.kill_switch.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.kill_switch.output_path
}

# ---------------------------------------------------------------------------
# The function
# ---------------------------------------------------------------------------
resource "google_cloudfunctions2_function" "kill_switch" {
  project     = google_project.hub.project_id
  name        = "billing-kill-switch"
  location    = var.region
  description = "Detaches billing from TARGET_PROJECT when the hard-cap budget fires"

  build_config {
    runtime     = "python312"
    entry_point = "kill_switch"
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.kill_switch.name
      }
    }
  }

  service_config {
    # Smallest available. This runs a few times a year and does one API call.
    available_memory = "256M"
    timeout_seconds  = 60
    # One at a time. Several notifications can arrive together at a threshold,
    # and a detach is not worth racing on.
    max_instance_count    = 1
    service_account_email = google_service_account.kill_switch.email

    environment_variables = {
      # THE TARGET, and the only place it is declared. Never read from the
      # message: a real budget notification names no project, so a payload-read
      # branch could only ever be exercised by a synthetic test. Also what makes
      # the scratch-project test possible -- point this elsewhere, fire it for
      # real, point it back.
      TARGET_PROJECT = google_project.hub.project_id
    }
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.budget_alerts.id
    retry_policy   = "RETRY_POLICY_RETRY"
  }

  depends_on = [google_project_service.enabled]
}
