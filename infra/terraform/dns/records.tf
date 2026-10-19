# -----------------------------------------------------------------------------
# Every A/CNAME record: each zone's own (zones.json) and the services
# (services.json), one resource keyed by FQDN.
# -----------------------------------------------------------------------------

resource "cloudflare_record" "record" {
  for_each = local.records

  zone_id         = data.cloudflare_zone.zone[each.value.apex].id
  name            = each.value.name
  content         = each.value.content
  type            = each.value.type
  ttl             = each.value.proxied ? 1 : var.dns_ttl
  proxied         = each.value.proxied
  allow_overwrite = true
  # The provider's default is 30s, and a create that outlives it can still land:
  # Terraform then taints a record that exists (lesson-543, TF-013). Every
  # cloudflare_record in this root carries the same block.
  timeouts {
    create = "2m"
    update = "2m"
  }
}
