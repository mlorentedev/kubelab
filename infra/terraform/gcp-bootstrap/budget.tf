# Spend guardrails: an alerting budget and a hard cap.
#
# Two thresholds and two DIFFERENT mechanisms, because GCP offers no single one
# that both warns and stops. The runbook states this plainly and it is worth
# restating at the code: a Google Cloud budget NOTIFIES; it does not cap.
#
# ---------------------------------------------------------------------------
# FINDING F4 — the trap that makes a budget lie about its own number
# ---------------------------------------------------------------------------
# `credit_types_treatment` defaults to INCLUDE_ALL_CREDITS, which measures spend
# NET of credits. With a $10/mo credit attached, a $10 budget on that default
# fires at $10 of REAL MONEY -- that is $20 of usage. The number on the budget
# and the number it enforces are different, and nothing surfaces the gap.
#
# Both budgets below use EXCLUDE_ALL_CREDITS, so they measure gross usage and the
# figure means what it says. This is the one setting here whose reversal would
# look locally reasonable and silently double the ceiling.

resource "google_billing_budget" "alerting" {
  billing_account = var.billing_account_id
  display_name    = "kubelab-hub alerting (${var.budget_alert_amount} ${var.currency})"

  budget_filter {
    projects               = ["projects/${google_project.hub.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = var.currency
      units         = tostring(var.budget_alert_amount)
    }
  }

  # 50 / 90 / 100. The first two exist so the third is never the first thing
  # anyone hears -- a cost problem found at 100% has already been running for
  # most of a month.
  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  all_updates_rule {
    monitoring_notification_channels = [
      google_monitoring_notification_channel.notify_webhook.id
    ]
    disable_default_iam_recipients = false
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_notification_channel" "notify_webhook" {
  project      = google_project.hub.project_id
  display_name = "KubeLab n8n Notification Fabric"
  type         = "webhook_tokenauth"
  labels = {
    url = "https://n8n.kubelab.live/webhook/notify"
  }
  user_labels = {
    domain = "ops"
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------------------
# The hard cap
# ---------------------------------------------------------------------------
# This budget's job is not to notify a human. It publishes to Pub/Sub, and the
# subscriber detaches the billing account -- which stops every billable resource
# in the project, the hub included.
#
# Accepted deliberately: the spokes keep reconciling without a hub (ADR-023's
# Autonomous Spoke property), so the cap's blast radius is the management plane
# rather than the workloads. Recovery is manual and that is the point; an
# automatic re-attach would defeat a cap.

resource "google_pubsub_topic" "budget_alerts" {
  project = google_project.hub.project_id
  name    = "billing-kill-switch"

  depends_on = [google_project_service.enabled]
}

resource "google_billing_budget" "hard_cap" {
  billing_account = var.billing_account_id
  display_name    = "kubelab-hub HARD CAP (${var.budget_cap_amount} ${var.currency})"

  budget_filter {
    projects               = ["projects/${google_project.hub.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = var.currency
      units         = tostring(var.budget_cap_amount)
    }
  }

  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "CURRENT_SPEND"
  }

  # Pub/Sub is what CAPS; the default IAM e-mail to billing admins is extra, not
  # a substitute, and it is left on.
  #
  # `disable_default_iam_recipients = true` was here and the API rejected it with
  # a bare `Error 400: Request contains an invalid argument` -- measured, on the
  # apply that created the sibling budget seconds earlier. The flag is only valid
  # alongside `monitoring_notification_channels`; every example in the provider
  # pairs the two. With a `pubsub_topic` and nothing else it is not accepted.
  #
  # Suppressing it bought nothing anyway: the human notification does not delay
  # the machine one, and at a hard cap a second channel is a feature.
  all_updates_rule {
    pubsub_topic   = google_pubsub_topic.budget_alerts.id
    schema_version = "1.0"
  }

  depends_on = [google_project_service.enabled]
}
