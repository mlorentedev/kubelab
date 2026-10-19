output "record_urls" {
  description = "Every managed A/CNAME record, by FQDN"
  value       = { for fqdn, r in local.records : fqdn => "https://${fqdn}" }
}

output "record_count" {
  description = "Total A/CNAME records managed (zone records + services)"
  value       = length(local.records)
}
