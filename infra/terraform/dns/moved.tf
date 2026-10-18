# State moves from the per-zone resources to the zones map (#2460). Each block
# maps an address that existed in state on 2026-10-18 (`make tf-state-list
# ROOT=dns`); they can go once every checkout has planned past this change.

moved {
  from = cloudflare_record.kubelab_root
  to   = cloudflare_record.record["kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_www
  to   = cloudflare_record.record["www.kubelab.live"]
}

moved {
  from = cloudflare_record.mlorente_root
  to   = cloudflare_record.record["mlorente.dev"]
}

moved {
  from = cloudflare_record.kubelab_svc["api"]
  to   = cloudflare_record.record["api.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["status"]
  to   = cloudflare_record.record["status.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["auth"]
  to   = cloudflare_record.record["auth.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["vpn"]
  to   = cloudflare_record.record["vpn.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["grafana"]
  to   = cloudflare_record.record["grafana.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["gitea"]
  to   = cloudflare_record.record["gitea.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["n8n"]
  to   = cloudflare_record.record["n8n.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["pr-agent"]
  to   = cloudflare_record.record["pr-agent.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["traefik"]
  to   = cloudflare_record.record["traefik.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["argo"]
  to   = cloudflare_record.record["argo.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["pihole"]
  to   = cloudflare_record.record["pihole.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["tasks"]
  to   = cloudflare_record.record["tasks.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["chat"]
  to   = cloudflare_record.record["chat.kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_svc["assets"]
  to   = cloudflare_record.record["assets.kubelab.live"]
}

moved {
  from = cloudflare_zone_settings_override.kubelab
  to   = cloudflare_zone_settings_override.zone["kubelab.live"]
}

moved {
  from = cloudflare_record.kubelab_caa_letsencrypt
  to   = cloudflare_record.caa["kubelab.live/letsencrypt.org"]
}

moved {
  from = cloudflare_record.kubelab_caa_digicert
  to   = cloudflare_record.caa["kubelab.live/digicert.com"]
}

moved {
  from = cloudflare_record.kubelab_caa_google
  to   = cloudflare_record.caa["kubelab.live/pki.goog"]
}

moved {
  from = cloudflare_zone_settings_override.mlorente
  to   = cloudflare_zone_settings_override.zone["mlorente.dev"]
}

moved {
  from = cloudflare_record.mlorente_caa_letsencrypt
  to   = cloudflare_record.caa["mlorente.dev/letsencrypt.org"]
}

moved {
  from = cloudflare_record.mlorente_caa_digicert
  to   = cloudflare_record.caa["mlorente.dev/digicert.com"]
}

moved {
  from = cloudflare_record.mlorente_caa_google
  to   = cloudflare_record.caa["mlorente.dev/pki.goog"]
}
