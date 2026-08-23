# -----------------------------------------------------------------------------
# kubelab.live — root records
# -----------------------------------------------------------------------------

resource "cloudflare_record" "kubelab_root" {
  zone_id         = var.zone_id_kubelab
  name            = "kubelab.live"
  content         = var.vps_ip
  type            = "A"
  ttl             = 1
  proxied         = true
  allow_overwrite = true
}

resource "cloudflare_record" "kubelab_www" {
  zone_id         = var.zone_id_kubelab
  name            = "www"
  content         = "kubelab.live"
  type            = "CNAME"
  ttl             = 1
  proxied         = true
  allow_overwrite = true
}

# -----------------------------------------------------------------------------
# kubelab.live — service records from services.json
# -----------------------------------------------------------------------------

resource "cloudflare_record" "kubelab_svc" {
  for_each = local.kubelab_services

  zone_id         = var.zone_id_kubelab
  name            = each.value.name
  content         = each.value.content
  type            = "A"
  ttl             = each.value.proxied ? 1 : var.dns_ttl
  proxied         = each.value.proxied
  allow_overwrite = true
}
