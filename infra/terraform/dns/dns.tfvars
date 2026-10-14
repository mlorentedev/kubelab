# Cloudflare Zone IDs — obtained via API (Phase 4)
zone_id_kubelab  = "a708cb04dd4572e76eb6da42cc09507d"
zone_id_mlorente = "4d0a0cf660577b845df5df982ad834a9"

# vps_ip is not here: the runner renders it from networking.vps.public_ip in
# common.yaml, so a rebuilt VPS is one edit, not two.

# TTL for non-proxied records (proxied records use TTL=auto/1)
dns_ttl = 300
