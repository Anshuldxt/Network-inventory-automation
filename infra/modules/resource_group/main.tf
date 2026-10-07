# INTERVIEW POINT: an Azure "resource group" is a logical folder — every
# resource (database, registry, container app...) must live inside exactly
# one resource group. It has no cost by itself; it exists for lifecycle and
# access-control grouping. Deleting the RG deletes everything inside it —
# handy for tearing down a whole environment in one command.

resource "azurerm_resource_group" "this" {
  name     = var.name
  location = var.location
  tags     = var.tags
}

output "name" {
  value = azurerm_resource_group.this.name
}

output "location" {
  value = azurerm_resource_group.this.location
}

output "id" {
  value = azurerm_resource_group.this.id
}
