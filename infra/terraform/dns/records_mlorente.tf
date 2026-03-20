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

# staging.mlorente.dev: resolved via Headscale split DNS → RPi4 CoreDNS → ace1
# No Cloudflare record needed — staging DNS is VPN-only

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
