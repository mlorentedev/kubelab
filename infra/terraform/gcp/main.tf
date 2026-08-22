# GCP Management Plane — Argo CD Hub (ADR-063, supersedes ADR-023 §3.1)
#
# Stateless K3s + Argo CD on a Spot VM inside a REGIONAL managed instance group
# of size 1. VPN-only access via Headscale; the external IP is ephemeral and
# exists solely so the instance has egress for its own bootstrap.
#
# Runnable: `make tf-gcp-{plan,apply,destroy}` and `make gcp1-*` landed with the
# `gcp-tfvars` renderer (#1220). Procedure: docs/runbooks/gcp-hub-bootstrap.md §6.
#
# This module assumes the PROJECT ALREADY EXISTS. It is created, with its APIs
# and its spend guardrails, by infra/terraform/gcp-bootstrap/ — a separate root
# with separate state, so that destroying the hub (routine: preemption drills,
# machine-type changes, the AWS cutover) cannot take the project with it.

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
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Network — the default VPC, with only what the hub actually needs open
# ---------------------------------------------------------------------------

# Zones in the configured region. Read rather than assumed: it is the only legal
# non-zero value for a regional MIG's maxUnavailable, and it differs by region.
data "google_compute_zones" "available" {
  region = var.region
}

data "google_compute_network" "default" {
  name = "default"
}

# SSH is bootstrap-only. Everything operational rides Tailscale, and the Ansible
# inventory addresses the node by its MagicDNS name, not this address.
resource "google_compute_firewall" "ssh_bootstrap" {
  name          = "${var.hostname}-ssh-bootstrap"
  network       = data.google_compute_network.default.name
  description   = "SSH for first-boot bootstrap; operational access is over Tailscale"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.hostname]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# WireGuard. Without this the node can still reach the mesh via DERP relay, but
# every hub->spoke API call would take the relay path instead of a direct one.
resource "google_compute_firewall" "tailscale" {
  name          = "${var.hostname}-tailscale"
  network       = data.google_compute_network.default.name
  description   = "Tailscale/WireGuard direct connections"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.hostname]

  allow {
    protocol = "udp"
    ports    = ["41641"]
  }
}

# ---------------------------------------------------------------------------
# Identity — least privilege, on named secrets only
# ---------------------------------------------------------------------------

resource "google_service_account" "hub" {
  account_id   = "${var.hostname}-hub"
  display_name = "KubeLab Argo CD hub (${var.hostname})"
  description  = "Reads only the named secrets cloud-init needs; no project-wide grant."
}

# Scoped to ONE secret by resource, not to the project. cloud-init needs the
# Headscale API key and nothing else at boot: it mints its own pre-auth key with
# that key rather than being handed a stored one (ADR-063 D7 / finding F2).
# Scoped to NAMED secrets by resource, never to the project. The set is derived
# rather than listed twice: the spoke entries follow `managed_spokes`, so a hub
# that does not reconcile prod cannot read prod's cluster credentials either.
# That is the single-writer invariant expressed as an IAM grant rather than as a
# convention -- adding a spoke to the list is what widens the access, in one
# place, visibly in the plan.
locals {
  hub_readable_secrets = concat(
    [var.headscale_api_key_secret],
    values(var.argocd_secret_ids),
    flatten([
      for env in var.managed_spokes : [
        "argocd-spokes-${env}-token",
        "argocd-spokes-${env}-ca",
      ]
    ]),
  )
}

resource "google_secret_manager_secret_iam_member" "hub_readable" {
  for_each = toset(local.hub_readable_secrets)

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.hub.email}"
}

# ---------------------------------------------------------------------------
# Instance template
# ---------------------------------------------------------------------------
#
# Spot, with instance_termination_action = DELETE rather than the STOP default:
# STOP leaves a TERMINATED husk behind after every preemption, and the MIG's
# reconciliation is cleaner when a preempted instance simply ceases to exist.

resource "google_compute_instance_template" "hub" {
  name_prefix  = "${var.hostname}-"
  machine_type = var.machine_type
  tags         = [var.hostname]

  scheduling {
    provisioning_model          = "SPOT"
    preemptible                 = true
    automatic_restart           = false
    on_host_maintenance         = "TERMINATE"
    instance_termination_action = "DELETE"
  }

  disk {
    source_image = "${var.image_project}/${var.image_family}"
    auto_delete  = true
    boot         = true
    disk_size_gb = var.disk_size_gb
    disk_type    = var.disk_type
  }

  network_interface {
    network = data.google_compute_network.default.name

    # Ephemeral external IP, deliberately: no google_compute_address anywhere in
    # this module. A RESERVED address costs $0.010/hr while unattached — 4x the
    # $0.0025/hr Spot-attached rate — and a MIG that recreates VMs is exactly the
    # machine for orphaning reserved addresses. The hub needs no stable public
    # address; every operational path is Tailscale. This is the likeliest single
    # route to the $15 budget cap, designed out rather than merely alerted on.
    access_config {
      # Explicit, never inherited -- see variables.tf for the reasoning and for
      # the figure that still needs console confirmation.
      network_tier = var.network_tier
    }
  }

  service_account {
    email  = google_service_account.hub.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    # TCP/22 is open to 0.0.0.0/0 for first-boot bootstrap, so project-level
    # metadata SSH keys would otherwise grant a login on every instance the MIG
    # ever creates -- an access path that widens silently as the project grows
    # and that nothing in this module would reflect. Only the key below is honoured.
    block-project-ssh-keys = "TRUE"

    # cloud-init runs on EVERY instance the MIG creates, not only the first: a
    # MIG recreates rather than restarts, so each preemption is a from-scratch
    # build. It therefore has to complete the WHOLE bring-up, Argo CD included
    # (ADR-063 D7 / finding F1) — a MIG alone restores the VM, not the hub.
    user-data = templatefile("${path.module}/cloud-init.yml", {
      hostname                 = var.hostname
      deploy_user              = var.deploy_user
      ssh_public_key           = file(pathexpand(var.ssh_public_key_path))
      timezone                 = var.timezone
      k3s_version              = var.k3s_version
      headscale_url            = var.headscale_url
      headscale_api_key_secret = var.headscale_api_key_secret
      project_id               = var.project_id

      # --- Argo CD stage (finding F1) ---------------------------------------
      argocd_chart_version = var.argocd_chart_version
      helm_version         = var.helm_version
      managed_spokes       = join(" ", var.managed_spokes)
      spoke_servers        = jsonencode(var.spoke_servers)

      # Passed individually rather than as one map: the bootstrap reads each by
      # name, and a jq lookup per secret would add a parse step whose failure
      # mode is an empty string -- which `--set-file` would then happily install
      # as a blank admin password.
      secret_admin_hash = var.argocd_secret_ids["admin_password_hash"]
      secret_oidc       = var.argocd_secret_ids["oidc_client_secret"]
      secret_slack      = var.argocd_secret_ids["slack_webhook_url"]
      secret_github     = var.argocd_secret_ids["github_webhook"]

      # Base64 so the embedded YAML never has to survive being quoted inside
      # this YAML, and so a `$${}` inside the chart values cannot collide with
      # templatefile interpolation. The repo file stays the SSOT and nothing is
      # cloned on the node (CLAUDE.md forbids cloning on deployment targets).
      argocd_values_b64 = base64encode(file("${path.module}/../../helm/argocd/values.yaml"))
      applications_b64 = base64encode(join("\n---\n", [
        for env in var.managed_spokes :
        file("${path.module}/../../k8s/argocd/applications/${env}.yaml")
      ]))
      cluster_secret_tpl_b64 = base64encode(file("${path.module}/../../k8s/argocd/cluster-secret.yaml.tpl"))
    })
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ---------------------------------------------------------------------------
# Regional MIG of one
# ---------------------------------------------------------------------------
#
# REGIONAL, not zonal. GCP Spot VMs do not auto-restart the way the AWS
# persistent Spot request this replaces did, so something must recreate them —
# and #1066 was precisely "no Spot capacity in the zone we picked", with the
# instance sitting stopped until capacity returned. A zonal group would
# self-heal and still reproduce that outage; a regional one places the VM
# wherever capacity currently is.
#
# No auto_healing_policies in v1 (ADR-063 D2): with DELETE termination the group
# already restores target size on preemption without a health check, and a probe
# firing before cloud-init's multi-minute bootstrap finishes would recreate-loop
# a Spot hub. Adding one later requires initial_delay_sec >= measured bootstrap.

resource "google_compute_region_instance_group_manager" "hub" {
  name                      = "${var.hostname}-mig"
  base_instance_name        = var.hostname
  region                    = var.region
  target_size               = 1
  distribution_policy_zones = []

  version {
    instance_template = google_compute_instance_template.hub.id
  }

  # No surge, and RECREATE rather than SUBSTITUTE. Both matter for a singleton
  # whose identity IS its name.
  #
  # With target_size = 1, any surge boots additional instances that all come up
  # as `gcp1`: several nodes racing to register the same Headscale given-name,
  # and several K3s control planes, simultaneously. That is exactly the
  # given-name collision this module's own cloud-init treats as its critical
  # hazard -- a registration landing as `gcp1-<random>` breaks the Ansible
  # inventory, the kubeconfig server URL and the prod EndpointSlice at once.
  #
  # So a replacement takes the node down and brings it back rather than
  # overlapping. For a management plane that is the right trade: the spokes keep
  # running without the hub (ADR-023's Autonomous Spoke property), whereas two
  # hubs sharing one identity is a state nothing recovers from cleanly.
  # RECREATE preserves the instance name across a replacement; SUBSTITUTE mints
  # a new one and reintroduces the same naming problem.
  update_policy {
    type                         = "PROACTIVE"
    minimal_action               = "REPLACE"
    replacement_method           = "RECREATE"
    instance_redistribution_type = "NONE"
    max_surge_fixed              = 0
    # DERIVED from the region's zone count, never typed as a number. Both halves
    # of that were forced by the API, one apply apart.
    #
    # A regional MIG rejects `max_unavailable_fixed = 1`:
    #
    #   has to be either 0 or at least equal to the number of zones
    #
    # and rejects the percent form for a different reason:
    #
    #   Percent updatePolicy.maxUnavailable ... is only allowed for regional
    #   managed instance groups with size at least 10
    #
    # So the zone count is the ONLY legal non-zero value here, and 0 would
    # forbid replacing the only instance -- the one thing this group exists to
    # do.
    #
    # Derived rather than written as `3`, because 3 is a fact about
    # europe-west4, not about this design. Beside a `region` that is a variable,
    # a literal goes silently wrong on any region with a different zone count,
    # and wrong in the direction that blocks replacement.
    max_unavailable_fixed = length(data.google_compute_zones.available.names)
  }
}
