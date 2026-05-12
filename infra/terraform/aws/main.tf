# AWS Management Plane — Argo CD Hub (ADR-023 Phase 3)
#
# Stateless K3s + Argo CD on Spot instance. VPN-only access via Headscale.
# No Elastic IP — temporary public IP used only for Tailscale bootstrap.
# Instance is disposable: destroy + apply → cloud-init → K3s → Argo resyncs.
#
# Usage:
#   cd infra/terraform/aws
#   terraform init
#   terraform plan -var-file=aws.tfvars
#   terraform apply -var-file=aws.tfvars
#
# After apply:
#   1. Wait ~5 min for cloud-init (K3s + Tailscale registration)
#   2. Verify MagicDNS: dig aws1.kubelab.internal (should resolve to new Tailscale IP)
#   3. Fetch kubeconfig: make fetch-kubeconfig-hub
#   4. Install Argo CD: make deploy-argocd

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = [var.ami_name_filter]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ---------------------------------------------------------------------------
# Security Group
# ---------------------------------------------------------------------------

resource "aws_security_group" "argo_hub" {
  name        = "${var.project_name}-argo-hub"
  description = "Argo CD hub - SSH bootstrap + Tailscale UDP"
  vpc_id      = data.aws_vpc.default.id

  # SSH — only for initial bootstrap, then use Tailscale
  ingress {
    description = "SSH bootstrap"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Tailscale WireGuard
  ingress {
    description = "Tailscale UDP"
    from_port   = 41641
    to_port     = 41641
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # All outbound (K3s pulls, GitHub polling, Tailscale)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-argo-hub"
    Project     = var.project_name
    Environment = "hub"
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# SSH Key
# ---------------------------------------------------------------------------

resource "aws_key_pair" "deployer" {
  key_name   = "${var.project_name}-deployer"
  public_key = file(var.ssh_public_key_path)

  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Spot Instance (Argo CD Hub)
# ---------------------------------------------------------------------------
#
# Uses aws_instance + instance_market_options (modern Spot API via
# RunInstances) instead of the legacy aws_spot_instance_request resource.
# The legacy resource does NOT propagate root_block_device updates to the
# underlying EBS volume (provider issue hashicorp/terraform-provider-aws#4252),
# turning every EBS resize into a destroy+recreate. aws_instance handles
# root_block_device updates correctly via ec2:ModifyVolume.

resource "aws_instance" "argo_hub" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.deployer.key_name
  vpc_security_group_ids = [aws_security_group.argo_hub.id]
  subnet_id              = data.aws_subnets.default.ids[0]

  # Spot config — modern API, mirrors the previous persistent + stop behaviour.
  instance_market_options {
    market_type = "spot"
    spot_options {
      spot_instance_type             = "persistent"
      instance_interruption_behavior = "stop"
    }
  }

  # EBS root volume
  root_block_device {
    volume_size           = var.ebs_size_gb
    volume_type           = "gp3"
    delete_on_termination = true
  }

  # cloud-init bootstrap
  user_data = templatefile("${path.module}/cloud-init.yml", {
    hostname           = var.hostname
    deploy_user        = var.deploy_user
    ssh_public_key     = file(var.ssh_public_key_path)
    timezone           = var.timezone
    k3s_version        = var.k3s_version
    headscale_url      = var.headscale_url
    tailscale_authkey  = var.tailscale_authkey
    tailscale_hostname = var.hostname
    headscale_api_key  = var.headscale_api_key
  })

  tags = {
    Name        = "${var.project_name}-${var.hostname}"
    Project     = var.project_name
    Environment = "hub"
    ManagedBy   = "terraform"
    Role        = "argo-cd"
  }

  # Cattle pattern (ADR-028): replacements are deliberate, not side effects.
  # data.aws_ami.ubuntu uses most_recent=true → fresh Canonical AMIs land every
  # plan, which would otherwise destroy+recreate the instance on routine ops
  # like an EBS resize. user_data is ignored for the same reason: SOPS
  # rotations (tailscale_authkey, headscale_api_key) must not force
  # replacement. To re-roll the instance with a fresh AMI/user_data:
  # `make aws1-replace`.
  lifecycle {
    ignore_changes = [ami, user_data]
  }
}
