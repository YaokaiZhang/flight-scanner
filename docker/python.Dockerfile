# Image for the Python services: Dagster webserver + daemon (with dbt) and the HTTP API.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    FS_DBT_PROJECT_DIR=/app/dbt \
    DAGSTER_HOME=/opt/dagster/home \
    FS_DATA_DIR=/data \
    POSTGRES_PORT=5432

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY dbt ./dbt
RUN uv sync --frozen --no-dev \
    && dbt parse --quiet --project-dir dbt --profiles-dir dbt --target-path target

COPY docker/dagster.yaml /opt/dagster/home/dagster.yaml
COPY docker/workspace.yaml /app/workspace.yaml
# OpenShift runs containers as a random user ID that belongs to group 0 (root's group, without
# root's powers). Give group 0 the owner's rights where the services write at runtime: Dagster's
# home (compute logs), the dbt project (target/, logs/) and the data directory.
RUN mkdir -p /data \
    && chgrp -R 0 /opt/dagster/home /app/dbt /data \
    && chmod -R g=u /opt/dagster/home /app/dbt /data
