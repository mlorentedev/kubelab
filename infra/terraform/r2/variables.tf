variable "cloudflare_api_token" {
  description = "Cloudflare API token with R2 admin permission. Supplied as TF_VAR_cloudflare_api_token by the Makefile target, which reads it from SOPS into the child process's environment, never as an argument and never printed."
  type        = string
  sensitive   = true
}

variable "account_id" {
  description = "Cloudflare account id. Rendered from backup.r2.account_id."
  type        = string
}

variable "node_buckets" {
  description = "Node name to bucket name, one per backup.sources key. Rendered; never edited by hand."
  type        = map(string)

  validation {
    condition     = length(var.node_buckets) > 0
    error_message = "node_buckets is empty: render it with `toolkit infra terraform r2-tfvars`."
  }
}

variable "locked_prefixes" {
  description = "Repository prefixes the lock covers. Rendered from toolkit/features/r2_tfvars.py, where the reason for each is written."
  type        = list(string)

  validation {
    condition     = length(setintersection(var.locked_prefixes, ["locks/", "index/"])) == 0
    error_message = "locks/ and index/ are rewritten by every restic run; locking them fails every ship."
  }
}

variable "lock_max_age_seconds" {
  description = "R in seconds. Rendered from backup.r2.lock_retention_days."
  type        = number
}

variable "scratch" {
  description = "Create the scratch bucket and lock used to measure the lock's behaviour. Off by default; turned on only for the measurement."
  type        = bool
  default     = false
}

variable "scratch_bucket" {
  description = "Name of the scratch bucket. Kept in step with SCRATCH_BUCKET in toolkit/features/r2_tfvars.py, which refuses a node with this name."
  type        = string
  default     = "kubelab-backup-scratch"
}

variable "scratch_max_age_seconds" {
  description = "R for the scratch bucket: one day, the shortest the measurement needs."
  type        = number
  default     = 86400
}
