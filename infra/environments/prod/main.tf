# main.tf — the "root module". This is what you actually run
# (`terraform apply`) — it calls the reusable modules in /infra/modules and
# wires their outputs into each other's inputs.
#
# INTERVIEW POINT: why split into modules at all instead of one big file?
# - Reusability: same `acr` module could spin up a second registry for a
#   staging environment just by calling it again with different variables.
# - Blast radius: a mistake in the postgres module can't accidentally touch
#   the resource_group module's code.
# - Readability: this root file reads almost like a sentence — "make a
#   resource group, then an ACR inside it" — the messy provider-specific
#   detail is hidden one level down.

module "resource_group" {
  source = "../../modules/resource_group"

  name     = "rg-network-inventory-${var.environment}"
  location = var.location
  tags     = local.common_tags
}

module "acr" {
  source = "../../modules/acr"

  name                = var.acr_name
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  tags                = local.common_tags
}

locals {
  common_tags = {
    project     = "network-inventory"
    environment = var.environment
    managed_by  = "terraform"
  }
}
