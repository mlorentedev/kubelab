# Zones are looked up by name from zones.json (#2460), so no zone ID is kept here.
# vps_ip is not here: the runner renders it from networking.vps.public_ip in
# common.yaml, so a rebuilt VPS is one edit, not two.

# TTL for non-proxied records (proxied records use TTL=auto/1)
dns_ttl = 300
