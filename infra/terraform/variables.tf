# Inputs. Values go in terraform.tfvars (git-ignored); see terraform.tfvars.example.

variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "flight-scanner"
}

variable "location" {
  description = "Azure region. Sweden Central and North Europe are the closest to Helsinki."
  type        = string
  default     = "swedencentral"
}

variable "node_vm_size" {
  description = "VM size of the cluster's single node. B2ms: 2 vCPU, 8 GiB."
  type        = string
  default     = "Standard_B2ms"
}

variable "node_count" {
  description = "Number of nodes. One is enough: the stack has one replica of everything."
  type        = number
  default     = 1
}

variable "alert_email" {
  description = "Where Azure Monitor sends alerts and budget warnings."
  type        = string
}

variable "monthly_budget_eur" {
  description = "Monthly spend for the resource group that triggers budget emails (80% actual, 100% forecast)."
  type        = number
  default     = 120
}

variable "log_daily_quota_gb" {
  description = "Hard cap on Log Analytics ingestion per day, which is the main variable cost of monitoring. -1 means no cap."
  type        = number
  default     = 0.5
}

variable "app_namespace" {
  description = "Kubernetes namespace of the app. Must match infra/k8s/base/namespace.yaml; the log alerts filter on it."
  type        = string
  default     = "flight-scanner"
}
