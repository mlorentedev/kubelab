# -----------------------------------------------------------------------------
# Zone settings — TLS, HSTS, OCSP (SEC-AUDIT-001, 002, 006), one per zone
#
# NOTE: API token needs Zone:Zone Settings:Edit permission.
# Update token in Cloudflare dashboard, then:
#   toolkit secrets set cloudflare.api_token <new-token> --env common
# -----------------------------------------------------------------------------

resource "cloudflare_zone_settings_override" "zone" {
  for_each = local.zones

  zone_id = data.cloudflare_zone.zone[each.key].id

  settings {
    min_tls_version  = "1.2"
    ssl              = "strict"
    always_use_https = "on"

    security_header {
      enabled            = true
      max_age            = 31536000
      include_subdomains = true
      preload            = true
      nosniff            = true
    }
  }
}

# -----------------------------------------------------------------------------
# CAA records — restrict certificate issuance (SEC-AUDIT-004), per zone
#
# Allow: Let's Encrypt (Traefik ACME), DigiCert + Google (Cloudflare Universal SSL)
# -----------------------------------------------------------------------------

locals {
  caa_issuers = ["letsencrypt.org", "digicert.com", "pki.goog"]

  caa = {
    for pair in setproduct(keys(local.zones), local.caa_issuers) :
    "${pair[0]}/${pair[1]}" => { apex = pair[0], issuer = pair[1] }
  }
}

resource "cloudflare_record" "caa" {
  for_each = local.caa

  zone_id = data.cloudflare_zone.zone[each.value.apex].id
  name    = each.value.apex
  type    = "CAA"
  ttl     = var.dns_ttl

  data {
    flags = "0"
    tag   = "issue"
    value = each.value.issuer
  }
  timeouts {
    create = "2m"
    update = "2m"
  }
}
