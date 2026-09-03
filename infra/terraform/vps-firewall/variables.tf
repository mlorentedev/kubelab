variable "hetzner_api_token" {
  description = "Hetzner Cloud API token. Supplied as TF_VAR_hetzner_api_token by the Makefile target, which reads it from SOPS into the child process's environment — never as a CLI argument and never printed."
  type        = string
  sensitive   = true
}

variable "server_name" {
  description = "Name of the ALREADY-RUNNING VPS in the Hetzner account. Looked up via a data source; this module never manages the server."
  type        = string
  default     = "kubelab-vps"
}

variable "project_name" {
  description = "Project label applied to the firewall"
  type        = string
  default     = "kubelab"
}

variable "firewall_name" {
  description = "Firewall name. Deliberately distinct from the DR module's ${project_name}-vps so a disaster-recovery recreate cannot collide with a firewall that survived the disaster."
  type        = string
  default     = "kubelab-vps-inbound"
}

variable "inbound_rules" {
  description = "Inbound allow-list. Generated from networking.firewall.vps_inbound in common.yaml by `toolkit infra terraform vps-firewall-tfvars` — do not hand-edit the tfvars, edit the SSOT."
  type = list(object({
    port        = number
    proto       = string
    description = string
  }))

  # No default, on purpose. An empty or defaulted list would render a firewall
  # that allows nothing and attaches anyway — locking every operator out of a
  # machine whose recovery path (Headscale) is on the same host. Terraform must
  # refuse to plan rather than silently produce that.

  validation {
    condition     = length(var.inbound_rules) > 0
    error_message = "inbound_rules is empty. An attached firewall with no rules drops ALL inbound traffic, including SSH. Run `toolkit infra terraform vps-firewall-tfvars` to render it from common.yaml."
  }

  validation {
    condition     = contains([for r in var.inbound_rules : "${r.port}/${r.proto}"], "22/tcp")
    error_message = "22/tcp is absent from inbound_rules. Applying this would lock every operator out of the VPS over SSH, and Headscale runs on the same host, so the VPN is not a way back in. Hetzner's web console is the only remaining path. Add it to networking.firewall.vps_inbound in common.yaml."
  }

  validation {
    condition     = alltrue([for r in var.inbound_rules : contains(["tcp", "udp"], r.proto)])
    error_message = "Every rule's proto must be tcp or udp. Hetzner cloud firewalls also accept icmp/gre/esp, but those take no port and this module renders one for every rule."
  }
}
