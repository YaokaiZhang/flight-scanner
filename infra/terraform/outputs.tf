# Values printed after `terraform apply`, and readable later with `terraform output -raw <name>`.
# infra/deploy.sh reads them, so the script never hard-codes a resource name.

output "resource_group" {
  value = azurerm_resource_group.main.name
}

output "cluster_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "acr_name" {
  value = azurerm_container_registry.main.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "app_namespace" {
  value = var.app_namespace
}

output "get_credentials" {
  description = "Writes the cluster's credentials to ~/.kube/config so kubectl can reach it."
  value       = "az aks get-credentials --resource-group ${azurerm_resource_group.main.name} --name ${azurerm_kubernetes_cluster.main.name}"
}
