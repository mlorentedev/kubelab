output "instance_group" {
  description = "Self-link of the regional MIG managing the hub."
  value       = google_compute_region_instance_group_manager.hub.self_link
}

output "service_account_email" {
  description = "Service account the instance runs as; holds secretAccessor on named secrets only."
  value       = google_service_account.hub.email
}

output "magicdns_name" {
  description = <<-EOT
    The hub's stable identity. Deliberately NOT an IP: the Tailscale address
    rotates on every re-registration, and under a MIG every preemption
    re-registers. Everything downstream (Ansible inventory, kubeconfig server
    URL, the prod Argo CD EndpointSlice) resolves this name.
  EOT
  value       = "${var.hostname}.kubelab.internal"
}

output "next_steps" {
  description = "Post-apply sequence, runnable as written."
  value       = <<-EOT
    1. make wait-node-ready NODE=${var.hostname} ENV=hub   # sshd AND cloud-init
    2. dig +short ${var.hostname}.kubelab.internal          # assert the given-name resolved
    3. make provision NODE=${var.hostname} ENV=hub          # twice; second must be changed=0
    4. make maintain-notify-test NODE=${var.hostname} ENV=hub

    Lifecycle afterwards, no terraform needed:
      make gcp1-status                 # describe the MIG
      make gcp1-stop / gcp1-start      # target_size 0 / 1
      make gcp1-replace                # a preemption on demand, then reprovision
  EOT
}
