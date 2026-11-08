# Deploying to OpenShift with a managed PostgreSQL

This runs the same stack as `compose.yaml` on an OpenShift cluster that someone else operates,
with the database in a managed PostgreSQL service instead of inside the cluster. There is
nothing to provision with Terraform: the cluster already exists, and you get a project in it.
If your university or employer gives you access to such a platform, this costs nothing.

```
  GitHub Actions (images.yml)                 OpenShift project                 managed PostgreSQL
 ┌───────────────────────────┐   pull   ┌──────────────────────────────┐  TLS  ┌──────────────────┐
 │ push to main ─► build ─►  │ ───────► │ api                Deployment│ ────► │ flightscanner db │
 │ ghcr.io/<owner>/…:<sha12> │          │ web                Deployment│       │ dagster db       │
 └───────────────────────────┘          │ dagster-daemon  ┐  same node,│       │ daily backups    │
                                        │ dagster-webserver┘ one disk  │       │ IP allowlist     │
                                        │ Secret from .env             │       └──────────────────┘
   infra/deploy-openshift.sh ─ apply ─► └──────────────────────────────┘
```

Read [README.md](README.md) first for the Kubernetes concepts. This page covers what is
different.

## How OpenShift differs from plain Kubernetes

OpenShift is Kubernetes with a stricter default policy and some extra objects. Everything in
`infra/k8s` is plain Kubernetes, so it runs on both.

| Concept | Plain Kubernetes | OpenShift | Here |
| --- | --- | --- | --- |
| Command-line tool | `kubectl` | `oc`, a superset of `kubectl` | Either works; the scripts use `kubectl` |
| Namespace | You create it | A *project*: `oc new-project`. Ordinary users may not create Namespace objects | The overlay deletes `namespace.yaml`; the deploy script uses your current project |
| Container user | Whatever the image says, often root | A **random user ID** per project, always in group 0. Containers that insist on root are refused | The images give group 0 write access where they write ([python.Dockerfile](../docker/python.Dockerfile), [web/Dockerfile](../web/Dockerfile)) |
| Security policy | Opt-in (Pod Security admission) | Security Context Constraints, `restricted` by default: no root, no privileged containers, no host access | The overlay sets `runAsNonRoot` and the default seccomp profile |
| Public URL | Ingress | Route, with HTTPS by default | None: the API has no login, so access is by port forward |
| Builds and images | Outside the cluster | BuildConfigs and ImageStreams can build inside it | Not used: GitHub Actions builds, so the cluster only pulls |
| Limits | Whatever the nodes hold | A ResourceQuota caps the project's total CPU, memory and storage, and a LimitRange sets defaults and ratios | Check yours before deploying (step 4) |

The random user ID is the change most likely to break an image. A file the image creates is
owned by root (user 0, group 0), so the random user can only write to it through the group.
`chgrp -R 0 <dir> && chmod -R g=u <dir>` gives group 0 the same rights as the owner, which is
the standard fix. Docker Compose and AKS still run the images as root, where it changes nothing.

## Why a managed PostgreSQL

Postgres in the cluster (the StatefulSet in
[components/in-cluster-postgres](k8s/components/in-cluster-postgres)) makes backups your
problem, uses most of a small project quota for its disk, and is the image least happy under a
random user ID. A managed service takes daily backups, upgrades minor versions, and leaves the
quota to the app.

What changes for the app: nothing in the code. Every component reads `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` (and Dagster
`DAGSTER_PG_DB`) from the environment, and all of them connect through libpq, which also reads
`PGSSLMODE`. The `openshift` overlay simply leaves the in-cluster Postgres component out, so
those values come from your `.env`.

The price is the network: the database is outside the cluster, so the connection must be
encrypted (`PGSSLMODE=require`) and the database must accept connections only from known
addresses (its allowlist).

## Deploy

### 0. Tools

- `oc`, the OpenShift CLI (the web console's **?** menu links to a download), or `kubectl`.
- `psql`, to check the database connection: `brew install libpq` or `apt install postgresql-client`.

### 1. Create the database

In your PostgreSQL service's console:

1. Create an instance running **PostgreSQL 16** (the version CI tests against). The smallest
   size is plenty.
2. Create a user, for example `flightscanner`, with a long random password.
3. Create two databases, `flightscanner` and `dagster`, **owned by that user**. Ownership
   matters: since PostgreSQL 15, only the owner may create tables in a database's `public`
   schema, and both the app's migrations and Dagster create tables on start.
4. Allow connections from your own IP address (to test and migrate) and from the cluster's
   outgoing address. The platform's documentation lists that address; it is not the address of
   your Routes.

Check from your laptop:

```sh
psql "host=<host> port=<port> user=flightscanner dbname=flightscanner sslmode=require" -c 'select version()'
```

### 2. Point `.env` at it

Add to `.env` (no quotes and no trailing comments, which Kubernetes would keep as part of the
value):

```sh
POSTGRES_HOST=<host>
POSTGRES_PORT=5432
POSTGRES_USER=flightscanner
POSTGRES_PASSWORD=<password>
POSTGRES_DB=flightscanner
DAGSTER_PG_DB=dagster
PGSSLMODE=require
```

Docker Compose ignores the first two, because `compose.yaml` sets them, so the same `.env` keeps
working on verda.

### 3. Images

Every push to `main` runs [images.yml](../.github/workflows/images.yml), which builds both images
and pushes them to `ghcr.io/<owner>/flight-scanner-python` and `-web`, tagged with the first 12
characters of the commit. Check the **Actions** tab: the deploy needs that run to have finished.

**Let the cluster pull the images.** Packages of a private repository are private. Either make
the two packages public (GitHub, your profile, **Packages**, the package, **Package settings**),
or give the project a pull secret: create a GitHub personal access token (classic) with only
the `read:packages` scope, then

```sh
oc create secret docker-registry ghcr-pull --docker-server=ghcr.io \
  --docker-username=<github user> --docker-password=<token>
oc secrets link default ghcr-pull --for=pull   # pods run as "default", which now uses it
```

### 4. Log in and pick the project

Copy the login command from the web console (your name, **Copy login command**), then:

```sh
oc login --token=<token> --server=<api url>
oc new-project <name>          # or `oc project <name>` for an existing one
oc describe quota              # the project's CPU, memory and storage allowance
oc describe limitrange         # default limits and the largest allowed limit/request ratio
oc get storageclass            # which one is (default)
```

The pods request about 0.35 CPU and 1.7 GiB of memory, with limits of about 6 GiB, plus a 20 GiB
volume. If the quota is smaller, lower the limits in `infra/k8s/base` or ask for more. If the
limit range rejects a limit/request ratio (the error names it), raise that container's request.

### 5. Deploy

```sh
infra/deploy-openshift.sh
```

It checks `.env`, renders `overlays/openshift` with your project, the image tags of the checked-out
commit and a Secret made from `.env`, applies it, and waits for every Deployment. On a failure
it prints the usual causes. Deploying an earlier commit, a rollback, is
`infra/deploy-openshift.sh --tag <first 12 characters of its hash>`.

### 6. Open the UIs

```sh
oc port-forward svc/web 3000:3000                 # http://127.0.0.1:3000
oc port-forward svc/dagster-webserver 3001:3001   # http://127.0.0.1:3001
```

## Monitoring and alerts

There is no Azure Monitor here, so the layers are:

| What fails | Who notices |
| --- | --- |
| A scan run fails, a source stalls, data quality gates trip | The app's own sensors, through your Telegram or email notifiers (main README, "Pipeline monitoring") |
| A container crashes or hangs | Kubernetes restarts it (liveness probes); the restart count shows in `oc get pods` |
| The database is down | The API's readiness probe fails; the next scan fails and is reported as above |
| CPU, memory, events | The web console: your project, **Observe** |

The gap is the cluster itself: if the whole project stops, nothing inside it can tell you. A
free external heartbeat service fixes that; see "Not done here".

## Day-to-day commands

The commands in [README.md](README.md#day-to-day-commands) work unchanged with `oc` or `kubectl`,
without `-n` once the project is selected, except the `psql` line. The database is outside the
cluster, so connect directly:

```sh
psql "host=<host> port=<port> user=flightscanner dbname=flightscanner sslmode=require"
```

## Moving the data from verda

```sh
# On verda: dump both databases.
docker compose exec -T postgres pg_dump -U flightscanner -Fc flightscanner > flightscanner.dump
docker compose exec -T postgres pg_dump -U flightscanner -Fc dagster > dagster.dump

# Locally (your IP on the allowlist): stop the writers, restore, start them again.
oc scale deploy/api deploy/dagster-daemon deploy/dagster-webserver --replicas=0
pg_restore --no-owner -d "host=<host> port=<port> user=flightscanner dbname=flightscanner sslmode=require" --clean --if-exists flightscanner.dump
pg_restore --no-owner -d "host=<host> port=<port> user=flightscanner dbname=dagster sslmode=require" --clean --if-exists dagster.dump
oc scale deploy/api deploy/dagster-daemon deploy/dagster-webserver --replicas=1
```

`--no-owner` makes the restored tables belong to the user you connect as.

## Removing it

`oc delete project <name>` deletes everything in the cluster, including the raw payload volume.
The database is separate: delete the instance in its own console, after a final `pg_dump` if you
want to keep the data.

## Not done here, on purpose

- **Public access.** A Route would give the UI a public HTTPS address, but the API has no login.
  If you add one, limit it to your address with the annotation
  `haproxy.router.openshift.io/ip_whitelist`, or put authentication in front.
- **Heartbeat.** A small CronJob that pings a dead man's switch service every 15 minutes would
  email you when the project stops entirely.
- **Continuous deployment.** The image workflow could deploy too, with a service account token as a
  repository secret. For now, deploys are manual.
