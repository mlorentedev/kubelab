# Variables for AWS Argo CD Hub
# Defaults mirror common.yaml; the secrets arrive as TF_VAR_* from SOPS
# through the runner (`make tf-aws-plan`), never as a tfvars file.

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-central-1"
}

variable "aws_access_key_id" {
  description = "IAM access key of kubelab-terraform, from SOPS aws.access_key_id"
  type        = string
  sensitive   = true
}

variable "aws_secret_access_key" {
  description = "IAM secret key of kubelab-terraform, from SOPS aws.secret_access_key"
  type        = string
  sensitive   = true
}

variable "project_name" {
  description = "Project name for resource naming and tags"
  type        = string
  default     = "kubelab"
}

variable "instance_type" {
  description = "EC2 instance type (ARM64 Graviton)"
  type        = string
  default     = "t4g.small"
}

variable "ami_name_filter" {
  description = "AMI name filter for Ubuntu ARM64"
  type        = string
  default     = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"
}

variable "ebs_size_gb" {
  description = <<-EOT
    Root EBS volume size in GB. Online resize: terraform apply triggers
    ec2:ModifyVolume (no instance replacement). After resize, reboot the
    instance — cloud-init cc_growpart + cc_resizefs auto-expand the
    partition + ext4 filesystem on next boot. See 40-runbooks/aws1-ebs-resize.md.
  EOT
  type        = number
  default     = 12
}

variable "hostname" {
  description = "Instance hostname (also used as Tailscale node name)"
  type        = string
  default     = "aws1"
}

variable "deploy_user" {
  description = "Non-root user created by cloud-init"
  type        = string
  default     = "deployer"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "timezone" {
  description = "Server timezone"
  type        = string
  default     = "Europe/Madrid"
}

variable "k3s_version" {
  description = "K3s version (match spoke versions)"
  type        = string
  default     = "v1.34.4+k3s1"
}

variable "headscale_url" {
  description = "Headscale login server URL"
  type        = string
  default     = "https://vpn.kubelab.live"
}

variable "tailscale_authkey" {
  description = "Headscale pre-auth key for automatic registration. Empty in a plan; the runner refuses an apply without it."
  type        = string
  sensitive   = true
  default     = ""
}

variable "headscale_api_key" {
  description = "Headscale management API key for node cleanup on recreate. Empty in a plan; the runner refuses an apply without it."
  type        = string
  sensitive   = true
  default     = ""
}
