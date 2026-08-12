terraform {
  required_version = ">= 1.5"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# -----------------------------------------------------------------------------
# Data sources — zone lookups
# -----------------------------------------------------------------------------

data "cloudflare_zone" "kubelab" {
  zone_id = var.zone_id_kubelab
}

data "cloudflare_zone" "mlorente" {
  zone_id = var.zone_id_mlorente
}

# -----------------------------------------------------------------------------
# Locals — parse services.json
# -----------------------------------------------------------------------------

locals {
  services = jsondecode(file("${path.module}/services.json"))

  # Node-name -> Tailscale IP, consumed by services.json's optional "target"
  # field. Mirrors networking.nodes.<name>.tailscale_ip in
  # infra/config/values/common.yaml — add an entry here only when a service
  # record actually targets that node (tailnet IPs are not stable across
  # re-enrollment, e.g. aws1 moved .4 -> .7, so this map is the one place
  # that needs updating, not services.json itself).
  node_tailscale_ips = {
    ace1 = "100.64.0.11"
  }

  # A service's record content: its target node's Tailscale IP if "target"
  # is set (an unresolvable target name is a hard error, not a silent
  # fallback to vps_ip), else the VPS public IP unchanged.
  services_resolved = [
    for svc in local.services : merge(svc, {
      content = try(svc.target, null) == null ? var.vps_ip : local.node_tailscale_ips[svc.target]
    })
  ]

  kubelab_services = {
    for svc in local.services_resolved :
    svc.name => svc
    if svc.zone == "kubelab" && contains(svc.environments, "prod")
  }

  mlorente_services = {
    for svc in local.services_resolved :
    svc.name => svc
    if svc.zone == "mlorente" && contains(svc.environments, "prod")
  }
}
