# Deploying to Azure with Terraform and Kubernetes

This folder runs the same stack as `compose.yaml` on Azure Kubernetes Service (AKS), with Azure
Monitor alerts. It is written as a walkthrough: each step says what happens and why, and the
files are commented with the same goal.

```
                 Terraform (infra/terraform)                     kubectl (infra/k8s, infra/deploy.sh)
 ┌────────────────────────────────────────────────────────┐   ┌──────────────────────────────────────┐
 │ resource group "flight-scanner"                        │   │ namespace "flight-scanner"           │
 │   container registry ── images ──┐                     │   │   postgres     StatefulSet + disk    │
 │   AKS cluster ── 1 node (VM) ────┼─ runs ──────────────┼──►│   api          Deployment            │
 │   Log Analytics ◄─ Container Insights agent            │   │   dagster-*    Deployments + Files   │
 │   alerts ─► action group ─► your email                 │   │   web          Deployment            │
 │   budget ─► your email                                 │   │   Secret from .env                   │
 └────────────────────────────────────────────────────────┘   └──────────────────────────────────────┘
```

The split matters: **Terraform owns the cloud resources** (things Azure bills you for), and
**Kubernetes owns what runs inside the cluster**. Terraform could apply the Kubernetes objects
too, but then every image change would be an infrastructure change. Here you change
infrastructure rarely and deploy the app often.

## The concepts, and where to see them

### Terraform

| Concept | What it is | Where |
| --- | --- | --- |
| Resource | One thing in the cloud that Terraform creates, updates and deletes | `resource "azurerm_kubernetes_cluster" "main"` in [main.tf](terraform/main.tf) |
| Provider | Plugin that turns resources into API calls (here `azurerm`) | [versions.tf](terraform/versions.tf) |
| Reference | One resource uses another's attribute, which also orders them | `azurerm_resource_group.main.name` everywhere |
| Variable / output | Inputs (from `terraform.tfvars`) and values printed after apply | [variables.tf](terraform/variables.tf), [outputs.tf](terraform/outputs.tf) |
| State | Terraform's record of what it created, mapping your code to real IDs | in Blob Storage, made by [bootstrap/](terraform/bootstrap/main.tf) |
| Plan / apply | Show the difference between code and reality, then make it so | the steps below |
| `for_each` | One resource block, many instances from a map | the alerts in [alerts.tf](terraform/alerts.tf) |
| `lifecycle` | Tweak how changes are handled, e.g. ignore a field that drifts on purpose | the budget in [alerts.tf](terraform/alerts.tf) |
| Lock file | Exact provider versions and checksums, committed like `uv.lock` | `.terraform.lock.hcl` |

Terraform is *declarative*: you describe the end state, not the steps. Delete a block and the
next `apply` deletes that resource. Rename one and Terraform plans a destroy and a create, so
read every plan before you apply it.

### Kubernetes

| Concept | What it is | Where |
| --- | --- | --- |
| Cluster, node | The control plane you talk to with `kubectl`, and the VMs that run pods | made by Terraform |
| Pod | One or more containers scheduled together; disposable | made for you by the objects below |
| Deployment | Keeps N identical pods running, and rolls them on change | [api.yaml](k8s/base/api.yaml), [web.yaml](k8s/base/web.yaml) |
| StatefulSet | Like a Deployment, but with a stable pod name and its own volume | [postgres.yaml](k8s/base/postgres.yaml) |
| Service | Stable DNS name for a set of pods (`postgres`, `api`) | bottom of each file |
| PersistentVolumeClaim | A request for storage that outlives pods | `raw-data` in [dagster.yaml](k8s/base/dagster.yaml) |
| Secret | Settings and keys, injected as environment variables | generated from `.env` by [deploy.sh](deploy.sh) |
| Probes | Readiness (send traffic?) and liveness (restart?) checks | every container |
| Requests / limits | CPU and memory reserved, and the ceiling | every container |
| Init container | Runs to completion before the main container | `wait-for-postgres` |
| Namespace | A folder for the app's objects | [namespace.yaml](k8s/base/namespace.yaml) |
| Kustomize | Base manifests plus small per-environment patches | [base/](k8s/base), [overlays/](k8s/overlays) |

Kubernetes is declarative too: `kubectl apply` sends the desired state, and controllers in the
cluster keep working until reality matches. That is why a crashed pod comes back by itself:
the Deployment still says "one replica", and there are zero.

### How Compose maps to Kubernetes

| `compose.yaml` | Here |
| --- | --- |
| `services.postgres` with a `pgdata` volume | StatefulSet with a claim template (an Azure disk) |
| `services.api`, `web`, `dagster-*` | Deployments, each with a Service |
| `depends_on: condition: service_healthy` | init container that waits for `pg_isready` |
| `healthcheck` | readiness and liveness probes |
| `env_file: .env` | a Secret made from `.env`, read with `envFrom` |
| `rawdata` volume shared by two services | a ReadWriteMany claim on Azure Files |
| `restart: unless-stopped` | built in: Kubernetes restarts what dies |
| `ports: 127.0.0.1:3000:3000` | ClusterIP Services plus `kubectl port-forward` |

## Cost

Roughly €95–110 a month in Sweden Central at pay-as-you-go prices. These are estimates, so
check the [pricing calculator](https://azure.microsoft.com/pricing/calculator/):

| Item | ≈ €/month |
| --- | --- |
| AKS control plane, Free tier | 0 |
| Node: 1 × Standard_B2ms, running all the time | 60–65 |
| Node OS disk, 64 GB premium | 9 |
| Standard load balancer and public IP (AKS's outbound internet) | 20 |
| Postgres disk (32 GB Standard SSD) and Azure Files (raw payloads) | 4 |
| Log Analytics: 5 GB a month free, then per GB; capped at 0.5 GB a day | 0–10 |
| Container registry, Basic | 5 |

That is about €40 more than one VM running Docker Compose, mostly the load balancer and the
managed pieces. The budget alert emails you at 80% of `monthly_budget_eur` (default €120), and
when the forecast passes 100%.

To pause, `az aks stop --resource-group flight-scanner --name flight-scanner` stops the node.
That saves the VM cost, but disks, load balancer and registry still bill, and the "no data"
alert will fire. `az aks start` brings everything back as it was.

## Try it locally first (optional, free)

The `local` overlay runs the manifests on a one-node cluster on your laptop. Nothing about Azure
is involved, so it is the cheapest way to get a feel for `kubectl`. With
[kind](https://kind.sigs.k8s.io/) and Docker:

```sh
kind create cluster --name flight-scanner
docker build -f docker/python.Dockerfile -t flight-scanner-python:local .
docker build -t flight-scanner-web:local web
kind load docker-image flight-scanner-python:local flight-scanner-web:local --name flight-scanner

kubectl apply -f infra/k8s/base/namespace.yaml
kubectl -n flight-scanner create secret generic flight-scanner-env --from-env-file=.env
kubectl apply -k infra/k8s/overlays/local
kubectl -n flight-scanner get pods --watch       # Ctrl-C once all are Running and 1/1
kubectl -n flight-scanner port-forward svc/web 3000:3000
```

`kind delete cluster --name flight-scanner` removes it all.

## Deploy to Azure

### 0. Tools and login

You need the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli),
[Terraform](https://developer.hashicorp.com/terraform/install) 1.9 or later and
[kubectl](https://kubernetes.io/docs/tasks/tools/) (`az aks install-cli` installs it).

```sh
az login
az account show --query '{name:name, id:id}'      # the subscription that will be billed
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

Terraform's `azurerm` provider uses your `az login` session and reads the subscription from
`ARM_SUBSCRIPTION_ID`. No credentials are written to any file.

### 1. Bootstrap the state storage (once)

```sh
terraform -chdir=infra/terraform/bootstrap init
terraform -chdir=infra/terraform/bootstrap apply
terraform -chdir=infra/terraform/bootstrap output -raw backend_config > infra/terraform/backend.hcl
```

`init` downloads the providers listed in the lock file. `apply` shows a plan (four resources)
and asks for `yes`. The last line saves the storage account's name for the next step. The
bootstrap's own state stays in `infra/terraform/bootstrap/terraform.tfstate` (git-ignored). Keep
that file, although losing it only means importing the four resources again.

### 2. Create the infrastructure

```sh
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars   # set alert_email
terraform -chdir=infra/terraform init -backend-config=backend.hcl
terraform -chdir=infra/terraform plan -out=tfplan
terraform -chdir=infra/terraform apply tfplan
```

Read the plan: each line marked `+` is something Azure will start billing for. Saving it with
`-out` and applying that file guarantees that what you reviewed is exactly what runs. The
cluster takes about 5–10 minutes.

Azure then emails `alert_email` to say it was added to the action group, so you know alerts
reach you.

### 3. Deploy the app

```sh
cp .env.example .env    # if you haven't: same file as for Docker Compose
infra/deploy.sh
```

The script:

1. Reads the Terraform outputs (registry and cluster names), so nothing is hard-coded.
2. Fetches cluster credentials into `~/.kube/config` (`az aks get-credentials`).
3. Builds both images **in Azure** with `az acr build`, tagged with the git commit. A commit
   that is already built is skipped.
4. Writes a small overlay that adds those image names and turns `.env` into a Secret, then
   runs `kubectl apply`.
5. Waits for each rollout, and prints the port-forward commands.

Run it again after every change to the code or to `.env`. Kubernetes replaces only what changed.
An unchanged commit with an unchanged `.env` is a no-op.

### 4. Open the UIs

```sh
kubectl -n flight-scanner port-forward svc/web 3000:3000                 # http://127.0.0.1:3000
kubectl -n flight-scanner port-forward svc/dagster-webserver 3001:3001   # http://127.0.0.1:3001
```

Nothing is exposed to the internet, because the API has no login. A port forward tunnels
through the Kubernetes API, which needs your Azure credentials, so it plays the role of the SSH
tunnel used on verda.

### 5. Check that monitoring works

In the portal, open the cluster, then **Monitoring > Insights** for live pod and node views, or
**Monitoring > Logs** to query. Data appears about 10 minutes after the cluster starts. Try:

```kusto
KubePodInventory
| where Namespace == "flight-scanner"
| summarize arg_max(TimeGenerated, PodStatus, ContainerRestartCount) by Name
```

```kusto
ContainerLogV2
| where PodNamespace == "flight-scanner" and ContainerName == "dagster-daemon"
| sort by TimeGenerated desc
| take 100
```

To see an alert fire, delete a pod: `kubectl -n flight-scanner delete pod -l app=web`. The
Deployment replaces it within seconds, which is self-healing at work, so no alert fires. To
see one fire, break the API's image instead:
`kubectl -n flight-scanner set image deploy/api api=does-not-exist`. Within about 15 minutes
you get "pod-not-running", and `infra/deploy.sh` puts it right.

## Monitoring and alerts

Alerts go to `alert_email` through one action group. Each alert sends one email when it fires
and another when it clears.

| Alert | Source | Fires when |
| --- | --- | --- |
| `node-cpu`, `node-memory` | AKS platform metric | above 85% averaged over 15 min |
| `node-disk` | AKS platform metric | node OS disk above 85% |
| `pod-not-running` | Container Insights | a pod is Pending or a container isn't running, at two checks in a row (≈10 min) |
| `pod-restarts` | Container Insights | any container restarted in the last 30 min (crash, OOM kill, failed liveness probe) |
| `node-not-ready` | Container Insights | a node reports anything but Ready, twice in a row |
| `volume-full` | Container Insights | the Postgres or raw-data volume is over 80% |
| `no-data` | Container Insights | no data at all for 30 min: cluster stopped, agent down or daily cap reached |
| budget | Cost Management | 80% of the monthly budget spent, or 100% forecast |

These watch the platform. The app still watches itself: failed Dagster runs and stalled sources
reach your Telegram or email notifiers, as on verda, because the daemon runs the same sensors.

## Day-to-day commands

```sh
kubectl -n flight-scanner get pods                                   # what runs, restarts, age
kubectl -n flight-scanner describe pod <name>                        # events: why it is Pending or restarting
kubectl -n flight-scanner logs deploy/dagster-daemon -f              # follow logs
kubectl -n flight-scanner logs <pod> --previous                      # logs of the crashed container
kubectl -n flight-scanner exec deploy/dagster-daemon -- python -m flight_scanner scan
kubectl -n flight-scanner exec -it statefulset/postgres -- psql -U flightscanner flightscanner
kubectl -n flight-scanner rollout undo deploy/api                    # back to the previous version
kubectl -n flight-scanner top pods                                   # live CPU and memory
```

The one-off commands in the main README work through `kubectl exec deploy/dagster-daemon --`,
just as they go through `docker compose exec dagster-daemon` on verda.

## Moving the data from verda

```sh
# On verda: dump both databases.
docker compose exec -T postgres pg_dump -U flightscanner -Fc flightscanner > flightscanner.dump
docker compose exec -T postgres pg_dump -U flightscanner -Fc dagster > dagster.dump

# Locally, with kubectl pointed at AKS: stop the writers, restore, start them again.
kubectl -n flight-scanner scale deploy/api deploy/dagster-daemon deploy/dagster-webserver --replicas=0
kubectl -n flight-scanner exec -i postgres-0 -- pg_restore -U flightscanner -d flightscanner --clean --if-exists < flightscanner.dump
kubectl -n flight-scanner exec -i postgres-0 -- pg_restore -U flightscanner -d dagster --clean --if-exists < dagster.dump
kubectl -n flight-scanner scale deploy/api deploy/dagster-daemon deploy/dagster-webserver --replicas=1
```

The raw payloads are only needed for `python -m flight_scanner rebuild`. If you want them, copy
the `rawdata` volume into a running Dagster pod with `kubectl cp`. With the raw archive turned on
(`FS_RAW_ARCHIVE`), older days are already on Databricks.

## Changing and removing things

- **Infrastructure:** edit `infra/terraform`, then `plan` and `apply`. For example,
  `node_vm_size = "Standard_B4ms"` in `terraform.tfvars` resizes the node. AKS moves the pods to
  a temporary pool first, so the app stays up.
- **App:** edit `infra/k8s`, commit, `infra/deploy.sh`. To preview what would change before
  deploying: `kubectl diff -k infra/k8s/overlays/aks` shows the difference against the cluster.
  Ignore the image names and the Secret's name, which only `deploy.sh` fills in.
- **Storage:** to grow a volume, raise its `storage:` request and deploy. Azure disks and files
  can grow but never shrink.
- **Remove everything:** `terraform -chdir=infra/terraform destroy`. This deletes the cluster,
  **the Postgres disk and its data**, the logs and the registry. Dump the database first if you
  want to keep it. The bootstrap state storage stays until you destroy that too.

## Not done here, on purpose

- **Public access.** Exposing the UI needs authentication in front of it first, for example an
  ingress controller with OAuth2 Proxy or Entra ID sign-in.
- **Continuous deployment.** A GitHub Actions workflow could run `infra/deploy.sh` on every push
  to `main`, logging in to Azure through OIDC federation (no stored secret). For now, deploys are
  manual.
- **Managed Postgres.** Azure Database for PostgreSQL would add automatic backups and point-in-time
  restore, for about €15 more a month. With Postgres in the cluster, backups are your job: dump it
  to Blob Storage on a schedule (a Kubernetes CronJob would do it), or enable Azure Backup for AKS.
