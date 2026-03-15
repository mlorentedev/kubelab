# Hetzner VPS provisioning — recreate-only DR module
#
# This module is NOT imported against the current VPS.
# It defines "how to create a VPS from scratch" for disaster recovery.
#
# Usage:
#   cd infra/terraform/compute
#   terraform init
#   terraform plan -var-file=compute.tfvars
#   terraform apply -var-file=compute.tfvars
#
# After apply:
#   1. Update common.yaml with new VPS IP
#   2. Update Cloudflare DNS (terraform apply in dns/)
#   3. Run: toolkit infra ansible run -p site -e prod
#   4. Restore backups

terraform {
  required_version = ">= 1.5"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
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
# SSH Key — upload pub key to Hetzner
# ---------------------------------------------------------------------------

resource "hcloud_ssh_key" "deployer" {
  name       = "${var.project_name}-deployer"
  public_key = file(var.ssh_public_key_path)
}

# ---------------------------------------------------------------------------
# Firewall — restrict inbound traffic
# ---------------------------------------------------------------------------

resource "hcloud_firewall" "vps" {
  name = "${var.project_name}-vps"

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "SSH"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "HTTP"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "HTTPS"
  }

  rule {
    direction = "in"
    protocol  = "udp"
    port      = "3478"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "Headscale STUN"
  }

  rule {
    direction = "in"
    protocol  = "udp"
    port      = "41641"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "Tailscale"
  }
}

# ---------------------------------------------------------------------------
# VPS Server
# ---------------------------------------------------------------------------

resource "hcloud_server" "vps" {
  name        = var.server_name
  server_type = var.server_type
  image       = var.server_image
  location    = var.server_location
  ssh_keys    = [hcloud_ssh_key.deployer.id]

  firewall_ids = [hcloud_firewall.vps.id]

  user_data = templatefile("${path.module}/cloud-init.yml", {
    deploy_user    = var.deploy_user
    ssh_public_key = file(var.ssh_public_key_path)
    hostname       = var.server_name
    timezone       = var.timezone
  })

  labels = {
    project     = var.project_name
    environment = "prod"
    managed_by  = "terraform"
  }
}
