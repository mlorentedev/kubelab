output "spot_request_id" {
  description = "Spot instance request ID"
  value       = aws_spot_instance_request.argo_hub.id
}

output "public_ip" {
  description = "Public IP (temporary — only for SSH bootstrap)"
  value       = aws_spot_instance_request.argo_hub.public_ip
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_spot_instance_request.argo_hub.spot_instance_id
}

output "ami_id" {
  description = "AMI used for the instance"
  value       = data.aws_ami.ubuntu.id
}

output "ssh_command" {
  description = "SSH command for bootstrap access"
  value       = "ssh ${var.deploy_user}@${aws_spot_instance_request.argo_hub.public_ip}"
}

output "next_steps" {
  description = "Post-apply instructions"
  value       = <<-EOT
    1. Wait ~5 min for cloud-init to complete
    2. SSH: ssh ${var.deploy_user}@${aws_spot_instance_request.argo_hub.public_ip}
    3. Verify Tailscale: tailscale status (should show as aws1)
    4. Verify MagicDNS: dig aws1.kubelab.internal (should resolve to Tailscale IP)
    5. Fetch kubeconfig: make fetch-kubeconfig-hub
    6. Install Argo CD: make deploy-argocd
  EOT
}
