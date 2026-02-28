variable "cloudflare_api_token" {
  description = "Cloudflare API token with Zone:DNS:Edit and Zone:Zone:Read permissions"
  type        = string
  sensitive   = true
}

variable "zone_id_kubelab" {
  description = "Cloudflare Zone ID for kubelab.live"
  type        = string
}

variable "zone_id_mlorente" {
  description = "Cloudflare Zone ID for mlorente.dev"
  type        = string
}

variable "vps_ip" {
  description = "VPS public IP address (Hetzner)"
  type        = string
  default     = "162.55.57.175"
}

variable "dns_ttl" {
  description = "Default TTL for DNS records (1 = auto when proxied)"
  type        = number
  default     = 300
}
