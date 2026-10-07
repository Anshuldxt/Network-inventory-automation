variable "environment" {
  type        = string
  default     = "prod"
  description = "Environment name — used in resource naming and tags"
}

variable "location" {
  type        = string
  default     = "centralindia"
  description = "Azure region. Pick one close to your users/VM — affects latency, not much affects cost."
}

variable "acr_name" {
  type        = string
  description = "Globally unique ACR name, e.g. networkinvacr2026"
}
