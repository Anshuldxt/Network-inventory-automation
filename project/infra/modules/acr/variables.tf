variable "name" {
  type        = string
  description = "Registry name — globally unique, alphanumeric only (no dashes/underscores)"
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
