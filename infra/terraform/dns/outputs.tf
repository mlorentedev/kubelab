output "kubelab_service_urls" {
  description = "All kubelab.live service URLs"
  value = {
    for name, svc in local.kubelab_services :
    name => "https://${name}.kubelab.live"
  }
}

output "mlorente_service_urls" {
  description = "All mlorente.dev service URLs"
  value = {
    for name, svc in local.mlorente_services :
    name => "https://${name}.mlorente.dev"
  }
}

output "kubelab_record_count" {
  description = "Total kubelab.live DNS records managed (root + www + services)"
  value       = 2 + length(local.kubelab_services)
}

output "mlorente_record_count" {
  description = "Total mlorente.dev DNS records managed (root + services)"
  value       = 1 + length(local.mlorente_services)
}
