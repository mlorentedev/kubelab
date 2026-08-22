output "project_id" {
  description = "The project every other root and every gcloud call targets."
  value       = google_project.hub.project_id
}

output "project_number" {
  description = "Numeric id. Budgets filter on this, not on the string id."
  value       = google_project.hub.number
}

output "kill_switch_topic" {
  description = "Pub/Sub topic the hard-cap budget publishes to."
  value       = google_pubsub_topic.budget_alerts.id
}

# Deliberately NOT an output: billing_account_id. It is a `sensitive` input and
# echoing it here would put it in `terraform output` and in the state's plain
# output map, for no benefit -- every consumer already reads it from SOPS.

output "next_steps" {
  description = "What to do after this root applies."
  value       = <<-EOT

    Bootstrap applied. Verify the link before trusting it:

      gcloud billing projects describe ${google_project.hub.project_id}

    Expect `billingEnabled: true` AND a `billingAccountName` matching the account
    holding the credit. `billingEnabled: true` alone does not tell you WHICH
    account -- and the wrong one is silent, because everything works and the bill
    simply arrives.

    Then, once per workstation:

      gcloud config set project ${google_project.hub.project_id}
      gcloud auth application-default set-quota-project ${google_project.hub.project_id}

    The second one clears the "Cannot find a quota project to add to ADC" warning
    that `gcloud auth application-default login` emits. It cannot be run earlier:
    the project has to exist first.

    The kill switch is deployed: budget -> Pub/Sub -> function -> billing
    detached. The ${var.budget_cap_amount} ${var.currency} threshold CAPS.

    IT HAS NOT FIRED YET, and a rule that has never fired is not evidence
    (AC2b). Prove it against a scratch project, never against this one -- testing
    here would work, and prove it by taking the hub down. See
    docs/runbooks/gcp-hub-bootstrap.md §4.3.
  EOT
}
