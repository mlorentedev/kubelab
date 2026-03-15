output "vps_public_ip" {
  description = "Public IPv4 address of the VPS"
  value       = hcloud_server.vps.ipv4_address
}

output "vps_ipv6" {
  description = "Public IPv6 address of the VPS"
  value       = hcloud_server.vps.ipv6_address
}

output "vps_id" {
  description = "Hetzner server ID"
  value       = hcloud_server.vps.id
}

output "next_steps" {
  description = "Post-provision instructions"
  value       = <<-EOT
    VPS created: ${hcloud_server.vps.ipv4_address}

    Next steps:
    1. Update infra/config/values/common.yaml → networking.vps.public_ip
    2. Update Cloudflare DNS: cd ../dns && terraform apply
    3. Provision with Ansible: toolkit infra ansible run -p site -e prod
    4. Restore backups: toolkit infra ansible run -p restore -e prod
  EOT
}
