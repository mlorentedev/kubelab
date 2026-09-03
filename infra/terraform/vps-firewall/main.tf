# Hetzner cloud firewall for the ALREADY-RUNNING production VPS (SEC-006).
#
# Read this before editing:
#
# This module manages a firewall and its attachment. It does NOT manage the
# server, and must never be made to. The server is reached through a `data`
# source, so it never enters this module's state: there is nothing to import,
# no `lifecycle { ignore_changes }` is needed, and `plan` cannot show a
# replacement because no managed resource here is replaceable. That property
# is the entire design, not an implementation detail — see AC2 in
# specs/SEC-006-cloud-firewall-for-running-vps/proposal.md.
#
# Not to be confused with infra/terraform/compute/, which declares a similar
# firewall. That module is recreate-only disaster recovery (ADR-020, Layer 0):
# it describes a world in which nothing exists yet, and has never been applied.
# Reading its declaration as evidence that prod had a firewall is exactly the
# mistake that let SEC-005 (#1538) happen — port 9000 answered the public
# internet for months while the repo appeared to say otherwise.
#
# Why a cloud firewall and not ufw: ufw CANNOT restrict a published port.
# Docker and klipper-lb DNAT in PREROUTING, before ufw's filter chains, and
# DOCKER-USER is empty fleet-wide (#959). Hetzner enforces at its own edge,
# upstream of the host entirely, which is why this layer holds where ufw does
# not. ufw is kept in step for defence in depth, from the same SSOT.

terraform {
  required_version = ">= 1.5"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.60"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "hcloud" {
  token = var.hetzner_api_token
}

# ---------------------------------------------------------------------------
# The running server — READ ONLY. Never promote this to a resource.
# ---------------------------------------------------------------------------

data "hcloud_server" "vps" {
  name = var.server_name
}

# ---------------------------------------------------------------------------
# Firewall
#
# Rules come from networking.firewall.vps_inbound in common.yaml, rendered into
# vps-firewall.auto.tfvars by `toolkit infra terraform vps-firewall-tfvars`.
# Do not hardcode a port here — the whole point of SEC-006 is that the list is
# declared once. A port added here and not in common.yaml would drift silently,
# and the guard (tests/) asserts the two agree.
# ---------------------------------------------------------------------------

resource "hcloud_firewall" "vps" {
  # Deliberately NOT "${var.project_name}-vps", which is the name the DR module
  # in infra/terraform/compute/ would claim. Distinct names mean a recreate
  # during an actual disaster cannot collide with a firewall that survived it.
  name = var.firewall_name

  dynamic "rule" {
    for_each = var.inbound_rules

    content {
      direction   = "in"
      protocol    = rule.value.proto
      port        = tostring(rule.value.port)
      source_ips  = ["0.0.0.0/0", "::/0"]
      description = rule.value.description
    }
  }

  labels = {
    project    = var.project_name
    managed_by = "terraform"
    spec       = "sec-006"
  }
}

# ---------------------------------------------------------------------------
# Attachment — the resource that makes this real.
#
# hcloud_firewall_attachment binds a firewall to server IDs the module does not
# own. Attaching via `hcloud_server.firewall_ids` instead would require managing
# the server, which is the thing this module exists to avoid.
# ---------------------------------------------------------------------------

resource "hcloud_firewall_attachment" "vps" {
  firewall_id = hcloud_firewall.vps.id
  server_ids  = [data.hcloud_server.vps.id]
}
