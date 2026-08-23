# State reconstruction — every object below EXISTS in GCP and is absent from state.
#
# WHY THIS FILE EXISTS. The local state file for this root was lost: the backend
# is `local`, `*.tfstate` is gitignored, and no copy survived on the workstation.
# `terraform plan` consequently reported `25 to add` against a project that is
# live and serving. An apply in that condition does not converge anything; it
# tries to re-create a running hub's guardrails.
#
# The IDs below were read from the live account, not transcribed from the spec.
# `terraform plan` validates every one of them: a wrong ID or a non-existent
# object fails the plan rather than silently importing nothing, which is what
# makes this file self-verifying.
#
# NOT IMPORTED, deliberately: `google_monitoring_notification_channel.notify_webhook`.
# It does not exist — it arrived with the change that was merged and never
# applied. It must stay a CREATE, and it is the one object whose creation this
# apply is actually for. Importing a resource that does not exist aborts the
# whole plan, so this list doubles as an assertion of what is live.
#
# REMOVE THIS FILE once the apply has run and the second plan reads "No changes".
# Import blocks are idempotent no-ops afterwards, but leaving them implies the
# state is still missing.

import {
  to = google_project.hub
  id = "projects/${var.project_id}"
}

# One block instead of fifteen. `local.services` is the same list the resource
# iterates, so this cannot drift from what it is importing into.
#
# `monitoring.googleapis.com` is subtracted because it is the one service that is
# NOT already enabled — it is being added in this same change, for the
# notification channel below. Importing it would abort the entire plan
# ("Cannot import non-existent remote object"), taking the other twenty-two
# imports down with it. Subtracting it here states, in one line, which single
# service this apply creates rather than adopts.
import {
  for_each = setsubtract(toset(local.services), ["monitoring.googleapis.com"])

  to = google_project_service.enabled[each.value]
  id = "${var.project_id}/${each.value}"
}

# Budget ids are server-generated UUIDs, so these two are the only literals here
# that no variable can supply. Read from
# `gcloud billing budgets list --billing-account=<id>` on 2026-08-23.
import {
  to = google_billing_budget.alerting
  id = "billingAccounts/${var.billing_account_id}/budgets/e78a413d-8fbc-4e99-9833-e1c69f8d6341"
}

import {
  to = google_billing_budget.hard_cap
  id = "billingAccounts/${var.billing_account_id}/budgets/aff176ef-b6d4-47f8-a115-8571d3a7ea13"
}

import {
  to = google_pubsub_topic.budget_alerts
  id = "projects/${var.project_id}/topics/billing-kill-switch"
}

import {
  to = google_service_account.kill_switch
  id = "projects/${var.project_id}/serviceAccounts/billing-kill-switch@${var.project_id}.iam.gserviceaccount.com"
}

# Space-separated triple, not a path: that is this resource type's documented
# import form, and the role is project-level rather than billing-account-level
# for the reason killswitch.tf records.
import {
  to = google_project_iam_member.kill_switch
  id = "${var.project_id} roles/billing.projectManager serviceAccount:billing-kill-switch@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_storage_bucket.function_source
  id = "${var.project_id}/${var.project_id}-function-source"
}

# NOT IMPORTED, and not by choice: the provider rejects it outright with
# "resource google_storage_bucket_object doesn't support import". It is
# re-uploaded instead, which is safe here precisely because of #1310 — the
# object name embeds the source md5, so the name Terraform will write
# (kill-switch-93899ba91c287bde9f2be71bf353c423.zip) is byte-for-byte the object
# already in the bucket. A reproducible zip turns an unimportable resource into
# an idempotent one.
#
#   import { to = google_storage_bucket_object.kill_switch  ... }  <- impossible

import {
  to = google_cloudfunctions2_function.kill_switch
  id = "projects/${var.project_id}/locations/${var.region}/functions/billing-kill-switch"
}
