# INTERVIEW POINT: Azure Container Registry (ACR) is a private Docker
# registry, same idea as Docker Hub but inside your Azure tenant with Azure
# AD-based access control. The pipeline builds an image, tags it with the
# git commit SHA, pushes it here — then Container Apps pulls that exact tag.
# Tagging by commit SHA (not "latest") is what makes deployments reproducible
# and rollback trivial: you just point Container Apps at yesterday's SHA.
#
# SKU choice: "Basic" is the cheapest tier (~$5/month) — fine for a small
# app with low pull volume. "Standard"/"Premium" add more storage, higher
# throughput, geo-replication — only worth it at real scale.

resource "azurerm_container_registry" "this" {
  name                = var.name # must be globally unique, alphanumeric only, no dashes
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Basic"

  # admin_enabled = false is the secure default — we don't want a shared
  # username/password. Instead, the pipeline and Container Apps both
  # authenticate via Azure AD managed identity (set up in a later step).
  admin_enabled = false

  tags = var.tags
}

output "login_server" {
  value = azurerm_container_registry.this.login_server
  # e.g. "networkinventoryacr.azurecr.io" — this is the prefix your
  # `docker build -t <login_server>/backend:<sha>` command will use.
}

output "id" {
  value = azurerm_container_registry.this.id
}
