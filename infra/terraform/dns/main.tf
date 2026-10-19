terraform {
  required_version = ">= 1.10"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }

  # Shared settings: ../backend.s3.tfbackend, passed by the runner (TF-007).
  backend "s3" {
    key = "dns/terraform.tfstate"
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# -----------------------------------------------------------------------------
# Data sources — one lookup per zone in zones.json, by name
# -----------------------------------------------------------------------------

data "cloudflare_zone" "zone" {
  for_each = local.zones
  name     = each.key
}

# -----------------------------------------------------------------------------
# Locals — parse services.json
# -----------------------------------------------------------------------------

locals {
  # Every Cloudflare zone this root manages, keyed by apex (#2460). Adding a
  # zone is one entry here: its settings, CAA set and apex records follow.
  zones = jsondecode(file("${path.module}/zones.json"))

  # services.json names a zone by its short key; an unknown key is a hard error.
  zone_apex = { for apex, z in local.zones : z.key => apex }

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

  # One map of every record, keyed by FQDN: each zone's own records, then the
  # prod services. Every element is built with the same attributes so the
  # two lists unify into one type.
  zone_records = flatten([
    for apex, z in local.zones : [
      for r in z.records : {
        apex    = apex
        name    = r.name
        type    = r.type
        content = try(r.content, var.vps_ip)
        proxied = r.proxied
      }
    ]
  ])

  service_records = [
    for svc in local.services_resolved : {
      apex    = local.zone_apex[svc.zone]
      name    = svc.name
      type    = "A"
      content = svc.content
      proxied = svc.proxied
    }
    if contains(svc.environments, "prod")
  ]

  records = {
    for r in concat(local.zone_records, local.service_records) :
    (r.name == r.apex ? r.apex : "${r.name}.${r.apex}") => r
  }
}
