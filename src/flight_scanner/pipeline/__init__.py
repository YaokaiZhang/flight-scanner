"""The Dagster pipeline: watch slots -> ingestion -> dbt (staging, marts) -> Deals -> Alerts.

`build_definitions(runtime)` is the only entry point; the deployed code location
(`flight_scanner.pipeline.workspace`) and the seam-1 harness both call it, so tests exercise
exactly the wiring that runs in production.
"""

from flight_scanner.pipeline.definitions import build_definitions, rebuild, run_once
from flight_scanner.pipeline.runtime import Runtime

__all__ = ["Runtime", "build_definitions", "rebuild", "run_once"]
