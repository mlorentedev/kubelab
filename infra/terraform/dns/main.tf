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

  kubelab_services = {
    for svc in local.services :
    svc.name => svc
    if svc.zone == "kubelab" && contains(svc.environments, "prod")
  }

  mlorente_services = {
    for svc in local.services :
    svc.name => svc
    if svc.zone == "mlorente" && contains(svc.environments, "prod")
  }
}
