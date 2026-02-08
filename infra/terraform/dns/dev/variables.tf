 Variables for dev environment

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "dns_ttl" {
  description = "DNS TTL in seconds"
  type        = number
  default     =
}
