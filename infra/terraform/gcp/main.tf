# GCP Management Plane — Argo CD Hub (ADR-063, supersedes ADR-023 §3.1)
#
# Stateless K3s + Argo CD on a Spot VM inside a REGIONAL managed instance group
# of size 1. VPN-only access via Headscale; the external IP is ephemeral and
# exists solely so the instance has egress for its own bootstrap.
#
# Usage:
#   make tf-gcp-plan / make tf-gcp-apply
# After apply, `make wait-node-ready NODE=gcp1 ENV=hub` blocks until sshd answers
# AND cloud-init has finished — see docs/runbooks/gcp-hub-bootstrap.md §6.

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
resource "google_secret_manager_secret_iam_member" "headscale_api_key" {
  secret_id = var.headscale_api_key_secret
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
    access_config {}
  }

  service_account {
    email  = google_service_account.hub.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    # cloud-init runs on EVERY instance the MIG creates, not only the first: a
    # MIG recreates rather than restarts, so each preemption is a from-scratch
    # build. It therefore has to complete the WHOLE bring-up, Argo CD included
    # (ADR-063 D7 / finding F1) — a MIG alone restores the VM, not the hub.
    user-data = templatefile("${path.module}/cloud-init.yml", {
      hostname                 = var.hostname
      deploy_user              = var.deploy_user
      ssh_public_key           = file(var.ssh_public_key_path)
      timezone                 = var.timezone
      k3s_version              = var.k3s_version
      headscale_url            = var.headscale_url
      headscale_api_key_secret = var.headscale_api_key_secret
      project_id               = var.project_id
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

  update_policy {
    type                         = "PROACTIVE"
    minimal_action               = "REPLACE"
    instance_redistribution_type = "NONE"
    max_surge_fixed              = 3
    max_unavailable_fixed        = 0
  }
}
