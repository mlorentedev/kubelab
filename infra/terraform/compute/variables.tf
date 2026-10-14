variable "hetzner_api_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "kubelab"
}

variable "server_name" {
  description = "VPS hostname"
  type        = string
  default     = "kubelab-vps"
}

variable "server_type" {
  description = "Hetzner server type (CAX11 = 2 vCPU ARM, 4GB RAM, 40GB)"
  type        = string
  default     = "cax11"
}

variable "server_image" {
  description = "OS image"
  type        = string
  default     = "ubuntu-24.04"
}

# The live CAX21 is in nbg1 per the Hetzner API (read 2026-09-25, #1847). The
# location forces replacement, so a default that differs from it would plan a
# new server on import. toolkit/features/platform_manifest.py mirrors this value.
variable "server_location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "nbg1"
}

variable "deploy_user" {
  description = "Non-root deploy user created by cloud-init"
  type        = string
  default     = "deployer"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key for deployer user"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "timezone" {
  description = "Server timezone"
  type        = string
  default     = "Europe/Madrid"
}
