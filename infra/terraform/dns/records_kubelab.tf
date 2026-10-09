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
  # The provider's default is 30s, and a create that outlives it can still land:
  # Terraform then taints a record that exists (lesson-543, TF-013). Every
  # cloudflare_record in this root carries the same block.
  timeouts {
    create = "2m"
    update = "2m"
  }
}

resource "cloudflare_record" "kubelab_www" {
  zone_id         = var.zone_id_kubelab
  name            = "www"
  content         = "kubelab.live"
  type            = "CNAME"
  ttl             = 1
  proxied         = true
  allow_overwrite = true
  timeouts {
    create = "2m"
    update = "2m"
  }
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
  timeouts {
    create = "2m"
    update = "2m"
  }
}
