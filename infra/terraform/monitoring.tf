# Where monitoring data goes: one Log Analytics workspace, fed by Container Insights.
#
# Two kinds of data reach Azure Monitor from the cluster:
# - Platform metrics (node CPU, memory, disk) come from AKS itself, at no cost. The metric
#   alerts in alerts.tf use them.
# - Container Insights data (pod inventory and restarts, node conditions, volume usage, container
#   logs) is collected by an agent on each node and stored in this workspace, billed per GB
#   ingested. The log alerts in alerts.tf query it, and you can too: Azure portal, the cluster,
#   Monitoring > Logs.

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.name}-logs"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30 # the free retention period
  # Ingestion stops for the day when the cap is reached, so a log storm can't run up the bill.
  # Alerts that need fresh data stay quiet until midnight UTC, except "no data" (alerts.tf).
  daily_quota_gb = var.log_daily_quota_gb
  tags           = local.tags
}

# A data collection rule tells the Container Insights agent what to collect and where to send it.
# `az aks enable-addons` creates one by itself; with Terraform it is declared explicitly.
resource "azurerm_monitor_data_collection_rule" "container_insights" {
  name                = "MSCI-${var.location}-${var.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  destinations {
    log_analytics {
      name                  = "workspace"
      workspace_resource_id = azurerm_log_analytics_workspace.main.id
    }
  }

  data_flow {
    # The default group: KubePodInventory, KubeNodeInventory, KubeEvents, InsightsMetrics,
    # ContainerLogV2 and the rest.
    streams      = ["Microsoft-ContainerInsights-Group-Default"]
    destinations = ["workspace"]
  }

  data_sources {
    extension {
      name           = "ContainerInsightsExtension"
      extension_name = "ContainerInsights"
      streams        = ["Microsoft-ContainerInsights-Group-Default"]
      extension_json = jsonencode({
        dataCollectionSettings = {
          interval               = "5m" # every 5 minutes: enough for the alerts, a fifth of the volume
          namespaceFilteringMode = "Off"
          enableContainerLogV2   = true
        }
      })
    }
  }
}

resource "azurerm_monitor_data_collection_rule_association" "container_insights" {
  name                    = "ContainerInsightsExtension"
  target_resource_id      = azurerm_kubernetes_cluster.main.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.container_insights.id
}
