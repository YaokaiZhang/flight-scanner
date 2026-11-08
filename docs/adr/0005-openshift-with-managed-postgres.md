# Kubernetes deployment on OpenShift with a managed PostgreSQL, AKS kept as an alternative

The Kubernetes deployment targets an OpenShift cluster run by someone else, with Postgres in a managed PostgreSQL service outside the cluster. The AKS setup of ADR 0004 would spend the available cloud credit within its first month, while a shared academic OpenShift platform and managed database cost nothing. The manifests stay plain Kubernetes: Postgres moves into a Kustomize component that `overlays/aks` and `overlays/local` include and `overlays/openshift` leaves out, so the app reads the database's address from `.env`. GitHub Actions builds the images on every push to `main` and pushes them to GitHub's container registry, and `infra/deploy-openshift.sh` applies the overlay. The Terraform for AKS stays in the repository, validated in CI, but is not applied.

## Considered options

- **Stay on AKS** — keeps hands-on Terraform and Azure Monitor practice, but costs about €95–110 a month.
- **Postgres as a StatefulSet in the OpenShift project** — one less service, but backups are ours, its disk takes most of a small quota, and it is the image least suited to OpenShift's random user IDs.
- **Build images inside the cluster (OpenShift BuildConfig)** — no registry credentials, but ties the build to one platform and uploads the build context from a laptop on every deploy.

## Consequences

- The database is reached over the network: the connection uses TLS (`PGSSLMODE`) and the database accepts only allowlisted addresses, which include the cluster's outgoing address.
- The images must run under an arbitrary user ID in group 0, so the directories they write to are group-writable. This changes nothing under Docker Compose or AKS, where they run as root.
- The raw payload volume is a plain disk (ReadWriteOnce); the two Dagster pods that share it are scheduled onto the same node.
- No cloud-side alerting: the app's own notifiers report failed runs and stalled sources, and Kubernetes restarts crashed containers. Losing the whole project goes unnoticed until a heartbeat check is added.
