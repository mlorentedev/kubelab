# Variables for the GCP Argo CD hub (ADR-063).
# Non-secret defaults mirror networking.gcp in common.yaml — the SSOT.
# Secrets arrive via `toolkit infra terraform gcp-tfvars`, which renders from
# SOPS and is deleted after every use. Nothing sensitive is defaulted here.

variable "project_id" {
  description = "GCP project holding the hub. Must be linked to the billing account carrying the credit — see docs/runbooks/gcp-hub-bootstrap.md §1."
  type        = string
  default     = "kubelab-hub"
}

variable "region" {
  description = <<-EOT
    Compute region. Spot pricing on GCP is set per REGION and is uniform across
    the zones inside it — unlike AWS, where Spot is priced per AZ. Choosing a
    "cheap zone" therefore buys nothing here; the regional MIG picks whichever
    zone has capacity.
  EOT
  type        = string
  default     = "europe-west4"
}

variable "machine_type" {
  description = "e2-small: 2 vCPU / 2 GB. Equal-or-better than the t4g.small it replaces (0.5 vs 0.4 vCPU sustained, same RAM)."
  type        = string
  default     = "e2-small"
}

variable "image_family" {
  description = "Image family, resolved at instance-template creation."
  type        = string
  default     = "ubuntu-2404-lts-amd64"
}

variable "image_project" {
  description = "Project publishing the image family."
  type        = string
  default     = "ubuntu-os-cloud"
}

variable "disk_size_gb" {
  description = "Boot disk size. Mirrors networking.gcp.disk_size_gb; a test asserts they agree."
  type        = number
  default     = 12
}

variable "disk_type" {
  description = "pd-balanced carries a 3,000 IOPS per-instance floor independent of size, so 12 GB yields 3,072 — matching gp3 rather than regressing."
  type        = string
  default     = "pd-balanced"
}

variable "hostname" {
  description = "Instance hostname, and the Headscale given-name the fleet addresses it by."
  type        = string
  default     = "gcp1"
}

variable "deploy_user" {
  description = "Non-root user created by cloud-init. Mirrors networking.ssh_users.cloud."
  type        = string
  default     = "deployer"
}

variable "ssh_public_key_path" {
  description = "Public key authorised for the deploy user."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "timezone" {
  description = "Server timezone."
  type        = string
  default     = "Europe/Madrid"
}

variable "k3s_version" {
  description = "K3s version — must match the spokes."
  type        = string
  default     = "v1.34.4+k3s1"
}

variable "network_tier" {
  description = <<-EOT
    Network Service Tier for the instance's external address. Set EXPLICITLY
    rather than inherited: the API default is PREMIUM, and a cost-relevant
    default nobody chose is the defect this variable exists to remove.

    Why STANDARD for this node. The hub's egress is Argo CD polling and syncing
    two spokes -- the Hetzner VPS and the homelab -- continuously and forever.
    That is internet egress out of GCP. Reported allowances differ by roughly two
    orders of magnitude between the tiers (PREMIUM: ~1 GiB free per destination,
    then ~$0.12/GiB to Europe; STANDARD: a much larger monthly allowance across
    all regions, then a lower per-GiB rate), which against $0.43/mo of headroom
    is the difference between free and not.

    What STANDARD gives up is irrelevant here: global load balancing (unused,
    single region) and Google's backbone in favour of the public internet
    (Tailscale encrypts the traffic either way, and a 3-minute Argo CD reconcile
    does not notice the latency difference).

    UNVERIFIED AT TIME OF WRITING: the exact allowances above come from a
    research pass that could not be confirmed first-hand -- Google's network
    pricing page renders per-region figures via XHR and truncates for a plain
    fetch. `docs/runbooks/gcp-hub-bootstrap.md` §6 already requires confirming
    rates in the console at plan review; this is one of them. If STANDARD turns
    out not to help, change the value here and the reasoning stays correct.
  EOT
  type        = string
  default     = "STANDARD"

  validation {
    condition     = contains(["STANDARD", "PREMIUM"], var.network_tier)
    error_message = "network_tier must be STANDARD or PREMIUM."
  }
}

variable "headscale_url" {
  description = "Headscale login server. Public hostname, never the Tailscale address: bootstrap cannot depend on the VPN being up."
  type        = string
  default     = "https://vpn.kubelab.live"
}

variable "headscale_api_key_secret" {
  description = <<-EOT
    Secret Manager secret NAME (not the value) holding the Headscale API key.
    cloud-init reads it at boot through the instance's service account and uses
    it for two things: deleting the stale node so the given-name is reused, and
    MINTING ITS OWN short-lived pre-auth key.

    That is why no pre-auth key variable exists. aws1 baked a long-lived key into
    user_data, which was survivable only because user_data was rendered fresh at
    each deliberate replacement. A MIG fires cloud-init months after the template
    was written, so a stored key would expire and the VM would silently never
    join the mesh (GCP-001 finding F2).
  EOT
  type        = string
  default     = "headscale-api-key"
}
