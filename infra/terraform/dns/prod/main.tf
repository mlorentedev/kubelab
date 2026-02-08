terraform {
  required_providers {
    hetznerdns = {
      source  = "timohirt/hetznerdns"
      version = "~> ."
    }
  }
}

provider "hetznerdns" {
  apitoken = var.hetzner_token
}

variable "zone_id" {}
variable "vps_ip" {}

locals {
  services = [for s in jsondecode(file("${path.module}/../services.json")).services : s.name]
}

resource "hetznerdns_record" "records" {
  for_each = toset(local.services)
  zone_id  = var.zone_id
  name     = each.key
  type     = "A"
  value    = var.vps_ip
  ttl      =
}
