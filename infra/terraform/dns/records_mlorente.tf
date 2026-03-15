# -----------------------------------------------------------------------------
# mlorente.dev — root record
# -----------------------------------------------------------------------------

resource "cloudflare_record" "mlorente_root" {
  zone_id = var.zone_id_mlorente
  name    = "mlorente.dev"
  content = var.vps_ip
  type    = "A"
  ttl     = var.dns_ttl
  proxied = false
}

# -----------------------------------------------------------------------------
# mlorente.dev — staging (VPN-only, Tailscale IP → K3s server)
# -----------------------------------------------------------------------------

resource "cloudflare_record" "mlorente_staging" {
  zone_id = var.zone_id_mlorente
  name    = "staging"
  content = "100.64.0.4"  # networking.nodes.k3s_server.tailscale_ip
  type    = "A"
  ttl     = var.dns_ttl
  proxied = false  # Tailscale IP, not routable from internet
}

# -----------------------------------------------------------------------------
# mlorente.dev — service records from services.json
# -----------------------------------------------------------------------------

resource "cloudflare_record" "mlorente_svc" {
  for_each = local.mlorente_services

  zone_id = var.zone_id_mlorente
  name    = each.value.name
  content = var.vps_ip
  type    = "A"
  ttl     = each.value.proxied ? 1 : var.dns_ttl
  proxied = each.value.proxied
}
