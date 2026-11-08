# Cloud-side alerts. They watch the platform: nodes, pods, volumes and spend. The app keeps
# watching itself as before: failed Dagster runs and stalled sources go to your Telegram or
# email notifiers (README, "Pipeline monitoring"). Together they cover "the pipeline is unhappy"
# and "the machine under it is unhappy".

# An action group is who gets told, and how. Every alert below points at it.
resource "azurerm_monitor_action_group" "owner" {
  name                = "${var.name}-owner"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "fs-owner" # at most 12 characters; shown in SMS and email subjects
  tags                = local.tags

  email_receiver {
    name                    = "owner"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

# --- Metric alerts: AKS platform metrics, free, evaluated every minute ---------------------------
locals {
  metric_alerts = {
    node-cpu = {
      description = "Node CPU above 85% for 15 minutes. Scans will slow down; consider a bigger node_vm_size."
      metric      = "node_cpu_usage_percentage"
      threshold   = 85
    }
    node-memory = {
      description = "Node memory working set above 85% for 15 minutes. Pods risk being OOM-killed or evicted."
      metric      = "node_memory_working_set_percentage"
      threshold   = 85
    }
    node-disk = {
      description = "Node OS disk above 85%. Usually old container images; the kubelet cleans them up at 85%, then evicts pods."
      metric      = "node_disk_usage_percentage"
      threshold   = 85
    }
  }
}

# for_each makes one resource per map entry, addressed as
# azurerm_monitor_metric_alert.node["node-cpu"] and so on in plans and state.
resource "azurerm_monitor_metric_alert" "node" {
  for_each = local.metric_alerts

  name                = "${var.name}-${each.key}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_kubernetes_cluster.main.id]
  description         = each.value.description
  severity            = 2 # 0 critical ... 4 verbose
  frequency           = "PT5M"
  window_size         = "PT15M" # ISO 8601 durations: PT15M = 15 minutes
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.ContainerService/managedClusters"
    metric_name      = each.value.metric
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = each.value.threshold
  }

  action {
    action_group_id = azurerm_monitor_action_group.owner.id
  }
}

# --- Log alerts: KQL queries over the Container Insights data in Log Analytics ------------------
# Each query returns the rows that are a problem. The alert fires when it returns any row
# (or, for "no data", when it returns none). Run a query yourself in the portal under the
# cluster's Monitoring > Logs to see what it sees.
locals {
  ns = var.app_namespace

  log_alerts = {
    pod-restarts = {
      severity    = 2
      description = "A flight-scanner container restarted in the last 30 minutes: a crash, an OOM kill or a failed liveness probe. See `kubectl -n ${local.ns} describe pod` and `kubectl logs --previous`."
      frequency   = "PT15M"
      window      = "PT30M"
      periods     = 1
      operator    = "GreaterThan"
      query       = <<-KQL
        KubePodInventory
        | where Namespace == "${local.ns}"
        | summarize Restarts = max(ContainerRestartCount) - min(ContainerRestartCount)
            by ControllerName, ContainerName
        | where Restarts > 0
      KQL
    }

    pod-not-running = {
      severity    = 1
      description = "A flight-scanner pod has not been Running for about 10 minutes (Pending, CrashLoopBackOff, ImagePullBackOff...). Scans or the UI are down."
      frequency   = "PT5M"
      window      = "PT15M"
      periods     = 2 # two evaluations in a row, so a pod starting during a deploy doesn't page
      operator    = "GreaterThan"
      query       = <<-KQL
        KubePodInventory
        | where Namespace == "${local.ns}"
        | summarize arg_max(TimeGenerated, PodStatus, ContainerStatus, ContainerStatusReason)
            by Name, ContainerName
        | where TimeGenerated > ago(10m) // pods that still exist (data arrives every 5 min)
        | where PodStatus != "Running" or ContainerStatus != "running"
      KQL
    }

    node-not-ready = {
      severity    = 1
      description = "A cluster node is not Ready, so nothing on it can run."
      frequency   = "PT5M"
      window      = "PT15M"
      periods     = 2
      operator    = "GreaterThan"
      query       = <<-KQL
        KubeNodeInventory
        | summarize arg_max(TimeGenerated, Status) by Computer
        | where Status != "Ready"
      KQL
    }

    volume-full = {
      severity    = 2
      description = "A flight-scanner volume (Postgres or raw payloads) is more than 80% full. Grow the PVC: edit its storage request and re-apply."
      frequency   = "PT30M"
      window      = "PT30M"
      periods     = 1
      operator    = "GreaterThan"
      query       = <<-KQL
        InsightsMetrics
        | where Namespace == "container.azm.ms/pv" and Name == "pvUsedBytes"
        | extend Tags = todynamic(Tags)
        | where tostring(Tags.pvcNamespace) == "${local.ns}"
        | summarize Used = max(Val), Capacity = max(todouble(Tags.pvCapacityBytes))
            by Claim = tostring(Tags.pvcName)
        | extend PercentUsed = round(100 * Used / Capacity, 1)
        | where PercentUsed > 80
      KQL
    }

    no-data = {
      severity    = 1
      description = "Nothing heard from the cluster for 30 minutes: it is stopped or broken, its monitoring agent is down, or the daily log cap was hit. The other log alerts are blind until data returns."
      frequency   = "PT15M"
      window      = "PT30M"
      periods     = 1
      operator    = "LessThan" # fires when the query returns no rows
      query       = "KubeNodeInventory"
    }
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "log" {
  for_each = local.log_alerts

  name                 = "${var.name}-${each.key}"
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  scopes               = [azurerm_log_analytics_workspace.main.id]
  description          = each.value.description
  severity             = each.value.severity
  evaluation_frequency = each.value.frequency
  window_duration      = each.value.window
  # Don't repeat the same email every evaluation while a problem lasts.
  mute_actions_after_alert_duration = "PT2H"
  # Send a second email when the problem clears.
  auto_mitigation_enabled = true
  tags                    = local.tags

  criteria {
    query                   = each.value.query
    time_aggregation_method = "Count"
    operator                = each.value.operator
    threshold               = each.value.operator == "LessThan" ? 1 : 0

    failing_periods {
      minimum_failing_periods_to_trigger_alert = each.value.periods
      number_of_evaluation_periods             = each.value.periods
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.owner.id]
  }

  # Container Insights must be sending data before the queries make sense.
  depends_on = [azurerm_monitor_data_collection_rule_association.container_insights]
}

# --- Budget: an email before the bill surprises you ----------------------------------------------
resource "azurerm_consumption_budget_resource_group" "monthly" {
  name              = "${var.name}-monthly"
  resource_group_id = azurerm_resource_group.main.id
  amount            = var.monthly_budget_eur
  time_grain        = "Monthly"

  time_period {
    # A budget must start on the first of a month. timestamp() changes on every run, so the
    # lifecycle block below tells Terraform to set it once and then leave it alone.
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.alert_email]
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}
