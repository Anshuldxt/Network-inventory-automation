# providers.tf — this file tells Terraform WHICH cloud it's talking to and HOW.
#
# INTERVIEW POINT: "providers" are plugins. `azurerm` is the official Azure
# provider — it translates Terraform's HCL into actual Azure Resource Manager
# (ARM) API calls. Pinning versions here (~> 3.x) means "any 3.x version" —
# this avoids a surprise breaking change from a major version bump silently
# breaking your pipeline six months from now.

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }

  # INTERVIEW POINT: remote state.
  # By default, Terraform stores its "state" (a JSON file mapping your .tf
  # code to real Azure resource IDs) as a plain file on whatever machine ran
  # `terraform apply`. That's fine solo, but breaks the moment:
  #   1. A pipeline agent runs it (a fresh VM every time — no local file to find)
  #   2. Two people/pipelines might run apply at the same time (need locking)
  #
  # The fix: store state in an Azure Storage Account blob container instead.
  # This block is deliberately left with placeholder values — you create this
  # storage account ONCE, by hand or via a tiny bootstrap script, BEFORE the
  # pipeline ever runs (a classic chicken-and-egg: Terraform can't create the
  # place it stores its own state on the very first run). It's intentionally
  # not overridable via variables — Terraform requires backend config to be
  # static, resolved before any variables are read.
  backend "azurerm" {
    resource_group_name  = "rg-tfstate"
    storage_account_name = "sttfstatenetworkinv"   # must be globally unique — change this
    container_name       = "tfstate"
    key                  = "prod.terraform.tfstate"
  }
}

provider "azurerm" {
  # `features {}` is required even when empty — it's how the provider knows
  # you're using the v3 feature-flag style rather than legacy behaviour.
  features {}
}
