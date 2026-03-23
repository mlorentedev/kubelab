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
    3. Check Tailscale: tailscale status
    4. Get Tailscale IP: tailscale ip -4
    5. Update common.yaml networking.aws.tailscale_ip
    6. Fetch kubeconfig via Tailscale IP (not public IP)
  EOT
}
