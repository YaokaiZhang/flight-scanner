terraform {
  required_version = ">= 1.9"

  # Providers are plugins that translate HCL into API calls. Pinning "~> 5.13" allows 5.x
  # upgrades from 5.13 on, but never 6.0, whose breaking changes would need a deliberate upgrade.
  # The exact versions in use are recorded in .terraform.lock.hcl, which is committed.
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.13"
    }
  }

  # State lives in Azure Blob Storage, created by bootstrap/. The settings are left out here and
  # come from backend.hcl (`terraform init -backend-config=backend.hcl`), so that no account
  # names are hard-coded. The backend also locks the state during a plan or apply, so two
  # applies can never run at once.
  backend "azurerm" {}
}

# The subscription comes from ARM_SUBSCRIPTION_ID, credentials from `az login`.
provider "azurerm" {
  features {
    resource_group {
      # `terraform destroy` deletes the group even if Azure added resources to it by itself
      # (AKS and Container Insights do).
      prevent_deletion_if_contains_resources = false
    }
  }
}
