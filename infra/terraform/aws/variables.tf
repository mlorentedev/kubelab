# Variables for AWS Argo CD Hub
# Values come from aws.tfvars (mirrors common.yaml SSOT)

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-central-1"
}

variable "aws_profile" {
  description = "AWS CLI profile name"
  type        = string
  default     = "kubelab"
}

variable "project_name" {
  description = "Project name for resource naming and tags"
  type        = string
  default     = "kubelab"
}

variable "instance_type" {
  description = "EC2 instance type (ARM64 Graviton)"
  type        = string
  default     = "t4g.micro"
}

variable "ami_name_filter" {
  description = "AMI name filter for Ubuntu ARM64"
  type        = string
  default     = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"
}

variable "ebs_size_gb" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 8
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
  description = "Headscale pre-auth key for automatic registration"
  type        = string
  sensitive   = true
}
