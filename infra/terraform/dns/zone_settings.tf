# -----------------------------------------------------------------------------
# Zone settings — TLS, HSTS, OCSP (SEC-AUDIT-001, 002, 006)
#
# NOTE: API token needs Zone:Zone Settings:Edit permission.
# Update token in Cloudflare dashboard, then:
#   toolkit secrets set cloudflare.api_token <new-token> --env common
# -----------------------------------------------------------------------------

resource "cloudflare_zone_settings_override" "kubelab" {
  zone_id = var.zone_id_kubelab

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

resource "cloudflare_zone_settings_override" "mlorente" {
  zone_id = var.zone_id_mlorente

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
# CAA records — restrict certificate issuance (SEC-AUDIT-004)
#
# Allow: Let's Encrypt (Traefik ACME), DigiCert + Google (Cloudflare Universal SSL)
# -----------------------------------------------------------------------------

resource "cloudflare_record" "kubelab_caa_letsencrypt" {
  zone_id = var.zone_id_kubelab
  name    = "kubelab.live"
  type    = "CAA"
  ttl     = var.dns_ttl

  data {
    flags = "0"
    tag   = "issue"
    value = "letsencrypt.org"
  }
}

resource "cloudflare_record" "kubelab_caa_digicert" {
  zone_id = var.zone_id_kubelab
  name    = "kubelab.live"
  type    = "CAA"
  ttl     = var.dns_ttl

  data {
    flags = "0"
    tag   = "issue"
    value = "digicert.com"
  }
}

resource "cloudflare_record" "kubelab_caa_google" {
  zone_id = var.zone_id_kubelab
  name    = "kubelab.live"
  type    = "CAA"
  ttl     = var.dns_ttl

  data {
    flags = "0"
    tag   = "issue"
    value = "pki.goog"
  }
}

resource "cloudflare_record" "mlorente_caa_letsencrypt" {
  zone_id = var.zone_id_mlorente
  name    = "mlorente.dev"
  type    = "CAA"
  ttl     = var.dns_ttl

  data {
    flags = "0"
    tag   = "issue"
    value = "letsencrypt.org"
  }
}

resource "cloudflare_record" "mlorente_caa_digicert" {
  zone_id = var.zone_id_mlorente
  name    = "mlorente.dev"
  type    = "CAA"
  ttl     = var.dns_ttl

  data {
    flags = "0"
    tag   = "issue"
    value = "digicert.com"
  }
}

resource "cloudflare_record" "mlorente_caa_google" {
  zone_id = var.zone_id_mlorente
  name    = "mlorente.dev"
  type    = "CAA"
  ttl     = var.dns_ttl

  data {
    flags = "0"
    tag   = "issue"
    value = "pki.goog"
  }
}
