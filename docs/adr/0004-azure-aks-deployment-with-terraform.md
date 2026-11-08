# Optional Azure deployment: AKS provisioned with Terraform, monitored with Azure Monitor

The operational stack can also run on Azure Kubernetes Service, next to the verda Compose deployment rather than replacing it. Terraform (`infra/terraform`) provisions the cloud resources: a resource group, a container registry, a one-node AKS cluster, Log Analytics with Container Insights, alerts and a budget. Kustomize manifests (`infra/k8s`) describe the app, and `infra/deploy.sh` builds the images in Azure and applies them. Terraform owns the cloud, kubectl owns the cluster, so app deploys never go through a Terraform plan. This builds Terraform, Kubernetes and Azure skills, which are in demand in the Nordic data-engineering market, at roughly €95–110 a month instead of a free host.

## Considered options

- **One Azure VM running Docker Compose** — about €60 a month and no changes, but it teaches neither Kubernetes nor much Azure.
- **Azure Container Apps with Azure Database for PostgreSQL** — less to operate, but the Dagster daemon needs exactly one always-on replica and a shared volume, which fits Container Apps poorly, and it avoids Kubernetes rather than learning it.
- **The Terraform Kubernetes provider for the app** — one tool for everything, but every image change becomes an infrastructure change, and the cluster has to exist before the provider can even be configured.

## Consequences

- Postgres runs in the cluster as a StatefulSet on an Azure disk, so backups are ours to arrange; managed Postgres remains an upgrade path.
- Nothing is public: the API has no login, so the UIs are reached with `kubectl port-forward`, the counterpart of the SSH tunnel on verda.
- Cloud alerts watch the platform (nodes, pods, volumes, spend); the app's own notifiers still report failed runs and stalled sources.
- The manifests mirror `compose.yaml`; a change to one (a new service, a new volume) needs the same change in the other.
