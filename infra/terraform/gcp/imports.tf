# State reconstruction — same incident as gcp-bootstrap, second root.
#
# The local state for this root was lost along with the bootstrap one: backend
# is `local`, tfstate is gitignored, no copy survived. `terraform plan` reported
# `14 to add` against a hub that is RUNNING and reconciling both spokes.
#
# THIS ROOT IS THE DANGEROUS ONE. `make tf-gcp-apply` carries `-auto-approve`
# (tf-gcp-bootstrap-apply does not), so an apply here with no state would have
# tried to build a SECOND gcp1-mig without asking anyone. The reverse is just as
# bad and quieter: `tf-gcp-destroy` would have reported `0 to destroy` and
# exited 0, a teardown that tears nothing down.
#
# Read from the live project on 2026-08-23 and validated by plan: a wrong id
# fails the plan rather than adopting nothing.
#
# REMOVE THIS FILE once the apply has run and the second plan reads "No changes".

import {
  to = google_service_account.hub
  id = "projects/${var.project_id}/serviceAccounts/${var.hostname}-hub@${var.project_id}.iam.gserviceaccount.com"
}

# Derived from the same local the resource iterates, so this cannot drift from
# what it adopts -- and it inherits the single-writer invariant for free: a hub
# that does not manage prod has no prod grant here to import.
import {
  for_each = toset(local.hub_readable_secrets)

  to = google_secret_manager_secret_iam_member.hub_readable[each.value]
  id = "projects/${var.project_id}/secrets/${each.value} roles/secretmanager.secretAccessor serviceAccount:${var.hostname}-hub@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_compute_firewall.ssh_bootstrap
  id = "projects/${var.project_id}/global/firewalls/${var.hostname}-ssh-bootstrap"
}

import {
  to = google_compute_firewall.tailscale
  id = "projects/${var.project_id}/global/firewalls/${var.hostname}-tailscale"
}

# The one id here no variable can supply. The template uses `name_prefix`, so
# its full name carries a server-generated timestamp suffix -- this is the
# template the running MIG is actually serving, not one reconstructed from the
# prefix.
import {
  to = google_compute_instance_template.hub
  id = "projects/${var.project_id}/global/instanceTemplates/${var.hostname}-20260823022852382500000001"
}

# Regional, not zonal: the id carries `regions/`, and getting that wrong is a
# plan error rather than a silent miss.
import {
  to = google_compute_region_instance_group_manager.hub
  id = "projects/${var.project_id}/regions/${var.region}/instanceGroupManagers/${var.hostname}-mig"
}
