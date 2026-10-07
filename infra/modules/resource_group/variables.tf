variable "name" {
  type        = string
  description = "Resource group name, e.g. rg-network-inventory-prod"
}

variable "location" {
  type        = string
  description = "Azure region, e.g. centralindia, eastus"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags applied to the resource group (cost tracking, ownership)"
}
