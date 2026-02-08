 Development environment - DNS managed via /etc/hosts
 No cloud DNS configuration needed

terraform {
  required_version = ">= ."
}

 Placeholder for development environment
 All DNS is handled via local /etc/hosts entries
output "dev_info" {
  value = "Development DNS managed via /etc/hosts entries"
}
