# Image for the Python services: Dagster webserver + daemon (with dbt) and the HTTP API.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    FS_DBT_PROJECT_DIR=/app/dbt \
    DAGSTER_HOME=/opt/dagster/home \
    FS_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY dbt ./dbt
RUN uv sync --frozen --no-dev \
    && dbt parse --quiet --project-dir dbt --profiles-dir dbt --target-path target

COPY docker/dagster.yaml /opt/dagster/home/dagster.yaml
COPY docker/workspace.yaml /app/workspace.yaml
RUN mkdir -p /data
