# Bootstrap: the storage account that holds Terraform's state for ../ (the real infrastructure).
#
# Terraform records everything it created in a *state file*. Kept on a laptop, that file is easy
# to lose, and a lost state means Terraform no longer knows it owns your cluster. So the main
# configuration keeps its state in Azure Blob Storage instead. That storage account has to exist
# before the main configuration can start, so this small configuration creates it, using local
# state (bootstrap/terraform.tfstate, git-ignored). It is run once and rarely touched again.

terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.13"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

# The subscription comes from ARM_SUBSCRIPTION_ID, credentials from `az login`.
provider "azurerm" {
  features {}
  storage_use_azuread = true
}

variable "location" {
  description = "Azure region for the state storage."
  type        = string
  default     = "swedencentral"
}

data "azurerm_client_config" "current" {}

# Storage account names are global across Azure, so a random suffix avoids collisions.
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "state" {
  name     = "flight-scanner-tfstate"
  location = var.location
}

resource "azurerm_storage_account" "state" {
  name                            = "fstfstate${random_string.suffix.result}"
  resource_group_name             = azurerm_resource_group.state.name
  location                        = azurerm_resource_group.state.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  # No access keys: only Entra ID (your `az login`) can read the state, which holds secrets.
  shared_access_key_enabled = false

  blob_properties {
    # Every state write keeps the previous version, so a bad apply can be rolled back by hand.
    versioning_enabled = true
  }
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

# Without access keys, you need a data-plane role to read and write blobs.
resource "azurerm_role_assignment" "state_writer" {
  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

output "backend_config" {
  description = "Paste into ../backend.hcl."
  value       = <<-EOT
    resource_group_name  = "${azurerm_resource_group.state.name}"
    storage_account_name = "${azurerm_storage_account.state.name}"
    container_name       = "${azurerm_storage_container.state.name}"
    key                  = "flight-scanner.tfstate"
    use_azuread_auth     = true
  EOT
}
