# The platform the app runs on: a resource group, a container registry and an AKS cluster.
# The app itself (Postgres, API, Dagster, UI) is not described here: it is Kubernetes
# manifests in infra/k8s, applied with kubectl. Terraform owns the cloud resources, Kubernetes
# owns what runs inside the cluster.

data "azurerm_client_config" "current" {}

locals {
  # Registry names are global across Azure and allow letters and digits only. A hash of the
  # subscription makes the name unique, and the same on every plan (unlike a random value).
  acr_name = "flightscanner${substr(md5(data.azurerm_client_config.current.subscription_id), 0, 6)}"

  tags = {
    app        = "flight-scanner"
    managed-by = "terraform"
  }
}

# A resource group is a folder for resources: deleting it deletes everything inside.
resource "azurerm_resource_group" "main" {
  name     = var.name
  location = var.location
  tags     = local.tags
}

# --- Container registry ------------------------------------------------------------------------
# Holds the two images (Python services and UI). infra/deploy.sh builds them in Azure with
# `az acr build`, so no local Docker is needed.
resource "azurerm_container_registry" "main" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  # No shared admin password. The cluster pulls with its own identity (role assignment below).
  admin_enabled = false
  tags          = local.tags
}

# --- Kubernetes cluster --------------------------------------------------------------------------
resource "azurerm_kubernetes_cluster" "main" {
  name                = var.name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  dns_prefix          = var.name
  # Free tier: no uptime SLA on the control plane (the API server you talk to with kubectl),
  # and no charge for it. You only pay for the node VMs, disks and logs.
  sku_tier = "Free"

  # Patch versions of Kubernetes and node OS images are applied automatically.
  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"

  # The node pool: the VMs that pods actually run on. AKS creates and manages them in a second
  # resource group, MC_<group>_<cluster>_<region>.
  default_node_pool {
    name       = "system"
    vm_size    = var.node_vm_size
    node_count = var.node_count
    # The default is a 128 GB premium disk; images and logs fit easily in half.
    os_disk_size_gb = 64
    # Changing the VM size replaces the pool. AKS first moves the pods to a temporary pool of
    # this name, so the change happens without downtime.
    temporary_name_for_rotation = "rotation"
    upgrade_settings {
      max_surge = "10%"
    }
  }

  # Manual: you size the node pool yourself (above). "Auto" would let AKS add and remove VMs
  # to fit the pods (Karpenter), which suits bigger, bursty clusters, not one small stack.
  node_provisioning_profile {
    mode = "Manual"
  }

  # The cluster's own Azure identity, used to create disks, load balancers and so on. No
  # passwords or client secrets to rotate.
  identity {
    type = "SystemAssigned"
  }

  network_profile {
    # Azure CNI overlay: pods get IPs from a private range that never touches the VNet.
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
  }

  # Container Insights: an agent on each node sends pod and node inventory, metrics and
  # container logs to Log Analytics (monitoring.tf). The alerts in alerts.tf query that data.
  oms_agent {
    log_analytics_workspace_id      = azurerm_log_analytics_workspace.main.id
    msi_auth_for_monitoring_enabled = true
  }

  tags = local.tags

  lifecycle {
    ignore_changes = [
      # The upgrade channel moves the version on its own; don't fight it on every plan.
      kubernetes_version,
    ]
  }
}

# Lets the nodes (their kubelet identity) pull images from the registry.
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
  skip_service_principal_aad_check = true
}
